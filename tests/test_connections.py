"""Plumbing evidence uses transformed faces and preserves unknown type compatibility."""
import pytest

from swhull import definitions
from swhull.connections import adjacency, transmission_ports
from swhull.components import full_faces, mounted, owners
from swhull.orientation import solve
from swhull.pieces import BLOCK, MIRRORED, ROTATIONS, Piece, Placed, apply


@pytest.fixture
def pipe_data(monkeypatch):
    def metadata(d):
        return {"directions": {}, "voxels": [], "properties": {}, "sealing_surfaces": [], "attachment_surfaces": [
            {"position": (0, 0, 0), "orientation": 0, "shape": 3, "trans_type": 1 if d == "pipe" else 2},
            {"position": (0, 0, 0), "orientation": 1, "shape": 3, "trans_type": 1 if d == "pipe" else 2}]}
    monkeypatch.setattr(definitions, "metadata", metadata)
    full_faces.cache_clear()
    yield
    full_faces.cache_clear()


def part(d, pos=(0, 0, 0), q=None, uid="a"):
    piece = Piece(d, 2, 1, BLOCK.footprint, BLOCK.verts, BLOCK.faces)
    return Placed(piece, pos, **({"Q": q} if q is not None else {}), uid=uid)


@pytest.mark.parametrize("q", [*ROTATIONS, *MIRRORED])
def test_pipe_connections_follow_rotations_and_reflections(pipe_data, q):
    left = part("pipe", q=q)
    right = part("pipe", apply(q, (1, 0, 0)), q, "b")
    pairs, open_ports = adjacency([left, right], "body")
    assert len(pairs) == 1 and len(open_ports) == 2
    assert pairs[0]["compatibility"] == "same_declared_type"
    assert pairs[0]["body_id"] == "body"
    assert transmission_ports(left)[0]["normal"] == apply(q, (1, 0, 0))


def test_touching_parts_without_facing_ports_do_not_connect(pipe_data):
    pairs, ports = adjacency([part("pipe"), part("pipe", (0, 1, 0), uid="b")], "body")
    assert pairs == [] and len(ports) == 4


def test_different_transmission_types_remain_unverified(pipe_data):
    pairs, _ = adjacency([part("pipe"), part("engine-port", (1, 0, 0), uid="b")], "body")
    assert pairs[0]["compatibility"] == "requires_game_verification"
    assert [port["trans_type"] for port in pairs[0]["ports"]] == [1, 2]


def test_pipe_orientation_can_target_its_connection_face(pipe_data):
    q = solve("pipe", {"port_0_normal": [0, 0, 1]})
    assert apply(q, (1, 0, 0)) == (0, 0, 1)


def test_attachment_contact_does_not_require_a_sealing_surface(pipe_data):
    p, support = part("pipe"), part("pipe", (1, 0, 0), uid="b")
    assert full_faces("pipe", p.Q) == frozenset()
    assert mounted(p, owners([support]))


def test_component_cannot_mount_to_its_own_footprint(monkeypatch):
    piece = Piece("internal", 2, 1, ((0, 0, 0), (1, 0, 0)), BLOCK.verts, BLOCK.faces)
    surfaces = [{"position": (0, 0, 0), "orientation": 0, "shape": 1, "trans_type": 0},
                {"position": (1, 0, 0), "orientation": 1, "shape": 1, "trans_type": 0}]
    monkeypatch.setattr(definitions, "metadata", lambda _d: {"attachment_surfaces": surfaces})
    full_faces.cache_clear()
    p = Placed(piece, (0, 0, 0))
    assert not mounted(p, owners([p]))
    full_faces.cache_clear()
