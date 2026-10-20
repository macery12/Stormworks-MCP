"""Construction metrics and reference scorecards, on synthetic vehicles without game files."""
import functools

import anyio
import pytest
from mcp.server.mcpserver.exceptions import ToolError

import server
from swhull import definitions
from swhull.study import scorecard, study_text
from swhull.tool_schemas import ReferenceVehicle

IDENTITY = "1,0,0,0,1,0,0,0,1"


@pytest.fixture(autouse=True)
def no_game(tmp_path, monkeypatch):
    # Unknown components fall back to one-cell footprints, so results don't depend on an install.
    empty = tmp_path / "definitions"
    empty.mkdir()
    monkeypatch.setattr(definitions, "definitions_dir", lambda: str(empty))
    definitions.load.cache_clear()
    definitions.metadata.cache_clear()
    yield
    definitions.load.cache_clear()
    definitions.metadata.cache_clear()


def part(d, x=0, y=0, z=0, colours=("C2C3C7",)):
    sc = f"{len(colours)}," + ",".join(colours)
    return f'<c d="{d}"><o r="{IDENTITY}" sc="{sc}"><vp x="{x}" y="{y}" z="{z}"/></o></c>'


def vehicle(*bodies):
    inner = "".join(f'<body unique_id="{i + 1}"><components>{"".join(b)}</components></body>'
                    for i, b in enumerate(bodies))
    return f'<vehicle data_version="3"><bodies>{inner}</bodies><logic_node_links/></vehicle>'


def test_slope_sizes_and_pyramid_pairing():
    s = study_text(vehicle([part("03_pyramid"), part("04_invpyramid", x=1), part("03_pyramid", x=5),
                            part("02_wedge", x=8), part("08_wedge_4", x=12), part("01_block", y=5)]))
    m = s["metrics"]
    assert s["counts"]["slopes_by_size"] == {"1x1": 4, "1x4": 1}
    assert m["slope_small_share"] == 0.8 and m["slope_large_share"] == 0.2
    assert m["pyramid_paired_share"] == 0.5  # the pyramid at x=5 stands alone


def test_ballast_height_and_rate_use_the_main_body():
    column = [part("01_block", y=y) for y in range(1, 10)]
    s = study_text(vehicle(column + [part("01_block_weight", y=0)], [part("01_block_weight", y=50)]))
    assert s["metrics"]["ballast_height"] == 0.0
    assert s["counts"]["weight_blocks"] == 2 and s["counts"]["bodies"] == 2
    assert s["metrics"]["ballast_per_1k"] == round(2 * 1000 / 11, 4)


def test_pipes_split_by_whether_their_run_reaches_equipment():
    working = [part("trans_straight", z=z) for z in range(3)] + [part("battery_small", z=3)]
    decor = [part("trans_straight", x=10, z=z) for z in range(4)]
    rail_end = [part("handle", x=10, z=4)]  # detail parts are not equipment
    s = study_text(vehicle(working + decor + rail_end + [part("01_block", y=9)]))
    assert s["counts"]["pipes_reaching_equipment"] == 3
    assert s["counts"]["pipes_decorative_estimate"] == 4
    assert s["counts"]["detail"] == {"pipes": 7, "handles": 1}


def test_paint_counts_patterns_and_multi_colour_parts():
    s = study_text(vehicle([part("01_block", colours=("FF0000",) * 6),
                            part("01_block", x=1, colours=("FF0000",) * 5 + ("00FF00",)),
                            part("01_block", x=2, colours=("FF0000",) * 6)]))
    assert s["counts"]["paint_colours"] == 2
    assert s["metrics"]["multi_colour_share"] == round(1 / 3, 4)
    assert s["metrics"]["paint_variants_per_1k"] == round(2 * 1000 / 3, 4)


def test_kind_detection_and_override():
    wheels = [part("wheel_advanced_5_sus", x=x * 10) for x in range(4)] + [part("01_block", y=9)]
    assert study_text(vehicle(wheels))["kind"] == "land"
    assert study_text(vehicle(wheels + [part("rudder", y=20)]))["kind"] == "boat"
    assert study_text(vehicle(wheels), kind="other")["kind"] == "other"
    with pytest.raises(ValueError, match="kind must be"):
        study_text(vehicle(wheels), kind="plane")


def test_scorecard_statuses_hints_and_kind_mismatch():
    refs = [{"kind": "boat", "metrics": {"slope_small_share": 0.4, "ballast_per_1k": 10.0, "detail_per_1k": 50.0}},
            {"kind": "boat", "metrics": {"slope_small_share": 0.6, "ballast_per_1k": 30.0, "detail_per_1k": 90.0}}]
    study = {"kind": "boat", "metrics": {"slope_small_share": 0.1, "ballast_per_1k": 20.0, "detail_per_1k": None}}
    card = scorecard(study, refs)
    rows = {r["metric"]: r for r in card["metrics"]}
    assert rows["slope_small_share"]["status"] == "below" and "1x1" in rows["slope_small_share"]["hint"]
    assert rows["ballast_per_1k"]["status"] == "within" and "hint" not in rows["ballast_per_1k"]
    assert rows["detail_per_1k"]["status"] == "not_applicable"
    assert (card["within"], card["scored"]) == (1, 2)
    with pytest.raises(ValueError, match="no references of kind 'land'"):
        scorecard(study, refs, kind="land")


def call(tool, *args, **kwargs):
    return anyio.run(functools.partial(tool, *args, **kwargs))


def test_tools_store_a_set_and_score_against_it(tmp_path, monkeypatch):
    vehicles = tmp_path / "vehicles"
    vehicles.mkdir()
    monkeypatch.setenv("SW_VEHICLES_DIR", str(vehicles))
    monkeypatch.setenv("SW_DESIGNS_DIR", str(tmp_path / "designs"))
    monkeypatch.setenv("SW_REFERENCES_DIR", str(tmp_path / "sets"))
    hull = [part("01_block", x=x) for x in range(8)]
    (vehicles / "Expert.xml").write_text(vehicle(hull + [part("02_wedge", y=1), part("01_block_weight", y=-1)]),
                                         encoding="utf-8")
    (vehicles / "Plain.xml").write_text(vehicle(hull), encoding="utf-8")

    out = call(server.study_references, [ReferenceVehicle(name="Expert", label="Good boat", kind="boat")],
               save_as="veteran")
    assert out["references"][0]["label"] == "Good boat"
    assert (tmp_path / "sets" / "veteran.json").is_file()
    assert out["ranges"]["boat"]["ballast_per_1k"]["references"] == 1

    card = call(server.score_vehicle, "veteran", name="Plain", kind="boat")
    rows = {r["metric"]: r["status"] for r in card["metrics"]}
    assert rows["ballast_per_1k"] == "below" and rows["slope_share"] == "below"
    assert card["counts"]["parts"] == 8

    with pytest.raises(ToolError, match="stored sets: veteran"):
        call(server.score_vehicle, "missing", name="Plain")
    with pytest.raises(ToolError, match="not both"):
        call(server.score_vehicle, "veteran", name="Plain", preset="tugboat")
