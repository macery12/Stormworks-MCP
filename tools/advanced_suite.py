"""Analyze saved vehicles, generate full rotation exhibits, and record in-game observations."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from swhull import definitions  # noqa: E402
from swhull.calibration import generate, record_observation  # noqa: E402
from swhull.reference import audit_text  # noqa: E402
from swhull.render import render_png  # noqa: E402
from swhull.vehicle import vehicles_dir  # noqa: E402

PRIORITY = ["rudder", "rudder_surface", "propeller", "engine", "trans_straight", "trans_angle", "trans_block_straight"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    audit = commands.add_parser("audit", help="Create read-only reference inventory, links and example corpus")
    audit.add_argument("--vehicle", default="attack boat", help="Saved vehicle name or XML path")
    audit.add_argument("--output", type=Path, default=Path("out/advanced-suite"))
    audit.add_argument("--samples", type=int, default=100, help="Distinct rotation/settings examples per definition, 1-100")
    calibrate = commands.add_parser("calibrate", help="All 24 rotations plus 24 mirrors per selected definition")
    calibrate.add_argument("--definition", action="append", help="Repeat for multiple parts; defaults to boat propulsion parts")
    calibrate.add_argument("--all-parts", action="store_true", help="Generate every installed definition")
    calibrate.add_argument("--output", type=Path, default=Path("out/advanced-suite/calibration"))
    calibrate.add_argument("--preview", action="store_true")
    observation = commands.add_parser("observe", help="Append a player observation, bound to an unchanged exhibit")
    observation.add_argument("manifest", type=Path)
    observation.add_argument("case_id")
    observation.add_argument("--check", required=True, choices=["mounting", "orientation", "motion", "connections", "spawn"])
    observation.add_argument("--result", required=True, choices=["pass", "fail", "uncertain"])
    observation.add_argument("--note", default="")
    args = parser.parse_args()
    if args.command == "observe":
        print(json.dumps(record_observation(args.manifest, args.case_id, args.check, args.result, args.note), indent=2))
        return
    args.output.mkdir(parents=True, exist_ok=True)
    if args.command == "audit":
        path = Path(args.vehicle)
        if not path.is_file():
            if Path(args.vehicle).name != args.vehicle or any(c in args.vehicle for c in "/\\"):
                parser.error("vehicle must be an existing XML path or a saved vehicle name")
            path = Path(vehicles_dir()) / f"{args.vehicle}.xml"
        report = audit_text(path.read_text(encoding="utf-8"), path.stem, args.samples)
        (args.output / "reference-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        with (args.output / "examples.jsonl").open("w", encoding="utf-8") as f:
            for part in report["parts"]:
                for sample in part["samples"]:
                    f.write(json.dumps({"definition": part["definition"], "source_sha256": report["source_sha256"],
                                        "evidence_level": report["evidence_level"], **sample}) + "\n")
        print(f"{report['part_count']} parts, {report['distinct_definitions']} definitions, "
              f"{report['body_count']} bodies, {report['link_count']} links")
        print(f"Definition coverage: {report['definition_coverage']['fraction']:.1%}; "
              f"rudder inspection issues: {len(report['placement_issues'])}")
        print(f"Reports: {args.output.resolve()}")
        return
    chosen = args.definition or PRIORITY
    if args.all_parts:
        base = definitions.definitions_dir()
        if base is None:
            parser.error("--all-parts requires installed definitions")
        chosen = sorted(p.stem for p in Path(base).glob("*.xml"))
    for d in chosen:
        placed, xml, manifest = generate(d)
        path = args.output / f"calibration-{d}"
        path.with_suffix(".xml").write_bytes(xml.encode())
        path.with_suffix(".json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        if args.preview:
            path.with_suffix(".png").write_bytes(render_png(placed, title=f"{d}: all rotations and mirrors"))
        print(f"{d}: {len(manifest['cases'])} numbered cases, {path.with_suffix('.xml')}")


if __name__ == "__main__":
    main()
