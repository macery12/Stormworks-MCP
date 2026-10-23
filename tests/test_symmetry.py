"""Symmetric hulls get symmetric skins, and a sharp stem ends on a clean nose.

Found on "Slim Speedboat" (2026-10-20): the greedy fit let port and starboard drift apart,
left notches in the bow sides, and put a one-wide, one-sided wedge on the stem. The player's
hand fix ("slim speadboat fixed") mirrored one side and ended the bow on wedge, block, wedge.
"""
import io

import pytest
from PIL import Image

from swhull.build import build, resolve_spec
from swhull.hull import build_solid
from swhull.pieces import BY_NAME, add, apply
from swhull.render import THUMB_BAND, THUMB_BG, THUMB_SIZE, render_thumbnail
from swhull.smooth import SAMPLES, _catalogue, _mirror_map, _slope, mirror_mask

SLIM = {
    "length": 9, "beam": 1.75, "depth": 1.25, "deck": "closed", "smoothing": "wedges_v2",
    "ballast": "none", "railings": "none", "mooring": "none",
    "bow": {"entry": 0.34, "fullness": 1.6, "stem_width": 0, "rake": 0.4, "rake_curve": 1.5,
            "flare": 0.06, "deadrise": 38},
    "stern": {"run": 0.08, "transom_width": 0.85, "fullness": 2, "keel_rise": 0.1},
    "section": {"deadrise": 8, "bilge_radius": 0, "flare": 0.02, "keel_width": 0.5},
    "sheer": {"bow": 0, "stern": 0},
    "colors": {"bottom": "1E3A5F", "stripe": "F2B705", "topsides": "F0F0F0", "deck": "D8CBB0"},
}


@pytest.fixture(scope="module")
def slim():
    placed, _info = build(resolve_spec(SLIM))
    return [p for p in placed if p.piece.d in BY_NAME]


def _shape(p):
    return frozenset(tuple(round(2 * c) for c in add(p.origin, apply(p.Q, v))) for v in p.piece.verts)


def test_mirror_map_is_an_involution():
    cat = _catalogue()["placements"]
    mirror = _mirror_map()
    for t, (m, k_of) in enumerate(mirror):
        assert cat[m]["piece"].d == cat[t]["piece"].d
        assert mirror[m][0] == t
        for k2, k in enumerate(k_of):
            assert int(cat[m]["vol"][k2]) == mirror_mask(cat[t]["vol"][k])


def test_mirror_mask_flips_samples_across_x():
    for i, (x, y, z) in enumerate(SAMPLES):
        j = SAMPLES.index((-x, y, z))
        assert mirror_mask(1 << i) == 1 << j


def test_symmetric_hull_gets_a_mirror_image_skin(slim):
    xs = [v[0] for p in slim for v in p.voxels()]
    x2 = 2 * (min(xs) + max(xs))            # in the doubled coordinates of _shape
    shapes = {_shape(p) for p in slim}
    lonely = [(p.piece.d, p.origin) for p in slim
              if frozenset((x2 - x, y, z) for x, y, z in _shape(p)) not in shapes]
    assert lonely == []


def test_sharp_stem_ends_on_a_three_wide_nose(slim):
    """No one-wide stub on the stem: the foremost row is wedge, block, wedge on every layer."""
    owner = {tuple(int(c) for c in v): p for p in slim for v in p.voxels()}
    tip = max(v[2] for v in owner)
    layers = sorted({v[1] for v in owner if v[2] == tip})
    assert len(layers) >= 3
    nose = 0
    for y in layers:
        row = {v[0]: owner[v] for v in owner if v[1] == y and v[2] == tip}
        if sorted(row) == [0]:
            # the forefoot under the nose may run to the tip, sloping down and forward
            normal = apply(row[0].Q, _slope(row[0].piece)[0])
            assert normal[1] < -0.4 and normal[2] > 0 and abs(normal[0]) < 1e-6, (y, normal)
            continue
        assert sorted(row) == [-1, 0, 1], (y, sorted(row))
        assert row[0].piece.d == "01_block"
        assert "wedge" in row[-1].piece.d and "wedge" in row[1].piece.d
        nose += 1
    assert nose >= 3


def test_bow_sides_are_the_same_on_every_layer_above_the_chine(slim):
    """A notch (one layer of a side wedge stack missing) reads as a hole in the side."""
    tip = max(v[2] for p in slim for v in p.voxels())
    bottom = min(v[1] for p in slim for v in p.voxels())
    slopes = {}
    for p in slim:
        if p.piece.d != "01_block" and p.origin[1] >= bottom + 2 and abs(p.origin[0]) >= 1 \
                and min(v[2] for v in p.voxels()) >= tip - 10:
            slopes.setdefault(p.origin[1], set()).add((p.piece.d, p.Q, p.origin[0], p.origin[2]))
    layers = sorted(slopes)
    assert len(layers) >= 3
    assert all(slopes[y] == slopes[layers[0]] for y in layers)


def test_stem_sliver_voxels_are_trimmed():
    """The voxel a sharp stem only reaches a third of the way into is not part of the solid."""
    spec = resolve_spec(SLIM)
    from swhull.build import game_units  # noqa: PLC0415
    shape, solid, region = build_solid(game_units(spec))
    for (x, y, z), tag in region.items():
        if tag != "hull" or (x - 1, y, z) in region or (x + 1, y, z) in region:
            continue
        if (x, y, z + 1) in region and (x, y, z - 1) in region:
            continue
        inside = bin(shape.sample_mask((x, y, z), SAMPLES)).count("1")
        assert inside >= 32, (x, y, z, inside)


def test_thumbnail_matches_the_game_layout(slim):
    png = render_thumbnail(slim)
    img = Image.open(io.BytesIO(png))
    assert img.mode == "RGBA" and img.size == (THUMB_SIZE, THUMB_SIZE)
    px = img.convert("RGB").load()
    assert px[2, 2] == THUMB_BG
    assert px[256, 60] == THUMB_BAND
    assert px[256, 256] not in (THUMB_BG, THUMB_BAND)     # the vehicle is drawn in the middle
