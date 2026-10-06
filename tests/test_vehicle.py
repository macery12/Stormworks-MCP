"""Vehicle XML writing and reading."""
import re

import pytest

from swhull.pieces import BLOCK, IDENTITY, PYRAMID2X4, WEDGE2, Placed, wedge_rotation
from swhull.vehicle import MISSING_R, load_placed, read_components, to_xml


def test_every_component_has_explicit_rotation_and_full_paint():
    placed = [Placed(BLOCK, (0, 0, 0), IDENTITY, "A52A2A"),
              Placed(WEDGE2, (1, 0, 0), wedge_rotation((0, 1, 0), (1, 0, 0)), "F0F0F0")]
    xml = to_xml(placed)
    # a missing `r` is not identity in Stormworks, and `x` in `sc` means unpainted
    assert xml.count(' r="') == len(placed)
    assert ",x" not in xml
    assert 'sc="6,A52A2A,A52A2A,A52A2A,A52A2A,A52A2A,A52A2A"' in xml
    assert not re.search(r" \d\d=", xml)


def test_round_trip(tmp_path):
    placed = [Placed(WEDGE2, (3, -2, 5), wedge_rotation((0, 0, 1), (0, -1, 0)), "123456")]
    path = tmp_path / "v.xml"
    path.write_text(to_xml(placed), encoding="utf-8")
    [(d, origin, Q, colour)] = list(read_components(path))
    assert (d, origin, Q, colour) == ("05_wedge_2", (3, -2, 5), placed[0].Q, "123456")


def test_preview_selects_one_body_and_ignores_controller_internals(tmp_path):
    nested = '<c d="microcontroller"><o><vp x="3"/><group><components><c><o><vp x="99"/></o></c></components></group></o></c>'
    text = ('<vehicle data_version="3"><bodies><body unique_id="1"><components>'
            '<c><o r="2,0,0,0,1,0,0,0,1" wheel_size="1.5"><vp/></o></c>' + nested +
            '</components></body><body unique_id="2"><components><c><o><vp x="10"/></o></c></components></body></bodies></vehicle>')
    path = tmp_path / "v.xml"
    path.write_text(text)
    parts, _ = load_placed(path)
    assert len(parts) == 2 and parts[0].Q[0][0] == 2
    assert parts[0].settings["wheel_size"] == "1.5" and parts[1].origin == (3, 0, 0)
    selected, _ = load_placed(path, body_id="2")
    assert len(selected) == 1 and selected[0].origin == (10, 0, 0)
    with pytest.raises(ValueError, match="no body"):
        load_placed(path, body_id="3")
    with pytest.raises(ValueError, match="axis-aligned"):
        list(read_components(path))  # Editing/geometry parser stays strict.


def test_reads_game_quirks(tmp_path):
    # digit attribute names, omitted d/r/coordinates, <vp/> at the origin
    text = ('<?xml version="1.0" encoding="UTF-8"?><vehicle data_version="3" bodies_id="1"><bodies>'
            '<body unique_id="1"><initial_local_transform 00="1" 01="0"/><components>'
            '<c><o sc="6"><vp x="-1"/></o></c>'
            '<c d="02_wedge"><o r="1,0,0,0,1,0,0,0,1" sc="5"><vp/></o></c>'
            '</components></body></bodies></vehicle>')
    path = tmp_path / "game.xml"
    path.write_text(text, encoding="utf-8")
    comps = list(read_components(path))
    assert comps[0][:3] == ("01_block", (-1, 0, 0), MISSING_R)
    assert comps[1][:3] == ("02_wedge", (0, 0, 0), IDENTITY)


def test_mirrored_parts_as_the_game_saves_them(tmp_path):
    # from a save made in game with mirror mode across the centreline: the mirrored copy keeps
    # `r` and gets `t`, a flip of the part's own axes (1 x, 4 z) applied before the rotation
    text = ('<?xml version="1.0" encoding="UTF-8"?><vehicle data_version="3" bodies_id="2"><bodies>'
            '<body unique_id="2"><components>'
            '<c d="12_pyramid_2x4"><o r="1,0,0,0,1,0,0,0,1" sc="18"><vp x="-1" y="2" z="7"/></o></c>'
            '<c d="12_pyramid_2x4" t="1"><o r="1,0,0,0,1,0,0,0,1" sc="18"><vp x="1" y="2" z="7"/></o></c>'
            '<c d="12_pyramid_2x4"><o r="0,0,-1,0,1,0,1,0,0" sc="18"><vp x="-4" y="2"/></o></c>'
            '<c d="12_pyramid_2x4" t="4"><o r="0,0,-1,0,1,0,1,0,0" sc="18"><vp x="4" y="2"/></o></c>'
            '</components></body></bodies></vehicle>')
    path = tmp_path / "mirrored.xml"
    path.write_text(text, encoding="utf-8")
    parts = [Placed(PYRAMID2X4, origin, Q) for _d, origin, Q, _c in read_components(path)]
    for original, mirrored in (parts[0:2], parts[2:4]):
        assert sorted((-x, y, z) for x, y, z in original.voxels()) == sorted(mirrored.voxels())
        x_row, *rest = original.Q                       # the same part reflected in world x
        assert (tuple(-q for q in x_row), *rest) == mirrored.Q
    # and a mirrored part is written back with `t`, reading back the same
    path.write_text(to_xml(parts), encoding="utf-8")
    assert [Q for _d, _o, Q, _c in read_components(path)] == [p.Q for p in parts]
    assert to_xml(parts).count(' t="1"') == 2
