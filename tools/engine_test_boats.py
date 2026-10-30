"""Build one test boat per prebuilt diesel (small, medium, large) for in-game engine telemetry.

    uv run tools/engine_test_boats.py [out_dir] [--port 38480]

Each boat is a powertrain build with that engine forced, plus a telemetry microcontroller wired
to the engine (throttle, starter, RPS, temperature), the fuel tank and a linear speed sensor, and
a starter battery. Run tools/telemetry_logger.py, spawn a boat on open water and let it run: it
starts itself, steps the throttle from 10% to 100% (40 s a step) and stops. Writes
"<out_dir>/engine test <size>.xml" and a thumbnail; copy them to the game's vehicles folder.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from swhull import definitions, networks  # noqa: E402
from swhull.build import build, resolve_spec  # noqa: E402
from swhull.editing import identify  # noqa: E402
from swhull.pieces import IDENTITY, Placed, add  # noqa: E402
from swhull.render import render_thumbnail  # noqa: E402
from swhull.telemetry import HOLD_SECONDS, NODES, PORT, STEPS, controller  # noqa: E402
from swhull.vehicle import to_xml  # noqa: E402

HULL = {"deck": "closed", "smoothing": "wedges_v2", "ballast": "auto", "railings": "none", "mooring": "none"}
# Hulls sized for each engine, so the runs also give speed against power per mass.
BOATS = {
    "small": {**HULL, "length": 7.5, "beam": 2.5, "depth": 1.5,
              "stern": {"run": 0.04, "transom_width": 0.85, "fullness": 2.0, "keel_rise": 0.0, "flat_bottom": 0.35}},
    "medium": {**HULL, "length": 12, "beam": 3.75, "depth": 2.25},
    "large": {**HULL, "length": 20, "beam": 6, "depth": 3.5},
}


def deck_spot(parts, cells):
    """Origin where `cells` sit on top of structure, clear of everything, nearest midships."""
    owner = {v: p for p in parts for v in p.voxels()}
    tops = [p.origin for p in parts if p.piece.d == "01_block" and add(p.origin, (0, 1, 0)) not in owner]
    mid = sum(v[2] for v in tops) / len(tops)
    for v in sorted(tops, key=lambda v: (abs(v[0]), abs(v[2] - mid), -v[1])):
        origin = add(v, (0, 1, 0))
        spot = [add(origin, c) for c in cells]
        if all(c not in owner and add(c, (0, -1, 0)) in owner for c in spot) and all(
                add(c, (0, 1, 0)) not in owner for c in spot):
            return origin
    raise ValueError("no clear deck spot")


def port(parts, uid, label, typ):
    p = next(p for p in parts if p.uid == uid)
    found = [n for n in networks.ports(p) if n["label"] == label and n["type"] == typ]
    if len(found) != 1:
        raise ValueError(f"{uid} has no single {label} port")
    return {"part_id": uid, "port": found[0]["index"]}


def boat(size, port_number=PORT, *, run=None, steps=STEPS, hold_seconds=HOLD_SECONDS):
    spec = resolve_spec({**BOATS[size], "fitout": {"stage": "powertrain", "engine_size": size}})
    parts, info = build(spec)
    engines = [p for p in parts if p.piece.d in ("engine", "aircraft_engine", "engine_diesel")]
    if len(engines) != 1:
        raise ValueError(f"{size}: powertrain did not place the engine: {info['warnings']}")
    identify(parts)
    run = run or size
    mc = controller((0, 0, 0), run, port=port_number, steps=steps, hold_seconds=hold_seconds)
    mc.origin = deck_spot(parts, mc.piece.footprint)
    mc.raw_xml = controller(mc.origin, run, port=port_number, steps=steps, hold_seconds=hold_seconds).raw_xml
    parts.append(mc)
    sensor = Placed(definitions.load("linear_speed_sensor"), (0, 0, 0), IDENTITY, "C2C3C7",
                    "telemetry:speed", "speed sensor")
    sensor.origin = deck_spot(parts, sensor.piece.footprint)
    parts.append(sensor)
    battery = next((p for p in parts if p.piece.d.startswith("battery")), None)
    if battery is None:
        battery = Placed(definitions.load("battery_small"), (0, 0, 0), IDENTITY, "C2C3C7",
                         "telemetry:battery", "starter battery")
        battery.origin = deck_spot(parts, battery.piece.footprint)
        parts.append(battery)
    engine, tank = engines[0], next(p for p in parts if p.piece.d == "fluid_tank_medium")
    mc_port = {label: {"part_id": mc.uid, "port": str(i)} for i, (label, *_rest) in enumerate(NODES, 1)}
    links = [
        (port(parts, engine.uid, "RPS", 1), mc_port["Engine RPS"]),
        (port(parts, tank.uid, "Tank Content", 1), mc_port["Fuel tank content"]),
        (port(parts, engine.uid, "Temperature", 1), mc_port["Engine temperature"]),
        (port(parts, sensor.uid, "Linear Speed", 1), mc_port["Linear speed"]),
        (mc_port["Throttle"], port(parts, engine.uid, "Throttle", 1)),
        (mc_port["Starter"], port(parts, engine.uid, "Starter", 0)),
        (port(parts, battery.uid, next(n["label"] for n in networks.ports(battery) if n["type"] == 4), 4),
         port(parts, engine.uid, "Electric", 4)),
    ]
    record = {"connection_edits": [{"op": "connect", "from": a, "to": b} for a, b in links]}
    for row in networks.wires(record, parts):
        networks.wire(parts, row["from"], row["to"], row["link_id"])  # type and direction checks
    xml = networks.write_xml(to_xml(parts), record, parts)
    return xml, parts, info


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("out", nargs="?", default="out")
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--size", action="append", choices=BOATS, help="Generate only this engine size (repeatable)")
    parser.add_argument("--single-step", action="append", type=int, choices=range(1, len(STEPS) + 1),
                        help="Make a separate fresh-tank boat for this throttle step, 1=10%% through 10=100%%")
    parser.add_argument("--hold-seconds", type=int, default=HOLD_SECONDS, help="Seconds at each throttle step (default: 40)")
    args = parser.parse_args()
    if args.hold_seconds < 10:
        parser.error("--hold-seconds must be at least 10")
    os.makedirs(args.out, exist_ok=True)
    for size in args.size or BOATS:
        for step in args.single_step or [None]:
            run = size if step is None else f"{size}_s{step}"
            steps = STEPS if step is None else (STEPS[step - 1],)
            xml, parts, info = boat(size, args.port, run=run, steps=steps, hold_seconds=args.hold_seconds)
            name = os.path.join(args.out, f"engine test {run}")
            with open(f"{name}.xml", "w", encoding="utf-8") as f:
                f.write(xml)
            with open(f"{name}.png", "wb") as f:
                f.write(render_thumbnail(parts))
            print(f"{name}.xml: " + next(c for c in info["components"] if c.startswith("engine size")))
            for w in info["warnings"]:
                print("   ", w)
    print(f"Run: uv run tools/telemetry_logger.py telemetry --port {args.port}")


if __name__ == "__main__":
    main()
