"""Lit previews: z-buffer rasterizing on the GPU (moderngl) or the CPU (NumPy), one lighting pass.

The lighting follows how Stormworks shades vehicles: vertex colour taken to linear space,
a Lambert sun with shadows, a two-colour sky/ground ambient chosen by the normal's height,
screen-space ambient occlusion, Hable's filmic tonemap and 1/2.2 gamma. Both backends only
rasterize: each returns, per pixel, which triangle is nearest and how deep it is. Shading
then runs once in NumPy, so the two backends give the same picture; the GPU is faster and
affords more supersampling.

Coordinates are the flat renderer's render coordinates (x already mirrored for display).
"""
import functools
import math
import os

import numpy as np

SUN = (0.25, 0.8, 0.55)            # towards the sun, render coordinates
SUN_COLOUR = np.array((2.0, 1.9, 1.75), np.float32)
AMBIENT_LOW = np.array((0.52, 0.53, 0.56), np.float32)    # light bounced up from below
AMBIENT_HIGH = np.array((0.80, 0.88, 1.02), np.float32)   # open sky
EXPOSURE = 1.9
WHITE = 11.2
AO_RADIUS = 1.6                    # blocks
AO_STRENGTH = 2.2
_KEY_BITS = 26                     # triangle index bits in the CPU depth key
_DEPTH_STEPS = float(1 << 36)
_CHUNK = 2_000_000                 # pixel samples per vectorised CPU step

BACKENDS = ("auto", "gpu", "cpu", "flat")


class Scene:
    """Triangles with one normal and linear albedo each, from renderer face fragments."""

    def __init__(self, faces):
        tris, owner = [], []
        for i, (pts, _n, _col, _cell) in enumerate(faces):
            for k in range(1, len(pts) - 1):
                tris.append((pts[0], pts[k], pts[k + 1]))
                owner.append(i)
        self.tris = np.array(tris, np.float64).reshape(-1, 3, 3)
        owner = np.array(owner, np.int64)
        normals = np.array([f[1] for f in faces], np.float32).reshape(-1, 3)
        colours = np.array([f[2] for f in faces], np.float32).reshape(-1, 3)
        self.normal = normals[owner] if len(owner) else normals
        self.albedo = (colours[owner] / 255.0) ** 2.2 if len(owner) else colours
        self._shadow = None

    def __len__(self):
        return len(self.tris)


def _basis(forward, up_hint=(0.0, 1.0, 0.0)):
    d = np.array(forward, np.float64)
    d /= np.linalg.norm(d)
    hint = np.array(up_hint, np.float64)
    if abs(float(d @ hint)) > 0.99:
        hint = np.array((0.0, 0.0, 1.0))
    right = np.cross(d, hint)
    right /= np.linalg.norm(right)
    return d, right, np.cross(right, d)


# --- rasterizers: screen triangles (N, 3, 3) of pixel x, pixel y, depth -> (index, depth) ---

def raster_cpu(screen, w, h):
    """Nearest triangle index (-1 for none) and its depth at every pixel centre."""
    keys = np.full(w * h, np.iinfo(np.int64).max, np.int64)
    n = len(screen)
    if n:
        if n >= 1 << _KEY_BITS:
            raise ValueError("too many triangles for the CPU renderer")
        x, y, z = screen[..., 0], screen[..., 1], screen[..., 2]
        zmin, zmax = float(z.min()), float(z.max())
        zspan = max(zmax - zmin, 1e-9)
        area = (x[:, 1] - x[:, 0]) * (y[:, 2] - y[:, 0]) - (y[:, 1] - y[:, 0]) * (x[:, 2] - x[:, 0])
        i0 = np.maximum(np.ceil(x.min(1) - 0.5), 0).astype(np.int64)
        i1 = np.minimum(np.floor(x.max(1) - 0.5), w - 1).astype(np.int64)
        j0 = np.maximum(np.ceil(y.min(1) - 0.5), 0).astype(np.int64)
        j1 = np.minimum(np.floor(y.max(1) - 0.5), h - 1).astype(np.int64)
        live = (np.abs(area) > 1e-12) & (i1 >= i0) & (j1 >= j0)
        span = np.maximum(i1 - i0, j1 - j0) + 1
        size = np.where(live, 2 ** np.ceil(np.log2(np.maximum(span, 1))).astype(np.int64), 0)
        for s in np.unique(size[size > 0]):
            ids = np.nonzero(size == s)[0]
            step = max(1, _CHUNK // int(s * s))
            ar = np.arange(int(s))
            for k in range(0, len(ids), step):
                t = ids[k:k + step]
                gx = i0[t, None, None] + ar[None, None, :]
                gy = j0[t, None, None] + ar[None, :, None]
                px, py = gx + 0.5, gy + 0.5
                xt, yt, a = x[t, :, None, None], y[t, :, None, None], area[t, None, None]
                w0 = ((xt[:, 1] - px) * (yt[:, 2] - py) - (yt[:, 1] - py) * (xt[:, 2] - px)) / a
                w1 = ((xt[:, 2] - px) * (yt[:, 0] - py) - (yt[:, 2] - py) * (xt[:, 0] - px)) / a
                w2 = 1.0 - w0 - w1
                inside = ((w0 >= -1e-7) & (w1 >= -1e-7) & (w2 >= -1e-7)
                          & (gx <= i1[t, None, None]) & (gy <= j1[t, None, None]))
                zt = z[t, :, None, None]
                depth = w0 * zt[:, 0] + w1 * zt[:, 1] + w2 * zt[:, 2]
                quant = np.clip((depth - zmin) / zspan * _DEPTH_STEPS, 0, _DEPTH_STEPS - 1).astype(np.int64)
                key = (quant << _KEY_BITS) | t[:, None, None]
                flat = np.broadcast_to(gy * w + gx, inside.shape)
                np.minimum.at(keys, flat[inside], key[inside])
    empty = keys == np.iinfo(np.int64).max
    index = np.where(empty, -1, keys & ((1 << _KEY_BITS) - 1)).astype(np.int64)
    depth = np.full(w * h, np.inf)
    if n:
        depth[~empty] = zmin + (keys[~empty] >> _KEY_BITS) / _DEPTH_STEPS * zspan
    return index.reshape(h, w), depth.reshape(h, w)


_VERTEX = """
#version 330
in vec3 in_pos;
uniform vec2 size;
void main() {
    gl_Position = vec4(in_pos.x / size.x * 2.0 - 1.0, 1.0 - in_pos.y / size.y * 2.0, in_pos.z * 2.0 - 1.0, 1.0);
}
"""
_FRAGMENT = """
#version 330
out int index;
void main() { index = gl_PrimitiveID + 1; }
"""


@functools.cache
def gpu_context():
    """A headless OpenGL 3.3 context, or None when this machine cannot make one."""
    try:
        import moderngl  # noqa: PLC0415 - the CPU path works without it
        ctx = moderngl.create_standalone_context(require=330)
        return ctx, ctx.program(vertex_shader=_VERTEX, fragment_shader=_FRAGMENT), moderngl
    except Exception:  # noqa: BLE001 - any driver or platform failure means "no GPU"
        return None


def raster_gpu(screen, w, h):
    ctx, program, moderngl = gpu_context()
    index = np.full((h, w), -1, np.int64)
    depth = np.full((h, w), np.inf)
    if not len(screen):
        return index, depth
    z = screen[..., 2]
    zmin, zspan = float(z.min()), max(float(z.max() - z.min()), 1e-9)
    verts = screen.astype(np.float64).copy()
    verts[..., 2] = (z - zmin) / zspan * 0.999 + 0.0005
    vbo = ctx.buffer(verts.astype("f4").tobytes())
    vao = ctx.vertex_array(program, [(vbo, "3f", "in_pos")])
    colour = ctx.renderbuffer((w, h), components=1, dtype="i4")
    depth_rb = ctx.depth_renderbuffer((w, h))
    fbo = ctx.framebuffer(color_attachments=[colour], depth_attachment=depth_rb)
    try:
        fbo.use()
        ctx.viewport = (0, 0, w, h)
        fbo.clear(0.0, 0.0, 0.0, 0.0, depth=1.0)
        ctx.enable(moderngl.DEPTH_TEST)
        ctx.disable(moderngl.CULL_FACE)
        program["size"].value = (float(w), float(h))
        vao.render(moderngl.TRIANGLES)
        ids = np.frombuffer(fbo.read(components=1, dtype="i4"), np.int32).reshape(h, w)[::-1]
        raw = np.frombuffer(fbo.read(attachment=-1, components=1, dtype="f4"), np.float32).reshape(h, w)[::-1]
    finally:
        for obj in (vao, vbo, fbo, colour, depth_rb):
            obj.release()
    hit = ids > 0
    index[hit] = ids[hit] - 1
    depth[hit] = zmin + (raw[hit] - 0.0005) / 0.999 * zspan
    return index, depth


def resolve(name=None):
    """The backend to use: an explicit choice, else SW_RENDERER, else auto (GPU, then CPU)."""
    name = name or os.environ.get("SW_RENDERER", "auto")
    if name not in BACKENDS:
        raise ValueError(f"renderer must be one of {', '.join(BACKENDS)}")
    if name == "auto":
        return "gpu" if gpu_context() else "cpu"
    if name == "gpu" and not gpu_context():
        raise ValueError("no GPU renderer here (OpenGL 3.3 context unavailable); use renderer=cpu")
    return name


def _raster(backend, screen, w, h):
    return raster_gpu(screen, w, h) if backend == "gpu" else raster_cpu(screen, w, h)


# --- shading -----------------------------------------------------------------------------

def _shadow_map(scene, backend):
    """Depth of the nearest surface along the sun direction, shared by every view of a scene."""
    if scene._shadow is not None and scene._shadow[0] == backend:
        return scene._shadow[1]
    forward, right, up = _basis(-np.array(SUN))
    pts = scene.tris.reshape(-1, 3)
    u, v = pts @ right, pts @ up
    extent = max(float(np.ptp(u)), float(np.ptp(v)), 1.0)
    res = int(min(4096 if backend == "gpu" else 2048, max(512, extent * 6)))
    texel = extent / (res - 4)
    origin = (float(u.min()) - 2 * texel, float(v.max()) + 2 * texel)
    screen = np.empty_like(scene.tris)
    screen[..., 0] = (scene.tris @ right - origin[0]) / texel
    screen[..., 1] = (origin[1] - scene.tris @ up) / texel
    screen[..., 2] = scene.tris @ forward
    _, depth = _raster(backend, screen, res, res)
    result = (forward, right, up, origin, texel, depth)
    scene._shadow = (backend, result)
    return result


def _sunlit(scene, backend, pos, normal):
    """Fraction of the sun each point sees, with a 3x3 percentage-closer filter."""
    forward, right, up, origin, texel, depth = _shadow_map(scene, backend)
    lifted = pos + normal * max(0.08, 1.5 * texel)
    u = (lifted @ right - origin[0]) / texel - 0.5
    v = (origin[1] - lifted @ up) / texel - 0.5
    d = lifted @ forward - max(0.04, 0.75 * texel)
    res = depth.shape[0]
    lit = np.zeros(len(pos), np.float32)
    for du in (-1, 0, 1):
        for dv in (-1, 0, 1):
            iu = np.clip(np.round(u).astype(np.int64) + du, 0, res - 1)
            iv = np.clip(np.round(v).astype(np.int64) + dv, 0, res - 1)
            lit += d <= depth[iv, iu]
    return lit / 9.0


def _occlusion(pos, normal, valid, px_per_block):
    """Screen-space ambient occlusion: how much nearby surface rises above each point's plane."""
    h, w = valid.shape
    radius_px = float(np.clip(AO_RADIUS * px_per_block, 2.0, 40.0))
    samples = []
    for ring, count in ((0.4, 6), (0.75, 6), (1.0, 6)):
        for k in range(count):
            angle = 2 * math.pi * (k + 0.5 * ring) / count
            dx, dy = round(math.cos(angle) * ring * radius_px), round(math.sin(angle) * ring * radius_px)
            if dx or dy:
                samples.append((dx, dy))
    samples = list(dict.fromkeys(samples))
    reach = radius_px / px_per_block
    total = np.zeros((h, w), np.float32)
    for dx, dy in samples:
        if abs(dx) >= w or abs(dy) >= h:
            continue
        # Pixels whose neighbour (y + dy, x + dx) is on screen, and those neighbours.
        ys, ys2 = slice(max(0, -dy), h - max(0, dy)), slice(max(0, dy), h + min(0, dy))
        xs, xs2 = slice(max(0, -dx), w - max(0, dx)), slice(max(0, dx), w + min(0, dx))
        here, there = pos[ys, xs], pos[ys2, xs2]
        offset = there - here
        dist = np.sqrt((offset * offset).sum(-1)) + 1e-6
        rise = (offset * normal[ys, xs]).sum(-1) / dist
        weight = np.clip(1.0 - dist / (reach * 1.5), 0.0, 1.0)
        contribution = np.clip(rise - 0.12, 0.0, 1.0) * weight * valid[ys2, xs2]
        total[ys, xs] += contribution
    ao = 1.0 - AO_STRENGTH * total / max(1, len(samples))
    return np.clip(ao, 0.25, 1.0) * valid


def _hable(x):
    a, b, c, d, e, f = 0.22, 0.10, 0.10, 0.50, 0.01, 0.30
    return ((x * (a * x + c * b) + d * e) / (x * (a * x + b) + d * f)) - e / f


def shade(scene, forward, right, up, frame, w, h, backend, supersample):
    """Premultiplied RGB (h, w, 3) in 0-1 and coverage (h, w) for one orthographic view.

    frame: (cx, cy, scale, ox, oy) as the flat renderer frames the view in pixels.
    """
    cx, cy, scale, ox, oy = frame
    s = supersample
    W, H = w * s, h * s
    forward, right, up = (np.asarray(v, np.float64) for v in (forward, right, up))
    facing = scene.normal @ forward.astype(np.float32) < 0
    tris = scene.tris[facing]
    order = np.nonzero(facing)[0]
    screen = np.empty_like(tris)
    screen[..., 0] = (ox + (tris @ right - cx) * scale) * s
    screen[..., 1] = (oy - (tris @ up - cy) * scale) * s
    screen[..., 2] = tris @ forward
    index, depth = _raster(backend, screen, W, H)
    valid = index >= 0
    tri = np.where(valid, order[np.maximum(index, 0)] if len(order) else 0, 0)
    gx, gy = np.meshgrid(np.arange(W) + 0.5, np.arange(H) + 0.5)
    sx = (gx / s - ox) / scale + cx
    sy = cy - (gy / s - oy) / scale
    pos = (sx[..., None] * right + sy[..., None] * up
           + np.where(valid, depth, 0.0)[..., None] * forward).astype(np.float32)
    normal = scene.normal[tri] * valid[..., None]
    albedo = scene.albedo[tri]
    sun = np.array(SUN, np.float32) / np.linalg.norm(SUN)
    ndl = np.clip(normal @ sun, 0.0, 1.0)
    lit = np.zeros((H, W), np.float32)
    mask = valid & (ndl > 0)
    if mask.any():
        lit[mask] = _sunlit(scene, backend, pos[mask].astype(np.float64), normal[mask].astype(np.float64))
    # Occlusion is soft, so compute it once per output pixel (its middle sample) and spread it.
    mid = s // 2
    ao = _occlusion(pos[mid::s, mid::s], normal[mid::s, mid::s], valid[mid::s, mid::s].astype(np.float32), scale)
    if s > 1:
        ao = np.repeat(np.repeat(ao, s, 0), s, 1)
    height = normal[..., 1:2] * 0.5 + 0.5
    ambient = AMBIENT_LOW * (1 - height) + AMBIENT_HIGH * height
    light = SUN_COLOUR * (ndl * lit)[..., None] + ambient * ao[..., None]
    colour = _hable(albedo * light * EXPOSURE) / _hable(WHITE)
    colour = np.clip(colour, 0.0, 1.0) ** (1 / 2.2) * valid[..., None]
    if s > 1:
        colour = colour.reshape(h, s, w, s, 3).mean((1, 3))
        coverage = valid.reshape(h, s, w, s).mean((1, 3))
    else:
        coverage = valid.astype(np.float32)
    return colour.astype(np.float32), coverage.astype(np.float32)
