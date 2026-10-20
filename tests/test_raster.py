"""Lit renderer: rasterizing, shadows, occlusion and backend choice."""
import io

import numpy as np
import pytest
from PIL import Image

from swhull import raster
from swhull.pieces import BY_NAME, Placed
from swhull.render import _world_faces, render_view

BLOCK = BY_NAME["01_block"]


def blocks(cells, color="C2C3C7"):
    return [Placed(BLOCK, cell, color=color) for cell in cells]


def test_cpu_raster_keeps_the_nearest_triangle_and_its_depth():
    far = [(0, 0, 10), (8, 0, 10), (0, 8, 10)]
    near = [(0, 0, 2), (4, 0, 2), (0, 4, 2)]
    index, depth = raster.raster_cpu(np.array([far, near], np.float64), 10, 10)
    assert index[1, 1] == 1 and depth[1, 1] == pytest.approx(2, abs=1e-6)
    assert index[5, 1] == 0 and depth[5, 1] == pytest.approx(10, abs=1e-6)
    assert index[9, 9] == -1 and np.isinf(depth[9, 9])
    # Half of an 8 x 8 square, give or take the pixels on the diagonal.
    assert 28 <= (index >= 0).sum() <= 40


def _screen(scene, w, h):
    forward, right, up = raster._basis((-1.0, -0.75, -1.1))
    pts = scene.tris.reshape(-1, 3)
    u, v = pts @ right, pts @ up
    scale = 0.9 * min(w / np.ptp(u), h / np.ptp(v))
    screen = np.empty_like(scene.tris)
    screen[..., 0] = w / 2 + (scene.tris @ right - u.mean()) * scale
    screen[..., 1] = h / 2 - (scene.tris @ up - v.mean()) * scale
    screen[..., 2] = scene.tris @ forward
    return screen


def test_gpu_and_cpu_rasterizers_agree():
    if raster.gpu_context() is None:
        pytest.skip("no OpenGL 3.3 context on this machine")
    parts = blocks([(x, y, z) for x in range(4) for y in range(3) for z in range(5) if (x + y + z) % 3])
    parts.append(Placed(BY_NAME["08_wedge_4"], (6, 0, 0)))
    scene = raster.Scene(_world_faces(parts, bake=False))
    screen = _screen(scene, 320, 240)
    cpu_index, cpu_depth = raster.raster_cpu(screen, 320, 240)
    gpu_index, gpu_depth = raster.raster_gpu(screen, 320, 240)
    either = (cpu_index >= 0) | (gpu_index >= 0)
    same = cpu_index == gpu_index
    assert same[either].mean() > 0.97  # only edge pixels may differ
    both = same & (cpu_index >= 0)
    assert np.abs(cpu_depth[both] - gpu_depth[both]).max() < 1e-2


@pytest.mark.parametrize("backend", ["cpu", "gpu"])
def test_a_raised_plate_shadows_the_floor_away_from_the_sun(backend):
    if backend == "gpu" and raster.gpu_context() is None:
        pytest.skip("no OpenGL 3.3 context on this machine")
    floor = [(x, 0, z) for x in range(-6, 7) for z in range(-6, 7)]
    plate = [(x, 5, z) for x in range(-1, 2) for z in range(-1, 2)]
    scene = raster.Scene(_world_faces(blocks(floor + plate), bake=False))
    sun = np.array(raster.SUN) / np.linalg.norm(raster.SUN)
    drop = 4.0 / sun[1]  # from the plate's underside (4.5) to the floor's top (0.5)
    centre = np.array((0.0, 0.5, 0.0)) - sun * drop
    centre[1] = 0.5
    points = np.array([centre, (4.0, 0.5, 4.0), (-5.0, 0.5, 5.0)])
    up = np.tile((0.0, 1.0, 0.0), (3, 1))
    lit = raster._sunlit(scene, backend, points, up)
    assert lit[0] == 0.0 and lit[1] == 1.0 and lit[2] == 1.0


def test_occlusion_darkens_the_floor_beside_a_step_only():
    h, w = 40, 80
    pos = np.zeros((h, w, 3), np.float32)
    xs = np.arange(w) / 4.0
    pos[..., 0] = xs[None, :]
    pos[..., 2] = (np.arange(h) / 4.0)[:, None]
    pos[:, w // 2:, 1] = 1.0  # a one-block step on the right half
    normal = np.zeros((h, w, 3), np.float32)
    normal[..., 1] = 1.0
    ao = raster._occlusion(pos, normal, np.ones((h, w), np.float32), 4.0)
    assert ao[20, w // 2 - 1] < 0.85  # floor at the foot of the step
    assert ao[20, 5] == pytest.approx(1.0)  # open floor
    assert ao[20, w - 5] == pytest.approx(1.0)  # top of the step


def test_backend_choice(monkeypatch):
    monkeypatch.delenv("SW_RENDERER", raising=False)
    monkeypatch.setattr(raster, "gpu_context", lambda: None)
    assert raster.resolve() == "cpu"
    assert raster.resolve("flat") == "flat"
    with pytest.raises(ValueError, match="no GPU renderer"):
        raster.resolve("gpu")
    with pytest.raises(ValueError, match="renderer must be"):
        raster.resolve("raytraced")
    monkeypatch.setenv("SW_RENDERER", "flat")
    assert raster.resolve() == "flat"


def test_lit_view_lights_tops_brighter_than_shadowed_sides():
    parts = blocks([(x, y, z) for x in range(6) for y in range(4) for z in range(8)])
    png = render_view(parts, yaw=35, pitch=30, width=300, height=200, renderer="cpu")
    pixels = np.asarray(Image.open(io.BytesIO(png)).convert("RGB")).astype(int)
    background = np.array((38, 45, 56))
    shaded = pixels[np.abs(pixels - background).sum(-1) > 30]
    assert len(shaded) > 2000
    brightness = shaded.sum(-1)
    # A grey box shows at least a lit top and a darker side, not one flat tone.
    assert brightness.max() - brightness.min() > 120
