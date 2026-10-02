"""Mounting and movement remain distinct through every orientation and reflection."""
import math
from itertools import product

import pytest

from swhull import definitions
from swhull.components import full_faces, mounted, owners, place, validate_placement
from swhull.interior import InteriorPlan
from swhull.orientation import describe, rudder_clearance, solve
from swhull.pieces import BLOCK, IDENTITY, MIRRORED, ROTATIONS, Placed, add, apply, parse_r


@pytest.fixture
def rudder_definitions(tmp_path, monkeypatch):
    for d in ("rudder", "rudder_surface"):
        cells = [(0, 0, z) for z in (-1, 0, 1)] + [(0, 1, z) for z in (-1, 0, 1)]
        voxels = ''.join(f'<voxel flags="{1 if y == 0 else 4}"><position x="{x}" y="{y}" z="{z}"/></voxel>'
                         for x, y, z in cells)
        surfaces = ''.join(f'<surface orientation="{ori}" shape="1"><position z="{z}"/></surface>'
                           for ori in (0, 1, 3) for z in (-1, 0, 1))
        hinge = '<dynamic_rotation_axes y="1"/>' if d == 'rudder' else '<dynamic_rotation_axes z="-1"/>'
        (tmp_path / f'{d}.xml').write_text(
            f'<definition name="Test Rudder" dynamic_min_rotation="{-math.pi/4}" dynamic_max_rotation="{math.pi/4}">'
            f'<voxels>{voxels}</voxels><surfaces>{surfaces}</surfaces>{hinge}'
            '<dynamic_side_axis x="1"/><dynamic_body_position/><force_dir/></definition>', encoding='utf-8')
    monkeypatch.setattr(definitions, "definitions_dir", lambda: str(tmp_path))
    definitions.load.cache_clear()
    definitions.metadata.cache_clear()
    full_faces.cache_clear()
    yield
    definitions.load.cache_clear()
    definitions.metadata.cache_clear()
    full_faces.cache_clear()


@pytest.mark.parametrize("d", ["rudder", "rudder_surface"])
@pytest.mark.parametrize("q", [*ROTATIONS, *MIRRORED])
def test_only_rudder_base_mounts_to_hull(rudder_definitions, d, q):
    p = Placed(definitions.load(d), (7, -3, 11), q, name="steering")
    base = add(p.origin, apply(q, (0, -1, 0)))
    side = add(p.origin, apply(q, (1, 0, 0)))
    backing = owners([Placed(BLOCK, base)])
    assert mounted(p, backing)
    assert not mounted(p, owners([Placed(BLOCK, side)]))
    validate_placement(p, {}, backing)
    with pytest.raises(ValueError, match="mounting"):
        validate_placement(p, {}, owners([Placed(BLOCK, side)]))


@pytest.mark.parametrize("d", ["rudder", "rudder_surface"])
@pytest.mark.parametrize("q", [*ROTATIONS, *MIRRORED])
def test_sweep_rotates_and_catches_blocked_blades(rudder_definitions, d, q):
    origin = (3, 8, -5)
    p = Placed(definitions.load(d), origin, q, name="steering")
    local = rudder_clearance(Placed(p.piece, (0, 0, 0), IDENTITY))
    assert local
    assert rudder_clearance(p) == {add(origin, apply(q, v)) for v in local}
    base = add(origin, apply(q, (0, -1, 0)))
    blocked = next(v for v in rudder_clearance(p) if v != base)
    with pytest.raises(ValueError, match="clearance"):
        validate_placement(p, {}, owners([Placed(BLOCK, base), Placed(BLOCK, blocked)]))


def test_sweep_encloses_independently_sampled_blade_motion(rudder_definitions):
    p = Placed(definitions.load("rudder_surface"), (0, 0, 0))
    envelope = rudder_clearance(p) | set(p.voxels())
    for step, cell, corner in product(range(101), [(0, 1, z) for z in (-1, 0, 1)], product((-.49, .49), repeat=3)):
        angle = -math.pi / 4 + step * math.pi / 200
        x, y, z = [cell[i] + corner[i] for i in range(3)]
        point = (x * math.cos(angle) + y * math.sin(angle), -x * math.sin(angle) + y * math.cos(angle), z)
        assert tuple(math.floor(n + .5) for n in point) in envelope


def test_semantic_axes_match_reference_fin_rotation(rudder_definitions):
    result = describe("rudder_surface", {"mount_normal": [0, 0, 1], "span_axis": [0, 1, 0]})
    assert result["rotation"] == parse_r("1,0,0,0,0,-1,0,1,0")
    assert result["world_axes"]["blade_direction"] == (0, 0, -1)
    assert describe("rudder")["world_axes"]["mount_normal"] == (0, 1, 0)


@pytest.mark.parametrize("targets", [{"unknown": [0, 1, 0]}, {"mount_normal": [0, 2, 0]},
                                     {"mount_normal": [True, 0, 0]}, {"mount_normal": [0, 1, 0], "blade_direction": [0, 1, 0]}])
def test_invalid_or_conflicting_constraints_fail(rudder_definitions, targets):
    with pytest.raises(ValueError):
        solve("rudder", targets)


@pytest.mark.parametrize("d,backing", [("rudder", (0, 4, 0)), ("rudder_surface", (0, 0, 0))])
@pytest.mark.parametrize("include_kind", [True, False])
def test_automatic_rudder_placement_mounts_base(rudder_definitions, d, backing, include_kind):
    from types import SimpleNamespace  # noqa: PLC0415
    parts = [Placed(BLOCK, backing)]
    info = {"interior": InteriorPlan(), "form": SimpleNamespace(L=40, depth=8), "warnings": [], "region": {}}
    cfg = {"name": "steering", "definition": d, **({"kind": "rudder"} if include_kind else {})}
    place(parts, info, {"components": [cfg]})
    p = next(p for p in parts if p.name)
    assert mounted(p, owners([parts[0]]))
    assert apply(p.Q, (0, -1, 0)) == ((0, 1, 0) if d == "rudder" else (0, 0, 1))
