"""Typed connections and routed topology use invented fixtures, not game asset copies."""
import copy

import pytest

from swhull import definitions
from swhull.connections import transmission_ports
from swhull.editing import VehicleDocument
from swhull.networks import edited, ports, query, wire, wires, write_xml
from swhull.pieces import BLOCK, IDENTITY, Piece, Placed, with_mirror
from swhull.reference import xml_root
from swhull.routing import route
from swhull.vehicle import to_xml


@pytest.fixture
def equipment(monkeypatch):
    data = {}
    for d, typ, mode in (("output", 1, 0), ("input", 1, 1), ("bool_output", 0, 0), ("electric", 4, 1)):
        data[d] = {"logic_nodes": [{"index": 0, "type": typ, "mode": mode, "label": d, "position": (0, 0, 0)}],
                   "attachment_surfaces": [], "footprint": [(0, 0, 0)]}
    shapes = {"trans_straight": (0, 1), "trans_angle": (1, 2), "trans_t": (1, 2, 3),
              "trans_block_straight": (0, 1), "trans_block_angle": (1, 2), "face_a": (0,), "face_b": (1,)}
    for d, normals in shapes.items():
        data[d] = {"logic_nodes": [], "footprint": [(0, 0, 0)], "attachment_surfaces": [
            {"orientation": n, "position": (0, 0, 0), "shape": 3, "trans_type": 1} for n in normals]}
    monkeypatch.setattr(definitions, "metadata", data.get)
    monkeypatch.setattr(definitions, "load", lambda d: Piece(d, 6, 1, BLOCK.footprint, BLOCK.verts, BLOCK.faces) if d in data else None)

    def part(d, uid, pos=(0, 0, 0), q=IDENTITY):
        return Placed(definitions.load(d), pos, q, uid=uid)
    return part


def ref(uid, port=0):
    return {"part_id": uid, "port": port}


def test_typed_wires_reject_mismatch_reverse_and_multiple_drivers(equipment):
    parts = [equipment("output", "a"), equipment("input", "b", (2, 0, 0)), equipment("output", "c", (4, 0, 0)),
             equipment("bool_output", "d", (6, 0, 0))]
    record = {"kind": "imported"}
    connect = {"op": "connect", "from": ref("a"), "to": ref("b")}
    proposed = edited(record, [connect], parts)
    assert "connection_edits" not in record
    assert wires(proposed, parts)[0]["type"] == 1
    with pytest.raises(ValueError, match="type mismatch"):
        wire(parts, ref("d"), ref("b"), "bad")
    with pytest.raises(ValueError, match="output"):
        wire(parts, ref("b"), ref("a"), "bad")
    with pytest.raises(ValueError, match="already driven"):
        edited(proposed, [{**connect, "from": ref("c")}], parts)
    with pytest.raises(ValueError, match="duplicate"):
        edited(proposed, [connect], parts)
    disconnected = edited(proposed, [{"op": "disconnect", "link_id": "connection:0"}], parts)
    assert wires(disconnected, parts) == []


def test_electricity_is_bidirectional_and_transformed_ports_serialize(equipment):
    parts = [equipment("electric", "a", (2, 3, 4)), equipment("electric", "b", (-2, -3, -4), with_mirror(IDENTITY, 1))]
    record = edited({}, [{"op": "connect", "from": ref("b"), "to": ref("a")}], parts)
    root = xml_root(write_xml(to_xml(parts), record, parts))
    link = root.find("logic_node_links/logic_node_link")
    assert link.get("type") == "4"
    assert link.find("voxel_pos_0").attrib == {"x": "-2", "y": "-3", "z": "-4"}
    assert link.find("voxel_pos_1").attrib == {"x": "2", "y": "3", "z": "4"}
    moved = copy.deepcopy(parts)
    moved[0].origin = (0, 0, 0)
    assert 'voxel_pos_1/>' in write_xml(to_xml(moved), record, moved)
    with pytest.raises(ValueError, match="stale"):
        write_xml(to_xml(parts[:1]), record, parts[:1])


def test_imported_controller_indices_and_unchanged_source_links_are_lossless(equipment):
    xml = to_xml([equipment("output", "a")]).replace('</components>',
        '<c d="unknown_controller"><o r="1,0,0,0,1,0,0,0,1"><vp x="4"/>'
        '<microprocessor_definition><nodes><n id="57"><node type="1" mode="1" label="Throttle"><position x="1"/></node></n>'
        '</nodes></microprocessor_definition></o></c></components>')
    document = VehicleDocument.parse(xml)
    record = {"kind": "imported", "source_xml": xml}
    assert ports(document.parts[1])[0]["index"] == "57"
    assert write_xml(xml, record, document.parts) == xml
    proposed = edited(record, [{"op": "connect", "from": ref("original:0"), "to": ref("original:1", "57")}], document.parts)
    connected = write_xml(xml, proposed, document.parts)
    assert 'voxel_pos_1 x="5"' in connected
    assert document.parts[1].raw_xml in connected
    reimported = VehicleDocument.parse(connected)
    rows = query({"kind": "imported", "source_xml": connected}, reimported.parts)
    assert rows["links"][0]["to"] == ref("original:1", "57")
    removed = edited({"kind": "imported", "source_xml": connected},
                     [{"op": "disconnect", "link_id": "source:0"}], reimported.parts)
    assert not xml_root(write_xml(connected, removed, reimported.parts)).findall("logic_node_links/logic_node_link")


def test_router_avoids_structure_and_uses_facing_corner_ports(equipment):
    a, b = equipment("face_a", "a"), equipment("face_b", "b", (6, 0, 0))
    obstacle = Placed(BLOCK, (3, 0, 0), uid="obstacle")
    original = [a, b, obstacle]
    result, added = route(original, {"part_id": "a", "surface_index": 0}, {"part_id": "b", "surface_index": 0},
                          extent=[[-1, -1, -1], [7, 1, 1]])
    assert len(original) == 3 and added
    assert all(p.origin != obstacle.origin for p in added)
    all_ports = {(f["position"], f["normal"]) for p in result for f in transmission_ports(p)}
    for p in added:
        for face in transmission_ports(p):
            other = tuple(face["position"][i] + face["normal"][i] for i in range(3))
            assert (other, tuple(-v for v in face["normal"])) in all_ports
    with pytest.raises(ValueError, match="no unobstructed"):
        route(original, {"part_id": "a", "surface_index": 0}, {"part_id": "b", "surface_index": 0},
              extent=[[0, 0, 0], [6, 0, 0]])


def test_router_reports_blocked_ports_and_rejects_self_intersecting_waypoints(equipment):
    a, b = equipment("face_a", "a"), equipment("face_b", "b", (6, 0, 0))
    with pytest.raises(ValueError, match="exit blocked.*obstacle"):
        route([a, b, Placed(BLOCK, (1, 0, 0), uid="obstacle")],
              {"part_id": "a", "surface_index": 0}, {"part_id": "b", "surface_index": 0})
    with pytest.raises(ValueError):
        route([a, b], {"part_id": "a", "surface_index": 0}, {"part_id": "b", "surface_index": 0},
              waypoints=[[3, 0, 0], [1, 0, 0]])
    with pytest.raises(ValueError, match="reserved access"):
        route([a, b], {"part_id": "a", "surface_index": 0}, {"part_id": "b", "surface_index": 0},
              reserved={(1, 0, 0)})


def test_disconnected_generated_endpoint_can_be_removed_without_replaying_a_stale_wire(equipment):
    parts = [equipment("output", "a"), equipment("input", "b", (2, 0, 0))]
    record = edited({}, [{"op": "connect", "from": ref("a"), "to": ref("b")}], parts)
    record = edited(record, [{"op": "disconnect", "link_id": "connection:0"}], parts)
    assert wires(record, parts[:1]) == []


def test_pipe_blocks_replace_only_selected_plain_wall_blocks_and_restore_on_route_removal(equipment):
    from swhull.routing import apply_routes  # noqa: PLC0415
    a, b = equipment("face_a", "a"), equipment("face_b", "b", (6, 0, 0))
    wall = Placed(BLOCK, (3, 0, 0), color="AABBCC", uid="wall")
    parts = [a, b, wall]
    op = {"from": {"part_id": "a", "surface_index": 0}, "to": {"part_id": "b", "surface_index": 0},
          "bounds": [[0, 0, 0], [6, 0, 0]], "through_blocks": ["wall"]}
    record = {"route_edits": [op]}
    result = apply_routes(record, parts)
    crossing = next(p for p in result if p.origin == wall.origin)
    assert crossing.piece.d == "trans_block_straight" and crossing.color == wall.color
    assert wall in parts and all(p.uid != "wall" for p in result)
    assert all(p.piece.d == "trans_straight" for p in result if p.uid.startswith("route:") and p is not crossing)
    assert apply_routes({"route_edits": [op, {"op": "remove", "route_id": "route:0"}]}, parts) == parts
    with pytest.raises(ValueError, match="no unobstructed"):
        apply_routes({"route_edits": [{k: v for k, v in op.items() if k != "through_blocks"}]}, parts)
    wall.protected = True
    with pytest.raises(ValueError, match="unconfigured, unlinked"):
        apply_routes(record, parts)


def test_explicit_enclosed_style_and_invalid_or_unused_block_selections(equipment):
    a, b = equipment("face_a", "a"), equipment("face_b", "b", (6, 0, 0))
    start, end = {"part_id": "a", "surface_index": 0}, {"part_id": "b", "surface_index": 0}
    _, added = route([a, b], start, end, pipe_style="enclosed")
    assert len(added) == 5 and all(p.piece.d == "trans_block_straight" for p in added)
    with pytest.raises(ValueError, match="pipe_style"):
        route([a, b], start, end, pipe_style="small")
    with pytest.raises(ValueError, match="stale through_blocks"):
        route([a, b], start, end, through_blocks=["missing"])
    wall = Placed(BLOCK, (3, 0, 2), uid="unused")
    with pytest.raises(ValueError, match="does not use selected wall blocks"):
        route([a, b, wall], start, end, through_blocks=[wall.uid])
    with pytest.raises(ValueError, match="distinct plain block"):
        route([a, b, wall], start, end, through_blocks=[wall.uid, wall.uid])
    wall.settings = {"signal": 1}
    with pytest.raises(ValueError, match="unconfigured, unlinked"):
        route([a, b, wall], start, end, through_blocks=[wall.uid])


def test_shortest_route_uses_minimum_bends_and_nearest_reachable_tree_target():
    from swhull.routing import _path  # noqa: PLC0415
    path = _path((0, 0, 0), (4, 0, 4), {}, set(), [[0, 0, 0], [4, 0, 4]],
                 initial_direction=(1, 0, 0), final_direction=(0, 0, 1))
    directions = [tuple(b[i] - a[i] for i in range(3)) for a, b in zip(path, path[1:])]
    assert len(path) == 9
    assert sum(a != b for a, b in zip(directions, directions[1:])) == 1
    assert directions[0] == (1, 0, 0) and directions[-1] == (0, 0, 1)
    # The nearer target lies behind a complete wall; choosing it before searching
    # incorrectly fails even though the existing network has an accessible branch.
    occupied = {(2, 0, z): Placed(BLOCK, (2, 0, z)) for z in range(5)}
    path = _path((1, 0, 0), {(3, 0, 0), (0, 0, 4)}, occupied, set(), [[0, 0, 0], [4, 0, 4]])
    assert path[-1] == (0, 0, 4)


@pytest.mark.installed
@pytest.mark.parametrize("wall_crossing", [False, True])
def test_mcp_connection_routing_commit_removal_undo_and_separate_export(tmp_path, monkeypatch, wall_crossing):
    if not definitions.definitions_dir():
        pytest.skip("Stormworks installation unavailable")
    import functools  # noqa: PLC0415
    import anyio  # noqa: PLC0415
    import server  # noqa: PLC0415
    from swhull.editing import revision  # noqa: PLC0415
    vehicles, designs = tmp_path / "vehicles", tmp_path / "designs"
    vehicles.mkdir()
    monkeypatch.setenv("SW_VEHICLES_DIR", str(vehicles))
    monkeypatch.setenv("SW_DESIGNS_DIR", str(designs))
    parts = [Placed(definitions.load("engine"), (0, 0, 0)), Placed(definitions.load("torque_clutch"), (0, 4, 0))]
    if wall_crossing:
        parts.append(Placed(BLOCK, (0, 3, 0), color="AABBCC"))
    xml = to_xml(parts)
    (vehicles / "original.xml").write_text(xml)

    def call(fn, *args, **kwargs):
        return anyio.run(functools.partial(fn, *args, **kwargs))

    call(server.import_vehicle, "original", "routing test")
    record = server._read_design("routing test")
    rows = call(server.query_connections, "routing test")
    a = next(f for r in rows["components"] if r["definition"] == "engine" for f in r["transmission_faces"] if f["trans_type"] == 1)
    b = next(f for r in rows["components"] if r["definition"] == "torque_clutch" for f in r["transmission_faces"] if f["normal"] == (0, -1, 0))
    routes = [{"from": {k: a[k] for k in ("part_id", "surface_index")}, "to": {k: b[k] for k in ("part_id", "surface_index")}}]
    if wall_crossing:
        routes[0]["through_blocks"] = ["original:2"]
    call(server.route_connections, "routing test", routes, rows["revision"])
    assert server._read_design("routing test") == record
    call(server.route_connections, "routing test", routes, rows["revision"], commit=True)
    rows = call(server.query_connections, "routing test")
    assert rows["routes"][0]["part_count"] == 1
    call(server.save_vehicle, "routed copy", "routing test")
    saved = VehicleDocument.parse((vehicles / "routed copy.xml").read_text()).parts
    assert len(saved) == 3
    assert any(p.piece.d == ("trans_block_straight" if wall_crossing else "trans_straight") for p in saved)
    assert (vehicles / "original.xml").read_text() == xml
    call(server.route_connections, "routing test", [{"op": "remove", "route_id": "route:0"}], rows["revision"], commit=True)
    current = server._read_design("routing test")
    assert not call(server.query_connections, "routing test")["routes"]
    server.undo_edits("routing test", revision(current))
    assert call(server.query_connections, "routing test")["routes"][0]["part_count"] == 1


@pytest.mark.installed
@pytest.mark.parametrize("preset", ["utility_4x4", "humvee_4x4"])
def test_installed_connected_4x4_has_all_subsystems_and_only_signal_electric_links(preset):
    if not definitions.definitions_dir():
        pytest.skip("Stormworks installation unavailable")
    from swhull.drafts import export, materialize  # noqa: PLC0415
    from swhull.networks import preflight  # noqa: PLC0415
    from swhull.part_policy import CURRENT_GEARBOXES, allowed  # noqa: PLC0415
    record = {"kind": "land", "spec": {"preset": preset, "bench": "S"}}
    parts, _ = materialize(record)
    result = preflight(record, parts)
    assert result["status"] == "connected geometry" and result["missing_count"] == 0
    assert result["physical_face_pairs"] > 50 and result["wire_count"] >= 20
    assert all(allowed(p.piece.d) for p in parts)
    assert not any(p.piece.d.startswith("heat_exchanger") or p.piece.d.startswith("modular_engine")
                   and p.piece.d not in CURRENT_GEARBOXES for p in parts)
    assert sum(p.piece.d == "modular_engine_gearbox_1x1" for p in parts) == 1
    gear = result["gearbox_configuration_checks"][0]
    assert gear["off"]["ratio"] == "1:1" and gear["on"]["ratio"] == "1:-1"
    xml, count, _ = export(record)
    assert count == len(parts)
    links = xml_root(xml).findall("logic_node_links/logic_node_link")
    assert len(links) == result["wire_count"]
    assert {int(link.get("type", "0")) for link in links} == {0, 1, 4}
    reparsed = VehicleDocument.parse(xml)
    assert all(link["status"] == "resolved" for link in query({"kind": "imported", "source_xml": xml}, reparsed.parts)["links"])
