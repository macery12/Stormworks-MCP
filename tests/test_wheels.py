"""Drive arrows, steering signs and axle mirroring survive different vehicle frames."""
import copy
from itertools import product

import pytest

from swhull import definitions
from swhull.components import full_faces
from swhull.connections import transmission_ports
from swhull.drafts import materialize
from swhull.editing import VehicleDocument, part, query
from swhull.networks import preflight, wheel_control_checks, wires, write_xml
from swhull.orientation import describe, solve, wheel_directions
from swhull.pieces import MIRRORED, ROTATIONS, apply, parse_r, with_mirror
from swhull.reference import xml_root
from swhull.vehicle import MISSING_R, component_xml, components_from_text, to_xml

WHEELS = [f"wheel_advanced_{size}{suffix}" for size, suffix in product((3, 5, 7, 9), ("", "_sus"))]


@pytest.fixture
def wheels(tmp_path, monkeypatch):
    # Invented shape/port fixtures; no installed asset files are copied.
    for d in WHEELS:
        (tmp_path / f"{d}.xml").write_text(
            '<definition><voxels><voxel flags="1"><position/></voxel>'
            '<voxel flags="2"><position y="2"/></voxel></voxels><surfaces>'
            '<surface orientation="3" shape="3" trans_type="1"><position/></surface></surfaces>'
            '<dynamic_rotation_axes y="1"/><dynamic_side_axis x="1"/>'
            '<logic_nodes><logic_node type="1" mode="1" label="Steering"><position/></logic_node>'
            '</logic_nodes></definition>')
    monkeypatch.setattr(definitions, "definitions_dir", lambda: str(tmp_path))
    definitions.load.cache_clear()
    definitions.metadata.cache_clear()
    full_faces.cache_clear()
    yield
    definitions.load.cache_clear()
    definitions.metadata.cache_clear()
    full_faces.cache_clear()


@pytest.mark.parametrize("d", WHEELS)
@pytest.mark.parametrize("frame", ROTATIONS)
@pytest.mark.parametrize("side", [-1, 1])
def test_complete_wheel_frame_keeps_drive_and_steering_arrows_consistent(wheels, d, frame, side):
    front, up, right = (apply(frame, v) for v in ((0, 0, 1), (0, 1, 0), (1, 0, 0)))
    outward = apply(frame, (side, 0, 0))
    pose = describe(d, {"axle_axis": outward, "wheel_reference_up": up, "wheel_forward": front})
    p = part({"definition": d, "position": [3, 7, -2], "rotation": pose["rotation"]})
    direction = wheel_directions(p, front, up)
    assert direction["forward_dot"] == direction["up_dot"] == 1
    assert direction["required_steering_sign"] == side
    assert pose["mirror"] == (2 if side == 1 else 0)
    # The game matrix is transposed on disk; t mirrors local y before rotation.
    q = with_mirror(parse_r(pose["r"]), pose["mirror"])
    assert q == p.Q
    c = xml_root(to_xml([p])).find("bodies/body/components/c")
    assert int(c.get("t", "0")) == pose["mirror"]
    assert list(components_from_text(to_xml([p])))[0][2] == p.Q
    # Inward RPS/mount port is unchanged by the drive direction constraint.
    assert transmission_ports(p)[0]["normal"] == tuple(-n for n in outward)
    # D=+1 must bend toward right, A=-1 toward left. The left wheel's
    # positive arrow points left, so its input is inverted (as in the quad).
    for axis1 in (-1, 1):
        signal = axis1 * direction["required_steering_sign"]
        tangent = tuple(n * signal for n in direction["wheel_positive_steering"])
        assert tangent == tuple(n * axis1 for n in right)


def test_mount_direction_alone_can_leave_the_drive_arrow_backwards(wheels):
    old_right = solve(WHEELS[0], {"axle_axis": [1, 0, 0], "wheel_reference_up": [0, 1, 0]})
    p = part({"definition": WHEELS[0], "position": [0, 0, 0], "rotation": old_right})
    assert wheel_directions(p)["forward_dot"] == -1
    assert wheel_directions(p)["required_steering_sign"] is None
    # Saved workshop wheels use the default editor rotation on the left and
    # that same rotation with t=2 on the right. Explicit r remains mandatory.
    left = solve(WHEELS[0], {"axle_axis": [-1, 0, 0], "wheel_reference_up": [0, 1, 0], "wheel_forward": [0, 0, 1]})
    right = solve(WHEELS[0], {"axle_axis": [1, 0, 0], "wheel_reference_up": [0, 1, 0], "wheel_forward": [0, 0, 1]})
    assert left == MISSING_R and right == with_mirror(MISSING_R, 2)


@pytest.mark.parametrize("q", MIRRORED)
def test_mirrored_query_rows_can_be_used_for_new_placements(wheels, q):
    p = part({"definition": WHEELS[0], "position": [0, 0, 0], "rotation": q})
    row = query([p])["parts"][0]
    assert row["mirror"] == 2 and row["transform"] == q
    assert q == part(row).Q
    assert q == part({"definition": WHEELS[0], "position": [0, 0, 0], "rotation": row["transform"]}).Q


@pytest.mark.parametrize("mask", [True, -1, 8, "2", 2.5])
def test_invalid_mirror_masks_are_rejected(wheels, mask):
    with pytest.raises(ValueError, match="mirror"):
        part({"definition": WHEELS[0], "position": [0, 0, 0], "mirror": mask})


def test_mirror_and_matrix_constraints_remain_unambiguous(wheels):
    with pytest.raises(ValueError, match="not both"):
        part({"definition": WHEELS[0], "position": [0, 0, 0], "rotation": MIRRORED[0], "mirror": 2})
    with pytest.raises(ValueError, match="no rotation"):
        solve(WHEELS[0], {"axle_axis": [1, 0, 0], "wheel_forward": [1, 0, 0]})


@pytest.fixture(scope="module")
def connected_humvee():
    if not definitions.definitions_dir():
        pytest.skip("Stormworks installation unavailable")
    record = {"kind": "land", "spec": {"preset": "humvee_4x4", "bench": "S"}}
    parts, _ = materialize(record)
    return record, parts


@pytest.mark.parametrize("front", [(0, 0, 1), (1, 0, 0), (0, 0, -1), (-1, 0, 0)])
def test_connected_humvee_controls_and_paths_survive_every_horizontal_heading(connected_humvee, front):
    record, source = connected_humvee
    yaw = next(q for q in ROTATIONS if apply(q, (0, 0, 1)) == front and apply(q, (0, 1, 0)) == (0, 1, 0))
    parts = copy.deepcopy(source)
    for p in parts:
        p.origin = apply(yaw, p.origin)
        p.Q = tuple(tuple(sum(yaw[i][k] * p.Q[k][j] for k in range(3)) for j in range(3)) for i in range(3))
    report = preflight(record, parts)
    assert report["status"] == "connected geometry"
    assert report["wire_count"] == 23 and report["configuration_checks"][0]["power_percent"] == 100
    assert len(report["wheel_direction_checks"]) == 4
    front_wheels = [r for r in report["wheel_direction_checks"] if "front" in r["name"]]
    assert all(r["steering_status"] == "matches arrows" for r in front_wheels)
    assert {r["steering_signal_sign"] for r in front_wheels} == {-1, 1}
    xml = write_xml(to_xml(parts), record, parts)
    document = VehicleDocument.parse(xml)
    imported = preflight({"kind": "imported", "source_xml": xml}, document.parts)
    assert imported["status"] == "connected geometry" and imported["wire_count"] == 23
    assert document.to_xml(document.parts) == xml


def test_preflight_reports_old_rotations_and_wrong_or_unknown_steering_logic(connected_humvee):
    record, source = connected_humvee
    parts = copy.deepcopy(source)
    right = next(p for p in parts if p.name == "front right wheel")
    right.Q = solve(right.piece.d, {"axle_axis": [1, 0, 0], "wheel_reference_up": [0, 1, 0]})
    assert any(i["part_id"] == right.uid and i["issue"] == "wheel arrows need review"
               for i in preflight(record, parts)["issues"])
    parts = copy.deepcopy(source)
    inverter = next(p for p in parts if p.name == "left steering inverter")
    inverter.settings["property_text"] = "x"
    report = preflight(record, parts)
    assert any(r["steering_status"] == "opposes arrows" for r in report["wheel_direction_checks"])
    # General functions/controllers are not evaluated or silently declared valid.
    inverter.settings["property_text"] = "sin(x)"
    rows = wheel_control_checks(parts, wires(record, parts))
    assert next(r for r in rows if r["name"] == "front left wheel")["steering_status"] == "unknown"
    assert all(component_xml(p) for p in parts)
