"""Parametric hull spec -> solid voxel set.

Coordinates while building: x lateral (0 = centreline, + = starboard), y up (0 = lowest keel
point), z along the hull (0 = transom, increasing toward the bow). 4 voxels per metre.
A spec length in metres maps to voxel faces at `m * VOX - 0.5` along y and z (voxel centres sit
on integers), and to `m * VOX` along x. The finished vehicle is re-centred on the workbench
origin in vehicle.py.
"""
import copy
import difflib
import math
import re

VOX = 4  # voxels per metre

DEFAULT_SPEC = {
    "length": 12.0,
    "beam": 3.6,
    "depth": 2.0,
    "hulls": 1,
    "hull_spacing": 0.0,
    "deck": "closed",
    "smoothing": "blocks",
    "scale": 1,
    "bench": None,
    "interior_units": "game",
    "bow": {"entry": 0.35, "fullness": 1.6, "stem_width": 0.0, "rake": 0.8,
            "rake_curve": 2.0, "flare": 0.15, "deadrise": 30.0, "bulb": None},
    "stern": {"run": 0.12, "transom_width": 0.85, "fullness": 2.0, "keel_rise": 0.0},
    "sheer": {"bow": 0.5, "stern": 0.1},
    "section": {"deadrise": 14.0, "bilge_radius": 0.3, "flare": 0.1, "keel_width": 0.25},
    "colors": {"bottom": "A52A2A", "stripe": "1A1A1A", "topsides": "F0F0F0",
               "deck": "6E6E6E", "waterline": None, "stripe_height": 0.25},
    "superstructure": [],
    "skegs": [],
    "paint": [],
    "components": [],
    "tanks": [],
    "edits": [],
    "fitout": None,
}

LIMITS = {"length": (1.0, 120.0), "beam": (0.5, 40.0), "depth": (0.25, 20.0)}
SHAPES = ("box", "cylinder", "dome", "sphere", "lattice")
PIVOTS = ("base", "back", "front", "aft", "fore", "centre")
FLOOR_HEIGHT = 2.5   # game metres per box floor: 2.25 m headroom plus a 0.25 m floor or roof

# Lengths multiplied by `scale`. The interior is never scaled: rooms need game-sized headroom.
_SCALED = {
    None: ("length", "beam", "depth", "hull_spacing"),
    "bow": ("rake",), "stern": ("keel_rise",), "sheer": ("bow", "stern"),
    "section": ("bilge_radius", "keel_width"), "colors": ("waterline", "stripe_height"),
}
_SCALED_BOX = ("z", "length", "width", "height", "x", "taper", "rake_front", "rake_back")
_SCALED_BULB = ("length", "width", "height", "y", "protrude")
_SCALED_SKEG = ("z", "length", "x", "width", "bottom")
_SCALED_PAINT = ("z", "length", "y", "height", "x", "width", "radius", "thickness")
_SCALED_ROOM = ("z", "length", "width", "x", "floor", "height")
_SCALED_HATCH = ("z", "x", "floor", "size")
_Y_REF = re.compile(r"^(.*?)\s*([+-]\s*\d+(?:\.\d*)?|[+-]\s*\.\d+)?$")


def merge(base, over):
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def scale_factor(spec):
    """`scale` as a number: 1, 0.25, or a ratio string such as "1:4"."""
    s = spec.get("scale", 1)
    if s is None:
        return 1.0
    if s == "fit":
        raise ValueError('scale "fit" is only known after a build (see build.fitted)')
    if isinstance(s, str):
        m = re.fullmatch(r"\s*(\d+(?:\.\d*)?)\s*:\s*(\d+(?:\.\d*)?)\s*", s)
        if not m or float(m.group(2)) == 0:
            raise ValueError(f'scale must be a number or a ratio such as "1:4" (got {s!r})')
        s = float(m.group(1)) / float(m.group(2))
    if not isinstance(s, (int, float)) or not 0 < s <= 10:
        raise ValueError(f"scale must be in (0, 10] (got {s!r})")
    return float(s)


def split_y_ref(y):
    """A string `y` such as "deck+0.25" or "deckhouse_02" -> (reference, offset in metres)."""
    m = _Y_REF.match(y.strip())
    ref, off = m.group(1).strip(), m.group(2)
    if not ref:
        raise ValueError(f"y {y!r} needs a reference: \"deck\" or a box name, e.g. \"deck+0.25\"")
    return ref, float(off.replace(" ", "")) if off else 0.0


def game_units(spec):
    """Copy of the spec with every length multiplied by `scale` (and scale set to 1)."""
    s = scale_factor(spec)
    out = copy.deepcopy(spec)
    out["scale"] = 1
    if s != 1.0:
        _scale_lengths(out, s)
    for box in out.get("superstructure") or []:
        if box.get("floors"):        # game metres, whatever the scale
            box["height"] = box["floors"] * FLOOR_HEIGHT
    return out


def _scale_lengths(out, s):
    """Multiply every spec-unit length in `out` by s, in place."""
    def mul(d, keys):
        for k in keys:
            if isinstance(d.get(k), (int, float)) and not isinstance(d.get(k), bool):
                d[k] = d[k] * s

    for group, keys in _SCALED.items():
        target = out if group is None else out.get(group)
        if isinstance(target, dict):
            mul(target, keys)
    if isinstance(out["bow"].get("bulb"), dict):
        mul(out["bow"]["bulb"], _SCALED_BULB)
    for box in out.get("superstructure") or []:
        mul(box, _SCALED_BOX)
        if isinstance(box.get("y"), (int, float)):
            box["y"] *= s
        elif isinstance(box.get("y"), str):
            ref, off = split_y_ref(box["y"])
            box["y"] = f"{ref}{off * s:+g}" if off else ref
        if isinstance(box.get("band"), dict):
            mul(box["band"], ("from", "to"))
        if isinstance(box.get("repeat"), dict):
            mul(box["repeat"], ("dx", "dy", "dz"))
    for skeg in out.get("skegs") or []:
        mul(skeg, _SCALED_SKEG)
    for item in out.get("paint") or []:
        mul(item, _SCALED_PAINT)
    interior = out.get("interior")
    if isinstance(interior, dict) and out.get("interior_units") == "spec":
        for key in ("decks", "bulkheads"):
            interior[key] = [v * s if _num(v) else v for v in interior.get(key) or []]
        for room in interior.get("rooms") or []:
            mul(room, _SCALED_ROOM)
        for hatch in interior.get("hatches") or []:
            mul(hatch, _SCALED_HATCH)


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def validate(spec):
    _validate_structure(spec)
    problems = []
    fit = spec.get("scale") == "fit"
    if fit and spec.get("bench") is None:
        problems.append('scale "fit" needs a bench to fit, e.g. "bench": "MAX"')
    try:
        game = game_units(merge(spec, {"scale": 1}) if fit else spec)
    except ValueError as exc:
        problems.append(str(exc))
        game = spec
    if spec.get("interior_units", "game") not in ("game", "spec"):
        problems.append('interior_units must be "game" or "spec"')
    for key, (lo, hi) in LIMITS.items():
        v = game.get(key)
        if fit and _num(v) and v > 0:     # checked against the bench once the scale is known
            continue
        if not _num(v) or not lo <= v <= hi:
            note = " after scale" if spec.get("scale", 1) not in (1, None) else ""
            problems.append(f"{key} must be a number in [{lo}, {hi}] metres{note} (got {v!r})")
    try:
        from .benches import parse_bench  # noqa: PLC0415 - benches imports hull
        parse_bench(spec.get("bench"))
    except ValueError as exc:
        problems.append(str(exc))
    if spec.get("smoothing") not in ("blocks", "wedges"):
        problems.append('smoothing must be "blocks" or "wedges"')
    if spec.get("deck") not in ("closed", "open"):
        problems.append('deck must be "closed" or "open"')
    if spec.get("hulls") not in (1, 2, 3):
        problems.append("hulls must be 1 (mono), 2 (catamaran) or 3 (trimaran)")
    if spec.get("hulls", 1) > 1 and spec.get("hull_spacing", 0) <= spec.get("beam", 0):
        problems.append("hull_spacing (centreline to centreline) must exceed beam for multihulls")
    for i, box in enumerate(spec.get("superstructure") or []):
        where = f"superstructure[{i}]" + (f" ({box['name']})" if isinstance(box, dict) and box.get("name") else "")
        if not isinstance(box, dict):
            problems.append(f"{where} must be an object")
            continue
        for k in ("z", "length", "width", "height"):
            if not _num(box.get(k)) and not (k == "height" and box.get("floors")):
                problems.append(f"{where}.{k} is required (metres)")
        if box.get("floors") is not None and not (isinstance(box["floors"], int) and 1 <= box["floors"] <= 40):
            problems.append(f"{where}.floors must be a whole number of floors (1-40)")
        if box.get("facing", "fore") not in ("fore", "aft"):
            problems.append(f'{where}.facing must be "fore" or "aft"')
        if box.get("y") is not None and not isinstance(box["y"], (int, float, str)):
            problems.append(f'{where}.y must be metres, "deck+0.5" or "<box name>+0.5"')
        if box.get("shape", "box") not in SHAPES:
            problems.append(f"{where}.shape must be one of {', '.join(SHAPES)}")
        if box.get("axis", "y") not in ("x", "y", "z"):
            problems.append(f"{where}.axis must be x, y or z")
        if box.get("pivot", "base") not in PIVOTS:
            problems.append(f"{where}.pivot must be one of {', '.join(PIVOTS)}")
        for k in ("pitch", "yaw", "taper", "rake_front", "rake_back", "x"):
            if box.get(k) is not None and not _num(box[k]):
                problems.append(f"{where}.{k} must be a number")
        rep = box.get("repeat")
        if rep is not None and (not isinstance(rep, dict) or not isinstance(rep.get("count"), int)
                                or not 1 <= rep["count"] <= 100):
            problems.append(f"{where}.repeat must be {{count: 1-100, dz, dx, dy}}")
    bulb = spec.get("bow", {}).get("bulb")
    if bulb is not None and not (isinstance(bulb, dict) and all(_num(bulb.get(k)) for k in ("length", "width", "height"))):
        problems.append("bow.bulb needs length, width and height (metres)")
    for i, skeg in enumerate(spec.get("skegs") or []):
        if not isinstance(skeg, dict) or not all(_num(skeg.get(k)) for k in ("z", "length")):
            problems.append(f"skegs[{i}] needs z and length (metres)")
    for i, item in enumerate(spec.get("paint") or []):
        if not isinstance(item, dict):
            problems.append(f"paint[{i}] must be an object")
            continue
        if item.get("shape", "rect") not in ("rect", "circle", "text"):
            problems.append(f"paint[{i}].shape must be rect, circle or text")
        if item.get("on", "sides") not in ("deck", "port", "starboard", "sides"):
            problems.append(f"paint[{i}].on must be deck, port, starboard or sides")
        if not _num(item.get("z")):
            problems.append(f"paint[{i}].z is required (metres)")
        if item.get("shape") == "text" and not isinstance(item.get("text"), str):
            problems.append(f"paint[{i}].text is required for shape text")
    interior = spec.get("interior") or {}
    if not isinstance(interior, dict):
        problems.append("interior must be an object")
        interior = {}
    for key in ("decks", "bulkheads"):
        if not all(_num(v) for v in interior.get(key) or []):
            problems.append(f"interior.{key} must be a list of numbers (metres)")
    for i, room in enumerate(interior.get("rooms") or []):
        for k in ("z", "length"):
            if not _num(room.get(k)):
                problems.append(f"interior.rooms[{i}].{k} is required (metres)")
        if room.get("engine") not in (None, "small", "medium", "large"):
            problems.append(f"interior.rooms[{i}].engine must be small, medium or large")
    for i, h in enumerate(interior.get("hatches") or []):
        if not _num(h.get("z")):
            problems.append(f"interior.hatches[{i}].z is required (metres)")
    if problems:
        raise ValueError("; ".join(problems))
    from .components import validate_config  # noqa: PLC0415 - delayed to avoid hull/smooth cycle
    validate_config(spec)
    from .tanks import validate_config as validate_tanks  # noqa: PLC0415
    validate_tanks(spec)


def _validate_structure(spec):
    """Catch misspelled shape parameters and malformed containers before geometry touches them."""
    if not isinstance(spec, dict):
        raise ValueError("spec must be a JSON object")

    def known_fields(data, allowed, where):
        for key in data:
            if key not in allowed:
                close = difflib.get_close_matches(key, allowed, n=1)
                suggestion = f"; did you mean '{close[0]}'?" if close else ""
                raise ValueError(f"unknown field {where}.{key}{suggestion}; see hull_design_guide")

    known_fields(spec, set(DEFAULT_SPEC) | {"interior"}, "spec")
    for group in ("bow", "stern", "sheer", "section", "colors"):
        data = spec.get(group)
        if not isinstance(data, dict):
            raise ValueError(f"{group} must be an object")
        known_fields(data, DEFAULT_SPEC[group], group)
    for group in ("superstructure", "skegs", "paint", "components", "tanks", "edits"):
        data = spec.get(group)
        if data is not None and (not isinstance(data, list) or any(not isinstance(item, dict) for item in data)):
            raise ValueError(f"{group} must be a list of objects")
    interior = spec.get("interior")
    if interior is not None:
        if not isinstance(interior, dict):
            raise ValueError("interior must be an object")
        for group in ("rooms", "hatches"):
            data = interior.get(group)
            if data is not None and (not isinstance(data, list) or any(not isinstance(item, dict) for item in data)):
                raise ValueError(f"interior.{group} must be a list of objects")
        for group in ("decks", "bulkheads"):
            data = interior.get(group)
            if data is not None and not isinstance(data, list):
                raise ValueError(f"interior.{group} must be a list of numbers")

    def finite(data, where):
        if isinstance(data, float) and not math.isfinite(data):
            raise ValueError(f"{where} must be finite (NaN and infinity are not supported)")
        if isinstance(data, dict):
            for key, value in data.items():
                finite(value, f"{where}.{key}")
        elif isinstance(data, list):
            for index, value in enumerate(data):
                finite(value, f"{where}[{index}]")

    finite(spec, "spec")


class HullForm:
    """Continuous hull shape; all lengths in voxels, s in [0, 1] from transom to stem."""

    def __init__(self, spec):
        self.spec = spec
        self.L = max(2, round(spec["length"] * VOX))
        self.B0 = spec["beam"] * VOX / 2
        self.depth = spec["depth"] * VOX
        self.bow, self.stern = spec["bow"], spec["stern"]
        self.sheer, self.sec = spec["sheer"], spec["section"]

    def s(self, z):
        return z / (self.L - 1)

    def bow_t(self, s):
        e = max(1e-6, self.bow["entry"])
        return max(0.0, (s - (1 - e)) / e)

    def half_beam(self, s):
        B = self.B0
        t = self.bow_t(s)
        if t > 0:
            p, sw = max(0.3, self.bow["fullness"]), self.bow["stem_width"]
            B *= sw + (1 - sw) * (1 - min(1.0, t) ** p) ** (1 / p)
        r = self.stern["run"]
        if r > 0 and s < r:
            t = (r - s) / r
            p, tw = max(0.3, self.stern["fullness"]), self.stern["transom_width"]
            B *= tw + (1 - tw) * (1 - t ** p) ** (1 / p)
        return B

    def deck(self, s):
        up = max(0.0, (s - 0.5) / 0.5) ** 2 * self.sheer["bow"]
        aft = max(0.0, (0.5 - s) / 0.5) ** 2 * self.sheer["stern"]
        return self.depth + (up + aft) * VOX

    def keel(self, s):
        k = 0.0
        t = self.bow_t(s)
        if t > 0:
            k += self.bow["rake"] * VOX * t ** max(0.5, self.bow["rake_curve"])
        r = self.stern["run"]
        if r > 0 and s < r and self.stern["keel_rise"]:
            k += self.stern["keel_rise"] * VOX * ((r - s) / r) ** 2
        return min(k, self.deck(s) - 1.5)

    def half_width(self, s, h, H, B):
        """Half-width of the section at height h above the keel (h in [0, H])."""
        t = min(1.0, self.bow_t(s))
        dr = math.radians(self.sec["deadrise"] + (self.bow["deadrise"] - self.sec["deadrise"]) * t)
        flare = self.sec["flare"] + self.bow["flare"] * t
        Bc = max(0.0, B * (1 - flare))
        kw = min(Bc, self.sec["keel_width"] * VOX / 2)
        hc = 0.0 if dr < math.radians(0.5) else min((Bc - kw) * math.tan(dr), H * 0.9)
        side_slope = (B - Bc) / max(H - hc, 1e-6)

        def raw(y):
            if y < 0:
                return max(0.0, kw + (Bc - kw) * y / hc) if hc > 0 else 0.0
            if y < hc:
                return kw + (Bc - kw) * y / hc
            return Bc + side_slope * (y - hc)

        r = self.sec["bilge_radius"] * VOX
        if r <= 0:
            return raw(h)
        n = 9
        return sum(raw(h - r + 2 * r * i / (n - 1)) for i in range(n)) / n


def expand_boxes(boxes):
    """Apply `repeat` and `mirror_x`. Returns copies with a unique `name` each, plus `_suffix`
    (how the name was extended) so `on`/`y` references can find the matching copy."""
    out = []
    for i, src in enumerate(boxes or []):
        base = dict(src)
        name = str(base.get("name") or f"superstructure[{i}]")
        rep = base.pop("repeat", None) or {"count": 1}
        mirror = bool(base.pop("mirror_x", False))
        count = rep.get("count", 1)
        for k in range(count):
            b = dict(base)
            r_suffix = f"_{k + 1}" if count > 1 else ""
            b["z"] = base["z"] + k * rep.get("dz", 0.0)
            b["x"] = base.get("x", 0.0) + k * rep.get("dx", 0.0)
            if _num(base.get("y")):
                b["y"] = base["y"] + k * rep.get("dy", 0.0)
            copies = [(b, "")]
            if mirror and b["x"]:
                twin = dict(b, x=-b["x"], yaw=-b.get("yaw", 0.0))
                side = "_stbd" if b["x"] > 0 else "_port"
                other = "_port" if b["x"] > 0 else "_stbd"
                copies = [(b, side), (twin, other)]
            for c, m_suffix in copies:
                c["name"] = name + r_suffix + m_suffix
                c["_suffix"] = (r_suffix, m_suffix)
                c["_mirror_on_centre"] = mirror and not b["x"]
                out.append(c)
    names = [b["name"] for b in out]
    dupes = sorted({n for n in names if names.count(n) > 1})
    if dupes:
        raise ValueError(f"superstructure names must be unique: {', '.join(dupes)}")
    return out


def _span(lo, hi, pad):
    """Interval [lo, hi], widened to at least 2*pad around its middle."""
    if pad and hi - lo < 2 * pad:
        c = (lo + hi) / 2
        return c - pad, c + pad
    return lo, hi


class Box:
    """Superstructure part as a continuous shape (voxel-centre coordinates).

    Local frame: u across (0 = box centreline), v up from the bottom face (0..h), w along from
    the aft face (0..zl). `pitch` raises the fore end, `yaw` swings it to starboard (+x), both
    about `pivot`.
    """

    def __init__(self, box, y0):
        self.spec = box
        self.name = box["name"]
        self.z0 = round(box["z"] * VOX)
        self.zl = max(1, round(box["length"] * VOX))
        self.hw = box["width"] * VOX / 2
        self.xc = box.get("x", 0.0) * VOX
        self.h = max(1, round(box["height"] * VOX))
        self.y0 = y0
        self.shape = box.get("shape", "box")
        self.axis = box.get("axis", "y")
        self.taper = box.get("taper", 0.0) * VOX
        self.rake_f = box.get("rake_front", 0.0) * VOX
        self.rake_b = box.get("rake_back", 0.0) * VOX
        self.ring = max(1, round(box.get("ring_every", 1.0) * VOX))
        # facing aft turns the part end for end about its footprint centre; yaw is negated so a
        # positive yaw still swings the front end to starboard
        self.flip = box.get("facing", "fore") == "aft"
        pitch = math.radians(box.get("pitch", 0.0))
        yaw = math.radians(box.get("yaw", 0.0)) * (-1 if self.flip else 1)
        self.rotated = abs(pitch) > 1e-9 or abs(yaw) > 1e-9
        self.cp, self.sp, self.cy, self.sy = math.cos(pitch), math.sin(pitch), math.cos(yaw), math.sin(yaw)
        # rotated parts sample voxel centres; keep thin ones at least ~1.5 blocks so a
        # diagonal stays face-connected instead of touching only at corners
        self.pad = 0.72 if self.rotated else 0.0
        h, zl = self.h, self.zl
        back, front = (0.0, h / 2, 0.0), (0.0, h / 2, zl)     # the part's own ends
        self.pivot = {"base": (0.0, 0.0, zl / 2), "back": back, "aft": back, "front": front,
                      "fore": front, "centre": (0.0, h / 2, zl / 2)}[box.get("pivot", "base")]
        self.cz2 = 2 * (self.z0 - 0.5) + zl      # twice the footprint centre along z (for flips)
        self._bounds = self._world_bounds()

    def warnings(self):
        out = []
        f_top = (self.h - 0.5) / self.h
        if self.shape == "box":
            for key, val in (("taper", self.taper), ("rake_front", self.rake_f), ("rake_back", self.rake_b)):
                if val > 0 and val * f_top < 0.5:
                    out.append(f"box '{self.name}': {key} {val / VOX:g} m is under half a block at the "
                               "top and changes nothing; use 0 or at least 0.25 m")
        elif self.rake_f or self.rake_b:
            out.append(f"box '{self.name}': rake_front/rake_back only apply to shape box")
        if self.spec.get("_mirror_on_centre"):
            out.append(f"box '{self.name}': mirror_x does nothing at x = 0")
        return out

    def top(self):
        return self.y0 + self.h

    # local <-> build coordinates
    def _origin(self):
        return (self.xc, self.y0 - 0.5, self.z0 - 0.5)

    def to_world(self, u, v, w):
        x, y, z = self._to_world(u, v, w)
        return (2 * self.xc - x, y, self.cz2 - z) if self.flip else (x, y, z)

    def _to_world(self, u, v, w):
        ox, oy, oz = self._origin()
        if not self.rotated:
            return (ox + u, oy + v, oz + w)
        pu, pv, pw = self.pivot
        a, b, c = u - pu, v - pv, w - pw
        b, c = b * self.cp + c * self.sp, -b * self.sp + c * self.cp          # pitch
        a, c = a * self.cy + c * self.sy, -a * self.sy + c * self.cy          # yaw
        return (ox + pu + a, oy + pv + b, oz + pw + c)

    def local(self, X, Y, Z):
        ox, oy, oz = self._origin()
        if self.flip:
            X, Z = 2 * self.xc - X, self.cz2 - Z
        if not self.rotated:
            return (X - ox, Y - oy, Z - oz)
        pu, pv, pw = self.pivot
        a, b, c = X - ox - pu, Y - oy - pv, Z - oz - pw
        a, c = a * self.cy - c * self.sy, a * self.sy + c * self.cy          # undo yaw
        b, c = b * self.cp - c * self.sp, b * self.sp + c * self.cp          # undo pitch
        return (a + pu, b + pv, c + pw)

    def _world_bounds(self):
        pts = [self.to_world(u, v, w) for u in (-self.hw, self.hw) for v in (0, self.h)
               for w in (0, self.zl)]
        lo = [math.floor(min(p[i] for p in pts)) - 1 for i in range(3)]
        hi = [math.ceil(max(p[i] for p in pts)) + 1 for i in range(3)]
        return lo, hi

    def bounds(self):
        lo, hi = self._bounds
        return ((lo[0], hi[0]), (lo[1], hi[1]), (lo[2], hi[2]))

    def _solid(self, u, v, w):
        h, zl, pad = self.h, self.zl, self.pad
        vlo, vhi = _span(0.0, h, pad)
        if not vlo - 1e-6 <= v <= vhi + 1e-6:
            return False
        f = min(1.0, max(0.0, v / h))
        inset = self.taper * f
        shape = self.shape
        if shape in ("box", "lattice"):
            wlo, whi = _span(inset + self.rake_b * f, zl - inset - self.rake_f * f, pad)
            if not wlo - 1e-6 <= w <= whi + 1e-6:
                return False
            return abs(u) <= max(self.hw - inset - 0.5, pad) + 1e-6
        if shape == "cylinder" and self.axis != "y":
            rv = max(h / 2 - 0.25, pad)
            if self.axis == "z":       # along the hull; taper narrows it toward the fore end
                wlo, whi = _span(0.0, zl, pad)
                if not wlo - 1e-6 <= w <= whi + 1e-6:
                    return False
                shrink = self.taper * min(1.0, max(0.0, w / zl))
                ru, rv = max(self.hw - 0.25 - shrink, pad), max(rv - shrink, pad)
                return ru > 0 and rv > 0 and (u / ru) ** 2 + ((v - h / 2) / rv) ** 2 <= 1 + 1e-6
            rw = max(zl / 2 - 0.25, pad)
            return (abs(u) <= max(self.hw - 0.5, pad) + 1e-6
                    and ((v - h / 2) / rv) ** 2 + ((w - zl / 2) / rw) ** 2 <= 1 + 1e-6)
        ru = max(self.hw - 0.25 - inset, pad)
        rw = max(zl / 2 - 0.25 - inset, pad)
        if ru <= 0 or rw <= 0:
            return False
        q = (u / ru) ** 2 + ((w - zl / 2) / rw) ** 2
        if shape == "cylinder":
            return q <= 1 + 1e-6
        if shape == "dome":
            return q + (v / h) ** 2 <= 1 + 1e-6
        rv = max(h / 2 - 0.25, pad)         # sphere / ellipsoid filling the box
        return q + ((v - h / 2) / rv) ** 2 <= 1 + 1e-6

    def inside(self, X, Y, Z):
        lo, hi = self._bounds
        if not (lo[0] <= X <= hi[0] and lo[1] <= Y <= hi[1] and lo[2] <= Z <= hi[2]):
            return False
        u, v, w = self.local(X, Y, Z)
        if not self._solid(u, v, w):
            return False
        if self.shape != "lattice":
            return True
        s = self._solid
        edge_u = not (s(u - 1, v, w) and s(u + 1, v, w))
        edge_w = not (s(u, v, w - 1) and s(u, v, w + 1))
        layer = int(math.floor(v))
        ring = layer % self.ring == 0 or v + 1 > self.h
        return (edge_u and edge_w) or (ring and (edge_u or edge_w))


def _lookup(target, suffix, by_name):
    """Box named `target`, preferring the copy with the same repeat/mirror suffix."""
    r, m = suffix
    for cand in (target + r + m, target + m, target + r, target):
        if cand in by_name:
            return by_name[cand]
    return None


def resolve_boxes(boxes, form):
    """Box objects with `y` resolved: number, "deck[+-d]", "<name>[+-d]" or `on: <name>`."""
    by_name = {b["name"]: b for b in boxes}
    y0s, active = {}, set()

    def deck_y0(b):
        z0, zl = round(b["z"] * VOX), max(1, round(b["length"] * VOX))
        zs = [min(max(z, 0), form.L - 1) for z in range(z0, z0 + zl)]
        return int(math.floor(min(form.deck(form.s(z)) for z in zs)))

    def y0_of(b):
        name = b["name"]
        if name in y0s:
            return y0s[name]
        if name in active:
            raise ValueError(f"box '{name}': its y refers back to itself through other boxes")
        active.add(name)
        y = b.get("y")
        if b.get("on") and y is None:
            y = str(b["on"])
        if y is None:
            y0 = deck_y0(b)
        elif _num(y):
            y0 = round(y * VOX)
        else:
            ref, off = (str(y).strip(), 0.0) if str(y).strip() in by_name else split_y_ref(str(y))
            if ref == "deck":
                y0 = deck_y0(b) + round(off * VOX)
            else:
                target = _lookup(ref, b.get("_suffix", ("", "")), by_name)
                if target is None:
                    raise ValueError(f"box '{name}': y/on refers to '{ref}', which is not a box name "
                                     "or \"deck\"")
                y0 = y0_of(target) + max(1, round(target["height"] * VOX)) + round(off * VOX)
        if b.get("floors"):
            # the hull keeps any layer the box dips into; add those so every floor keeps 2.25 m
            zc = min(max(round(b["z"] * VOX + b["length"] * VOX / 2), 0), form.L - 1)
            free = math.floor(form.deck(form.s(zc)) - 0.5) + 1
            b["height"] = b["floors"] * FLOOR_HEIGHT + max(0, free - y0) / VOX
        active.discard(name)
        y0s[name] = y0
        return y0

    return [Box(b, y0_of(b)) for b in boxes]


class HullShape:
    """The whole design as a point-inside test. Voxel (x, y, z) is centred at (x, y, z)."""

    def __init__(self, spec):
        self.form = form = HullForm(spec)
        n = spec["hulls"]
        spacing = spec["hull_spacing"] * VOX
        self.offsets = [0] if n == 1 else [round(spacing * (i - (n - 1) / 2)) for i in range(n)]
        self.boxes = resolve_boxes(expand_boxes(spec.get("superstructure")), form)
        self.by_name = {b.name: b for b in self.boxes}
        self.warnings = [w for b in self.boxes for w in b.warnings()]
        self.bulb = self._bulb(spec["bow"].get("bulb"))
        self.skegs = []
        for sk in spec.get("skegs") or []:
            for sx in ([sk.get("x", 0.0), -sk.get("x", 0.0)] if sk.get("mirror_x") and sk.get("x") else
                       [sk.get("x", 0.0)]):
                self.skegs.append((round(sx * VOX), max(0.5, sk.get("width", 0.25) * VOX / 2),
                                   round(sk["z"] * VOX), round((sk["z"] + sk["length"]) * VOX) - 1,
                                   round(sk.get("bottom", 0.0) * VOX)))
        self._hw = {}
        self._bottom = {}

    def _bulb(self, b):
        if not b:
            return None
        f = self.form
        length = b["length"] * VOX
        tip = (f.L - 0.5) + b.get("protrude", b["length"] * 0.4) * VOX
        return {"zc": tip - length / 2, "az": length / 2, "ax": b["width"] * VOX / 2,
                "ay": b["height"] * VOX / 2, "yc": b.get("y", self.form.depth / VOX * 0.35) * VOX - 0.5}

    def hull_half_width(self, Y, Z):
        key = (round(Y, 4), round(Z, 4))
        w = self._hw.get(key)
        if w is None:
            f = self.form
            w = -1.0
            if -0.5 <= Z <= f.L - 0.5:
                s = min(1.0, max(0.0, f.s(Z)))
                K, D = f.keel(s), f.deck(s)
                h = Y + 0.5 - K
                if 0.0 <= h <= D - K:
                    w = f.half_width(s, h, D - K, f.half_beam(s))
            self._hw[key] = w
        return w

    def in_hull(self, X, Y, Z):
        """Hull proper, bulb and skegs."""
        w = self.hull_half_width(Y, Z)
        if w >= 0 and any(abs(X - o) <= w + 1e-6 for o in self.offsets):
            return True
        return self._in_extras(X, Y, Z)

    def _in_extras(self, X, Y, Z):
        """Bulb and skegs."""
        b = self.bulb
        if b and any(((X - o) / b["ax"]) ** 2 + ((Y - b["yc"]) / b["ay"]) ** 2
                     + ((Z - b["zc"]) / b["az"]) ** 2 <= 1 for o in self.offsets):
            return True
        for sx, shw, z0, z1, ybot in self.skegs:
            if z0 <= Z <= z1 and abs(X - sx) <= shw - 0.5 + 1e-6:
                bottom = self._hull_bottom(X, Z)
                if bottom is not None and ybot <= Y < bottom:
                    return True
        return False

    def _hull_bottom(self, X, Z):
        key = (X, Z)
        if key not in self._bottom:
            top = int(self.form.depth + 4 * VOX)
            self._bottom[key] = next(
                (y for y in range(-2, top) if (w := self.hull_half_width(y, Z)) >= 0
                 and any(abs(X - o) <= w + 1e-6 for o in self.offsets)), None)
        return self._bottom[key]

    def region(self, X, Y, Z):
        """'hull', 'boxN', or None when the point is outside."""
        if self.in_hull(X, Y, Z):
            return "hull"
        for i, b in enumerate(self.boxes):
            if b.inside(X, Y, Z):
                return f"box{i}"
        return None

    _CHUNK = 8

    def contains(self, X, Y, Z):
        """Is the point inside anything? Like `region(...) is not None`, but only tests the
        boxes whose bounds reach the point."""
        if self.in_hull(X, Y, Z):
            return True
        return any(b.inside(X, Y, Z) for b in self.boxes_near((math.floor(X), math.floor(Y), math.floor(Z))))

    def sample_mask(self, v, samples):
        """Bit i set when voxel v + samples[i] is inside the shape. Same answer as testing
        `contains` on each sample, computed once per voxel: one hull half-width per (y, z) pair
        and one list of nearby boxes."""
        X, Y, Z = v
        boxes = self.boxes_near(v)
        extras = any(x0 <= X <= x1 and y0 <= Y <= y1 and z0 <= Z <= z1
                     for (x0, x1), (y0, y1), (z0, z1) in self.extra_bounds())
        offsets = self.offsets
        o0 = offsets[0] if len(offsets) == 1 else None
        hw = self.hull_half_width
        wc = {}
        m = 0
        for i, (dx, dy, dz) in enumerate(samples):
            x, y, z = X + dx, Y + dy, Z + dz
            k = (dy, dz)
            w = wc.get(k)
            if w is None:
                w = wc[k] = hw(y, z)
            in_hull = w >= 0 and (abs(x - o0) <= w + 1e-6 if o0 is not None
                                  else any(abs(x - o) <= w + 1e-6 for o in offsets))
            if (in_hull or (extras and self._in_extras(x, y, z))
                    or (boxes and any(b.inside(x, y, z) for b in boxes))):
                m |= 1 << i
        return m

    def extra_bounds(self):
        """Voxel bounds of the bulb and each skeg, padded a block (the only places
        `_in_extras` can be true)."""
        eb = self.__dict__.get("_extra_bounds")
        if eb is None:
            eb = []
            if self.bulb:
                b = self.bulb
                for o in self.offsets:
                    eb.append(((math.floor(o - b["ax"]) - 1, math.ceil(o + b["ax"]) + 1),
                               (math.floor(b["yc"] - b["ay"]) - 1, math.ceil(b["yc"] + b["ay"]) + 1),
                               (math.floor(b["zc"] - b["az"]) - 1, math.ceil(b["zc"] + b["az"]) + 1)))
            for sx, shw, z0, z1, ybot in self.skegs:
                eb.append(((math.floor(sx - shw) - 1, math.ceil(sx + shw) + 1), (ybot - 1, 10**6),
                           (z0 - 1, z1 + 1)))
            self._extra_bounds = eb
        return eb

    def boxes_near(self, v):
        """Boxes whose (padded) bounds contain voxel v. Bounds are padded a block beyond the
        shape, so any point within half a block of v that is inside a box finds it here."""
        index = self.__dict__.get("_index")
        if index is None:
            index = self._index = {}
            c = self._CHUNK
            for b in self.boxes:
                (x0, x1), (y0, y1), (z0, z1) = b.bounds()
                for cx in range(x0 // c, x1 // c + 1):
                    for cy in range(y0 // c, y1 // c + 1):
                        for cz in range(z0 // c, z1 // c + 1):
                            index.setdefault((cx, cy, cz), []).append(b)
        c = self._CHUNK
        x, y, z = v
        out = []
        for b in index.get((x // c, y // c, z // c), ()):
            (x0, x1), (y0, y1), (z0, z1) = b.bounds()
            if x0 <= x <= x1 and y0 <= y <= y1 and z0 <= z <= z1:
                out.append(b)
        return out

    def bounds(self):
        f = self.form
        top = max(f.deck(f.s(z)) for z in range(f.L))
        xs = [o + sgn * (f.B0 * 1.5 + 2) for o in self.offsets for sgn in (-1, 1)]
        lo = [int(min(xs)), -1, -1]
        hi = [int(max(xs)) + 1, int(top) + 1, f.L]
        for b in self.boxes:
            (x0, x1), (y0, y1), (z0, z1) = b.bounds()
            lo = [min(lo[0], x0), min(lo[1], y0), min(lo[2], z0)]
            hi = [max(hi[0], x1), max(hi[1], y1), max(hi[2], z1)]
        if self.bulb:
            b = self.bulb
            hi[2] = max(hi[2], int(math.ceil(b["zc"] + b["az"])) + 1)
            lo[1] = min(lo[1], int(math.floor(b["yc"] - b["ay"])) - 1)
        for _sx, _shw, _z0, _z1, ybot in self.skegs:
            lo[1] = min(lo[1], ybot - 1)
        return lo, hi


def build_solid(spec):
    """Return (shape, solid voxel set, region map voxel -> region tag).

    Same result as testing `shape.region` on every voxel of the bounding box, but each part is
    only visited inside its own bounds: hull rows come straight from the half-width, and boxes
    go in list order so the hull, then earlier boxes, keep shared voxels.
    """
    shape = HullShape(spec)
    lo, hi = shape.bounds()
    region = {}
    f = shape.form
    for z in range(max(lo[2], 0), min(hi[2], f.L - 1) + 1):
        for y in range(lo[1], hi[1] + 1):
            w = shape.hull_half_width(y, z)
            if w < 0:
                continue
            for o in shape.offsets:
                for x in range(max(lo[0], math.ceil(o - w - 1e-6)), min(hi[0], math.floor(o + w + 1e-6)) + 1):
                    region[(x, y, z)] = "hull"
    extras = []                       # bulb and skeg candidates, tested with the full hull test
    if shape.bulb:
        b = shape.bulb
        for o in shape.offsets:
            extras.append(((math.floor(o - b["ax"]), math.ceil(o + b["ax"])),
                           (math.floor(b["yc"] - b["ay"]), math.ceil(b["yc"] + b["ay"])),
                           (math.floor(b["zc"] - b["az"]), math.ceil(b["zc"] + b["az"]))))
    for sx, shw, z0, z1, ybot in shape.skegs:
        extras.append(((math.floor(sx - shw), math.ceil(sx + shw)), (ybot, hi[1]), (z0, z1)))
    for (x0, x1), (y0, y1), (z0, z1) in extras:
        for z in range(max(lo[2], z0), min(hi[2], z1) + 1):
            for y in range(max(lo[1], y0), min(hi[1], y1) + 1):
                for x in range(max(lo[0], x0), min(hi[0], x1) + 1):
                    if (x, y, z) not in region and shape.in_hull(x, y, z):
                        region[(x, y, z)] = "hull"
    shape.box_vox = {}
    for i, b in enumerate(shape.boxes):
        tag = f"box{i}"
        vox = box_voxels(b, lo, hi)
        shape.box_vox[b.name] = vox
        for v in vox:
            if v not in region:
                region[v] = tag
    return shape, set(region), region


def box_voxels(box, lo=None, hi=None):
    (x0, x1), (y0, y1), (z0, z1) = box.bounds()
    if lo is not None:
        x0, y0, z0 = max(x0, lo[0]), max(y0, lo[1]), max(z0, lo[2])
        x1, y1, z1 = min(x1, hi[0]), min(y1, hi[1]), min(z1, hi[2])
    inside = box.inside
    return {(x, y, z) for z in range(z0, z1 + 1) for y in range(y0, y1 + 1)
            for x in range(x0, x1 + 1) if inside(x, y, z)}


def box_report(shape, region):
    """(overlapping box pairs [(a, b, blocks)], boxes hidden inside others or the hull)."""
    vox = getattr(shape, "box_vox", None) or {b.name: box_voxels(b) for b in shape.boxes}
    pairs = []
    for i, a in enumerate(shape.boxes):
        (ax0, ax1), (ay0, ay1), (az0, az1) = a.bounds()
        for b in shape.boxes[i + 1:]:
            (bx0, bx1), (by0, by1), (bz0, bz1) = b.bounds()
            if ax1 < bx0 or bx1 < ax0 or ay1 < by0 or by1 < ay0 or az1 < bz0 or bz1 < az0:
                continue
            if a.spec.get("overlap_ok") or b.spec.get("overlap_ok"):
                continue
            n = len(vox[a.name] & vox[b.name])
            if n:
                pairs.append((a.name, b.name, n))
    hidden = []
    for i, b in enumerate(shape.boxes):
        if b.spec.get("overlap_ok"):
            continue
        own = sum(1 for v in vox[b.name] if region.get(v) == f"box{i}")
        if vox[b.name] and own == 0:
            hidden.append(b.name)
        elif not vox[b.name]:
            hidden.append(b.name + " (too small to make any block)")
    return pairs, hidden
