"""The modular engine builder (place_modular_engine) and the preflight fixes learned from the
player's modular engine examples."""
import functools

import anyio
import pytest

import server
from swhull import definitions, engine_builder, modular, networks
from swhull.connections import transmission_ports
from swhull.editing import VehicleDocument, apply_edits, part
from swhull.physics import Model, grouped
from swhull.pieces import BLOCK, Placed
from swhull.vehicle import to_xml
from tool_results import unpack

installed = pytest.mark.skipif(not definitions.metadata("modular_engine_crankshaft"),
                               reason="installed modular engine definitions required")


def build(**spec):
    return engine_builder.place([], {"op": "engine", "position": [0, 0, 0], **spec}, "edit:0")


def size(parts):
    cells = [v for p in parts for v in p.voxels()]
    return [max(v[a] for v in cells) - min(v[a] for v in cells) + 1 for a in range(3)]


LAYOUTS = [
    {"size": 1, "cylinders": 1}, {"size": 1, "cylinders": 5},
    {"size": 1, "cylinders": 7, "banks": ["top", "right", "bottom", "left"], "flywheel": True, "alternators": 2},
    {"size": 1, "cylinders": 6, "banks": ["left", "right"]}, {"size": 1, "cylinders": 9, "banks": ["left", "top", "right"]},
    {"size": 3, "cylinders": 1}, {"size": 3, "cylinders": 4, "banks": ["left", "right"]},
    {"size": 3, "cylinders": 6, "banks": ["top", "right"], "temperature_sensor": True},
    {"size": 3, "cylinders": 8, "banks": ["top", "right", "bottom", "left"], "starters": 4, "alternators": 2},
    {"size": 5, "cylinders": 2, "flywheel": True}, {"size": 5, "cylinders": 4, "banks": ["left", "right"], "air_rams": True},
    {"size": 1, "cylinders": 3, "coolant": False, "air_rams": True, "output": "-x", "top": "+z"},
]


@installed
@pytest.mark.parametrize("spec", LAYOUTS)
def test_every_layout_is_one_coupled_engine_with_every_cylinder_fed(spec):
    parts = build(**spec)  # place() refuses an engine that fails the coupling model
    groups, pairs = modular.engines(parts)
    assert len(groups) == 1
    feeds = modular._feeds(groups[0], pairs)
    assert len(feeds) == spec["cylinders"]
    need = {"air", "fuel", "exhaust"} | ({"coolant"} if spec.get("coolant", True) else set())
    assert all(need <= f for f in feeds.values())
    starters = sum(p.piece.d == "modular_engine_starter" for p in parts)
    assert starters == spec.get("starters", engine_builder.MIN_STARTERS[spec["size"]])
    assert min(v[a] for p in parts for v in p.voxels() for a in range(3) if a == 0) == 0


@installed
def test_four_bank_1x1_engine_is_the_players_compact_ring():
    parts = build(size=1, cylinders=4, banks=["top", "right", "bottom", "left"])
    assert size(parts)[:2] == [3, 3]
    bridges = [p for p in parts if "bridge" in p.name]
    # Neighbouring banks meet in a corner cell of the 3x3 cross-section: one corner each.
    assert len(bridges) == 3 and all(p.piece.d == "modular_engine_manifold_corner" for p in bridges)


@installed
def test_opposed_3x3_banks_are_bridged_by_a_manifold_run_like_the_players_engine():
    parts = build(size=3, cylinders=4, banks=["left", "right"])
    bridges = sorted(p.piece.d for p in parts if "bridge" in p.name)
    assert bridges.count("modular_engine_manifold_corner") == 2 and "modular_engine_manifold_straight" in bridges


@installed
@pytest.mark.parametrize("output, top", [("+z", "+y"), ("-x", "+y"), ("+x", "+z"), ("-y", "+x")])
def test_power_output_faces_the_requested_direction(output, top):
    parts = build(size=3, cylinders=2, output=output, top=top)
    clutch = next(p for p in parts if p.piece.d == "modular_engine_clutch_3x3")
    assert [f["normal"] for f in transmission_ports(clutch)] == [engine_builder.DIRECTIONS[output]]
    cylinder = next(p for p in parts if p.piece.d == "modular_engine_piston_3x3")
    crank = next(p for p in parts if p.piece.d == "modular_engine_crankshaft_3x3")
    offset = tuple(a - b for a, b in zip(cylinder.origin, crank.origin))
    assert offset == tuple(3 * c for c in engine_builder.DIRECTIONS[top])


@installed
@pytest.mark.parametrize("spec, message", [
    ({"size": 1, "cylinders": 2, "banks": ["top", "left", "right"]}, "at least 3 cylinders"),
    ({"size": 2}, "size must be 1, 3 or 5"),
    ({"size": 1, "banks": ["up"]}, "banks must list"),
    ({"size": 1, "output": "+y", "top": "+y"}, "perpendicular"),
    ({"size": 1, "starters": 3, "alternators": 2}, "no free socket"),
])
def test_bad_engine_requests_are_refused(spec, message):
    with pytest.raises(ValueError, match=message):
        build(**spec)


@installed
def test_engine_operation_refuses_overlap_and_replays_from_the_record():
    base = [part({"position": [x, -1, z]}, f"b{x},{z}") for x in range(-2, 9) for z in range(-2, 9)]
    op = {"op": "engine", "size": 1, "cylinders": 3, "position": [0, 0, 0]}
    first = apply_edits(base, [op])
    again = apply_edits(base, [op])
    assert [(p.piece.d, p.origin, p.Q) for p in first] == [(p.piece.d, p.origin, p.Q) for p in again]
    with pytest.raises(ValueError, match="overlaps"):
        apply_edits(base, [{**op, "position": [0, -1, 0]}])


@installed
def test_place_modular_engine_tool_end_to_end(tmp_path, monkeypatch):
    vehicles, designs = tmp_path / "vehicles", tmp_path / "designs"
    vehicles.mkdir()
    monkeypatch.setenv("SW_VEHICLES_DIR", str(vehicles))
    monkeypatch.setenv("SW_DESIGNS_DIR", str(designs))
    plate = [Placed(BLOCK, (x, -1, z)) for x in range(-6, 7) for z in range(-8, 9)]
    (vehicles / "plate.xml").write_text(to_xml(plate), encoding="utf-8")

    def call(tool, *a, **k):
        return anyio.run(functools.partial(tool, *a, **k))

    call(server.import_vehicle, "plate", "bench")
    rev = call(server.query_parts, "bench", limit=1)["revision"]
    _, _, res = unpack(call(server.place_modular_engine, "bench", 1, [-1, 0, -4], cylinders=4,
                            banks=["left", "top", "right"], alternators=1, revision=rev, commit=True))
    assert res["committed"] and res["attached"] and res["cylinders"] == 4 and res["alternators"] == 1
    names = {p["name"] for p in res["points"]}
    assert {"power output (RPS)", "air in", "fuel in", "exhaust out", "coolant loop end"} <= names
    report = call(server.preflight_vehicle, "bench", detail=True)
    assert report["modular_engines"][0]["cylinders"] == 4
    assert not [c for c in report["checks"] if c["system"] in ("modular engine cylinders", "modular engine manifolds",
                                                               "modular engine starter", "modular engine clutch")
                and c["status"] == "missing"]


# --- preflight fixes from the player's examples ------------------------------------------


@installed
def test_power_passes_through_a_circuit_breaker_and_a_diode_one_way():
    battery = part({"definition": "battery_small", "position": [0, 0, 0]}, "bat")
    breaker = part({"definition": "electric_curcuit_breaker", "position": [2, 0, 0]}, "brk")
    starter = part({"definition": "modular_engine_starter", "position": [4, 0, 0]}, "st")
    nodes = {p.uid: {n["label"]: n["index"] for n in networks.ports(p) if n["type"] == 4}
             for p in (battery, breaker, starter)}

    def wire(a, la, b, lb):
        return {"type": 4, "from": {"part_id": a, "port": nodes[a][la]}, "to": {"part_id": b, "port": nodes[b][lb]}}

    links = [wire("bat", "Electric Store", "brk", "Electric A"), wire("brk", "Electric B", "st", "Electric")]
    powered = networks.powered_nodes([battery, breaker, starter], links)
    assert ("st", str(nodes["st"]["Electric"])) in powered


@installed
def test_fluid_passes_through_an_impeller_pump_but_not_between_heat_exchanger_circuits():
    pump = part({"definition": "turbocharger_small", "position": [0, 0, 0]}, "pump")
    exchanger = part({"definition": "air_exchanger", "position": [5, 0, 0]}, "hx")
    graph = modular.through_valves({}, [pump, exchanger], transmission_ports)
    fluid = [(f["part_id"], f["surface_index"]) for f in transmission_ports(pump) if f["trans_type"] == 2]
    assert fluid[1] in graph[fluid[0]]
    labels = {n["label"]: n["position"] for n in networks.ports(exchanger) if n["type"] == 3}
    faces = {(f["part_id"], f["surface_index"]): f["position"] for f in transmission_ports(exchanger)}
    air = [k for k, v in faces.items() if v in (labels["Air In"], labels["Air Out"])]
    water = [k for k, v in faces.items() if v in (labels["Fluid In"], labels["Fluid Out"])]
    assert not any(w in graph[a] for a in air for w in water if a != w)


@installed
def test_temperature_sensor_in_a_cylinder_hole_joins_the_engine():
    parts = build(size=3, cylinders=2, temperature_sensor=True)
    groups, _ = modular.engines(parts)
    assert any(p.piece.d == modular.SENSOR for p in groups[0])


@installed
def test_premade_tank_without_a_fluid_setting_holds_diesel_and_blocked_ends_are_notes():
    tank = part({"definition": "fluid_tank_small", "position": [0, 0, 0]}, "tank")
    doc = VehicleDocument.parse(to_xml([tank]))
    assert Model(grouped(doc.parts)).tanks[0]["fluid"] == "diesel"
    pipe = part({"definition": "trans_straight", "position": [0, 0, 0]}, "pipe")
    wall = [part({"position": list(v)}, f"w{i}") for i, v in enumerate(((0, 1, 0), (0, -1, 0), (1, 0, 0), (-1, 0, 0),
                                                                          (0, 0, 1), (0, 0, -1)))]
    report = networks.preflight({"kind": "imported", "source_xml": to_xml([pipe, *wall])}, [pipe, *wall])
    assert not [i for i in report["issues"] if i["issue"] == "blocked transmission face"]
    assert report["blocked_faces"]
