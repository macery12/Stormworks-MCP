"""Every installed part, all rotations/reflections, against an independent XML footprint oracle."""
import os
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from swhull import definitions
from swhull.components import full_faces, mounted, owners
from swhull.orientation import RUDDERS
from swhull.pieces import BLOCK, BY_NAME, IDENTITY, MIRRORED, ROTATIONS, Placed, add, apply, parse_r, with_mirror
from swhull.smooth import _full_faces
from swhull.vehicle import components_from_text, to_xml

BASE = definitions.definitions_dir()
INSTALLED = sorted(p.stem for p in Path(BASE).glob("*.xml")) if BASE else [None]


@pytest.mark.installed
@pytest.mark.parametrize("d", INSTALLED)
def test_every_installed_definition_all_orientations(d):
    if d is None:
        pytest.skip("Stormworks definitions unavailable")
    root = ET.fromstring(re.sub(r'(\s)(\d\w*)=', r'\1sw_\2=', (Path(BASE) / f"{d}.xml").read_text(encoding="utf-8")))
    expected = [tuple(int(float(n.get(a, '0'))) for a in 'xyz')
                for v in root.findall('voxels/voxel')
                for n in [v.find('position')] if n is not None] or [(0, 0, 0)]
    piece, data = definitions.load(d), definitions.metadata(d)
    assert set(piece.footprint) == set(expected)
    assert set(piece.footprint) == set(data["footprint"])
    assert piece.surfaces == max(1, len(root.findall("surfaces/surface")))
    assert piece.mass == float(root.get("mass", "0"))
    origin = (13, -7, 29)
    for q in [*ROTATIONS, *MIRRORED]:
        p = Placed(piece, origin, q, color="123ABC")
        xml = to_xml([p])
        component = ET.fromstring(xml).find("bodies/body/components/c")
        stored = [int(n) for n in component.find("o").get("r").split(",")]
        flip = int(component.get("t", "0"))
        # Independently multiply the stored transposed matrix and local mirror bits.
        expected_world = {tuple(origin[i] + sum(stored[j * 3 + i] * cell[j] * (-1 if flip >> j & 1 else 1)
                                                for j in range(3)) for i in range(3)) for cell in expected}
        assert set(p.voxels()) == expected_world
        [(back_d, back_origin, back_q, back_color)] = components_from_text(xml)
        assert (back_d, back_origin, back_q, back_color) == (d, origin, q, "123ABC")
        # Check a declared grid-aligned attachment against an actual supporting block.
        faces = full_faces(d, q, attachment=True)
        if d in RUDDERS:
            faces = [f for f in faces if f[1] == apply(q, (0, -1, 0))]
        face = next(((v, n) for v, n in sorted(faces)
                     if add(origin, add(v, n)) not in expected_world and all(isinstance(x, int) for x in v)), None)
        if face:
            support = Placed(BLOCK, add(origin, add(*face)))
            assert mounted(p, owners([support]))


@pytest.mark.parametrize("d", sorted(BY_NAME))
def test_slope_faces_and_serialization_all_mirror_masks(d):
    piece = BY_NAME[d]
    local_faces = set(_full_faces(piece, IDENTITY))
    for q in ROTATIONS:
        for mask in range(8):
            mirrored = with_mirror(q, mask)
            assert set(_full_faces(piece, mirrored)) == {(apply(mirrored, v), apply(mirrored, n)) for v, n in local_faces}
            p = Placed(piece, (1, 2, 3), mirrored)
            [(_, pos, back, _)] = components_from_text(to_xml([p]))
            assert pos == p.origin and back == mirrored


@pytest.mark.parametrize("bad", ["1,0,0", "1,0,0,0,1,0,0,0,1,0", "1.1,0,0,0,1,0,0,0,1",
                                  "nan,0,0,0,1,0,0,0,1", "1,0,0,0,1,0,0,0,-1", "1,1,0,0,1,0,0,0,1"])
def test_malformed_rotations_are_not_rounded_into_valid_placements(bad):
    with pytest.raises(ValueError):
        parse_r(bad)


@pytest.mark.reference
def test_private_reference_covers_bodies_without_rewriting():
    from swhull.reference import audit_text  # noqa: PLC0415
    path = os.environ.get("SW_REFERENCE_VEHICLE")
    if not path:
        pytest.skip("set SW_REFERENCE_VEHICLE to a local reference XML")
    path = Path(path)
    original = path.read_bytes()
    report = audit_text(original.decode("utf-8"))
    root = ET.fromstring(re.sub(r'(\s)(\d\w*)=', r'\1sw_\2=', original.decode("utf-8")))
    assert report["part_count"] == len(root.findall("bodies/body/components/c"))
    assert report["body_count"] == len(root.findall("bodies/body"))
    assert report["link_count"] == len(root.findall("logic_node_links/logic_node_link"))
    assert sum(row["part_count"] for row in report["bodies"]) == report["part_count"]
    assert path.read_bytes() == original


@pytest.mark.installed
@pytest.mark.parametrize("d", ["rudder", "rudder_surface", "propeller", "engine", "trans_straight", "trans_angle"])
def test_propulsion_calibration_exhibits_have_no_overlapping_parts(d):
    from swhull.calibration import generate  # noqa: PLC0415
    if BASE is None:
        pytest.skip("Stormworks definitions unavailable")
    parts, _, manifest = generate(d)
    seen = set()
    for p in parts:
        assert not (set(p.voxels()) & seen), (d, p.name)
        seen.update(p.voxels())
    assert len(manifest["cases"]) == 48
