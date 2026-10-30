"""Engine room fit-out, inset propellers/rudders and colour-coded pipes.

The layout copies the player's in-game fix of a generated Mini Speedboat (2026-10): engine low
inside the hull, deck fluid-port intake, exhaust out of the transom above the propeller, the
propeller hub in the transom and the rudder in the bottom row, never past the transom.
"""
import importlib.util
import pathlib
import re
from types import SimpleNamespace
import xml.etree.ElementTree as ET

import pytest

from swhull import definitions, networks, seal, telemetry
from swhull.build import ballast_warnings, build, propulsion_warnings, resolve_spec
from swhull.networks import compact, preflight
from swhull.powertrain import LayoutError, _mirrored_engines, power_target
from swhull.connections import adjacency
from swhull.pieces import BY_NAME, IDENTITY, Placed, add
from swhull.pipe_colours import COLOURS
from swhull.routing import _body_colour, apply_routes
from swhull.vehicle import components_from_text, hex6, placed_from_text

pytestmark = pytest.mark.skipif(definitions.definitions_dir() is None, reason="Stormworks not installed")

SPEEDBOAT = {
    "length": 7.5, "beam": 2.5, "depth": 1.5, "deck": "closed", "smoothing": "blocks",
    "bow": {"entry": 0.4, "fullness": 1.2, "stem_width": 0.0, "rake": 0.5, "rake_curve": 1.6, "flare": 0.1,
            "deadrise": 35},
    "stern": {"run": 0.04, "transom_width": 0.85, "fullness": 2.0, "keel_rise": 0.0, "flat_bottom": 0.35},
    "sheer": {"bow": 0.25, "stern": 0},
    "section": {"deadrise": 14, "bilge_radius": 0, "flare": 0.12, "keel_width": 0.25},
}


def fitted(stage="powertrain", **extra):
    spec = resolve_spec({**SPEEDBOAT, **extra, "fitout": {"stage": stage, **extra.pop("fitout", {})}})
    return build(spec)


def named(parts, d):
    return [p for p in parts if p.piece.d == d]


def stern_z(parts):
    return min(p.origin[2] for p in parts if p.piece.d in BY_NAME)


def test_speedboat_engine_room_matches_the_players_fix():
    parts, info = fitted()
    assert not [w for w in info["warnings"] if "powertrain" in w or "loose" in w or "transom" in w
                or "above the deck" in w]
    (engine,), (prop,), (rudder,) = named(parts, "engine"), named(parts, "propeller"), named(parts, "rudder")
    (exhaust,), (intake,), (tank,) = named(parts, "fluid_exhaust"), named(parts, "water_inlet"), named(parts, "fluid_tank_medium")
    shift, region = info["shift"], info["region"]

    def tag(v):
        return region.get(add(v, shift))

    stern = stern_z(parts)
    # Engine inside the hull, facing aft; the deck closes over it.
    assert all(tag(v) == "hull" for v in engine.voxels())
    assert engine.Q == ((-1, 0, 0), (0, 1, 0), (0, 0, -1))
    # Propeller hub in the transom, blades one cell aft; rudder under the hull, never past the transom.
    assert min(v[2] for v in prop.voxels()) == stern - 1
    assert prop.origin[2] == stern
    assert min(v[2] for v in rudder.voxels()) >= stern
    assert max(v[1] for v in rudder.voxels()) == min(v[1] for v in rudder.voxels()) + 3
    # Exhaust points aft out of the transom directly above the hub; intake sits flush in the deck.
    assert exhaust.origin == (prop.origin[0], prop.origin[1] + 1, stern - 1)
    bottom, top = sorted(intake.voxels(), key=lambda v: v[1])
    assert tag(bottom) == "hull" and tag(top) is None
    assert tank.settings["fluid_type"] == 1 and tank.settings["fluid_fill"] == 1
    # Every engine transmission face is connected.
    _, free = adjacency(parts, 1)
    assert not [f for f in free if f["definition"] in ("engine", "fluid_radiator", "fluid_exhaust", "water_inlet")
                or f["part_id"] == prop.uid]
    # No two parts share a cell.
    cells = [v for p in parts for v in p.voxels()]
    assert len(cells) == len(set(cells))


def test_exposed_pipes_are_colour_coded_and_hull_pipes_take_the_hull_colour():
    parts, _ = fitted()
    by_route = {}
    for p in parts:
        if p.uid.startswith("powertrain:"):
            by_route.setdefault(p.uid.rsplit(":", 1)[0], []).append(p)
    expected = {"shaft": "shaft", "exhaust": "exhaust", "fuel": "fuel", "air": "air",
                "coolant-in": "fresh_water", "coolant-out": "fresh_water"}
    assert set(by_route) == {f"powertrain:{k}" for k in expected}
    for key, medium in expected.items():
        exposed = [p for p in by_route[f"powertrain:{key}"] if not p.piece.d.startswith("trans_block_")]
        assert exposed and {p.color for p in exposed} == {COLOURS[medium]}, key
    enclosed = [p for p in by_route["powertrain:exhaust"] if p.piece.d.startswith("trans_block_")]
    assert enclosed, "the exhaust passes through the transom in an enclosed pipe"
    hull = {p.origin: p.color for p in parts if p.piece.d in BY_NAME}
    for p in enclosed:
        around = {hull[add(p.origin, d)] for d in ((1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0)) if add(p.origin, d) in hull}
        assert p.color in around


def test_propulsion_stage_insets_without_engines_and_keeps_the_shaft_port_clear():
    parts, info = fitted("propulsion")
    assert not named(parts, "engine")
    (prop,) = named(parts, "propeller")
    assert prop.origin[2] == stern_z(parts)
    assert not [w for w in info["warnings"] if "transom" in w or "above the deck" in w]
    occupied = {v for p in parts for v in p.voxels()}
    assert (prop.origin[0], prop.origin[1], prop.origin[2] + 2) not in occupied


def test_twin_engines_are_mirrored_where_they_show():
    parts, info = fitted(beam=4.0, length=9, depth=1.75, fitout={"engines": 2})
    assert not [w for w in info["warnings"] if "powertrain" in w]
    assert len(named(parts, "engine")) == 2
    for d in ("propeller", "rudder", "fluid_exhaust", "water_inlet"):
        a, b = sorted(named(parts, d), key=lambda p: p.origin[0])
        assert a.origin[0] == -b.origin[0] and a.origin[1:] == b.origin[1:], d


def test_catamaran_needs_one_engine_per_hull():
    _, info = build(resolve_spec({"fitout": {"stage": "powertrain"}}, preset="catamaran"))
    assert any("engines=2" in w for w in info["warnings"])
    parts, info = build(resolve_spec({"fitout": {"stage": "powertrain", "engines": 2}}, preset="catamaran"))
    engines = named(parts, "engine")
    assert len(engines) == 2 and engines[0].origin[0] == -engines[1].origin[0]


def test_existing_room_engines_are_reported_not_doubled():
    parts, info = build(resolve_spec({"fitout": {"stage": "powertrain"}}, preset="tugboat"))
    assert any("already places 1 engine" in w for w in info["warnings"])
    assert not named(parts, "engine") and named(parts, "propeller")


def test_hand_placed_machinery_outside_the_hull_is_flagged():
    _, info = fitted("core", components=[{"name": "engine", "definition": "engine", "position": [0, 1.5, 0.6]}])
    assert any(w.startswith("engine 'engine' sits above the deck") for w in info["warnings"])
    parts, info = fitted("structure")
    shift = info["shift"]
    region = {tuple(v[i] - shift[i] for i in range(3)): t for v, t in info["region"].items()}
    stern = stern_z(parts)
    prop = Placed(definitions.load("propeller"), (0, 0, stern - 3), ((1, 0, 0), (0, 0, -1), (0, 1, 0)), name="screw")
    rudder = Placed(definitions.load("rudder"), (0, -6, stern - 1), ((-1, 0, 0), (0, -1, 0), (0, 0, 1)), name="fin")
    warnings = propulsion_warnings([*parts, prop, rudder], region)
    assert any(w.startswith("propeller 'screw' hangs 3 block(s)") for w in warnings)
    assert any(w.startswith("rudder 'fin' reaches 2 block(s)") for w in warnings)
    assert not propulsion_warnings(parts, region)


def test_fitout_engine_count_is_validated():
    with pytest.raises(ValueError, match="engines"):
        fitted(fitout={"engines": 3})


def test_manual_propulsion_cannot_silently_skip_powertrain_or_twin_engines():
    custom = {"propeller": {"position": [0, 0, 0]}}
    with pytest.raises(ValueError, match="requires automatic propeller/rudder"):
        fitted(fitout=custom)
    with pytest.raises(ValueError, match="requires automatic propeller/rudder"):
        fitted("propulsion", fitout={**custom, "engines": 2})


def test_twin_engine_intakes_must_mirror(monkeypatch):
    room = SimpleNamespace(snapshot=lambda: "before", restore=lambda _state: None)
    monkeypatch.setattr("swhull.powertrain._engines", lambda *_args: ([], [(1, 2, 3), (2, 2, 3)]))
    with pytest.raises(LayoutError, match="could not be mirrored"):
        _mirrored_engines(room, [object(), object()], "engine", [])


def test_enclosed_pipe_colour_tie_is_deterministic():
    parts = [Placed(BY_NAME["01_block"], (x, 0, 0), IDENTITY, colour)
             for x, colour in ((-1, "ABCDEF"), (1, "123456"))]
    assert _body_colour(parts, (0, 0, 0)) == "123456"


def test_route_colour_override():
    parts, _ = fitted()
    pairs, _ = adjacency(parts, 1)
    tank_face = next(port["surface_index"] for pair in pairs for port in pair["ports"]
                     if port["part_id"] == "component:fuel tank")
    record = {"route_edits": [{"from": {"part_id": "component:engine", "surface_index": 9},
                               "to": {"part_id": "component:fuel tank", "surface_index": tank_face},
                               "name": "spare", "color": "123abc"}]}
    keep = [p for p in parts if not p.uid.startswith("powertrain:fuel")]
    routed = apply_routes(record, keep)
    assert {p.color for p in routed if p.uid.startswith("route:0")} == {"123ABC"}


def test_short_saved_colours_read_zero_padded():
    assert hex6("E232") == "00E232" and hex6("x") is None
    xml = ('<vehicle data_version="3"><bodies><body unique_id="1"><components>'
           '<c d="trans_straight"><o r="1,0,0,0,1,0,0,0,1" bc="E232" ac="E232" sc="2"><vp x="1"/></o></c>'
           '</components></body></bodies></vehicle>')
    assert next(components_from_text(xml))[3] == "00E232"
    parts, _ = placed_from_text(xml)
    assert parts[0].color == "00E232"


def test_engine_size_follows_power_per_mass_and_the_medium_engine_stands_on_beds():
    spec = resolve_spec({"fitout": {"stage": "powertrain"}}, preset="fishing_trawler")
    parts, info = build(spec)
    (engine,) = [p for p in parts if p.piece.d in ("engine", "aircraft_engine", "engine_diesel")]
    mass, hull_type, need = power_target(info)
    assert hull_type == "displacement" and 20 < need < 60
    assert engine.piece.d == "aircraft_engine"  # the smallest that meets the target
    assert any(c.startswith("engine size: 1 x Medium Engine = 60 kW") for c in info["components"])
    assert len([p for p in parts if p.piece.d == "fluid_exhaust"]) == 2  # one outlet per exhaust port
    # A boat's preflight: no clutch or gearbox demanded, a fluid port counts as the air intake.
    report = preflight({"spec": spec}, parts)
    missing = {c["system"] for c in report["checks"] if c["status"] == "missing" and c["part_id"] == engine.uid}
    assert not missing & {"drivetrain", "air", "exhaust", "fuel", "cooling loop", "drivetrain control parts"}
    spare = Placed(definitions.load("wheel_advanced_3_sus"), (1000, 0, 0), IDENTITY, name="spare wheel")
    with_spare = preflight({"spec": spec}, [*parts, spare])
    assert not [c for c in with_spare["checks"] if c["part_id"] == engine.uid
                and c["system"] == "drivetrain control parts"]
    short = compact(report)
    assert all(c["status"] != "connected" for c in short["checks"])
    assert all(not f["suggested_operations"] for f in short["findings"])


def test_a_forced_engine_that_does_not_fit_says_why():
    _, info = fitted(fitout={"engine_size": "large"})
    assert any("powertrain skipped" in w and "Large Engine" in w for w in info["warnings"])
    with pytest.raises(ValueError, match="engine_size"):
        fitted(fitout={"engine_size": "huge"})


def test_unmounted_component_error_names_the_faces_and_the_fix():
    with pytest.raises(ValueError, match=r"no verified mounting contact: mount faces: .* facing \[0, -1, 0\]"):
        fitted("core", components=[{"name": "floating", "definition": "aircraft_engine", "position": [0, 3, 0]}])


def test_seal_checks_every_hull_space_and_trusts_the_rudder_plate():
    parts, info = fitted()
    shift = info["shift"]
    for p in parts:
        p.origin = tuple(p.origin[i] + shift[i] for i in range(3))
    seeds = seal.auto_seeds(parts, info)
    assert seeds and all(s["name"].startswith("hull") for s in seeds)
    result = seal.check(parts, seeds)
    assert result["status"] == "sealed", result["compartments"]


def test_ballast_warnings_flag_capsizing_and_the_cap():
    state = {"plane": 4.0, "gm": -2.0, "beam": 12.0}
    report = {"shortfall": "stopped at the limit of 40 weight blocks before it could lower the centre of mass",
              "after": state, "bottom": -0.5, "waterline": 4.5}
    warnings = ballast_warnings(report)
    assert warnings[0].startswith("ballast stopped at the limit")
    assert any(w.startswith("unstable: metacentric height -0.50 m") for w in warnings)
    assert any(w.startswith("low stability margin") for w in ballast_warnings({**report, "after": {**state, "gm": 0.8}}))


def test_telemetry_controller_parses_and_its_boat_is_wired():
    lua = telemetry.script("small")
    assert "async.httpGet(PORT" in lua and 'RUN = "small"' in lua and "--" not in lua
    root = ET.fromstring(telemetry.definition_xml("small"))
    assert [n.find("node").get("label") for n in root.findall("nodes/n")] == [n[0] for n in telemetry.NODES]
    # A plain XML parser folds attribute newlines into spaces; the script is written to survive that.
    assert root.find(".//c[@type='56']/object").get("script").split() == lua.split()
    mc = telemetry.controller((0, 0, 0), "small")
    assert [(n["label"], n["type"], n["mode"]) for n in networks.ports(mc)] == [n[:3] for n in telemetry.NODES]
    path = pathlib.Path(__file__).parent.parent / "tools" / "engine_test_boats.py"
    spec = importlib.util.spec_from_file_location("engine_test_boats", path)
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    xml, parts, _ = tool.boat("small")
    assert len(re.findall(r"<logic_node_link[ >]", xml)) == 7 and "microprocessor_definition" in xml
    cells = [v for p in parts for v in p.voxels()]
    assert len(cells) == len(set(cells))
    _, resumed_parts, _ = tool.boat("small", run="small_s8", steps=(0.8,), hold_seconds=30)
    raw = next(p.raw_xml for p in resumed_parts if p.uid == "telemetry:small_s8")
    lua = ET.fromstring(raw).find(".//c[@type='56']/object").get("script")
    assert 'RUN = "small_s8"' in lua and "STEPS = {0.8}" in lua and "HOLD = 1800" in lua
