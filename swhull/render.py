"""Flat-shaded preview renders (3/4 view + side/top/front orthographics) with Pillow."""
import io
import math

from PIL import Image, ImageDraw, ImageFont

from .pieces import add, apply

BG = (38, 45, 56)
GRID = (52, 61, 74)
LABEL = (200, 210, 222)
LIGHT = (0.35, 0.85, 0.4)


def _norm(v):
    m = math.sqrt(sum(c * c for c in v)) or 1.0
    return tuple(c / m for c in v)


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _hex(c):
    c = c.strip().lstrip("#")
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))


def _clip(poly, axis, value):
    """Split a convex polygon by the plane p[axis] == value into (below, above)."""
    below, above = [], []
    for i, a in enumerate(poly):
        b = poly[(i + 1) % len(poly)]
        da, db = a[axis] - value, b[axis] - value
        if da <= 1e-9:
            below.append(a)
        if da >= -1e-9:
            above.append(a)
        if (da < -1e-9 and db > 1e-9) or (da > 1e-9 and db < -1e-9):
            t = da / (da - db)
            q = tuple(a[k] + (b[k] - a[k]) * t for k in range(3))
            below.append(q)
            above.append(q)
    return [p for p in (below, above) if len(p) >= 3]


def _fragments(poly):
    """Cut a polygon along voxel boundaries so every fragment lies within one voxel cell."""
    polys = [poly]
    for axis in range(3):
        lo = min(p[axis] for p in poly)
        hi = max(p[axis] for p in poly)
        k = math.floor(lo - 0.5) + 1
        while k + 0.5 < hi - 1e-9:
            if k + 0.5 > lo + 1e-9:
                nxt = []
                for q in polys:
                    nxt.extend(_clip(q, axis, k + 0.5))
                polys = nxt
            k += 1
    return polys


def _mirror(v):
    """Stormworks axes are left-handed (confirmed against an in-game screenshot), so flip x
    for display; otherwise every render shows the vehicle mirrored port-to-starboard."""
    return (-v[0], v[1], v[2])


def _piece_polys(p):
    verts = [_mirror(add(p.origin, apply(p.Q, v))) for v in p.piece.verts]
    centre = tuple(sum(v[i] for v in verts) / len(verts) for i in range(3))
    for f in p.piece.faces:
        pts = [verts[i] for i in f]
        n = _newell(pts)
        fc = tuple(sum(q[i] for q in pts) / len(pts) for i in range(3))
        if _dot(n, tuple(fc[i] - centre[i] for i in range(3))) < 0:
            pts.reverse()
            n = tuple(-c for c in n)
        yield pts, n


def _axis_dir(n):
    for i in range(3):
        if abs(n[i]) > 0.999:
            d = [0, 0, 0]
            d[i] = 1 if n[i] > 0 else -1
            return tuple(d)
    return None


_RDIRS = ((1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1))


def _square(c, d):
    """Unit face of the voxel centred at c, on side d."""
    a, b = [i for i in range(3) if d[i] == 0]
    f = [c[i] + d[i] * 0.5 for i in range(3)]
    out = []
    for sa, sb in ((-0.5, -0.5), (0.5, -0.5), (0.5, 0.5), (-0.5, 0.5)):
        q = list(f)
        q[a] += sa
        q[b] += sb
        out.append(tuple(q))
    return out


def _world_faces(placed, light=LIGHT, ambient=0.42, facing=None):
    """(polygon, outward normal, rgb, voxel cell) per visible voxel-sized face fragment.

    Plain blocks, nearly every piece of a hull, take a fast path: their six faces are unit
    squares, emitted only where no neighbour covers them. Other pieces go through the general
    polygon path. `facing` (a camera direction) drops faces that point away from that camera.
    """
    dirs = _RDIRS if facing is None else tuple(d for d in _RDIRS if _dot(d, facing) < -1e-6)
    light = _norm(light)
    shades = {d: ambient + (1 - ambient) * max(0.0, _dot(d, light)) for d in _RDIRS}
    blocks, polys = [], []
    full = set()  # (voxel, direction) pairs covered by a full square face, in render coordinates
    for p in placed:
        if p.piece.d == "01_block":
            v = _mirror(p.origin)
            blocks.append((v, p.color))
            for d in _RDIRS:
                full.add((v, d))
            continue
        for pts, n in _piece_polys(p):
            frags = _fragments(pts)
            d = _axis_dir(n)
            polys.append((frags, n, d, p.color))
            if d is None:
                continue
            for fr in frags:
                if len(fr) == 4 and abs(_area(fr) - 1.0) < 1e-6:
                    fc = tuple(sum(q[i] for q in fr) / 4 for i in range(3))
                    inner = tuple(int(round(fc[i] - d[i] * 0.5)) for i in range(3))
                    full.add((inner, d))
    faces = []
    cols = {}
    for v, color in blocks:
        for d in dirs:
            if ((v[0] + d[0], v[1] + d[1], v[2] + d[2]), (-d[0], -d[1], -d[2])) in full:
                continue
            key = (color, d)
            col = cols.get(key)
            if col is None:
                col = cols[key] = tuple(min(255, int(c * shades[d])) for c in _hex(color))
            faces.append((_square(v, d), d, col, v))
    for frags, n, d, color in polys:
        rgb = _hex(color)
        shade = ambient + (1 - ambient) * max(0.0, _dot(n, light))
        col = tuple(min(255, int(c * shade)) for c in rgb)
        if facing is not None and _dot(n, facing) >= -1e-6:
            continue
        for fr in frags:
            if d is not None:
                fc = tuple(sum(q[i] for q in fr) / len(fr) for i in range(3))
                beyond = tuple(int(round(fc[i] + d[i] * 0.5)) for i in range(3))
                if (beyond, tuple(-c for c in d)) in full:
                    continue
            fc = tuple(sum(q[i] for q in fr) / len(fr) for i in range(3))
            cell = tuple(round(fc[i] - n[i] * 0.01) for i in range(3))   # voxel this piece sits in
            faces.append((fr, n, col, cell))
    return faces


def _area(poly):
    n = [0.0, 0.0, 0.0]
    for i, a in enumerate(poly):
        b = poly[(i + 1) % len(poly)]
        c = _cross(a, b)
        n = [n[k] + c[k] for k in range(3)]
    return 0.5 * math.sqrt(sum(c * c for c in n))


def _newell(pts):
    nx = ny = nz = 0.0
    for i, a in enumerate(pts):
        b = pts[(i + 1) % len(pts)]
        nx += (a[1] - b[1]) * (a[2] + b[2])
        ny += (a[2] - b[2]) * (a[0] + b[0])
        nz += (a[0] - b[0]) * (a[1] + b[1])
    return _norm((nx, ny, nz))


def _camera(direction, up_hint=(0, 1, 0)):
    d = _norm(direction)
    right = _norm(_cross(d, up_hint))
    up = _cross(right, d)
    return d, right, up


VIEWS = {
    "3/4 view": _camera((-1.0, -0.75, -1.1)),
    "side (bow right)": _camera((1, 0, 0)),
    "top (bow right)": _camera((0, -1, 0), (1, 0, 0)),
    "front (from bow)": _camera((0, 0, -1)),
}


def _aligned(vec):
    """(world axis, sign) when a screen axis lines up with a world axis, else None."""
    for i in range(3):
        if abs(vec[i]) > 0.999:
            return i, (1 if vec[i] > 0 else -1)
    return None


def _ruler_axes(ruler, right, up, cx, cy, scale, w, h, ox, oy):
    """Tick positions for each screen axis that lines up with a world axis.

    ruler: per world axis (a, b) with render coordinate = a * metres + b.
    Yields (screen axis "h"/"v", world axis, [(metres, pixel)], label step).
    """
    for which, vec in (("h", right), ("v", up)):
        al = _aligned(vec)
        if al is None:
            continue
        i, sgn = al
        a, b = ruler[i]
        if which == "h":
            lo, hi = cx - ox / scale, cx + (w - ox) / scale
        else:
            lo, hi = cy - (h - oy) / scale, cy + oy / scale
        m1, m2 = sorted(((sgn * lo - b) / a, (sgn * hi - b) / a))
        px_per_m = abs(a) * scale
        step = next((st for st in (0.25, 0.5, 1, 2, 5, 10, 20, 50, 100) if st * px_per_m >= 42), 100)
        fine = 1 if px_per_m >= 6 else step
        ticks = []
        k = math.ceil(m1 / fine)
        while k * fine <= m2 and len(ticks) < 2000:
            m = k * fine
            t = sgn * (a * m + b)
            px = ox + (t - cx) * scale if which == "h" else oy - (t - cy) * scale
            ticks.append((m, px))
            k += 1
        yield which, i, ticks, step


def _draw_view(faces, cam, w, h, title, scale=None, grid=False, zoom=1.0, focus=None, labels=(),
               ruler=None):
    d, right, up = cam
    img = Image.new("RGB", (w, h), BG)
    dr = ImageDraw.Draw(img)
    vis = [(pts, col, cell) for pts, n, col, cell in faces if _dot(n, d) < -1e-6]
    if not vis:
        return img, scale
    # Back-to-front by the depth of each fragment's voxel cell: exact for unit cells in an
    # orthographic view, unlike sorting by face centroid (which lets floors paint over walls).
    proj = [([(_dot(p, right), _dot(p, up)) for p in pts],
             (_dot(cell, d), sum(_dot(p, d) for p in pts) / len(pts)), col)
            for pts, col, cell in vis]
    xs = [q[0] for pts, _, _ in proj for q in pts]
    ys = [q[1] for pts, _, _ in proj for q in pts]
    margin = 28
    if scale is None:
        scale = min((w - 2 * margin) / max(1e-6, max(xs) - min(xs)),
                    (h - 2 * margin - 16) / max(1e-6, max(ys) - min(ys)))
    cx, cy = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2
    scale *= zoom
    if focus is not None:
        cx, cy = _dot(focus, right), _dot(focus, up)
    ox, oy = w / 2, h / 2 + 8

    def to_px(q):
        return (ox + (q[0] - cx) * scale, oy - (q[1] - cy) * scale)

    axes = list(_ruler_axes(ruler, right, up, cx, cy, scale, w, h, ox, oy)) if ruler else []
    for which, _i, ticks, step in axes:  # 1 m grid in design metres, heavier at labelled ticks
        for m, px in ticks:
            major = abs(m / step - round(m / step)) < 1e-6
            col = tuple(c + 10 for c in GRID) if major else GRID
            dr.line([(px, 20), (px, h)] if which == "h" else [(0, px), (w, px)], fill=col)
    if grid and not ruler:  # 1 m grid (4 voxels)
        for gx in range(int(math.floor(min(xs) / 4)) - 1, int(math.ceil(max(xs) / 4)) + 2):
            x = to_px((gx * 4, 0))[0]
            dr.line([(x, 20), (x, h)], fill=GRID)
        for gy in range(int(math.floor(min(ys) / 4)) - 1, int(math.ceil(max(ys) / 4)) + 2):
            y = to_px((0, gy * 4))[1]
            dr.line([(0, y), (w, y)], fill=GRID)
    outline_px = scale >= 5
    for pts, _, col in sorted(proj, key=lambda f: (-f[1][0], -f[1][1])):
        poly = [to_px(q) for q in pts]
        edge = tuple(int(c * 0.82) for c in col) if outline_px else None
        dr.polygon(poly, fill=col, outline=edge)
    font = ImageFont.load_default()
    for point, text in labels:
        px, py = to_px((_dot(point, right), _dot(point, up)))
        tw = dr.textlength(text, font=font)
        dr.rectangle([px - tw / 2 - 3, py - 7, px + tw / 2 + 3, py + 7], fill=(20, 24, 30))
        dr.text((px - tw / 2, py - 6), text, fill=(240, 244, 248), font=font)
    names = "xyz"
    for which, i, ticks, step in axes:
        for m, px in ticks:
            if abs(m / step - round(m / step)) > 1e-6:
                continue
            text = f"{m:g}"
            tw = dr.textlength(text, font=font)
            if which == "h":
                if not 20 < px < w - 40:
                    continue
                dr.rectangle([px - tw / 2 - 2, h - 15, px + tw / 2 + 2, h - 2], fill=BG)
                dr.text((px - tw / 2, h - 14), text, fill=LABEL, font=font)
            else:
                if not 36 < px < h - 20:
                    continue
                dr.rectangle([2, px - 7, tw + 6, px + 6], fill=BG)
                dr.text((4, px - 6), text, fill=LABEL, font=font)
        tag = f"{names[i]} m"
        tw = dr.textlength(tag, font=font)
        if which == "h":
            dr.text((w - tw - 6, h - 14), tag, fill=(240, 200, 120), font=font)
        else:
            dr.text((4, 20), tag, fill=(240, 200, 120), font=font)
    dr.text((8, 4), title, fill=LABEL, font=font)
    return img, scale


def render_view(placed, yaw=35.0, pitch=25.0, zoom=1.0, focus=None, title="",
                width=1200, height=800, ruler=None, labels=()):
    """One large view from any angle.

    yaw: 0 = side view with the bow to the right, 90 = from the bow, 180 = the other side,
    270 = from the stern. pitch: degrees above (+) or below (-) the horizon.
    zoom: 1 fits the whole vehicle; 2-6 for close-ups. focus: (fx, fy, fz) fractions of the
    bounding box to centre on, e.g. (0.5, 0.2, 0.9) = low on the bow; default is the middle.
    """
    faces = _world_faces(placed)
    yr, pr = math.radians(yaw), math.radians(max(-89.9, min(89.9, pitch)))
    cam_pos = (-math.cos(pr) * math.cos(yr), math.sin(pr), math.cos(pr) * math.sin(yr))
    cam = _camera(tuple(-c for c in cam_pos))
    target = None
    if focus is not None:
        pts = [q for pts, _, _, _ in faces for q in pts]
        lo = [min(q[i] for q in pts) for i in range(3)]
        hi = [max(q[i] for q in pts) for i in range(3)]
        f = list(focus)
        f[0] = 1 - f[0]   # x is mirrored for display
        target = tuple(lo[i] + (hi[i] - lo[i]) * f[i] for i in range(3))
    label = f"{title}  yaw {yaw:.0f}, pitch {pitch:.0f}, zoom {zoom:g}".strip()
    img, _ = _draw_view(faces, cam, width, height, label, grid=abs(pitch) < 1 or abs(pitch) > 89,
                        zoom=zoom, focus=target, ruler=ruler, labels=labels)
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def render_png(placed, title="", width=1350, height=900, ruler=None):
    faces = _world_faces(placed)
    top_h = int(height * 0.5)
    low_h = height - top_h
    third, half = width // 3, width // 2
    canvas = Image.new("RGB", (width, height), BG)
    panels = [
        ((0, 0), _draw_view(faces, VIEWS["3/4 view"], third, top_h, "3/4 from above")[0]),
        ((third, 0), _draw_view(faces, _camera((-1.0, 0.8, -1.1)), third, top_h,
                                "3/4 from below (hull bottom)")[0]),
        ((2 * third, 0), _draw_view(faces, VIEWS["front (from bow)"], width - 2 * third, top_h,
                                    "front (from bow)  grid = 1 m", grid=True, ruler=ruler)[0]),
        ((0, top_h), _draw_view(faces, VIEWS["side (bow right)"], half, low_h,
                                "side (bow right)  grid = 1 m", grid=True, ruler=ruler)[0]),
        ((half, top_h), _draw_view(faces, VIEWS["top (bow right)"], width - half, low_h,
                                   "top (bow right)  grid = 1 m", grid=True, ruler=ruler)[0]),
    ]
    for pos, img in panels:
        canvas.paste(img, pos)
    dr = ImageDraw.Draw(canvas)
    for x in (third, 2 * third):
        dr.line([(x, 0), (x, top_h)], fill=GRID, width=2)
    dr.line([(half, top_h), (half, height)], fill=GRID, width=2)
    dr.line([(0, top_h), (width, top_h)], fill=GRID, width=2)
    if title:
        dr.text((width - 8 - 7 * len(title), 4), title, fill=LABEL, font=ImageFont.load_default())
    buf = io.BytesIO()
    canvas.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def render_interior(placed, info, title="", width=1350, ruler=None):
    """Longitudinal section on the centreline plus a labelled plan view of every room level."""
    plan = info["interior"]
    sx, sy, sz = info["shift"]
    cut_x = -sx                     # build-coordinate centreline after centring

    def to_render(v):
        return _mirror((v[0] - sx, v[1] - sy, v[2] - sz))

    section = [p for p in placed if p.origin[0] <= cut_x]
    labels = [(to_render((0, r.ylo + 1.5, (r.zlo + r.zhi) / 2)), r.name) for r in plan.rooms]
    sec_h = 430
    levels = sorted({r.ylo for r in plan.rooms})
    per_row = max(1, min(2, len(levels)))
    rows = (len(levels) + per_row - 1) // per_row
    plan_h = 380
    canvas = Image.new("RGB", (width, sec_h + rows * plan_h), BG)
    sec_cam = _camera((1, 0, 0))
    img, _ = _draw_view(_world_faces(section, light=(-1, 0.5, 0.3), ambient=0.5, facing=sec_cam[0]),
                        sec_cam, width, sec_h,
                        f"{title}  section on the centreline (bow right)  grid = 1 m", grid=True,
                        labels=labels, ruler=ruler)
    canvas.paste(img, (0, 0))
    names = {y: lbl for lbl, y in plan.levels}
    main_deck = max((y for lbl, y in plan.levels if lbl == "main deck"), default=None)
    pw = width // per_row
    plan_cam = _camera((0, -1, 0), (1, 0, 0))
    for i, y in enumerate(levels):
        here = [r for r in plan.rooms if r.ylo == y]
        # walls up to 1.25 m above the floor; floors hide anything more than 2 m below
        lo_y, hi_y = y - 8, y + 5
        box = None
        if main_deck is not None and y > main_deck:   # superstructure floor: crop to its rooms
            air = [v for r in here for v in r.air]
            box = (min(v[0] for v in air) - 6, max(v[0] for v in air) + 6,
                   min(v[2] for v in air) - 6, max(v[2] for v in air) + 6)
        cut = []
        for p in placed:
            bx, by, bz = p.origin[0] + sx, p.origin[1] + sy, p.origin[2] + sz
            if not lo_y <= by <= hi_y:
                continue
            if box and not (box[0] <= bx <= box[1] and box[2] <= bz <= box[3]):
                continue
            cut.append(p)
        lab = [(to_render(((r.xlo + r.xhi) / 2 if r.xlo > -400 else 0, y, (r.zlo + r.zhi) / 2)), r.name)
               for r in here]
        name = names.get(y, f"level at {y / 4:.2f} m")
        if box:
            name += ", cropped to its rooms"
        img, _ = _draw_view(_world_faces(cut, light=(0.3, 1, 0.2), ambient=0.45, facing=plan_cam[0]),
                            plan_cam, pw, plan_h,
                            f"deck plan: {name} (bow right)", grid=True, labels=lab, ruler=ruler)
        canvas.paste(img, ((i % per_row) * pw, sec_h + (i // per_row) * plan_h))
    buf = io.BytesIO()
    canvas.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def design_ruler(info, scale=1.0):
    """Ruler for a built design: render coordinate = a * spec metres + b on each axis."""
    sx, sy, sz = info["shift"]
    k = 4 * scale
    return ((-k, sx), (k, -0.5 - sy), (k, -0.5 - sz))


VEHICLE_RULER = ((-4, 0), (4, 0), (4, 0))   # saved vehicles: metres from the workbench centre
