"""Sloped deckhouse intersections reported in the player's Zumwalt screenshot."""
from collections import Counter

import pytest

from swhull.hull import Box
from swhull.pieces import BY_NAME, DIRS, add, apply
from swhull.smooth import (FULL_MASK, _cells, _corner_closeouts, _fit_metrics,
                          _full_faces, to_pieces)


@pytest.fixture(scope="module")
def deckhouse():
    # Same taper/end-rake ratios as the 10 m deckhouse, on a smaller test body.
    box = Box({"name": "deckhouse", "z": 0, "width": 6, "length": 7,
               "height": 4, "taper": 1.6, "rake_front": 0.4, "rake_back": 0.2}, 0)
    def inside(p):
        return box.inside(*p)
    solid = {(x, y, z) for x in range(-14, 15) for y in range(16) for z in range(-1, 29)
             if inside((x, y, z))}
    cells, masks = _cells(solid, inside, set(), None, set())
    parts = to_pieces(solid, lambda _: "9DA5AA", inside=inside, smoothing="wedges")
    return solid, inside, cells, masks, parts


def test_corner_closeouts_improve_joints_and_shape(deckhouse):
    solid, inside, cells, masks, before = deckhouse
    after, changes = _corner_closeouts(before, solid, cells, masks, inside, set(), lambda _: "9DA5AA")
    old, new = _fit_metrics(before, cells, masks), _fit_metrics(after, cells, masks)
    assert changes > 0
    assert new["wrong_samples"] <= old["wrong_samples"]
    assert new["mismatched_joints"] < old["mismatched_joints"]
    old_families = Counter(p.piece.d for p in before)
    new_families = Counter(p.piece.d for p in after)
    assert new_families["06_pyramid_2"] > old_families["06_pyramid_2"]
    voxels = [v for p in after for v in p.voxels()]
    assert len(voxels) == len(set(voxels))
    hollow = solid - set(voxels)
    for p in after:
        if p.piece.d == "01_block":
            continue
        full = _full_faces(p.piece, p.Q)
        for f in p.piece.footprint:
            w = apply(p.Q, f)
            cell = add(p.origin, w)
            for d in DIRS:
                if add(cell, d) in hollow:
                    assert (w, d) in full


def test_corner_pass_respects_protected_parts_and_openings(deckhouse):
    solid, inside, cells, masks, parts = deckhouse
    protected = {v for p in parts for v in p.voxels()}
    same, _ = _corner_closeouts(parts, solid, cells, masks, inside, protected, lambda _: "9DA5AA")
    original = {v: p for p in parts for v in p.voxels()}
    repaired = {v: p for p in same for v in p.voxels()}
    assert all(repaired[v] is original[v] for v in protected)
    same, changes = _corner_closeouts(parts, solid, cells, masks, inside, set(cells), lambda _: "9DA5AA")
    assert changes == 0
    assert same == parts
    # _cells retains some sampled entries excluded from the allowed set. An opening
    # must stay empty even if its removed material still has a nonzero target mask.
    removed = {v for v in cells if v[2] <= 5}
    allowed = [v for v in cells if v not in removed]
    opened = [p for p in parts if not (set(p.voxels()) & removed)]
    repaired, _ = _corner_closeouts(opened, solid, allowed, masks, inside, set(),
                                    lambda _: "9DA5AA", removed)
    assert all(not (set(p.voxels()) & removed) for p in repaired)


def test_axis_aligned_box_stays_sharp():
    solid = {(x, y, z) for x in range(6) for y in range(6) for z in range(6)}
    def inside(p):
        return all(-0.5 <= c <= 5.5 for c in p)
    cells, masks = _cells(solid, inside, set(), None, set())
    parts = to_pieces(solid, lambda _: "9DA5AA", inside=inside, smoothing="blocks")
    after, changes = _corner_closeouts(parts, solid, cells, masks, inside, set(), lambda _: "9DA5AA")
    assert changes == 0
    assert all(p.piece == BY_NAME["01_block"] for p in after)
    assert all(masks[v] in (0, FULL_MASK) for v in cells)
