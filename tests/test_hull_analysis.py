"""Subvoxel surfaces must not be confused with editor bounding cells."""
import math

import pytest

from swhull.build import build, resolve_spec
from swhull.hull_analysis import (block_choices, design_depths, reference_structure,
                                 structural_report, vertical_interval)
from swhull.pieces import BLOCK, BY_NAME, IDENTITY, Placed, ROTATIONS, with_mirror
from swhull.vehicle import to_xml


def test_vertical_ray_reports_wedge_material_not_whole_reserved_cell():
    piece = BY_NAME["08_wedge_4"]
    wedge = Placed(piece, (0, 0, 0))
    assert vertical_interval(wedge, 0, -3) == pytest.approx((-0.5, -0.375))
    assert vertical_interval(wedge, 0, 0) == pytest.approx((-0.5, 0.375))
    assert vertical_interval(wedge, 1, 0) is None


@pytest.mark.parametrize("q", ROTATIONS + [with_mirror(IDENTITY, 1)])
def test_rotated_block_ray_keeps_exact_height(q):
    block = Placed(BLOCK, (2, 7, 9), q)
    assert vertical_interval(block, 2, 9) == pytest.approx((6.5, 7.5))


def test_column_gaps_measure_top_of_floor_and_bottom_of_ceiling():
    parts = [Placed(BLOCK, (0, 0, 0)), Placed(BLOCK, (0, 1, 0)), Placed(BLOCK, (0, 10, 0))]
    report = structural_report(parts, [0])
    section = report["sections"][0]
    assert section["material_y_blocks"] == [[-0.5, 1.5], [9.5, 10.5]]
    assert section["gaps"] == [{"floor_surface_y_blocks": 1.5,
                                "ceiling_surface_y_blocks": 9.5, "clear_height_m": 2.0}]


def test_angle_choice_distinguishes_one_slope_from_two_and_flat():
    assert block_choices([0, 1, 0])["choices"][0]["definitions"] == ["01_block"]
    wedge = block_choices([0, 1, 0.25])["choices"][0]
    assert wedge["angle_error_degrees"] == 0
    assert wedge["definitions"] == ["08_wedge_4"]
    corner = block_choices([0.5, 1, 0.25])["choices"][0]
    assert corner["angle_error_degrees"] == 0
    assert corner["definitions"] == ["12_pyramid_2x4", "15_invpyramid_2x4"]


@pytest.mark.parametrize("normal", [[0, 0, 0], [1, 2], [True, 0, 1], [math.inf, 0, 1]])
def test_bad_normal_is_rejected(normal):
    with pytest.raises(ValueError):
        block_choices(normal)


def test_reference_chooses_structural_body_and_preserves_frame():
    xml = to_xml([Placed(BLOCK, (0, 7, 9)), Placed(BLOCK, (0, 8, 9))])
    xml = xml.replace('</bodies>', '<body unique_id="2"><components><c d="sensor"><o><vp/></o>'
                      '</c></components></body></bodies>')
    parts, context = reference_structure(xml)
    assert context["body_id"] == "1"
    assert context["body_count"] == 2
    assert parts[0].origin == (0, 7, 9)
    _, other = reference_structure(xml, "2")
    assert other["excluded_definitions"] == {"sensor": 1}
    with pytest.raises(ValueError, match="body_id"):
        reference_structure(xml, "missing")


def test_floor_drop_varies_with_sheer_and_uses_game_units():
    spec = resolve_spec({"length": 8, "beam": 4, "depth": 2, "deck": "open",
                         "sheer": {"bow": 1, "stern": 0}, "interior": {"decks": [1.75]}})
    _, info = build(spec)
    rows = design_depths(info, [16, 31])
    assert rows[0]["floors"][0]["height_above_keel_m"] == 1.75
    assert rows[0]["floors"][0]["drop_from_rim_m"] < rows[1]["floors"][0]["drop_from_rim_m"]
    assert rows[1]["floors"][0]["drop_from_rim_m"] == 1.25


def test_mirrored_asymmetric_pyramid_material_reflects_exactly():
    pyramid = BY_NAME["12_pyramid_2x4"]
    a = Placed(pyramid, (0, 0, 0))
    b = Placed(pyramid, (0, 0, 0), with_mirror(IDENTITY, 1))
    for x, z in [(0, 0), (-1, -1), (-1, -2)]:
        assert vertical_interval(a, x, z) == vertical_interval(b, -x, z)
