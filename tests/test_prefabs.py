"""Prefabs (vehicles reused inside other vehicles), block-built tanks and modular engine couplings."""
import functools
import json

import anyio
import pytest
from mcp.server.mcpserver.exceptions import ToolError

import server
from swhull import definitions, modular, prefabs
from swhull.drafts import edited, export, materialize
from swhull.editing import VehicleDocument, apply_edits
from swhull.jobs import import_draft
from swhull.networks import wires
from swhull.pieces import BLOCK, Piece, Placed
from swhull.vehicle import components_from_text, to_xml
from tool_results import unpack

SC = 'sc="6,AAAAAA,AAAAAA,AAAAAA,AAAAAA,AAAAAA,AAAAAA"'


def block(x, y, z):
    vp = "".join(f' {k}="{v}"' for k, v in zip("xyz", (x, y, z)) if v)
    return f'<c><o r="1,0,0,0,1,0,0,0,1" {SC}><vp{vp}/></o></c>'


def controller(name, x, y, nodes):
    body = "".join(f'<n id="{i}" component_id="{i}"><node label="{label}" type="1" mode="{mode}"><position z="{i - 1}"/></node></n>'
                   for i, (label, mode) in enumerate(nodes, 1))
    return (f'<c d="microprocessor"><o r="1,0,0,0,1,0,0,0,1" sc="6,111111,111111,111111,111111,111111,111111">'
            f'<microprocessor_definition name="{name}" width="1" length="1"><nodes>{body}</nodes>'
            f'</microprocessor_definition><vp x="{x}" y="{y}"/></o></c>')


# A small prefab: three blocks, two microcontrollers wired together, one unwired input, and a
# second body holding one block.
KIT = ('<?xml version="1.0" encoding="UTF-8"?>\n<vehicle data_version="3" bodies_id="3"><authors/><bodies>'
       '<body unique_id="1"><components>' + block(0, 0, 0) + block(1, 0, 0) + block(2, 0, 0)
       + controller("A", 0, 1, [("Out", 0)]) + controller("B", 2, 1, [("In", 1), ("Spare", 1)])
       + '</components></body><body unique_id="3"><components>' + block(1, 1, 0) + '</components></body>'
       '</bodies><logic_node_links><logic_node_link type="1"><voxel_pos_0 y="1"/><voxel_pos_1 x="2" y="1"/>'
       '</logic_node_link></logic_node_links></vehicle>\n')
QUARTER_Y = "0,0,1,0,1,0,-1,0,0"


def floor():
    record, _, _ = import_draft(to_xml([Placed(BLOCK, (x, 0, z)) for x in range(-4, 5) for z in range(-4, 5)]),
                                "floor")
    return record


def call(tool, *args, **kwargs):
    return anyio.run(functools.partial(tool, *args, **kwargs))


def test_microcontroller_position_is_read_after_its_logic():
    # The game saves a microcontroller's logic before its position; it used to read as (0, 0, 0).
    assert [g[1] for g in components_from_text(controller("A", 3, 2, [("Out", 0)]))] == [(3, 2, 0)]
    doc = VehicleDocument.parse(KIT)
    assert [p.origin for p in doc.parts if p.piece.d == "microprocessor"] == [(0, 1, 0), (2, 1, 0)]


def test_connection_points_are_unwired_nodes():
    rows = prefabs.points(KIT)
    assert [(r["name"], r["kind"], r["direction"]) for r in rows] == [("spare", "wire", "input")]
    assert prefabs.links(KIT) == [(1, (0, 1, 0), (2, 1, 0))]
    assert prefabs.summary(KIT) == {"parts": 6, "bodies": 2, "size_blocks": [3, 2, 1],
                                    "bounds": [[0, 0, 0], [2, 1, 0]], "microcontrollers": 2, "wires": 1}


def test_paste_copies_parts_and_wires_and_numbers_bodies():
    record = floor()
    proposed = edited(record, [prefabs.paste_operation(KIT, [0, 1, 0])])
    parts, _ = materialize(proposed)
    pasted = [p for p in parts if p.uid.startswith("edit:0:")]
    assert len(pasted) == 6 and {p.body for p in pasted} == {"1", "2"}
    assert next(p for p in pasted if p.piece.d == "microprocessor").origin == (0, 2, 0)
    links = [w for w in wires(proposed, parts) if w["link_id"].startswith("paste:")]
    assert len(links) == 1 and links[0]["from"]["part_id"] == "edit:0:3" and links[0]["to"]["part_id"] == "edit:0:4"
    xml, _, _ = export(proposed)
    back = VehicleDocument.parse(xml)
    assert '<voxel_pos_0 y="2"/><voxel_pos_1 x="2" y="2"/>' in xml.replace("\n", "")
    assert 'bodies_id="2"' in xml and len(back.bodies) == 2
    assert 'name="B"' in xml   # the microcontroller's logic is copied exactly


def test_rotated_paste_moves_wires_with_the_parts():
    proposed = edited(floor(), [prefabs.paste_operation(KIT, [0, 1, 0], QUARTER_Y)])
    parts, _ = materialize(proposed)
    mcs = [p.origin for p in parts if p.piece.d == "microprocessor"]
    assert mcs == [(0, 2, 0), (0, 2, 2)]       # x turned onto z; lowest corner at [0, 1, 0]
    link = next(w for w in wires(proposed, parts) if w["link_id"].startswith("paste:"))
    assert (link["from"]["part_id"], link["to"]["part_id"]) == ("edit:0:3", "edit:0:4")


def test_overlap_is_refused_unless_replacing():
    record = floor()
    with pytest.raises(ValueError, match="overlaps 3 part"):
        materialize(edited(record, [prefabs.paste_operation(KIT, [0, 0, 0])]))
    parts, _ = materialize(edited(record, [prefabs.paste_operation(KIT, [0, 0, 0], replace=True)]))
    assert len(parts) == 81 - 3 + 6


def test_paste_report_lists_points_and_loose_groups():
    from swhull.jobs import paste_prefab  # noqa: PLC0415
    record = floor()
    _, _, note, report = paste_prefab(record, prefabs.paste_operation(KIT, [0, 1, 0], name="kit"), "floor")
    assert report["attached"] and report["parts"] == 6 and report["replaced"] == 0
    assert report["points"] == [{"name": "spare", "kind": "wire", "label": "Spare", "definition": "microprocessor",
                                 "part_id": "edit:0:4", "port": "2", "type": "number", "direction": "input",
                                 "position": (2, 2, 1)}]
    _, _, note, report = paste_prefab(record, prefabs.paste_operation(KIT, [0, 5, 0]), "floor")
    assert not report["attached"] and report["loose_groups"][0]["parts"] == 6 and "touch nothing" in note


def test_cut_keeps_whole_parts_and_inside_wires():
    xml, report = prefabs.cut(KIT, [[2, 0, 0], [2, 1, 0]])
    assert report == {"parts": 2, "in_box": 2, "followed_pipes": 0, "followed_wires": 0, "wires": 0, "bodies": 1}
    assert len(prefabs.points(xml)) == 2          # In and Spare: their wire left with controller A
    xml, report = prefabs.cut(KIT, [[2, 0, 0], [2, 1, 0]], ["wires"])
    assert report["followed_wires"] == 1 and report["wires"] == 1
    doc = VehicleDocument.parse(xml)
    assert doc.to_xml(doc.parts) == xml and len(prefabs.links(xml)) == 1
    with pytest.raises(ValueError, match="no parts"):
        prefabs.cut(KIT, [[9, 9, 9], [9, 9, 9]])


def test_rename_keeps_names_across_file_changes(tmp_path, monkeypatch):
    monkeypatch.setenv("SW_PREFABS_DIR", str(tmp_path))
    record = prefabs.make_record("kit", "kit", KIT, rename={"spare": "aux"})
    prefabs.write(record)
    assert prefabs.describe(prefabs.read("kit"), KIT)["points"][0]["name"] == "aux"
    changed = KIT.replace(block(2, 0, 0), block(2, 0, 0) + block(3, 0, 0))
    shown = prefabs.describe(prefabs.read("kit"), changed)
    assert shown["status"].startswith("changed") and shown["points"][0]["name"] == "aux"
    with pytest.raises(ValueError, match="no connection point"):
        prefabs.make_record("kit", "kit", KIT, record, {"nope": "x"})
    with pytest.raises(ValueError, match="already names"):
        prefabs.make_record("kit", "other", KIT, record)


def test_prefab_tools_register_cut_paste_and_save(tmp_path, monkeypatch):
    vehicles, designs = tmp_path / "vehicles", tmp_path / "designs"
    vehicles.mkdir()
    monkeypatch.setenv("SW_VEHICLES_DIR", str(vehicles))
    monkeypatch.setenv("SW_DESIGNS_DIR", str(designs))
    monkeypatch.setattr(server, "_thumbnail", lambda xml: anyio.sleep(0))
    (vehicles / "kit.xml").write_text(KIT, encoding="utf-8")
    (vehicles / "floor.xml").write_text(to_xml([Placed(BLOCK, (x, 0, 0)) for x in range(-3, 4)]), encoding="utf-8")
    info = call(server.create_prefab, "kit", rename={"spare": "aux"})
    assert info["connection_points"] == 1 and info["points"][0]["name"] == "aux"
    listed = call(server.list_prefabs)
    assert listed["prefabs"][0]["name"] == "kit" and "points" not in listed["prefabs"][0]
    assert call(server.list_prefabs, "kit")["prefabs"][0]["points"][0]["name"] == "aux"
    cut = call(server.create_prefab, "kit end", "kit", [[2, 0, 0], [2, 1, 0]], ["wires"])
    assert cut["cut"]["parts"] == 3 and (vehicles / "kit end.xml").exists()
    with pytest.raises(ToolError, match="overwrite"):
        call(server.create_prefab, "kit end", "kit", [[2, 0, 0], [2, 1, 0]])
    with pytest.raises(ToolError, match="did not cut"):
        call(server.create_prefab, "floor", "kit", [[2, 0, 0], [2, 1, 0]])
    call(server.import_vehicle, "floor", "deck")
    revision = call(server.query_parts, "deck")["revision"]
    result = unpack(call(server.paste_prefab, "deck", "kit", [-1, 1, 0], revision=revision, commit=True))[2]
    assert result["committed"] and result["attached"] and result["points"][0]["name"] == "aux"
    assert result["points"][0]["part_id"] == "edit:0:4"
    with pytest.raises(ToolError, match="overlaps"):
        call(server.paste_prefab, "deck", "kit", [-1, 1, 0])
    call(server.save_vehicle, "deck kit", "deck")
    saved = (vehicles / "deck kit.xml").read_text(encoding="utf-8")
    assert saved.count('d="microprocessor"') == 2 and saved.count("<logic_node_link ") == 1
    side = json.loads((tmp_path / "prefabs" / "kit end.json").read_text(encoding="utf-8"))
    assert side["cut_from"]["vehicle"] == "kit"


# --- block-built tanks --------------------------------------------------------------------

SPAWNER = definitions.load("water_spawner") is not None
spawner_installed = pytest.mark.skipif(not SPAWNER, reason="installed Fluid Spawner definition required")


def box(lo, hi, hollow=True):
    return [Placed(BLOCK, (x, y, z)) for x in range(lo[0], hi[0] + 1) for y in range(lo[1], hi[1] + 1)
            for z in range(lo[2], hi[2] + 1)
            if not hollow or x in (lo[0], hi[0]) or y in (lo[1], hi[1]) or z in (lo[2], hi[2])]


@spawner_installed
def test_tank_in_a_closed_space_adds_a_spawner_and_checks_the_seal():
    parts = box((0, 0, 0), (4, 4, 4))
    out = apply_edits(parts, [{"op": "tank", "seed": [2, 2, 2], "fluid": "jet_fuel", "fill": 0.5, "name": "fuel"}])
    unit = next(p for p in out if p.piece.d == "water_spawner")
    assert unit.origin == (1, 1, 1) and unit.settings["fluid_type"] == 2 and unit.settings["fluid_fill"] == 0.5
    leaky = [p for p in parts if p.origin != (4, 2, 2)]
    with pytest.raises(ValueError, match="open to the outside"):
        apply_edits(leaky, [{"op": "tank", "seed": [2, 2, 2]}])
    with pytest.raises(ValueError, match="inside a part"):
        apply_edits(parts, [{"op": "tank", "seed": [0, 0, 0]}])


@spawner_installed
def test_box_tank_builds_its_walls():
    base = box((-1, -1, -1), (5, -1, 5), hollow=False)
    out = apply_edits(base, [{"op": "tank", "bounds": [[0, 0, 0], [3, 3, 3]], "name": "water", "fluid": "water"}])
    walls = [p for p in out if p.name == "water wall"]
    assert len(walls) == 4 ** 3 - 2 ** 3
    assert sum(p.piece.d == "water_spawner" for p in out) == 1
    with pytest.raises(ValueError, match="at least 3 blocks"):
        apply_edits(base, [{"op": "tank", "bounds": [[0, 0, 0], [1, 3, 3]]}])
    with pytest.raises(ValueError, match="not empty"):
        apply_edits(base + [Placed(BLOCK, (1, 1, 1))], [{"op": "tank", "bounds": [[0, 0, 0], [3, 3, 3]]}])


@spawner_installed
def test_tank_edit_reports_litres():
    from swhull.jobs import change_summary  # noqa: PLC0415
    record, _, _ = import_draft(to_xml(box((0, 0, 0), (4, 4, 4))), "box")
    proposed = edited(record, [{"op": "tank", "seed": [2, 2, 2], "name": "fuel"}])
    note = change_summary(record, proposed)
    # 27 empty blocks less the spawner's sealed base: 26 x 15.625 L.
    assert "Tank 'fuel': 406.2 L of diesel" in note


# --- modular engine couplings -------------------------------------------------------------

def fake(d):
    return Piece(d, 6, 1.0, ((0, 0, 0),), BLOCK.verts, BLOCK.faces)


def test_couplings_join_facing_matching_ends(monkeypatch):
    def coupling(orientation, kind, gender, name="c"):
        return {"attributes": {"orientation": str(orientation), "coupling_type": kind, "coupling_name": name,
                               "coupling_gender": str(gender)}, "position": (0, 0, 0)}
    table = {"modular_engine_crankshaft": [coupling(0, "cylinder", 2, "cylinder_a")],
             "modular_engine_cylinder_straight": [coupling(1, "cylinder", 1, "cylinder_straight"),
                                                  coupling(0, "manifold", 0, "manifold_a")],
             "modular_engine_air_manifold": [coupling(1, "manifold", 0, "intake_manifold")]}
    monkeypatch.setattr(definitions, "metadata", lambda d: {"couplings": table.get(d, [])})
    modular._local.cache_clear()
    try:
        crank = Placed(fake("modular_engine_crankshaft"), (0, 0, 0), uid="crank")
        cylinder = Placed(fake("modular_engine_cylinder_straight"), (1, 0, 0), uid="cyl")
        air = Placed(fake("modular_engine_air_manifold"), (2, 0, 0), uid="air")
        groups, pairs = modular.engines([crank, cylinder, air])
        assert [len(g) for g in groups] == [3] and len(pairs) == 2
        assert modular._feeds(groups[0], pairs) == {"cyl": {"air"}}
        # Turned away, the cylinder no longer meets the crankshaft.
        turned = Placed(fake("modular_engine_cylinder_straight"), (1, 0, 0), ((-1, 0, 0), (0, 1, 0), (0, 0, -1)),
                        uid="cyl")
        assert modular.engines([crank, turned])[0] == [[crank]]
    finally:
        modular._local.cache_clear()
