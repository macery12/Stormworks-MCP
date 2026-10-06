"""Render separate deliberate faults and export an untested Humvee baseline.

Run: uv run tools/diagnostic_milestone.py out/diagnostic-review
Needs installed definitions. Writes only to the requested output directory.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from swhull.diagnostic_view import preview  # noqa: E402
from swhull.drafts import edited, materialize  # noqa: E402
from swhull.editing import revision  # noqa: E402
from swhull.jobs import diagnostic_geometry  # noqa: E402
from swhull.networks import edited as wire_edit, ports, template_wires, wires  # noqa: E402
from swhull.repairs import plan, repair  # noqa: E402
from swhull.validation import prepare  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    record = {"kind": "land", "spec": {"preset": "humvee_4x4", "bench": "S"}, "generation": 0}
    parts, _ = materialize(record)
    record["base_connections"] = template_wires(record, parts)
    target = (args.output / "Humvee diagnostics baseline.xml").resolve()
    xml, manifest = prepare(record, "Humvee diagnostics baseline", "Humvee diagnostics baseline", target)
    target.write_bytes(xml.encode("utf-8"))
    (args.output / "validation.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    for kind in ("fuel", "starter", "steering"):
        if kind == "fuel":
            pipe = next(p for p in parts if p.name == "fuel line")
            broken = edited(record, [{"op": "remove", "select": {"ids": [pipe.uid]}}])
        else:
            component = next(p for p in parts if p.name == ("diesel engine" if kind == "starter" else "front left wheel"))
            label = "Starter" if kind == "starter" else "Steering"
            node = next(n for n in ports(component) if n["label"] == label)
            link = next(link for link in wires(record, parts) if link.get("to") == {"part_id": component.uid, "port": node["index"]})
            ops = [{"op": "disconnect", "link_id": link["link_id"]}]
            if kind == "steering":
                driver = next(p for p in parts if p.name == "driver")
                axis = next(n for n in ports(driver) if n["label"].startswith("Axis 1"))
                ops.append({"op": "connect", "from": {"part_id": driver.uid, "port": axis["index"]}, "to": link["to"]})
            broken = wire_edit(record, ops, parts)
        proposal = plan(broken)
        ids = [f["finding_id"] for f in proposal["findings"] if f["repair_status"] == "available"]
        fixed, report = repair(broken, proposal["plan_id"], ids)
        assert not report["after"]["findings"], report
        png, _ = preview(broken, f"{kind} fault and repair", fixed, pitch=-15)
        (args.output / f"{kind}-repair.png").write_bytes(png)
        (args.output / f"{kind}-plan.json").write_text(json.dumps({"plan": proposal, "result": report}, indent=2), encoding="utf-8")
        print(f"{kind}: repair preview rendered; no remaining findings; base {revision(broken)}")
    from server import _viewer_page  # noqa: PLC0415
    text, geometry = diagnostic_geometry(broken)
    page = _viewer_page(text, "Steering fault diagnostics", geometry)
    (args.output / "steering-viewer.html").write_bytes(page.read_bytes())
    print(f"Untested Humvee baseline: {target}; SHA-256 {manifest['export_sha256']}")


if __name__ == "__main__":
    main()
