"""Static physics estimates: buoyancy formula, exact volumes, flotation, tanks and the tool."""
import functools
from itertools import product

import anyio
import pytest
from mcp.server.mcpserver.exceptions import ToolError

import server
from swhull import game_constants
from swhull.physics import Model, analyze, buoyancy_mass, piece_volume
from swhull.pieces import BLOCK, BY_NAME, Piece, Placed
from tool_results import unpack

WEIGHT = BY_NAME["01_block_weight"]


def call(tool, *args, **kwargs):
    return anyio.run(functools.partial(tool, *args, **kwargs))


def hollow_box(x=(-3, 2), y=(0, 3), z=(0, 7)):
    """A sealed box hull of blocks with an empty inside."""
    return [Placed(BLOCK, v, uid=f"b{i}") for i, v in enumerate(
        v for v in product(range(x[0], x[1] + 1), range(y[0], y[1] + 1), range(z[0], z[1] + 1))
        if v[0] in x or v[1] in y or v[2] in z)]


def test_buoyancy_mass_follows_the_base_game_constants():
    assert game_constants.GAME_CONSTANTS["buoyancy_mass_multiplier"] == 10.0
    assert buoyancy_mass(1000) == 10_000             # below the lower bound: x10
    assert buoyancy_mass(2000) == 20_000
    assert buoyancy_mass(13_500) == pytest.approx(13_500 * 15)   # halfway up the ramp
    assert buoyancy_mass(40_000) == 40_000 * 20      # ramp capped at 1


def test_slope_pieces_count_by_their_exact_volume():
    assert piece_volume("01_block") == pytest.approx(1)
    assert piece_volume("02_wedge") == pytest.approx(0.5)
    assert piece_volume("03_pyramid") == pytest.approx(1 / 6)
    assert piece_volume("04_invpyramid") == pytest.approx(5 / 6)
    assert piece_volume("08_wedge_4") == pytest.approx(2)
    model = Model([("1", [Placed(BY_NAME["02_wedge"], (0, 0, 0))])])
    assert model.solid_m3 == pytest.approx(0.5 * game_constants.CELL_M3)


def test_a_sealed_box_floats_level_at_the_draft_its_weight_needs():
    hull = hollow_box()
    model = Model([("1", hull)])
    inside = 4 * 2 * 6
    assert model.air_m3 == pytest.approx(inside * game_constants.CELL_M3)
    row = model.solve({})
    mass = len(hull)
    assert row["floats"] and row["mass"] == mass
    expected = buoyancy_mass(mass) / 1000 / (6 * 8 * 0.25 ** 2)    # prism: volume / waterplane area
    assert row["draft_m"] == pytest.approx(expected, abs=0.04)
    assert abs(row["trim_deg"]) < 0.5 and abs(row["heel_deg"]) < 0.5 and row["stable"]


def test_off_centre_weight_heels_and_trims_toward_it():
    hull = hollow_box()
    weights = [Placed(WEIGHT, (1, 1, 6)), Placed(WEIGHT, (1, 1, 5))]   # +x side, near the +z end
    row = Model([("1", hull + weights)]).solve({})
    assert row["floats"] and row["heel_deg"] > 0.5 and row["trim_deg"] < -0.2


def test_a_vehicle_heavier_than_its_volume_sinks():
    solid = [Placed(WEIGHT, v) for v in product(range(2), range(2), range(2))]
    row = Model([("1", solid)]).solve({})
    assert not row["floats"] and row["reserve_buoyancy_pct"] < 0 and "sinks" in row["summary"]


def test_block_built_tank_holds_its_pocket_and_defaults_to_diesel():
    hull = hollow_box()
    wall = [Placed(BLOCK, (x, y, 4), uid=f"w{x}{y}") for x in range(-2, 2) for y in range(1, 3)]
    # The real Fluid Spawner is two voxels: a sealed base and a marker above it.
    spawner = Placed(Piece("water_spawner", 6, 1.0, ((0, 0, 0), (0, 1, 0)), BLOCK.verts, BLOCK.faces), (0, 1, 5),
                     uid="spawner", settings={"fluid_fill": "0.5"})
    model, report = analyze([("1", hull + wall + [spawner])])
    tank = report["tanks"][0]
    pocket = 4 * 2 * 2      # x -2..1, y 1..2, z 5..6
    assert tank["kind"] == "custom" and tank["fluid"] == "diesel" and tank["saved_fill"] == 0.5
    # With game definitions the spawner's sealed base cell is not fluid space; without, it is.
    assert tank["litres"] / game_constants.CELL_LITRES == pytest.approx(pocket, abs=1)
    flotation = report["flotation"]
    fluid = tank["litres"] * game_constants.FLUID_MASS_PER_LITRE
    assert flotation["full"]["mass"] == pytest.approx(flotation["empty"]["mass"] + fluid)
    assert flotation["as_saved"]["mass"] == pytest.approx(flotation["empty"]["mass"] + fluid / 2)
    assert flotation["full"]["draft_m"] > flotation["empty"]["draft_m"]
    _, custom = analyze([("1", hull + wall + [spawner])], tank_fill={tank["name"]: 0.25})
    assert custom["flotation"]["custom"]["tank_fill"][tank["name"]] == 0.25
    with pytest.raises(ValueError, match="no tank named"):
        analyze([("1", hull)], tank_fill={"missing": 1})


def test_multi_body_masses_are_reported_per_body():
    hull = hollow_box()
    arm = [Placed(BLOCK, (0, 4, 3), uid="a"), Placed(BLOCK, (0, 5, 3), uid="b")]
    _, report = analyze([("1", hull), ("7", arm)])
    bodies = {b["body_id"]: b for b in report["mass"]["bodies"]}
    assert bodies["7"]["mass"] == 2 and bodies["7"]["centre_of_mass_m"] == [0.0, 1.125, 0.75]
    assert report["mass"]["empty_mass"] == len(hull) + 2


def test_physics_tool_reads_drafts_and_never_writes(tmp_path, monkeypatch):
    vehicles, designs = tmp_path / "vehicles", tmp_path / "designs"
    vehicles.mkdir()
    monkeypatch.setenv("SW_VEHICLES_DIR", str(vehicles))
    monkeypatch.setenv("SW_DESIGNS_DIR", str(designs))
    server.store_design("boat", preset="rowboat")
    before = sorted(p.name for p in tmp_path.rglob("*"))
    image, notes, report = unpack(call(server.analyze_physics, design="boat"))
    assert image[:4] == b"\x89PNG" and "empty:" in notes
    assert set(report["flotation"]) == {"empty", "full", "as_saved"}
    assert "waterline" not in report["flotation"]["empty"] and report["provisional"]
    assert sorted(p.name for p in tmp_path.rglob("*")) == before
    with pytest.raises(ToolError, match="exactly one"):
        call(server.analyze_physics)
    with pytest.raises(ToolError, match="no tank named"):
        call(server.analyze_physics, design="boat", tank_fill={"nope": 1})
