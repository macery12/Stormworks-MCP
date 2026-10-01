"""Spec features added from real builds: placement helpers, shapes, paint, scale, patches."""
import pytest

from swhull import build as build_module
from swhull.benches import SIZES, fits
from swhull.build import apply_patch, build, deck_profile, resolve_spec, summary
from swhull.hull import VOX, HullShape, box_voxels, game_units
from swhull.pieces import DIRS, SLOPES, add
from swhull.render import design_ruler, render_png, render_view
from swhull.smooth import SAMPLES

BASE = {"length": 12.0, "beam": 4.0, "depth": 1.5, "sheer": {"bow": 0.0, "stern": 0.0}}


def _spec(**over):
    return resolve_spec({**BASE, **over}, preset="barge")


def _shape(boxes):
    return HullShape(game_units(_spec(superstructure=boxes)))


def test_band_measured_from_box_bottom_when_overlapped():
    # funnel starts inside the deckhouse, which owns those voxels; the band still lands on top
    boxes = [{"name": "deckhouse", "z": 4, "length": 4, "width": 2, "height": 0.75},
             {"name": "funnel", "z": 5, "length": 1, "width": 1, "height": 2,
              "band": {"from": 1.75, "to": 2.0, "color": "000000"}}]
    placed, info = build(_spec(superstructure=boxes))
    funnel = info["shape"].by_name["funnel"]
    sx, sy, sz = info["shift"]
    black = [p for p in placed if p.color == "000000"]
    assert black
    assert all(p.origin[1] + sy == funnel.top() - 1 for p in black)


def test_taper_too_small_warns():
    _, info = build(_spec(superstructure=[{"name": "f", "z": 4, "length": 2, "width": 2,
                                           "height": 2, "taper": 0.1}]))
    assert any("taper" in w and "'f'" in w for w in info["warnings"])


def test_mirror_and_repeat():
    shape = _shape([{"name": "mount", "z": 2, "length": 1, "width": 1, "height": 0.5, "x": 1.5,
                     "mirror_x": True, "repeat": {"count": 3, "dz": 2}}])
    names = sorted(b.name for b in shape.boxes)
    assert names == sorted(f"mount_{k}_{s}" for k in (1, 2, 3) for s in ("port", "stbd"))
    b = shape.by_name["mount_3_port"]
    assert b.xc == -1.5 * VOX and b.z0 == 6 * VOX


def test_on_and_relative_y():
    shape = _shape([{"name": "house", "z": 4, "length": 4, "width": 2, "height": 1.0},
                    {"name": "bridge", "z": 5, "length": 2, "width": 1.5, "height": 1.0, "on": "house"},
                    {"name": "mast", "z": 5.5, "length": 0.5, "width": 0.5, "height": 1.0,
                     "y": "bridge+0.25"},
                    {"name": "crate", "z": 1, "length": 1, "width": 1, "height": 0.5, "y": "deck+0.5"}])
    house, bridge, mast, crate = (shape.by_name[n] for n in ("house", "bridge", "mast", "crate"))
    assert bridge.y0 == house.top()
    assert mast.y0 == bridge.top() + 1
    deck = shape.boxes[0].y0          # house sits on the flat deck
    assert crate.y0 == deck + 2


def test_mirrored_box_stacks_on_matching_twin():
    shape = _shape([{"name": "barbette", "z": 2, "length": 1, "width": 1, "height": 0.5, "x": 1.5,
                     "mirror_x": True},
                    {"name": "gun", "z": 2, "length": 1, "width": 1, "height": 0.5, "x": 1.5,
                     "mirror_x": True, "on": "barbette"}])
    assert shape.by_name["gun_port"].y0 == shape.by_name["barbette_port"].top()


def test_bad_reference_is_an_error():
    with pytest.raises(ValueError, match="not a box name"):
        build(_spec(superstructure=[{"name": "a", "z": 1, "length": 1, "width": 1, "height": 1,
                                     "on": "nothing"}]))


def test_round_shapes_are_smaller_than_their_box():
    box = {"name": "b", "z": 3, "length": 2, "width": 2, "height": 1.5}
    sizes = {s: len(box_voxels(_shape([{**box, "shape": s}]).boxes[0]))
             for s in ("box", "cylinder", "dome", "sphere", "lattice")}
    assert sizes["box"] > sizes["cylinder"] > sizes["dome"] > 0
    assert sizes["box"] > sizes["sphere"] > 0
    assert sizes["box"] > sizes["lattice"] > 0


def test_pitched_barrel_rises_and_stays_connected():
    barrel = {"name": "barrel", "shape": "cylinder", "axis": "z", "z": 3, "length": 4, "width": 0.25,
              "height": 0.25, "y": 2.0, "pitch": 25, "pivot": "aft"}
    vox = box_voxels(_shape([barrel]).boxes[0])
    aft = min(vox, key=lambda v: v[2])
    fore = max(vox, key=lambda v: v[2])
    assert fore[1] - aft[1] >= 5          # ~4 m * sin 25 = 1.7 m
    seen, todo = {aft}, [aft]
    while todo:
        v = todo.pop()
        for d in DIRS:
            n = add(v, d)
            if n in vox and n not in seen:
                seen.add(n)
                todo.append(n)
    assert seen == vox, "a pitched barrel must be face-connected"


def test_overlap_report():
    _, info = build(_spec(superstructure=[
        {"name": "a", "z": 3, "length": 2, "width": 2, "height": 1},
        {"name": "b", "z": 4, "length": 2, "width": 2, "height": 1}]))
    assert [(a, b) for a, b, _ in info["overlaps"]] == [("a", "b")]


def test_scale():
    spec = resolve_spec({"scale": "1:4", "length": 48, "beam": 16, "depth": 8,
                         "superstructure": [{"name": "h", "z": 20, "length": 8, "width": 8, "height": 4}]})
    placed, info = build(spec)
    assert info["form"].L == 48            # 12 m game = 48 voxels
    assert info["shape"].by_name["h"].z0 == 20                  # 5 m game
    with pytest.raises(ValueError, match="after scale"):
        resolve_spec({"scale": "1:2", "length": 300})
    with pytest.raises(ValueError, match="scale"):
        resolve_spec({"scale": "four"})


def test_patch():
    spec = _spec(superstructure=[{"name": "house", "z": 4, "length": 4, "width": 2, "height": 1}])
    out = apply_patch(spec, [
        {"op": "replace", "path": "/superstructure/house/height", "value": 2.0},
        {"op": "add", "path": "/superstructure/-", "value": {"name": "mast", "z": 5, "length": 0.5,
                                                             "width": 0.5, "height": 2}},
        {"op": "replace", "path": "/colors/deck", "value": "112233"},
        {"op": "remove", "path": "/superstructure/0/width"},
    ])
    assert out["superstructure"][0] == {"name": "house", "z": 4, "length": 4, "height": 2.0}
    assert out["superstructure"][1]["name"] == "mast"
    assert out["colors"]["deck"] == "112233"
    assert spec["superstructure"][0]["height"] == 1          # original untouched
    for bad in ([{"path": "/superstructure/nope/height", "value": 1}],
                [{"op": "move", "path": "/length"}], [{"path": "/length"}], {"path": "/length"}):
        with pytest.raises(ValueError):
            apply_patch(spec, bad)


def test_paint_text_on_both_sides_and_deck():
    spec = _spec(paint=[{"shape": "text", "text": "61", "on": "sides", "z": 6, "y": 0.25,
                         "height": 1.25, "color": "FFFFFF"},
                        {"shape": "circle", "on": "deck", "z": 3, "radius": 1, "color": "FFFF00"}])
    placed, info = build(spec)
    sx = info["shift"][0]
    white = [p.origin[0] + sx for p in placed if p.color == "FFFFFF"]
    assert any(x > 0 for x in white) and any(x < 0 for x in white)
    assert any(p.color == "FFFF00" for p in placed)
    assert not info["warnings"]


def test_bulb_and_skegs():
    spec = _spec(bow={"bulb": {"length": 2, "width": 1, "height": 0.75, "y": 0.5, "protrude": 1}},
                 skegs=[{"z": 0.5, "length": 3, "x": 1, "width": 0.25, "bottom": -0.5, "mirror_x": True}])
    placed, info = build(spec)
    _, _, sz = info["shift"]
    sy = info["shift"][1]
    zs = [v[2] + sz for p in placed for v in p.voxels()]
    ys = [v[1] + sy for p in placed for v in p.voxels()]
    assert max(zs) >= 12 * VOX + 3            # 1 m past the bow, give or take a block
    assert min(ys) == -2                      # skegs reach 0.5 m below the keel


def test_deck_profile_rows():
    text = deck_profile(resolve_spec(preset="fishing_trawler"), step=2)
    rows = [line for line in text.splitlines() if line.strip()[:1].isdigit()]
    assert len(rows) == 9                     # 0, 2, ... 16 m


def test_rulers_render():
    placed, info = build(resolve_spec(preset="tugboat"))
    ruler = design_ruler(info)
    for png in (render_png(placed, ruler=ruler), render_view(placed, yaw=0, pitch=0, ruler=ruler),
                render_view(placed, yaw=0, pitch=90, ruler=ruler)):
        assert png[:4] == b"\x89PNG"


def test_door_reports_sill():
    _, info = build(resolve_spec(preset="patrol_boat"))
    doors = [d for r in info["interior"].rooms for d in r.doors]
    assert any("sill" in d for d in doors)


def test_sample_mask_matches_point_tests():
    spec = game_units(resolve_spec({
        "bow": {"bulb": {"length": 2, "width": 1, "height": 0.75, "y": 0.5, "protrude": 1}},
        "skegs": [{"z": 0.5, "length": 3, "x": 1, "width": 0.25, "bottom": -0.5, "mirror_x": True}],
        "superstructure": [
            {"name": "gun", "shape": "cylinder", "axis": "z", "z": 6, "length": 3, "width": 0.5,
             "height": 0.5, "y": 2.2, "pitch": 20, "yaw": 15, "pivot": "back", "facing": "aft"},
            {"name": "dome", "shape": "dome", "z": 3, "length": 1.5, "width": 1.5, "height": 1}]},
        preset="catamaran"))
    shape = HullShape(spec)
    lo, hi = shape.bounds()
    for z in range(lo[2], hi[2] + 1, 3):
        for y in range(lo[1], hi[1] + 1, 2):
            for x in range(lo[0], hi[0] + 1, 2):
                expect = sum(1 << i for i, s in enumerate(SAMPLES)
                             if shape.contains(x + s[0], y + s[1], z + s[2]))
                assert shape.sample_mask((x, y, z), SAMPLES) == expect, (x, y, z)


def test_wedges_leave_paint_alone():
    spec = resolve_spec({"smoothing": "wedges", "paint": [
        {"shape": "text", "text": "61", "on": "sides", "z": 11, "y": 0.6, "height": 1.25,
         "color": "FFFFFF"}]}, preset="patrol_boat")
    placed, _ = build(spec)
    assert all(p.piece.d == "01_block" for p in placed if p.color == "FFFFFF")


def test_long_pieces_do_not_cross_colours():
    # a piece over several voxels (Wedge 1x4, Pyramid 2x4, ...) takes one colour, so it must
    # not straddle the waterline or boot-top; it may reach a sliver into empty air beyond
    spec = resolve_spec({"smoothing": "wedges"}, preset="tugboat")
    placed, info = build(spec)
    sy = info["shift"][1]
    wl, stripe = 1.2 * VOX, 0.25 * VOX            # tugboat waterline and stripe height

    def band(y):
        yc = y + sy + 0.5
        return 0 if yc < wl else 1 if yc < wl + stripe else 2

    shape, shift = info["shape"], info["shift"]

    def reached(v):
        return shape.sample_mask(tuple(v[i] + shift[i] for i in range(3)), SAMPLES) != 0

    long = [p for p in placed if p.piece in SLOPES and len(p.piece.footprint) > 1]
    assert long
    for p in long:
        assert len({band(v[1]) for v in p.voxels() if reached(v)}) == 1, p


def test_scale_fit_fills_the_bench():
    spec = resolve_spec({"scale": "fit", "bench": "M", "length": 40, "beam": 8, "depth": 4},
                        preset="fishing_trawler")
    placed, info = build(spec)
    vox = [v for p in placed for v in p.voxels()]
    lo = [min(v[i] for v in vox) for i in range(3)]
    hi = [max(v[i] for v in vox) for i in range(3)]
    assert fits(SIZES["M"], lo, hi)
    grown = [lo[i] * 1.03 for i in range(3)], [hi[i] * 1.03 for i in range(3)]
    assert not fits(SIZES["M"], *grown), "fit should come within a few percent of the bench"
    assert "fitted to the bench" in summary(spec, placed, info)
    with pytest.raises(ValueError, match="needs a bench"):
        resolve_spec({"scale": "fit"})


def test_interior_units_spec():
    rooms = {"decks": [1.0], "rooms": [{"name": "r", "level": 0, "z": 8, "length": 8}]}
    a = resolve_spec({"scale": 0.5, "length": 24, "beam": 8, "depth": 4, "interior": rooms,
                      "interior_units": "spec"}, preset="barge")
    b = resolve_spec({"scale": 0.5, "length": 24, "beam": 8, "depth": 4,
                      "interior": {"decks": [0.5], "rooms": [{"name": "r", "level": 0, "z": 4, "length": 4}]}},
                     preset="barge")
    ra, rb = build(a)[1]["interior"].rooms[0], build(b)[1]["interior"].rooms[0]
    assert (ra.zlo, ra.zhi, ra.ylo) == (rb.zlo, rb.zhi, rb.ylo)


def test_floors_give_walkable_headroom():
    spec = resolve_spec({"scale": 0.4, "superstructure": [
        {"name": "house", "z": 10, "length": 10, "width": 6, "floors": 1}],
        "interior": {"rooms": [{"name": "bridge", "level": "main", "z": 4.5, "length": 3, "width": 2}]}},
        preset="barge")
    _, info = build(spec)
    assert info["shape"].by_name["house"].h >= 10          # 2.5 m in game, whatever the scale
    room = info["interior"].rooms[0]
    assert room.yhi - room.ylo + 1 == 9                     # 2.25 m clear


def test_facing_aft_points_to_the_stern():
    gun = {"name": "gun", "shape": "cylinder", "axis": "z", "z": 4, "length": 3, "width": 0.25,
           "height": 0.25, "y": 2.0, "pitch": 20, "pivot": "back", "facing": "aft"}
    vox = box_voxels(_shape([gun]).boxes[0])
    low = min(vox, key=lambda v: v[1])
    high = max(vox, key=lambda v: v[1])
    assert high[2] < low[2], "the raised muzzle end should be the aft end"
    assert min(v[2] for v in vox) >= 4 * VOX - 1 and max(v[2] for v in vox) <= 7 * VOX + 1


def test_overlap_ok_silences_the_report():
    _, info = build(_spec(superstructure=[
        {"name": "a", "z": 3, "length": 2, "width": 2, "height": 1},
        {"name": "b", "z": 4, "length": 2, "width": 2, "height": 1, "overlap_ok": True}]))
    assert info["overlaps"] == []


def test_patch_hatch_by_name_and_negative_offset():
    spec = resolve_spec({"superstructure": [
        {"name": "mast", "z": 5, "length": 0.5, "width": 0.5, "height": 4},
        {"name": "yard", "z": 5, "length": 0.5, "width": 2, "height": 0.25, "y": "mast-1"}],
        "interior": {"hatches": [{"name": "fwd", "z": 8}]}}, preset="barge")
    out = apply_patch(spec, [{"op": "replace", "path": "/interior/hatches/fwd/z", "value": 9}])
    assert out["interior"]["hatches"][0]["z"] == 9
    shape = HullShape(game_units(spec))
    assert shape.by_name["yard"].y0 == shape.by_name["mast"].top() - 4


def test_loose_parts_are_reported():
    _, info = build(_spec(superstructure=[
        {"name": "floating", "z": 4, "length": 1, "width": 1, "height": 0.5, "y": "deck+1"}]))
    assert any("loose part" in w and "floating" in w for w in info["warnings"])
    _, info = build(_spec(superstructure=[
        {"name": "standing", "z": 4, "length": 1, "width": 1, "height": 0.5}]))
    assert not any("loose part" in w for w in info["warnings"])


def test_spawn_limit_warning(monkeypatch):
    placed, info = build(resolve_spec(preset="tugboat"))
    assert "of 131072" in build_module.spawn_limit_lines(placed, info)[0]
    monkeypatch.setattr(build_module, "SPAWN_LIMIT", 1000)
    line = build_module.spawn_limit_lines(placed, info)[0]
    assert line.startswith("! ") and "is missing after spawn" in line
