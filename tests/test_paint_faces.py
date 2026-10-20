"""Per-face paint: the surface table, writing and reading `sc`, rendering, schemes and liveries."""
import pytest

from swhull import definitions, faces
from swhull.build import build, resolve_spec
from swhull.liveries import LIVERIES
from swhull.paint import designer, shaded, validate
from swhull.pieces import BLOCK, BY_NAME, WEDGE, Placed
from swhull.render import _world_faces
from swhull.vehicle import placed_from_text, to_xml

COLOURS = ["E02020", "20B020", "2040E0", "F0D020", "D020D0", "20D0D0"]


@pytest.mark.parametrize("d", sorted(BY_NAME))
def test_surface_table_matches_the_game_definitions(d):
    data = definitions.metadata(d)
    if data is None or definitions.definitions_dir() is None:
        pytest.skip("game definitions not installed")
    assert faces.SURFACES[d] == tuple((tuple(s["position"]), s["orientation"], s["shape"])
                                      for s in data["attachment_surfaces"])


@pytest.mark.parametrize("d", sorted(BY_NAME))
def test_every_sc_entry_has_a_face(d):
    entries = faces.entries(d)
    assert len(entries) == BY_NAME[d].surfaces
    slopes = [n for _cell, n in entries if max(abs(c) for c in n) < 0.999]
    assert len(slopes) == sum(1 for *_x, shape in faces.SURFACES[d] if faces._sloped(shape))
    for n in slopes:                                   # every slope faces up or down and out
        assert abs(sum(c * c for c in n) - 1) < 1e-6 and abs(n[1]) > 0.2


def test_repainting_a_part_drops_its_face_colours():
    p = Placed(BLOCK, (0, 0, 0), color="E02020", faces=tuple(COLOURS))
    p.origin = (1, 0, 0)
    assert p.faces
    p.color = "123456"
    assert p.faces == () and p.color == "123456"


def test_face_colours_are_written_read_and_rendered():
    block = Placed(BLOCK, (0, 0, 0), color=COLOURS[0], faces=tuple(COLOURS))
    wedge = Placed(WEDGE, (3, 0, 0), color=COLOURS[0], faces=tuple(COLOURS[:5]))
    text = to_xml([block, wedge])
    assert 'sc="6,E02020,20B020,2040E0,F0D020,D020D0,20D0D0"' in text
    back, _ = placed_from_text(text)
    assert [p.faces for p in back] == [block.faces, wedge.faces]
    # The renderer shows each face its own colour: the block's top is entry 2 (+y).
    out = _world_faces([block], bake=False)
    top = next(col for _pts, n, col, _cell in out if n == (0, 1, 0))
    assert top == tuple(int(COLOURS[2][i:i + 2], 16) for i in (0, 2, 4))
    slope = next(col for _pts, n, col, _cell in _world_faces([wedge], bake=False) if 0 < abs(n[1]) < 0.99)
    assert slope == tuple(int(COLOURS[4][i:i + 2], 16) for i in (0, 2, 4))


def test_unconfirmed_pairs_share_the_visible_colour():
    wanted = {(1, 0, 0): "AAAAAA", (-1, 0, 0): "BBBBBB"}
    p = Placed(BLOCK, (0, 0, 0))
    cols = faces.paint(p, lambda cell, n: wanted.get(n, "CCCCCC"), exposed=lambda cell, n: n == (1, 0, 0))
    by_normal = dict(zip([n for _c, n in faces.world(p)], cols))
    assert by_normal[(1, 0, 0)] == by_normal[(-1, 0, 0)] == "AAAAAA"
    assert by_normal[(0, 1, 0)] == "CCCCCC"


def surface(parts, cell, normal):
    """Colour a built vehicle shows on the face of `cell` facing `normal`."""
    for p in parts:
        if cell in p.voxels() and p.piece.d in BY_NAME:
            return faces.colour_of(p, cell, normal)
    return None


def test_the_deck_edge_is_crisp_and_side_paint_stays_off_the_deck():
    spec = resolve_spec({"paint": [{"shape": "rect", "on": "sides", "z": 0, "length": 100, "y": 0,
                                    "height": 100, "color": "00FF00"}]}, "barge")
    parts, info = build(spec)
    colours = info["spec"]["colors"]
    tops = {}
    for p in parts:
        if p.piece.d == "01_block":
            x, y, z = p.origin
            if (x, z) not in tops or y > tops[(x, z)][1]:
                tops[(x, z)] = p.origin
    edge = max((v for v in tops.values()), key=lambda v: v[0])           # starboard deck edge
    assert surface(parts, edge, (0, 1, 0)) == colours["deck"].upper()
    assert surface(parts, edge, (1, 0, 0)) == "00FF00"


def test_box_roofs_trim_and_caps():
    spec = resolve_spec({"colors": {"roof": "111111"}, "superstructure": [
        {"name": "house", "z": 6.0, "length": 3.0, "width": 2.5, "height": 2.0, "color": "EEEEEE",
         "cap": {"height": 0.5, "color": "222222"}}]}, "barge")
    parts, _ = build(spec)
    house = [p for p in parts if p.faces or p.color in ("111111", "222222", "EEEEEE")]
    shown = {c for p in house for c in (p.faces or (p.color,))}
    assert {"111111", "222222", "EEEEEE"} <= shown


@pytest.mark.parametrize("shape,extra", [
    ("polygon", {"points": [[0, 0], [2, 0], [1, 2]]}), ("line", {"from": [0, 0], "to": [3, 1], "width": 0.5}),
    ("stripes", {"colors": ["F2B705", "1A1A1A"], "stripe": 0.25}), ("panels", {"shade": -0.1}),
    ("camo", {"style": "dazzle", "colors": ["111111", "EEEEEE", "335577"]}),
    ("camo", {"style": "splinter", "colors": ["111111", "EEEEEE"]}),
    ("camo", {"style": "blotch", "colors": ["111111", "EEEEEE"]})])
def test_paint_shapes_are_valid_and_seeded(shape, extra):
    item = {"shape": shape, "on": "sides", **extra}
    assert validate([item]) == []
    first = designer({**item, "seed": 3}, [], 0, ((0, 20), (0, 5)))
    again = designer({**item, "seed": 3}, [], 0, ((0, 20), (0, 5)))
    grid = [(a / 4, b / 4) for a in range(80) for b in range(20)]
    results = [first(a, b, 1) for a, b in grid]
    assert results == [again(a, b, 1) for a, b in grid] and any(results)
    if shape == "camo":
        other = designer({**item, "seed": 4}, [], 0, ((0, 20), (0, 5)))
        assert results != [other(a, b, 1) for a, b in grid]


def test_paint_validation_messages():
    assert validate([{"shape": "hexagon"}])
    assert validate([{"shape": "polygon", "points": [[0, 0], [1, 1]]}])
    assert validate([{"shape": "camo", "colors": ["111111"]}])
    assert validate([{"shape": "rect", "on": "roof", "z": 1}])
    assert shaded("808080", -0.5) == "404040" and shaded("808080", 0.5) == "C0C0C0"


@pytest.mark.parametrize("name", sorted(LIVERIES))
def test_every_livery_builds_and_keeps_the_bottom_plain(name):
    parts, info = build(resolve_spec({"livery": {"name": name, "number": "61"}}, "patrol_boat"))
    colours = info["spec"]["colors"]
    shown = {c for p in parts for c in (p.faces or (p.color,))}
    assert colours["topsides"].upper() in shown and colours["deck"].upper() in shown
    keel = min(p.origin[1] for p in parts)
    bottom = {faces.colour_of(p, p.origin, (0, -1, 0)) for p in parts if p.origin[1] == keel}
    assert bottom == {colours["bottom"].upper()}
    if name == "coast_guard":
        assert {"BB4242", "243C55"} <= shown


def test_livery_validation_and_overrides():
    with pytest.raises(ValueError, match="livery must be"):
        resolve_spec({"livery": "rainbow"}, "barge")
    with pytest.raises(ValueError, match="livery.colors"):
        resolve_spec({"livery": {"name": "navy", "colors": {"sky": "FFFFFF"}}}, "barge")
    parts, info = build(resolve_spec({"livery": {"name": "navy", "colors": {"deck": "123456"}}}, "barge"))
    assert info["spec"]["colors"]["deck"] == "123456"


def test_sheer_step_risers_are_deck_not_hull_side():
    parts, info = build(resolve_spec({}, "fishing_trawler"))
    deck = info["spec"]["colors"]["deck"].upper()
    occupied = {v for p in parts for v in p.voxels()}
    risers, shift, region = 0, info["shift"], info["region"]
    top = max(p.origin[1] for p in parts if region.get(tuple(p.origin[i] + shift[i] for i in range(3))) == "hull")
    for p in parts:
        if p.origin[1] < top - 3:          # only the deck's own steps, not the keel's
            continue
        if p.piece.d != "01_block" or region.get(tuple(p.origin[i] + shift[i] for i in range(3))) != "hull":
            continue
        for d in ((0, 0, 1), (0, 0, -1)):
            beyond = tuple(p.origin[i] + d[i] for i in range(3))
            below = (beyond[0], beyond[1] - 1, beyond[2])
            if beyond not in occupied and below in occupied and (p.origin[0], p.origin[1] + 1, p.origin[2]) \
                    not in occupied and abs(p.origin[0]) < 4:
                risers += 1
                assert faces.colour_of(p, p.origin, d) == deck
    assert risers
