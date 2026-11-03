"""Multi-body vehicles: lossless import, body assignment, hinge/pivot pairs and body previews."""
import functools

import anyio
import pytest
from mcp.server.mcpserver.exceptions import ToolError

import server
from swhull import bodies, body_view, definitions
from swhull.editing import VehicleDocument, apply_edits, query
from swhull.pieces import BLOCK, Piece, Placed
from swhull.vehicle import placed_from_text, to_xml
from tool_results import unpack

INSTALLED = definitions.load("multibody_compact_pivot_robotic_a") is not None
installed = pytest.mark.skipif(not INSTALLED, reason="installed pivot definitions required")

THREE_BODIES = (
    '<?xml version="1.0" encoding="UTF-8"?>\n<vehicle data_version="3" bodies_id="7"><authors/><bodies>'
    '<body unique_id="1"><components><c><o r="1,0,0,0,1,0,0,0,1" sc="6,AAAAAA,AAAAAA,AAAAAA,AAAAAA,AAAAAA,AAAAAA">'
    '<vp/></o></c>\n<c><o r="1,0,0,0,1,0,0,0,1" sc="6,BBBBBB,BBBBBB,BBBBBB,BBBBBB,BBBBBB,BBBBBB"><vp x="1"/></o></c>'
    '</components></body>\n<body unique_id="7"><components><c><o r="1,0,0,0,1,0,0,0,1" '
    'sc="6,CCCCCC,CCCCCC,CCCCCC,CCCCCC,CCCCCC,CCCCCC"><vp y="5"/></o></c></components></body>'
    '<body unique_id="1"><components><c><o r="1,0,0,0,1,0,0,0,1" sc="6,DDDDDD,DDDDDD,DDDDDD,DDDDDD,DDDDDD,DDDDDD">'
    '<vp z="9"/></o></c></components></body></bodies><logic_node_links/></vehicle>\n')


def fake(d):
    return Piece(d, 6, 1.0, ((0, 0, 0),), BLOCK.verts, BLOCK.faces)


def call(tool, *args, **kwargs):
    return anyio.run(functools.partial(tool, *args, **kwargs))


def test_multi_body_imports_write_back_byte_for_byte_and_keep_repeated_ids_apart():
    doc = VehicleDocument.parse(THREE_BODIES)
    assert [b["id"] for b in doc.bodies] == ["1", "7", "1#2"] and doc.floor == 7
    assert [(p.uid, p.body) for p in doc.parts] == [("original:0", "1"), ("original:1", "1"),
                                                     ("original:2", "7"), ("original:3", "1#2")]
    assert doc.to_xml(doc.parts) == THREE_BODIES
    rows = query(doc.parts)["parts"]
    assert [r["body"] for r in rows] == ["1", "1", "7", "1#2"]
    added = apply_edits(doc.parts, [{"op": "add", "part": {"position": [0, 6, 0]}},
                                    {"op": "add", "part": {"position": [5, 5, 5], "body": "new"}}])
    assert [p.body for p in added[-2:]] == ["7", "8"]          # touches body 7; then a new body after the counter
    xml = doc.to_xml(added)
    assert 'bodies_id="8"' in xml and xml.count("<body ") == 4
    assert '<body unique_id="8"><components>' in xml
    shown, _ = placed_from_text(THREE_BODIES)
    assert [p.body for p in shown] == ["1", "1", "7", "1#2"]
    removed = apply_edits(doc.parts, [{"op": "remove", "select": {"body": "7"}}])
    assert '<body unique_id="7">' not in doc.to_xml(removed)


def test_new_parts_join_the_one_body_they_touch():
    main = [Placed(BLOCK, (0, 0, 0), uid="a", body="1")]
    arm = [Placed(BLOCK, (0, 3, 0), uid="b", body="4")]
    chain = [Placed(BLOCK, (0, 5, 0)), Placed(BLOCK, (0, 4, 0))]   # the far one first: spreads through the batch
    bodies.assign(main + arm + chain, chain)
    assert [p.body for p in chain] == ["4", "4"]
    loose = [Placed(BLOCK, (9, 9, 9))]
    bodies.assign(main + arm + loose, loose)
    assert loose[0].body == "1"
    bridge = [Placed(BLOCK, (0, 1, 0)), Placed(BLOCK, (0, 2, 0))]
    with pytest.raises(ValueError, match="touches bodies 1, 4"):
        bodies.assign(main + arm + bridge, bridge)
    bodies.assign(main + arm + bridge, bridge, {id(bridge[0]): "1", id(bridge[1]): "4"})
    assert [p.body for p in bridge] == ["1", "4"]


def test_pairs_must_stay_together_in_separate_bodies():
    parent = Placed(fake("multibody_compact_pivot_robotic_a"), (0, 1, 0), body="1")
    child = Placed(fake("multibody_compact_pivot_b"), (0, 2, 0), body="2")
    base = [Placed(BLOCK, (0, 0, 0), body="1")]
    assert bodies.problems(base + [parent, child]) == set()
    assert any("lost its" in m for m in bodies.problems(base + [parent]))
    assert any("no parent half" in m for m in bodies.problems(base + [child]))
    same = Placed(fake("multibody_compact_pivot_b"), (0, 2, 0), body="1")
    assert any("its own body" in m for m in bodies.problems(base + [parent, same]))
    assert bodies.child_half("multibody_pivot_a") == "multibody_pivot_b"
    assert bodies.child_half("linear_compact_base") == "linear_compact_head"
    # Bodies without a pair (payloads on hardpoints, loose parts) are allowed.
    assert bodies.problems(base + [Placed(BLOCK, (5, 5, 5), body="3")]) == set()


def test_body_view_colours_are_fixed_per_body():
    parts = [Placed(BLOCK, (0, 0, 0), body="1"), Placed(BLOCK, (0, 1, 0), body="2"), Placed(BLOCK, (0, 2, 0), body="12")]
    shown = body_view.recolour(parts)
    assert shown[0].color == body_view.PALETTE[0] and shown[1].color != shown[0].color
    assert len({q.color for q in shown}) == 3 and parts[1].color == "C2C3C7"   # distinct; originals untouched
    assert body_view.recolour([parts[2]], parts)[0].color == shown[2].color   # a subset keeps its colours
    assert "1 (main)" in body_view.legend(parts) and len(body_view.labels(parts)) == 3
    assert body_view.only(parts, ["2"]) == [parts[1]]
    with pytest.raises(ValueError, match="no body '9'"):
        body_view.only(parts, ["9"])


@installed
def test_placing_a_pivot_creates_its_child_body_and_splits_are_refused():
    start = [Placed(BLOCK, (0, 0, 0), uid="start")]
    pivot = {"definition": "multibody_compact_pivot_robotic_a", "position": [0, 1, 0]}
    parts = apply_edits(start, [{"op": "add", "part": pivot}])
    child = next(p for p in parts if p.piece.d == "multibody_compact_pivot_b")
    assert child.origin == (0, 2, 0) and child.body == "2"
    assert next(p for p in parts if p.piece.d == pivot["definition"]).body == "1"
    arm = apply_edits(parts, [{"op": "add", "part": {"position": [0, 3, 0]}}])
    assert arm[-1].body == "2"
    with pytest.raises(ValueError, match="lost its multibody_compact_pivot_b"):
        apply_edits(parts, [{"op": "remove", "select": {"definition": "multibody_compact_pivot_b"}}])
    with pytest.raises(ValueError, match="no parent half"):
        apply_edits(start, [{"op": "add", "part": {"definition": "multibody_compact_pivot_b", "position": [0, 1, 0]}}])
    both = apply_edits(parts, [{"op": "remove", "select": {"bounds": [[0, 1, 0], [0, 2, 0]]}}])
    assert [p.uid for p in both] == ["start"]
    xml = to_xml(arm)
    assert xml.count("<body ") == 2 and 'bodies_id="2"' in xml


@installed
def test_multi_body_draft_tools_edit_save_and_preview(tmp_path, monkeypatch):
    vehicles, designs = tmp_path / "vehicles", tmp_path / "designs"
    vehicles.mkdir()
    monkeypatch.setenv("SW_VEHICLES_DIR", str(vehicles))
    monkeypatch.setenv("SW_DESIGNS_DIR", str(designs))
    call(server.create_vehicle, "arm")
    q = call(server.query_parts, "arm")
    ops = [{"op": "add", "part": {"definition": "multibody_compact_pivot_robotic_a", "position": [0, 1, 0]}},
           {"op": "add", "parts": [{"position": [0, 3, 0]}, {"position": [0, 4, 0]}]}]
    unpack(call(server.edit_parts, "arm", ops, q["revision"], commit=True))
    rows = call(server.query_parts, "arm", select={"body": "2"})["parts"]
    assert len(rows) == 3 and {r["body"] for r in rows} == {"2"}
    image, notes, _ = unpack(call(server.preview_vehicle, "arm", view="bodies", markers=True))
    assert image[:4] == b"\x89PNG" and "1 (main)" in notes and "CoM red" in notes
    image, notes, _ = unpack(call(server.preview_vehicle, "arm", bodies=["2"]))
    assert image[:4] == b"\x89PNG"
    with pytest.raises(ToolError, match="no body '5'"):
        call(server.preview_vehicle, "arm", bodies=["5"])
    report = unpack(call(server.analyze_physics, design="arm"))[2]
    assert [b["body_id"] for b in report["mass"]["bodies"]] == ["1", "2"]
    call(server.save_vehicle, "arm copy", "arm")
    saved = (vehicles / "arm copy.xml").read_text(encoding="utf-8")
    assert saved.count("<body ") == 2
    call(server.import_vehicle, "arm copy", "arm import")
    assert {r["body"] for r in call(server.query_parts, "arm import")["parts"]} == {"1", "2"}
    image, notes, _ = unpack(call(server.preview_game_vehicle, "arm copy", view="bodies"))
    assert "2 body(ies)" in notes and image[:4] == b"\x89PNG"


def test_xml_edited_parts_import_protected_and_unchanged():
    """Stretched or sheared `r` matrices (XML editing) import with the nearest grid rotation for
    geometry, stay protected, and are written back exactly as saved."""
    text = THREE_BODIES.replace('r="1,0,0,0,1,0,0,0,1" sc="6,BBBBBB', 'r="1,0,0,0,2,1,0,0,1" sc="6,BBBBBB')
    doc = VehicleDocument.parse(text)
    assert doc.stretched == 1 and doc.parts[1].protected and not doc.parts[0].protected
    assert doc.to_xml(doc.parts) == text
    with pytest.raises(ValueError, match="protected"):
        apply_edits(doc.parts, [{"op": "move", "select": {"ids": ["original:1"]}, "delta": [0, 0, 1]}])
    painted = apply_edits(doc.parts, [{"op": "paint", "select": {"ids": ["original:0"]}, "color": "123456"}])
    assert 'r="1,0,0,0,2,1,0,0,1"' in doc.to_xml(painted)
