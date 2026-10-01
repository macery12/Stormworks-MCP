"""Render staged calibrations into out/; optionally benchmark cold/repeated large previews.

    uv run tools/staged_builder_test.py out/staged-builder --benchmark

Does not write to the player's vehicles folder. Copy chosen XML files into it for game checks.
"""
import argparse
import copy
import hashlib
import json
import os
import sys
import time
from itertools import product
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import anyio  # noqa: E402

from swhull.access import install_hatch  # noqa: E402
from swhull.build import build, resolve_spec, summary  # noqa: E402
from swhull.interior import InteriorPlan  # noqa: E402
from swhull.jobs import run_job  # noqa: E402
from swhull.pieces import BLOCK, Placed  # noqa: E402
from swhull.render import design_ruler, render_interior, render_png, render_view  # noqa: E402
from swhull.seal import auto_seeds, check  # noqa: E402
from swhull.tanks import ensure_valid  # noqa: E402
from swhull.vehicle import to_xml  # noqa: E402


def save(out, name, parts, png, text):
    (out / f"{name}.xml").write_bytes(to_xml(parts).encode())
    (out / f"{name}.png").write_bytes(png)
    (out / f"{name}.txt").write_text(text, encoding="utf-8")
    print(f"{name}: {len(parts)} parts; {text.splitlines()[-1]}", flush=True)


def calibrate(out):
    for name, spec in (
        ("staged-tug", resolve_spec({"fitout": {"stage": "propulsion"}}, preset="tugboat")),
        ("staged-tank", resolve_spec({"tanks": [{"name": "fuel", "position": [-1, .25, 3],
                                               "size": [2, 1.5, 2]}]}, preset="barge")),
    ):
        parts, info = build(spec)
        ensure_valid(info)
        text = summary(spec, parts, info)
        uncentred = copy.deepcopy(parts)
        for p in uncentred:
            p.origin = tuple(p.origin[i] + info["shift"][i] for i in range(3))
        report = check(uncentred, auto_seeds(uncentred, info))
        (out / f"{name}-seal.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        save(out, name, parts, render_png(parts, title=name, ruler=design_ruler(info)), text)
        if info["interior"].rooms:
            (out / f"{name}-interior.png").write_bytes(render_interior(parts, info, title=name))
        if info.get("tanks"):
            (out / f"{name}-tanks.json").write_text(json.dumps(info["tank_validation"], indent=2), encoding="utf-8")
            tank = [p for p in uncentred if p.name.startswith("fuel")
                    and (p.piece.d != "01_block" or p.origin[1] < 6 and p.origin[0] <= 0)]
            (out / f"{name}-cutaway.png").write_bytes(render_view(tank, title="tank kit cutaway", yaw=35, pitch=25))
    solid = set(product(range(-6, 7), range(20), range(17)))
    skin = {v for v in solid if v[0] in (-6, 6) or v[1] in (0, 19) or v[2] in (0, 16)}
    plan = InteriorPlan(blocks={v: "8A8F96" for v in solid - skin if v[1] == 9})
    ok, reason = install_hatch({"name": "access", "floor": 2.5, "z": 2}, {}, skin,
                               {v: "hull" for v in solid}, lambda _x, _z: 19, plan)
    if not ok:
        raise ValueError(f"access calibration failed: {reason}")
    parts = [Placed(BLOCK, v, color=plan.blocks.get(v, "C2C3C7"))
             for v in sorted((skin - plan.carve) | set(plan.blocks))] + plan.components
    reports = {state: check(parts, [{"name": "lower", "position": [0, 1, 8]},
                                    {"name": "upper", "position": [0, 10, 8]}], state)
               for state in ("closed", "open")}
    assert all(r["status"] == "sealed" for r in reports.values())
    assert reports["open"]["compartments"][0]["connected"] == ["lower", "upper"]
    (out / "staged-access-seal.json").write_text(json.dumps(reports, indent=2), encoding="utf-8")
    cutaway = [p for p in parts if p in plan.components or p.origin[0] <= 0 and p.origin[1] != 19]
    cutaway = copy.deepcopy(cutaway)
    for p in cutaway:
        if p.piece.d == "ladder_small":
            p.color = "19C8DD"
        elif p.piece.d == "door_manual_small":
            p.color = "FF9933"
    save(out, "staged-access", parts, render_view(cutaway, title="complete hatch and ladder", yaw=35, pitch=25), reason)


async def benchmark(out):
    # A dedicated directory makes "cold" reproducible without deleting any existing cache.
    os.environ["SW_BUILD_CACHE_DIR"] = str(out / f"benchmark-cache-{time.time_ns()}")
    spec = resolve_spec({"length": 118, "beam": 20, "depth": 8, "deck": "closed", "bench": "L"})
    rows = []

    async def measured(label, job, *args):
        start = time.perf_counter()
        result = await run_job(job, *args)
        elapsed = time.perf_counter() - start
        rows.append({"operation": label, "seconds": round(elapsed, 3)})
        print(f"{label}: {elapsed:.3f} s", flush=True)
        return result

    png, cold = await measured("cold preview", "preview", spec, "large cold")
    (out / "large-cold.png").write_bytes(png)
    png, warm = await measured("repeated preview", "preview", spec, "large repeated")
    (out / "large-repeated.png").write_bytes(png)
    assert "cache reused" in warm and "rebuilt" in cold
    record = {"spec": spec}
    await measured("camera-only preview", "preview_draft", record, "large camera", 270, -20, 1, None)
    q = await run_job("query_draft", record, None, 0, 1)
    edited = copy.deepcopy(record)
    edited["spec"]["edits"] = [{"op": "paint", "select": {"ids": [q["parts"][0]["id"]]}, "color": "FF8800"}]
    png, edit_text = await measured("single-part repaint preview", "preview_draft", edited, "large edit")
    assert "cache reused" in edit_text
    (out / "large-edit.png").write_bytes(png)
    overlay = copy.deepcopy(record)
    overlay["spec"]["fitout"] = {"stage": "core"}
    _, component_text = await measured("core-component preview", "preview_draft", overlay, "large core")
    assert "cache reused" in component_text
    # Exact export equivalence with caching disabled, including component ordering and paint.
    cached, count, _ = await run_job("vehicle_xml", spec)
    os.environ["SW_BUILD_CACHE"] = "0"
    try:
        uncached, _, _ = await measured("uncached export equivalence", "vehicle_xml", spec)
    finally:
        os.environ.pop("SW_BUILD_CACHE", None)
    assert cached == uncached
    result = {"spec": spec, "parts": count, "timings": rows, "cached_uncached_equal": True,
              "xml_sha256": hashlib.sha256(cached.encode()).hexdigest(),
              "environment": {"python": sys.version, "platform": sys.platform},
              "notes": "Wall time includes a fresh worker and rendering; component/paint overlays reuse base geometry."}
    (out / "benchmark.json").write_text(json.dumps(result, indent=2), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("out", nargs="?", default="out/staged-builder")
    parser.add_argument("--benchmark", action="store_true")
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    calibrate(out)
    if args.benchmark:
        anyio.run(benchmark, out)


if __name__ == "__main__":
    main()
