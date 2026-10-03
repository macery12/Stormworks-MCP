"""Compare slope joints and sampled shape error on identical continuous geometry.

uv run tools/smoothing_benchmark.py out/smoothing --preset rowboat --preset runabout
uv run tools/smoothing_benchmark.py out/smoothing --spec path/to/spec.json
Outputs remain local. Joint counts include intentional creases; never call them accuracy.
"""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from swhull.build import build, resolve_spec  # noqa: E402
from swhull.hull_analysis import structural_report  # noqa: E402
from swhull.pieces import CONTAINS, add, apply  # noqa: E402
from swhull.render import render_png, render_interior  # noqa: E402
from swhull.smooth import FULL_MASK, SAMPLES, _cells, _transpose, deck_plates, shell  # noqa: E402


def shape_error(parts, info):
    """Test the same partial target cells, including border slivers, for both fitters."""
    shape, solid = info["shape"], set(info["region"])
    removed = set(info["interior"].carve)
    if info["spec"]["deck"] == "open":
        removed |= deck_plates(solid, {v for v in shell(solid) if info["region"][v] == "hull"})
    cells, masks = _cells(solid, lambda p: shape.contains(*p), removed,
                         lambda v: shape.sample_mask(v, SAMPLES), set())
    owner = {add(v, info["shift"]): p for p in parts for v in p.voxels()}
    wrong, count = 0, 0
    for v in cells:
        target = masks[v]
        if not 0 < target < FULL_MASK:
            continue
        p = owner.get(v)
        actual = 0
        if p is not None:
            test = CONTAINS.get(p.piece.d)
            if test is None:
                continue
            back = _transpose(p.Q)
            local = tuple(v[i] - info["shift"][i] - p.origin[i] for i in range(3))
            actual = sum(1 << i for i, sample in enumerate(SAMPLES)
                         if test(apply(back, add(local, sample))))
        wrong += (target ^ actual).bit_count()
        count += 64
    return {"wrong_samples": wrong, "tested_samples": count,
            "partial_cell_volume_error_fraction": wrong / count if count else 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--preset", action="append", default=[])
    parser.add_argument("--spec", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    cases = [(name, {}) for name in args.preset]
    if args.spec:
        data = json.loads(args.spec.read_text(encoding="utf-8-sig"))
        cases.append((None, data.get("spec", data)))
    if not cases:
        cases = [(name, {}) for name in ("rowboat", "runabout", "fishing_trawler")]
    rows = []
    for preset, spec in cases:
        for mode in ("wedges", "wedges_v2"):
            full = resolve_spec({**spec, "smoothing": mode}, preset=preset)
            started = time.monotonic()
            parts, info = build(full)
            build_seconds = time.monotonic() - started
            report = structural_report(parts)
            error = shape_error(parts, info)
            name = f"{preset or 'custom'}_{mode}"
            args.output.joinpath(name + ".png").write_bytes(render_png(parts, title=name))
            args.output.joinpath(name + "_section.png").write_bytes(render_interior(parts, info, title=name))
            row = {"case": preset or "custom", "mode": mode, "build_seconds": round(build_seconds, 3),
                   "cache_hit": info.get("cache_hit", False), "parts": len(parts),
                   "joints": report["partial_joints"], "shape_error": error,
                   "selection": info.get("smoothing_report"),
                   "warnings": info["warnings"]}
            rows.append(row)
            print(f"{name}: {len(parts)} parts; {row['joints']['mismatched']} mismatched joints; "
                  f"{error['partial_cell_volume_error_fraction']:.4f} sampled error; {build_seconds:.2f}s", flush=True)
    args.output.joinpath("comparison.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
