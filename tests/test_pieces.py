"""Rotation convention and piece catalogue (verified in game: all 40 test orientations)."""
from swhull.pieces import (INVPYRAMID, PYRAMID, ROTATIONS, WEDGE, WEDGE2, WEDGE4, apply, parse_r,
                           r_attr, wedge_rotation)
from swhull.smooth import _placements


def test_24_distinct_proper_rotations():
    assert len(set(ROTATIONS)) == 24


def test_r_attribute_round_trips():
    for Q in ROTATIONS:
        assert parse_r(r_attr(Q)) == Q


def test_r_is_stored_transposed():
    # world = M^T @ local, where M is `r` read row-major
    Q = parse_r("0,0,-1,-1,0,0,0,1,0")
    assert apply(Q, (0, 0, -1)) == (0, -1, 0)


def test_wedge_rotation_points_slope():
    Q = wedge_rotation((1, 0, 0), (0, 0, 1))
    assert apply(Q, (0, 1, 0)) == (1, 0, 0)
    assert apply(Q, (0, 0, -1)) == (0, 0, 1)


def test_distinct_orientation_counts():
    counts = {p.d: len(_placements(p)) for p in (WEDGE, PYRAMID, INVPYRAMID, WEDGE2, WEDGE4)}
    assert counts == {"02_wedge": 12, "03_pyramid": 8, "04_invpyramid": 8,
                      "05_wedge_2": 24, "08_wedge_4": 24}
