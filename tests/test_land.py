"""Land discovery/layout and chassis invariants without distributing game assets."""
import copy
import functools
from itertools import product

import anyio
import pytest
from mcp.server.mcpserver.exceptions import ToolError

import server
from swhull import definitions
from swhull.components import full_faces, mounting_contacts, owners, validate_placement
from swhull.connections import transmission_ports
from swhull.drafts import edited, export, materialize
from swhull.land import catalogue, category, layout_text, scan_library
from swhull.land_build import build_chassis
from swhull.land_presets import build_land
from swhull.orientation import describe, solve
from swhull.pieces import BLOCK, Placed
from swhull.vehicle import component_xml, to_xml


@pytest.fixture
def land_definitions(tmp_path, monkeypatch):
    # Deliberately simple invented fixtures; this is not copied installed game XML.
    shapes = {
        "wheel_advanced_3_sus": ([(0, 0, 0), *product(range(-1, 2), (1, 2), range(-1, 2))], 3, 1),
        "wheel_advanced_3": ([(0, 0, 0), *product(range(-1, 2), (1,), range(-1, 2))], 3, 1),
        "searchlight_small_2": ([(0, 0, 0)], 0, 0),
        "searchlight_small": ([(0, 0, 0)], 0, 0),
        "small_light": ([(0, 0, 0), (0, 1, 0)], 1, 0),
        "seat_racing": (list(product(range(-1, 2), range(5), range(-1, 3))), 0, 0),
        "seat_passenger": (list(product(range(-1, 2), range(5), range(-1, 2))), 0, 0),
        "motor_small": ([(0, 0, 0)], 1, 0),
        "modular_engine_flywheel": ([(0, 0, 0)], 1, 0),
        "train_wheel": ([(0, 0, 0)], 1, 0),
    }
    for d, (cells, shape, trans) in shapes.items():
        voxels = "".join(f'<voxel flags="{2 if d.startswith("wheel_") and y else 1}">'
                         f'<position x="{x}" y="{y}" z="{z}"/></voxel>' for x, y, z in cells)
        surfaces = "".join(f'<surface orientation="3" shape="{shape}" trans_type="{trans}">'
                           f'<position x="{x}" z="{z}"/></surface>' for x, y, z in cells if y == 0)
        extra = ('<dynamic_rotation_axes y="1"/><dynamic_side_axis x="1"/>' if d.startswith("wheel_") else "")
        extra += ('<light_forward x="1"/>' if d == "searchlight_small_2" else
                  '<light_forward/>' if d == "searchlight_small" else '<light_forward y="1"/>')
        nodes = ('<logic_node label="Axis 1" type="1" mode="0"><position/></logic_node>'
                 if d == "seat_racing" else '')
        if d == "seat_racing":
            extra += '<seat_front z="1"/><seat_up y="1"/>'
        (tmp_path / f"{d}.xml").write_text(
            f'<definition name="{d}" light_type="{1 if d.startswith("searchlight") else 0}">'
            f'<voxels>{voxels}</voxels><surfaces>{surfaces}</surfaces><logic_nodes>{nodes}</logic_nodes>'
            f'{extra}</definition>')
    monkeypatch.setattr(definitions, "definitions_dir", lambda: str(tmp_path))
    monkeypatch.setenv("SW_DEFINITIONS_DIR", str(tmp_path))
    definitions.load.cache_clear()
    definitions.metadata.cache_clear()
    full_faces.cache_clear()
    yield tmp_path
    definitions.load.cache_clear()
    definitions.metadata.cache_clear()
    full_faces.cache_clear()


@pytest.fixture
def buggy_definitions(land_definitions):
    shapes = {
        "seat_saddle": [*product(range(-1, 2), range(4), (-1, 0)), *product(range(-1, 2), (1,), (2,))],
        "engine": list(product(range(-1, 2), range(3), range(-1, 2))),
        "fluid_tank_small": [(0, 0, -1), (0, 0, 0)],
        "battery_small": [(-1, 0, 0), (0, 0, 0)],
        "fluid_radiator": list(product(range(-1, 2), range(-1, 2), (0,))),
    }
    for d, cells in shapes.items():
        voxels = ''.join(f'<voxel flags="1"><position x="{x}" y="{y}" z="{z}"/></voxel>' for x, y, z in cells)
        surfaces = ''.join(f'<surface orientation="{side}" shape="1"><position x="{x}" y="{y}" z="{z}"/></surface>'
                           for x, y, z in cells for side in range(6))
        nodes = '<logic_node label="Axis 1" type="1" mode="0"><position/></logic_node>' if d == "seat_saddle" else ''
        (land_definitions / f"{d}.xml").write_text(f'<definition><voxels>{voxels}</voxels><surfaces>{surfaces}</surfaces>'
                                                f'<logic_nodes>{nodes}</logic_nodes></definition>')
    definitions.load.cache_clear()
    definitions.metadata.cache_clear()
    full_faces.cache_clear()
    return land_definitions


def test_land_catalogue_excludes_flywheels_from_road_wheels(land_definitions):
    result = catalogue("wheels", limit=1)
    assert result["total"] == 2 and result["next_offset"] == 1
    assert catalogue("propulsion", "motor")["parts"][0]["definition"] == "motor_small"
    with pytest.raises(ValueError, match="category"):
        catalogue("unknown")


@pytest.mark.parametrize("definition, expected", [
    ("trans_straight", "transmission"), ("trans_block_angle", "transmission"),
    ("modular_engine_clutch", "transmission"), ("modular_engine_gearbox_3x3", "transmission"),
    ("fluid_radiator_electric_5", "cooling"), ("gate_float_switch", "logic"),
    ("sensor_linear_speed", "utility"), ("modular_engine_flywheel", "propulsion"),
])
def test_installed_component_family_names_are_categorized(definition, expected):
    assert category(definition) == expected


def test_discovery_reads_only_body_components_and_skips_bad_files(land_definitions, tmp_path):
    directory = tmp_path / "saves"
    directory.mkdir()
    wheel = component_xml(Placed(definitions.load("wheel_advanced_3"), (0, 0, 0)))
    nested = '<c d="microprocessor"><o><vp/><microprocessor_definition><group><components>' + wheel + '</components></group></microprocessor_definition></o></c>'
    xml = to_xml([Placed(BLOCK, (0, 0, 0))]).replace("</components>", nested + "</components>")
    (directory / "controller only.xml").write_text(xml)
    road = to_xml([Placed(definitions.load("wheel_advanced_3_sus"), (0, 0, 0))])
    (directory / "unnamed.xml").write_text(road)
    (directory / "flywheel.xml").write_text(to_xml([Placed(definitions.load("modular_engine_flywheel"), (0, 0, 0))]))
    (directory / "broken.xml").write_text("<vehicle")
    result = scan_library(directory)
    assert [r["name"] for r in result["vehicles"]] == ["unnamed"]
    assert result["skipped_count"] == 1
    assert (directory / "unnamed.xml").read_text() == road
    assert scan_library(directory, "unnamed")["total"] == 1


def test_wheel_and_headlight_semantic_axes(land_definitions):
    for side in (-1, 1):
        target = {"axle_axis": [side, 0, 0], "wheel_reference_up": [0, 1, 0]}
        axes = describe("wheel_advanced_3_sus", target)["world_axes"]
        assert axes["axle_axis"] == (side, 0, 0)
        assert axes["mount_normal"] == (-side, 0, 0)
        assert "dynamic_rotation_axes" in axes  # Flag-2 wheels must retain their dynamic axle.
    axes = describe("searchlight_small_2", {"light_forward": [0, 0, 1], "mount_normal": [0, -1, 0]})["world_axes"]
    assert axes["light_forward"] == (0, 0, 1) and axes["mount_normal"] == (0, -1, 0)
    assert "light_forward" not in describe("seat_racing")["axes"]


def test_layout_infers_negative_z_and_retains_settings(land_definitions):
    parts = build_chassis()
    for p in parts:
        if p.name == "driver":
            p.Q = solve("seat_racing", {"seat_front": [0, 0, -1], "seat_up": [0, 1, 0]})
        if p.name == "axle 1 left wheel":
            p.settings["wheel_size"] = 1.5
    xml = to_xml(parts)
    report = layout_text(xml, limit=2)
    body = report["bodies"][0]
    assert body["forward"] == (0, 0, -1) and body["forward_source"] == "driver seat"
    assert body["axle_count"] == 2 and body["wheelbase_metres"] == 2.5
    assert body["axles"][0]["mount_span_metres"] == 1.5
    assert report["counts"]["issues"] == 0 and report["next_offset"] == 2
    wheel = next(r for r in report["wheels"] if r["settings"].get("wheel_size"))
    assert wheel["settings"]["wheel_size"] == "1.5" and "clearance_note" in wheel
    lights = layout_text(xml, forward=[0, 0, 1], section="lights")["lights"]
    assert [r["beam_forward_dot"] for r in lights if "beam_forward_dot" in r] == [1, 1]


def test_layout_does_not_merge_articulated_coordinates(land_definitions):
    wheel = component_xml(Placed(definitions.load("wheel_advanced_3"), (0, 0, 0)))
    body = '<body unique_id="{id}"><components>' + wheel + '</components></body>'
    xml = '<vehicle data_version="3"><bodies>' + body.format(id=1) + body.format(id=2) + '</bodies></vehicle>'
    report = layout_text(xml)
    assert len(report["bodies"]) == 2
    assert all(b["overlap_count"] == 0 and b["wheelbase_metres"] is None for b in report["bodies"])
    assert "assumed" in report["bodies"][0]["forward_source"]
    assert len(layout_text(xml, body_id="2")["wheels"]) == 1
    with pytest.raises(ValueError, match="no body"):
        layout_text(xml, body_id="3")
    with pytest.raises(ValueError, match="horizontal"):
        layout_text(xml, forward=[0, 1, 0])


def test_omitted_light_direction_remains_unknown(land_definitions):
    lamp = Placed(definitions.load("searchlight_small"), (0, 0, 0))
    report = layout_text(to_xml([lamp]), section="lights")
    assert report["lights"][0]["beam_forward_dot"] is None
    assert "calibration" in report["lights"][0]["beam_note"]


def test_layout_reports_modded_parts_without_losing_ordinary_wheels(land_definitions):
    parts = [Placed(BLOCK, (0, 0, 0)), Placed(definitions.load("wheel_advanced_3"), (0, 0, 2))]
    xml = to_xml(parts).replace('r="1,0,0,0,1,0,0,0,1"', 'r="3,0,0,0,1,0,0,0,1"', 1)
    report = layout_text(xml)
    assert report["counts"]["wheels"] == 1
    assert not report["bodies"][0]["geometry_complete"]
    assert report["bodies"][0]["omitted_components"][0]["definition"] == "01_block"


def test_buggy_contains_real_equipment_and_supports_side_access(buggy_definitions):
    parts = build_land({"bench": "S"})
    cells = [v for p in parts for v in p.voxels()]
    assert len(set(cells)) == len(cells)
    required = {"seat_saddle": 1, "engine": 1, "fluid_tank_small": 2, "battery_small": 1,
                "fluid_radiator": 1, "wheel_advanced_3_sus": 4, "searchlight_small_2": 2, "small_light": 2}
    for d, count in required.items():
        assert sum(p.piece.d == d for p in parts) == count
    assert {"side footboard", "rear engine cover", "fender bevel", "sloped nose"} <= {p.name for p in parts}
    report = layout_text(to_xml(parts))
    assert report["bodies"][0]["forward_source"] == "driver seat"
    assert report["bodies"][0]["wheelbase_metres"] == 2
    assert report["counts"]["issues"] == 0


@pytest.mark.parametrize("operation, message", [
    ({"op": "add", "part": {"position": [0, 2, 5]}}, "service access"),
    ({"op": "fill", "bounds": [[-4, 1, 0], [-2, 1, 2]]}, "side access"),
    ({"op": "remove", "select": {"bounds": [[1, -1, 4], [1, -1, 4]]}}, "mounting"),
])
def test_buggy_edits_cannot_block_service_or_detach_wheels(buggy_definitions, operation, message):
    spec = {"edits": [operation]}
    # Block both side approaches when testing access; either side on its own is usable.
    if operation["op"] == "fill":
        spec["edits"].append({"op": "fill", "bounds": [[2, 1, 0], [4, 1, 2]]})
    with pytest.raises(ValueError, match=message):
        build_land(spec)


def test_chassis_records_keep_their_previous_geometry_and_ids(land_definitions):
    legacy = {"kind": "land", "spec": {}, "vehicle": False, "generation": 0}
    explicit = {**legacy, "spec": {"preset": "chassis"}}
    old, _ = materialize(legacy)
    new, _ = materialize(explicit)
    assert [(p.uid, p.piece.d, p.origin) for p in old] == [(p.uid, p.piece.d, p.origin) for p in new]


@pytest.mark.installed
def test_installed_buggy_geometry_and_premade_tanks():
    if definitions.metadata("seat_saddle") is None:
        pytest.skip("Stormworks installation unavailable")
    parts = build_land({"preset": "utility_buggy", "bench": "S"})
    report = layout_text(to_xml(parts), section="equipment")
    assert report["counts"]["issues"] == 0 and report["bodies"][0]["wheelbase_metres"] == 2
    tanks = [r for r in report["equipment"] if r["definition"] == "fluid_tank_small"]
    assert len(tanks) == 2 and all(r["settings"]["fluid_type"] == "1" for r in tanks)
    engine = next(p for p in parts if p.piece.d == "engine")
    owner = owners(parts)
    for port in transmission_ports(engine):
        exit_cell = tuple(port["position"][i] + port["normal"][i] for i in range(3))
        assert exit_cell not in owner, f"Engine connection blocked by {owner[exit_cell].name}"


def test_default_buggy_and_workshop_tools_preserve_reference_files(buggy_definitions, tmp_path, monkeypatch):
    def call(tool, *args, **kwargs):
        return anyio.run(functools.partial(tool, *args, **kwargs))

    designs, vehicles, workshop = (tmp_path / name for name in ("designs", "vehicles", "workshop"))
    vehicles.mkdir()
    monkeypatch.setenv("SW_DESIGNS_DIR", str(designs))
    monkeypatch.setenv("SW_VEHICLES_DIR", str(vehicles))
    monkeypatch.setenv("SW_WORKSHOP_DIR", str(workshop))
    image, text, created = call(server.create_land_vehicle, "buggy", {"bench": "S"})
    stored = server.load_design("buggy")
    assert stored["spec"]["preset"] == "utility_buggy" and created["kind"] == "land"
    assert "premade fuel tank" in text and "unfinished" in text
    assert image.data.startswith(b"\x89PNG") and not list(vehicles.iterdir())
    image, note = call(server.preview_vehicle, "buggy", layer="components", yaw=35)
    assert image.data.startswith(b"\x89PNG") and "footprint fallbacks" in note
    with pytest.raises(ToolError, match="layer"):
        call(server.preview_vehicle, "buggy", layer="invalid")
    opened = []
    monkeypatch.setattr(server.webbrowser, "open", opened.append)
    call(server.open_in_viewer, design="buggy")
    from pathlib import Path  # noqa: PLC0415
    from urllib.parse import urlparse  # noqa: PLC0415
    from urllib.request import url2pathname  # noqa: PLC0415
    page = Path(url2pathname(urlparse(opened[0]).path))
    assert '"geometry": {' in page.read_text(encoding="utf-8")

    xml = to_xml(build_land())
    controller = ('<c d="microcontroller"><o r="1,0,0,0,1,0,0,0,1"><vp x="12"/>'
                  '<microprocessor_definition><group><components><c type="42"><object id="7"/></c>'
                  '</components></group></microprocessor_definition></o></c>')
    xml = xml.replace("</components>", controller + "</components>")
    xml = xml.replace("<logic_node_links/>", '<logic_node_links><logic_node_link><voxel_pos_0/><voxel_pos_1 x="12"/></logic_node_link></logic_node_links>')
    for item in ("111", "222"):
        folder = workshop / item
        folder.mkdir(parents=True)
        (folder / "vehicle.xml").write_text(xml, encoding="utf-8")
    original = (workshop / "111" / "vehicle.xml").read_bytes()
    page = call(server.find_land_vehicles, source="workshop", limit=1)
    assert page["total"] == 2 and page["next_offset"] == 1
    assert call(server.find_land_vehicles, source="workshop", offset=1)["vehicles"][0]["name"] == "222"
    report = call(server.analyze_land_vehicle, name="111", source="workshop")
    assert report["counts"]["wheels"] == 4 and report["link_count"] == 1
    image, note = call(server.preview_game_vehicle, "111", source="workshop")
    assert image.data.startswith(b"\x89PNG") and "Body 1 of 1" in note
    call(server.open_in_viewer, name="111", source="workshop")
    call(server.import_vehicle, "111", "workshop study", source="workshop")
    report = call(server.analyze_land_vehicle, design="workshop study")
    assert report["link_count"] == 1  # Imported draft analysis retains the original links.
    call(server.save_vehicle, "workshop copy", "workshop study")
    assert (vehicles / "workshop copy.xml").read_bytes() == original
    assert (workshop / "111" / "vehicle.xml").read_bytes() == original
    with pytest.raises(ToolError, match="numeric"):
        call(server.preview_game_vehicle, "../111", source="workshop")
    with pytest.raises(ToolError, match="no body"):
        call(server.preview_game_vehicle, "111", source="workshop", body_id="wrong")


def test_chassis_has_no_overlaps_and_every_component_mounts(land_definitions):
    parts = build_chassis()
    cells = [v for p in parts for v in p.voxels()]
    assert len(cells) == len(set(cells))
    owner = owners(parts)
    for p in parts:
        if p.piece.d != "01_block":
            assert mounting_contacts(p, owner)
    assert sum(p.name.endswith("wheel") for p in parts) == 4
    assert {p.name for p in parts if p.piece.d == "searchlight_small_2"} == {"left headlight", "right headlight"}


@pytest.mark.parametrize("spec, message", [
    ({"width": 1.1}, "grid"),
    ({"length": True}, "grid"),
    ({"axles": [{"z": 0}, {"z": 0}]}, "distinct"),
    ({"axles": [{"z": 0}, {"z": 20}]}, "within"),
    ({"driver": []}, "boolean"),
    ({"wheel_definition": "train_wheel"}, "road-wheel"),
    ({"components": [{"position": [0, 0, 0]}]}, "collision"),
    ({"components": [{"definition": "motor_small", "position": [10, 1, 10]}]}, "mounting"),
    ({"length": 1.25, "axles": [{"z": -.25}, {"z": .25}]}, "clearance|collision|passage"),
])
def test_chassis_rejects_bad_geometry_without_mutating_spec(land_definitions, spec, message):
    original = copy.deepcopy(spec)
    with pytest.raises(ValueError, match=message):
        build_chassis(spec)
    assert spec == original


def test_land_draft_edits_and_export_use_stable_build_frame(land_definitions):
    record = {"kind": "land", "spec": {}, "generation": 0, "vehicle": False}
    parts, info = materialize(record)
    assert info is None
    driver = next(p for p in parts if p.name == "driver")
    change = [{"op": "paint", "select": {"ids": [driver.uid]}, "color": "123456"}]
    proposed = edited(record, change)
    after, _ = materialize(proposed)
    assert next(p for p in after if p.uid == driver.uid).origin == driver.origin
    assert next(p for p in after if p.uid == driver.uid).color == "123456"
    xml, count, note = export(proposed)
    assert count == len(after) and 'r="' in xml and "Land chassis" in note
    assert "edits" not in record["spec"]


def test_passenger_seat_on_open_chassis_has_real_access_and_obstruction_diagnostics(land_definitions):
    spec = {"length": 4.25, "width": 1.75, "driver": False, "headlights": False, "tail_lights": False,
            "components": [{"name": "passenger on open chassis", "definition": "seat_passenger", "position": [0, .25, 0]}]}
    parts = build_chassis(spec)
    assert any(p.piece.d == "seat_passenger" for p in parts)
    blocked = {**spec, "edits": [{"op": "fill", "bounds": [[-4, 1, -4], [4, 6, -2]]},
                                 {"op": "add", "parts": [{"position": [-2, 1, 0]}, {"position": [2, 1, 0]}]}]}
    with pytest.raises(ValueError, match="access diagnostics=.*part_id.*missing_support_cells"):
        build_chassis(blocked)


def test_land_seat_needs_a_supported_sill_without_a_large_external_platform(land_definitions):
    seat = Placed(definitions.load("seat_passenger"), (0, 0, 0), name="passenger")
    floor = [Placed(BLOCK, (x, -1, z), uid=f"floor:{x}:{z}")
             for x, z in product(range(-1, 3), range(-1, 2))]
    # One block deep beside the seat, rather than a 3x3 platform extending out.
    space = validate_placement(seat, {"vehicle_kind": "land"}, owners(floor))
    assert len(space) == 45 and max(v[1] for v in space) == 4
    assert {v[0] for v in space} == {2, 3, 4}
    missing = [p for p in floor if p.origin != (2, -1, 0)]
    with pytest.raises(ValueError, match="missing_support_cells"):
        validate_placement(seat, {"vehicle_kind": "land"}, owners(missing))
    blocked = [*floor, Placed(BLOCK, (3, 3, 0), uid="entry-blocker")]
    with pytest.raises(ValueError, match="entry-blocker"):
        validate_placement(seat, {"vehicle_kind": "land"}, owners(blocked))


@pytest.mark.installed
def test_humvee_body_preserves_custom_door_bays_compact_glass_and_short_hidden_pipework():
    if not definitions.definitions_dir():
        pytest.skip("Stormworks installation unavailable")
    from swhull.networks import preflight  # noqa: PLC0415
    record = {"kind": "land", "spec": {"preset": "humvee_4x4", "bench": "S"}}
    parts, _ = materialize(record)
    owner = owners(parts)
    assert not any(p.piece.d.startswith("door") or p.piece.d.startswith("window_angle_xl") for p in parts)
    assert sum(p.piece.d.startswith("window") for p in parts) == 6
    assert sum(p.name == "rear spare tyre" for p in parts) == 1
    for side, z, y in product((-4, 4), (-4, -3, -2, 0, 1, 2), range(5)):
        assert (side, y, z) not in owner
        assert (side, -1, z) in owner
    hood = [p for p in parts if "hood" in p.name]
    assert max(v[1] for p in hood for v in p.voxels()) == 3
    assert sum(p.piece.d == "05_wedge_2" for p in parts) == 7
    pipes = [p for p in parts if p.piece.d.startswith("trans_")]
    assert len(pipes) < 50  # Previous layout needed 99 pieces.
    enclosed = [p for p in pipes if p.piece.d.startswith("trans_block_")]
    assert len(enclosed) >= 30
    assert all(p.piece.d.startswith("trans_block_") for p in pipes if p.origin[1] < 0)
    assert not any(p.name in ("engine shaft", "clutch shaft") for p in pipes)
    report = preflight(record, parts)
    assert report["status"] == "connected geometry" and report["wire_count"] == 23
    assert len(report["non_driven_wheel_faces"]) == 1
    xml, _, note = export(record)
    assert "Connected template" in note
    evidence = layout_text(xml)
    layout = evidence["bodies"][0]
    assert layout["wheelbase_metres"] == 3.5 and len(layout["axles"]) == 2
    assert len(evidence["wheels"]) == 5 and sum(w["wheel_role"] == "spare" for w in evidence["wheels"]) == 1
    # Edits still enforce the completed assembly's access and service checks.
    with pytest.raises(ValueError, match="side access"):
        materialize(edited(record, [{"op": "fill", "bounds": [[-4, 0, 0], [-4, 4, 2]]}]))


def test_named_spare_and_explicit_roles_do_not_extend_road_wheelbase(land_definitions):
    parts = build_chassis()
    spare = Placed(definitions.load("wheel_advanced_3"), (0, 4, -12), name="rear spare wheel")
    xml = to_xml([*parts, spare])
    report = layout_text(xml)
    assert report["bodies"][0]["wheelbase_metres"] == 2.5
    row = next(r for r in report["wheels"] if r["wheel_role"] == "spare")
    assert row["role_source"] == "saved name"
    assert report["counts"]["wheels"] == 5
    explicit = layout_text(xml, wheel_roles={row["part_id"]: "excluded"})
    assert explicit["bodies"][0]["axle_count"] == 2
    with pytest.raises(ValueError, match="stale"):
        layout_text(xml, wheel_roles={"wrong": "spare"})


def test_equipment_policy_filters_modular_engines_and_rejects_new_placements(land_definitions):
    from swhull.editing import part  # noqa: PLC0415
    assert not catalogue(search="modular")["parts"]
    assert not definitions.catalogue(search="modular")["parts"]
    for d in ("modular_engine_flywheel", "heat_exchanger_2_2", "fluid_heatsink"):
        with pytest.raises(ValueError, match="disabled|restricted"):
            part({"definition": d, "position": [0, 0, 0]})


def test_unknown_part_diagnostics_distinguish_a_wrong_id_from_a_missing_install(land_definitions, monkeypatch):
    with pytest.raises(ToolError, match="unknown definition.*search_parts"):
        server.get_part_definition("04_wedge")
    assert "edits" in server.hull_design_guide("topics")
    assert server.hull_design_guide("edits").startswith("#")
    monkeypatch.setattr(definitions, "definitions_dir", lambda: None)
    with pytest.raises(ToolError, match="game definitions not found.*SW_DEFINITIONS_DIR"):
        server.get_part_definition("window_4x4")


@pytest.mark.parametrize("operation, message", [
    ({"op": "remove", "select": {"bounds": [[2, 0, -5], [2, 0, -5]]}}, "mounting"),
    ({"op": "add", "parts": [{"position": [0, 1, -2]}, {"position": [-2, 1, 1]},
                              {"position": [2, 1, 1]}]}, "clearance"),
])
def test_bodywork_edits_cannot_detach_wheels_or_block_driver(land_definitions, operation, message):
    with pytest.raises(ValueError, match=message):
        build_chassis({"edits": [operation]})


def test_rear_obstacle_does_not_block_a_clear_supported_side_entry(land_definitions):
    assert build_chassis({"edits": [{"op": "add", "part": {"position": [0, 1, -2]}}]})


@pytest.mark.installed
def test_installed_chassis_and_wheel_mount_conventions():
    if definitions.metadata("wheel_advanced_3_sus") is None:
        pytest.skip("Stormworks definitions unavailable")
    parts = build_chassis({"bench": "S"})
    report = layout_text(to_xml(parts))
    assert report["counts"]["wheels"] == 4 and report["counts"]["issues"] == 0
    assert report["bodies"][0]["wheelbase_metres"] == 2.5


def test_land_tools_create_edit_analyze_and_save_a_draft(land_definitions, tmp_path, monkeypatch):
    def call(tool, *args, **kwargs):
        return anyio.run(functools.partial(tool, *args, **kwargs))

    vehicles, designs = tmp_path / "vehicles", tmp_path / "designs"
    vehicles.mkdir()
    monkeypatch.setenv("SW_VEHICLES_DIR", str(vehicles))
    monkeypatch.setenv("SW_DESIGNS_DIR", str(designs))
    image, text, created = call(server.create_land_vehicle, "road draft", {"preset": "chassis", "bench": "S"})
    assert image.data[:8] == b"\x89PNG\r\n\x1a\n" and "Land chassis" in text
    assert created["kind"] == "land" and not list(vehicles.iterdir())
    query = call(server.query_parts, "road draft", select={"name": "driver"})
    assert query["revision"] == created["revision"]
    operations = [{"op": "paint", "select": {"ids": [query["parts"][0]["id"]]}, "color": "123456"}]
    _, _, committed = call(server.edit_parts, "road draft", operations, query["revision"], commit=True)
    assert committed["committed"]
    report = call(server.analyze_land_vehicle, design="road draft")
    assert report["evidence_level"] == "draft_geometry" and report["counts"]["wheels"] == 4
    call(server.save_vehicle, "road copy", "road draft")
    assert '123456' in (vehicles / "road copy.xml").read_text()
    assert call(server.find_land_vehicles)["vehicles"][0]["name"] == "road copy"
    report = call(server.analyze_land_vehicle, name="road copy")
    assert report["evidence_level"] == "observed_saved_vehicle"
    assert call(server.search_land_parts, category="lights")["total"] == 3
    stored = server.load_design("road draft")
    assert stored["kind"] == "land" and stored["revision"] == committed["revision"]
    server.undo_edits("road draft", committed["revision"])
    assert call(server.query_parts, "road draft", select={"name": "driver"})["parts"][0]["color"] != "123456"
    assert "0.25 m" in server.land_vehicle_guide()
    with pytest.raises(ToolError, match="already exists"):
        call(server.create_land_vehicle, "road draft")
    with pytest.raises(ToolError, match="land draft"):
        call(server.preview_hull, design="road draft")
    with pytest.raises(ToolError, match="exactly one"):
        call(server.analyze_land_vehicle, name="road copy", design="road draft")
    with pytest.raises(ToolError):
        call(server.create_land_vehicle, "../unsafe")
    with pytest.raises(ToolError, match="grid"):
        call(server.create_land_vehicle, "invalid", {"preset": "chassis", "width": 1.1})
    assert not (designs / "invalid.json").exists()
