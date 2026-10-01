import copy

import pytest

from swhull.editing import VehicleDocument, apply_edits, identify, query, revision
from swhull.pieces import BLOCK, IDENTITY, WEDGE2, Placed, r_attr
from swhull.vehicle import components_from_text, to_xml


def blocks():
    return identify([Placed(BLOCK, (0, 0, 0)), Placed(BLOCK, (1, 0, 0))])


def test_atomic_collision_and_stale_id():
    parts = blocks()
    before = copy.deepcopy(parts)
    with pytest.raises(ValueError, match="collision"):
        apply_edits(parts, [{"op": "paint", "select": {"ids": [parts[0].uid]}, "color": "123456"},
                            {"op": "move", "select": {"ids": [parts[1].uid]}, "delta": [-1, 0, 0]}])
    assert parts == before
    with pytest.raises(ValueError, match="stale"):
        apply_edits(parts, [{"op": "remove", "select": {"ids": ["no such id"]}}])


def test_regions_do_not_slice_multivoxel_parts():
    parts = identify([Placed(WEDGE2, (0, 0, 0))])
    with pytest.raises(ValueError, match="partially"):
        query(parts, {"bounds": [[0, 0, 0], [0, 0, 0]]})
    assert query(parts, {"ids": [parts[0].uid]})["parts"][0]["footprint"] == parts[0].voxels()


def test_batch_fill_copy_repeat_mirror_replace_rotate_remove():
    p = blocks()
    out = apply_edits(p, [
        {"op": "fill", "bounds": [[0, 1, 0], [1, 1, 0]], "color": "123456"},
        {"op": "copy", "select": {"ids": [p[0].uid]}, "delta": [0, 0, 2]},
        {"op": "repeat", "select": {"ids": [p[1].uid]}, "delta": [0, 0, 2], "count": 2},
        {"op": "mirror", "select": {"ids": [p[1].uid]}},
        {"op": "replace", "select": {"ids": [p[0].uid]}, "part": {"definition": "01_block", "color": "ABCDEF"}},
        {"op": "rotate", "select": {"ids": [p[0].uid]}, "rotation": r_attr(IDENTITY)},
        {"op": "remove", "select": {"ids": [p[1].uid]}},
    ])
    assert len(out) == 7
    assert len({v for item in out for v in item.voxels()}) == 7
    assert next(item for item in out if item.uid == p[0].uid).color == "ABCDEF"
    assert (-1, 0, 0) in {v for item in out for v in item.voxels()}


def test_lossless_import_and_protection():
    source = to_xml(blocks()).replace("<authors/>", '<authors><author name="Someone"/></authors>')
    source = source.replace("<logic_node_links/>", '<logic_node_links><opaque data="preserve"/></logic_node_links>')
    custom = '<c d="unknown_control"><o r="1,0,0,0,1,0,0,0,1" sc="2,ABCDEF,123456" custom_name="configured"><vp x="8"/><logic_slots><slot foo="1"/></logic_slots></o></c>'
    source = source.replace("</components>", custom + "</components>")
    doc = VehicleDocument.parse(source)
    assert doc.to_xml(doc.parts) == source
    with pytest.raises(ValueError, match="protected"):
        apply_edits(doc.parts, [{"op": "move", "select": {"ids": ["original:2"]}, "delta": [0, 1, 0]}])
    changed = apply_edits(doc.parts, [{"op": "move", "select": {"ids": ["original:0"]}, "delta": [0, 1, 0]}])
    exported = doc.to_xml(changed)
    assert custom in exported
    assert doc.suffix in exported
    assert list(components_from_text(exported))[0][1] == (0, 1, 0)
    painted = apply_edits(doc.parts, [{"op": "paint", "select": {"ids": ["original:2"]}, "color": "AABBCC"}])
    assert 'sc="2,AABBCC,AABBCC"' in doc.to_xml(painted)
    assert '<slot foo="1"/>' in doc.to_xml(painted)


def test_import_version_body_and_link_guards():
    source = to_xml(blocks())
    with pytest.raises(ValueError, match="version"):
        VehicleDocument.parse(source.replace('data_version="3"', 'data_version="2"'))
    with pytest.raises(ValueError, match="single-body"):
        VehicleDocument.parse(source.replace("</bodies>", '<body unique_id="2"/></bodies>'))
    source = source.replace("<logic_node_links/>", '<logic_node_links><link><voxel_pos_0/></link></logic_node_links>')
    doc = VehicleDocument.parse(source)
    assert doc.parts[0].protected


def test_nested_component_settings_remain_intact():
    raw = '<c d="microcontroller"><o sc="1"><vp x="5"/><nodes><c type="0"><c/></c></nodes></o></c>'
    source = to_xml(blocks()).replace("</components>", raw + "</components>")
    doc = VehicleDocument.parse(source)
    assert len(doc.parts) == 3
    assert doc.to_xml(doc.parts) == source


def test_revision_tracks_source_spec_and_overlays():
    assert revision({"spec": {"length": 1}}) != revision({"spec": {"length": 2}})
    assert revision({"spec": {"edits": []}}) != revision({"spec": {"edits": [{"op": "paint"}]}})


def test_mirror_import_preserves_each_surface_color():
    source = to_xml([Placed(WEDGE2, (2, 0, 0))]).replace("C2C3C7", "ABCDEF", 1)
    doc = VehicleDocument.parse(source)
    parts = apply_edits(doc.parts, [{"op": "mirror", "select": {"ids": ["original:0"]}}])
    text = doc.to_xml(parts)
    assert text.count("ABCDEF") == 2
    back = list(components_from_text(text))
    assert sorted((-x, y, z) for x, y, z in parts[0].voxels()) == sorted(parts[1].voxels())
    assert len(back) == 2
