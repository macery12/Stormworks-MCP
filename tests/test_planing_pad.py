"""`stern.flat_bottom`: the flat planing pad aft that speedboat builders give their hulls.

From the player's hand fix of "Slim Speedboat" (2026-10-21): the V and the keel rise at the
stern were replaced with a flat, level bottom of blocks, the corners cut with wedges.
"""
import pytest

from swhull.build import build, game_units, resolve_spec
from swhull.hull import PAD_BLEND, PAD_CHAMFER, VOX, HullForm
from swhull.pieces import BY_NAME, add, apply


def _form(**stern):
    spec = resolve_spec({"length": 8, "beam": 2.5, "depth": 1.2, "section": {"deadrise": 20, "bilge_radius": 0},
                         "stern": {"keel_rise": 0.3, **stern}})
    return HullForm(game_units(spec))


def test_pad_is_flat_and_level_to_the_transom_with_chamfered_corners():
    form = _form(flat_bottom=0.3)
    B = form.half_beam(0.0)
    H = form.deck(0.0) - form.keel(0.0)
    assert form.keel(0.0) == 0.0                         # keel rise does not lift the pad
    bottom = form.half_width(0.0, 0.0, H, B)
    above = form.half_width(0.0, PAD_CHAMFER, H, B)
    assert above - bottom == pytest.approx(PAD_CHAMFER)  # a 45 degree corner cut
    assert form.half_width(0.0, 2 * PAD_CHAMFER, H, B) >= above
    assert bottom > 0.6 * B                              # flat across, not a V


def test_v_is_unchanged_forward_of_the_pad():
    pad, plain = _form(flat_bottom=0.3), _form()
    s = 0.3 + PAD_BLEND + 0.05
    H, B = pad.deck(s) - pad.keel(s), pad.half_beam(s)
    for h in (0.0, 0.5, 1.0, 2.0):
        assert pad.half_width(s, h, H, B) == plain.half_width(s, h, H, B)


def test_without_pad_the_stern_keeps_its_v_and_keel_rise():
    form = _form()
    assert form.keel(0.0) == pytest.approx(0.3 * VOX)
    H, B = form.deck(0.0) - form.keel(0.0), form.half_beam(0.0)
    assert form.half_width(0.0, 0.0, H, B) < 0.3 * B


@pytest.mark.parametrize("bad", [-0.1, 0.7, "flat"])
def test_bad_pad_is_rejected(bad):
    with pytest.raises(ValueError, match="flat_bottom"):
        resolve_spec({"stern": {"flat_bottom": bad}})


def test_runabout_has_a_symmetric_pad():
    placed, _ = build(resolve_spec({"smoothing": "wedges_v2", "ballast": "none", "railings": "none",
                                    "mooring": "none"}, preset="runabout"))
    shell = [p for p in placed if p.piece.d in BY_NAME]

    def shape(p):
        return frozenset(tuple(round(2 * c) for c in add(p.origin, apply(p.Q, v))) for v in p.piece.verts)
    xs = [v[0] for p in shell for v in p.voxels()]
    x2 = 2 * (min(xs) + max(xs))
    shapes = {shape(p) for p in shell}
    assert all(frozenset((x2 - x, y, z) for x, y, z in shape(p)) in shapes for p in shell)
    # the bottom layer at the transom is flat: plain blocks across all but the chamfered corners
    bottom = min(v[1] for p in shell for v in p.voxels())
    stern = min(v[2] for p in shell for v in p.voxels())
    row = sorted((p.origin[0], p.piece.d) for p in shell if p.origin[1] == bottom and p.origin[2] == stern)
    blocks = [d for _x, d in row if d == "01_block"]
    assert len(blocks) >= len(row) - 2 and len(blocks) >= 4, row
