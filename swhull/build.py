"""Spec -> finished pieces + a human-readable summary."""
import hashlib
import json
import math
import os
import tempfile
from collections import Counter

from .benches import fit_lines, parse_bench, reach
from .hull import (DEFAULT_SPEC, LIMITS, VOX, box_report, build_solid, game_units, merge, scale_factor,
                   validate)
from .interior import plan_interior
from .paint import paint_map
from .pieces import DIRS, add
from .presets import PRESETS
from .smooth import SAMPLES, shell, to_pieces
from .vehicle import SPAWN_LIMIT, centre



def resolve_spec(spec=None, preset=None, base=None, patch=None):
    """Full spec: defaults <- preset <- base (a saved design's spec) <- spec <- patch ops."""
    for label, value in (("spec", spec), ("base", base)):
        if value is not None and not isinstance(value, dict):
            raise ValueError(f"{label} must be a JSON object")
    full = DEFAULT_SPEC
    if preset:
        if preset not in PRESETS:
            raise ValueError(f"unknown preset {preset!r}; choose from {', '.join(PRESETS)}")
        full = merge(full, PRESETS[preset]["spec"])
    if base:
        full = merge(full, base)
    full = merge(full, spec or {})
    if patch:
        full = apply_patch(full, patch)
    validate(full)
    return full


def _step(container, seg, path):
    """Index into a dict or list. List segments: an index, or the `name` of an item."""
    if isinstance(container, dict):
        if seg not in container:
            raise ValueError(f"patch path {path}: no key '{seg}'")
        return seg
    if isinstance(container, list):
        if seg.lstrip("-").isdigit():
            i = int(seg)
            if not -len(container) <= i < len(container):
                raise ValueError(f"patch path {path}: index {i} is out of range (list has {len(container)})")
            return i % len(container)
        for i, item in enumerate(container):
            if isinstance(item, dict) and item.get("name") == seg:
                return i
        raise ValueError(f"patch path {path}: no item named '{seg}'")
    raise ValueError(f"patch path {path}: '{seg}' is inside a value, not an object or list")


def apply_patch(spec, ops):
    """JSON-Patch style edits: [{"op": "replace"|"add"|"remove", "path": "/a/b", "value": ...}].

    List items can be addressed by index or by `name` ("/superstructure/funnel_fwd/height");
    "-" appends ("/superstructure/-"). `replace` on an object creates a missing key.
    """
    if not isinstance(ops, list):
        raise ValueError("patch must be a list of {op, path, value} objects")
    out = merge({}, spec)
    for op in ops:
        if not isinstance(op, dict) or not isinstance(op.get("path"), str):
            raise ValueError('each patch op needs a string path, e.g. {"op": "replace", '
                             '"path": "/superstructure/bridge/height", "value": 2.5}')
        kind, path = op.get("op", "replace"), op["path"]
        segs = [g.replace("~1", "/").replace("~0", "~") for g in path.strip("/").split("/")]
        if not path.strip("/"):
            raise ValueError("patch path must name something inside the spec")
        node = out
        for seg in segs[:-1]:
            node = node[_step(node, seg, path)]
        last = segs[-1]
        if kind in ("replace", "add"):
            if "value" not in op:
                raise ValueError(f"patch {kind} {path} needs a value")
            if isinstance(node, list):
                if last == "-":
                    node.append(op["value"])
                elif kind == "add" and last.isdigit():
                    node.insert(min(int(last), len(node)), op["value"])
                else:
                    node[_step(node, last, path)] = op["value"]
            elif isinstance(node, dict):
                node[last] = op["value"]
            else:
                raise ValueError(f"patch path {path}: parent is not an object or list")
        elif kind == "remove":
            del node[_step(node, last, path)]
        else:
            raise ValueError(f"patch op must be replace, add or remove (got {kind!r})")
    return out


def _fit_cache_path():
    return os.path.join(tempfile.gettempdir(), "stormworks-hull-mcp-fit.json")


def _extent(spec, s):
    """Blocks from the centre the finished vehicle reaches on each axis at scale s."""
    game = game_units(merge(spec, {"scale": s, "interior": None, "paint": []}))
    _, solid, _ = build_solid(game)
    lo = [min(v[i] for v in solid) for i in range(3)]
    hi = [max(v[i] for v in solid) for i in range(3)]
    pad = 1 if spec.get("smoothing") in ("wedges", "wedges_v2") else 0
    return [max(hi[i] - (lo[i] + hi[i]) // 2, (lo[i] + hi[i]) // 2 - lo[i]) + pad for i in range(3)]


def fit_scale(spec):
    """Largest scale (4 decimals) at which the design fits its `bench`, counting everything
    outside the hull line (bulb, masts, barrels). Cached on disk by spec."""
    key = hashlib.sha1(json.dumps(merge(spec, {"interior": None, "paint": []}), sort_keys=True,
                                  default=str).encode()).hexdigest()
    try:
        with open(_fit_cache_path(), encoding="utf-8") as f:
            cache = json.load(f)
    except (OSError, ValueError):
        cache = {}
    if key in cache:
        return cache[key]
    r = reach(parse_bench(spec["bench"])[1])
    s = 40.0 / spec["length"]                       # cheap trial build about 40 m long
    e = _extent(spec, s)
    s = min(10.0, s * min(r[i] / max(e[i], 1) for i in range(3)))
    for _ in range(12):                             # voxel rounding: shrink until it really fits
        s = int(s * 10000) / 10000
        e = _extent(spec, s)
        if all(e[i] <= r[i] for i in range(3)):
            break
        s *= min(0.996, *(r[i] / e[i] for i in range(3)))
    else:
        raise ValueError("could not find a scale that fits the bench; set `scale` by hand")
    cache[key] = s
    try:
        with open(_fit_cache_path(), "w", encoding="utf-8") as f:
            json.dump(dict(list(cache.items())[-200:]), f)
    except OSError:
        pass
    return s


def fitted(spec):
    """The spec with `scale: "fit"` replaced by the fitted number (unchanged otherwise)."""
    if spec.get("scale") != "fit":
        return spec
    out = merge({}, spec)
    out["scale"] = fit_scale(spec)
    length = spec["length"] * out["scale"]
    lo, hi = LIMITS["length"]
    if not lo <= length <= hi:
        raise ValueError(f"at the fitted scale {out['scale']:g} the hull is {length:.1f} m long; "
                         f"hulls must be {lo}-{hi} m")
    return out


def _build_base(spec):
    scale_fit = spec.get("scale") == "fit"
    spec = fitted(spec)
    scale = scale_factor(spec)
    spec = game_units(spec)
    shape, solid, region = build_solid(spec)
    form = shape.form
    colors = spec["colors"]
    waterline = colors.get("waterline")
    wl = (waterline * VOX) if waterline is not None else form.depth * 0.45
    stripe = colors.get("stripe_height", 0.25) * VOX
    boxes = shape.boxes
    warnings = list(shape.warnings)
    painted = paint_map(spec, solid, warnings)

    probe = ((0, 0, 0), (0, -1, 0), (1, 0, 0), (-1, 0, 0), (0, 0, 1), (0, 0, -1), (0, 1, 0))
    box_index = {id(b): i for i, b in enumerate(boxes)}
    outside_tags = {}

    def region_at(p):
        if shape.in_hull(*p):
            return "hull"
        for b in shape.boxes_near(tuple(math.floor(c + 0.5) for c in p)):
            if b.inside(*p):
                return f"box{box_index[id(b)]}"
        return None

    def tag_of(v):
        tag = region.get(v)
        if tag is not None:
            return tag
        tag = outside_tags.get(v)
        if tag is None:
            # slope piece placed just outside the solid: the part of the design that reaches
            # into this voxel, else the neighbour it rests on (a sheer ramp beside a deckhouse
            # is deck, not deckhouse)
            for d in probe:
                tag = region_at(tuple(v[i] + 0.4 * d[i] for i in range(3)))
                if tag:
                    break
            else:
                for d in probe[1:]:
                    tag = region.get(add(v, d))
                    if tag:
                        break
            tag = outside_tags[v] = tag or "hull"
        return tag

    def color_of(v):
        if v in painted:
            return painted[v]
        tag = tag_of(v)
        if tag != "hull":
            b = boxes[int(tag[3:])]
            box = b.spec
            band = box.get("band")
            if band:   # from the box's own bottom, even where the hull or another box covers it
                y = (v[1] - b.y0 + 0.5) / VOX
                if band.get("from", 0) <= y <= band.get("to", 0):
                    return band.get("color", "1F2A36")
            return box.get("color", colors["topsides"])
        up = (v[0], v[1] + 1, v[2])
        if up not in solid and v[1] + 0.5 >= form.deck(form.s(v[2])) - 1.5:
            return colors["deck"]
        yc = v[1] + 0.5
        if yc < wl:
            return colors["bottom"]
        if yc < wl + stripe:
            return colors["stripe"]
        return colors["topsides"]

    skin = shell(solid)
    interior = plan_interior(spec, shape, solid, region, skin)
    smoothing_report = {}
    placed = to_pieces(solid, color_of, inside=lambda p: shape.contains(*p),
                       sample_mask=lambda v: shape.sample_mask(v, SAMPLES),
                       smoothing=spec["smoothing"], open_deck=spec["deck"] == "open",
                       region=region, skin=skin, extra=interior.blocks, carve=interior.carve,
                       fixed={add(v, d) for v in painted for d in DIRS} | set(painted),
                       diagnostics=smoothing_report)
    # hull skin that never faces the outside is the inner surface (cockpit floor, bilge)
    for p in placed:
        if p.origin in interior.blocks:
            continue
        if tag_of(p.origin) == "hull" and not any(
                add(v, d) not in solid for v in p.voxels() for d in DIRS):
            p.color = colors["deck"]
    placed += interior.components
    before = placed[0].origin
    placed = centre(placed)
    after = placed[0].origin
    overlaps, hidden = box_report(shape, region)
    warnings += [f"box '{name}' is completely inside the hull or earlier boxes" for name in hidden]
    shift = tuple(before[i] - after[i] for i in range(3))
    warnings += _loose_parts(placed, region, shape, shift)
    info = {"form": form, "shape": shape, "spec": spec, "region": region, "scale": scale,
            "scale_fit": scale_fit,
            "smoothing_report": smoothing_report,
            "solid_voxels": len(solid), "interior": interior, "warnings": warnings,
            "overlaps": overlaps, "shift": shift}
    return placed, info


def build(spec):
    """Reuse procedural geometry, then apply fixed-frame overlays before centring."""
    from . import cache  # noqa: PLC0415 - cache reconstructs interior objects
    from .editing import apply_edits, identify  # noqa: PLC0415
    from .components import place  # noqa: PLC0415
    from .tanks import place as place_tanks, verify as verify_tanks  # noqa: PLC0415
    base = {k: v for k, v in spec.items() if k not in ("edits", "components", "fitout", "tanks")}
    if (spec.get("fitout") or {}).get("stage") in ("access", "propulsion", "tanks"):
        interior = merge({}, base.get("interior") or {})
        interior["door_parts"] = True
        for h in interior.get("hatches", []):
            h["assemble"] = True
        base = merge(base, {"interior": interior})
    enabled = os.environ.get("SW_BUILD_CACHE", "1") != "0"
    cache_key = cache.key(base) if enabled else None
    result = cache.read(cache_key) if enabled else None
    if result is None:
        result = _build_base(base)
        result[1]["cache_hit"] = False
        if enabled:
            cache.write(cache_key, *result)
    placed, info = result
    shift = info["shift"]
    for p in placed:
        p.origin = add(p.origin, shift)
    identify(placed)
    if spec.get("tanks"):
        placed = place_tanks(placed, info, spec)
    if spec.get("components") or spec.get("fitout"):
        placed = place(placed, info, spec)
    if spec.get("edits"):
        placed = apply_edits(placed, spec["edits"], reserved=info["interior"].reserved)
    if spec.get("tanks"):
        verify_tanks(placed, info)
    before = placed[0].origin
    centre(placed)
    info["shift"] = tuple(before[i] - placed[0].origin[i] for i in range(3))
    if spec.get("edits") or spec.get("components") or spec.get("fitout") or spec.get("tanks"):
        info["warnings"] = [w for w in info["warnings"] if not w.startswith(("loose part", "... and"))]
        info["warnings"] += _loose_parts(placed, info["region"], info["shape"], info["shift"])
    return placed, info


def _loose_parts(placed, region, shape, shift):
    """Warnings for groups of parts not face-connected to the main body: the game splits them
    off as separate bodies on spawn, so they fall away."""
    owner = {}
    for i, p in enumerate(placed):
        for v in p.voxels():
            owner[v] = i
    seen, groups = set(), []
    for start in owner:
        if start in seen:
            continue
        seen.add(start)
        stack, group = [start], []
        while stack:
            v = stack.pop()
            group.append(v)
            for d in DIRS:
                n = add(v, d)
                if n in owner and n not in seen:
                    seen.add(n)
                    stack.append(n)
        groups.append(group)
    if len(groups) < 2:
        return []
    groups.sort(key=len, reverse=True)
    out = []
    for g in groups[1:9]:
        tags = {region.get(add(v, shift)) for v in g} - {None}
        names = sorted(shape.boxes[int(t[3:])].name if t.startswith("box") else t for t in tags)
        z = sum(v[2] + shift[2] + 0.5 for v in g) / len(g) / VOX
        y = min(v[1] + shift[1] for v in g) / VOX
        what = ", ".join(names) or "unknown"
        out.append(f"loose part ({len(g)} blocks of {what}) at {z:.1f} m from the stern, {y:.1f} m "
                   "up, is not attached to the rest: it falls off on spawn. Move it to touch a face.")
    if len(groups) > 9:
        out.append(f"... and {len(groups) - 9} more loose parts")
    return out


def spawn_limit_lines(placed, info):
    """Warn when the vehicle has more parts than the game spawns."""
    n = len(placed)
    if n <= SPAWN_LIMIT:
        return [f"Parts vs spawn limit: {n} of {SPAWN_LIMIT} ({n * 100 // SPAWN_LIMIT}%)."]
    cut = placed[SPAWN_LIMIT].origin[2] + info["shift"][2]
    return [f"! {n} parts is over the {SPAWN_LIMIT} the game spawns: in game everything from about "
            f"{(cut + 0.5) / VOX:.1f} m from the stern forward is missing after spawn, and the open hull "
            f"sinks. Cut {n - SPAWN_LIMIT} parts: fewer or simpler rooms, a smaller scale, or fewer "
            "superstructure blocks. (Parts are written stern first; the editor still shows them all.)"]


def deck_profile(spec, step=1.0):
    """Deck height table along the hull, in spec units (real-world metres when `scale` is set)."""
    spec = fitted(spec)
    s = scale_factor(spec)
    game = game_units(spec)
    shape, _, _ = build_solid(merge(game, {"superstructure": [], "skegs": [], "paint": [],
                                           "bow": {"bulb": None}}))
    form = shape.form
    step = max(0.25, float(step))
    unit = "m" if s == 1 else f"m in spec units (scale {s:g}; multiply by {s:g} for game metres)"
    lines = [f"Deck profile every {step:g} {unit}.",
             "deck: deck surface above the keel. box y: where a 1-block-long box sits when `y` is "
             "left out (a longer box sits at the lowest 'box y' under it). half-beam: deck edge to "
             "centreline.",
             "     z  |   deck | box y  | half-beam"]
    n = int(spec["length"] / step + 1e-9)
    for k in range(n + 1):
        z = min(k * step, spec["length"])
        zv = min(max(round(z * s * VOX), 0), form.L - 1)
        d = form.deck(form.s(zv))
        hw = shape.hull_half_width(int(d) - 1, zv)
        lines.append(f"  {z:6.2f} | {d / VOX / s:6.2f} | {int(d) / VOX / s:6.2f} | "
                     f"{max(0.0, hw) / VOX / s:6.2f}")
    return "\n".join(lines)


def summary(spec, placed, info):
    form = info["form"]
    s = info.get("scale", 1.0)
    spec = info.get("spec", spec)
    vox = [v for p in placed for v in p.voxels()]
    lo = [min(v[i] for v in vox) for i in range(3)]
    hi = [max(v[i] for v in vox) for i in range(3)]
    size = [hi[i] - lo[i] + 1 for i in range(3)]
    counts = Counter(p.piece.d for p in placed)
    mass = sum(p.piece.mass for p in placed)
    lines = [
        f"Overall: {size[2] / VOX:.2f} m long x {size[0] / VOX:.2f} m wide x {size[1] / VOX:.2f} m tall "
        f"({size[2]} x {size[0]} x {size[1]} voxels, L x W x H)",
        f"Parts: {len(placed)}  ({', '.join(f'{k} {v}' for k, v in counts.most_common())})",
        f"Mass (definition units): {mass:.0f}",
        "Deck height above keel (m) at stern / midship / bow: "
        + " / ".join(f"{form.deck(s) / VOX:.2f}" for s in (0.0, 0.5, 1.0)),
        "Superstructure 'z' is metres from the transom; hull length is "
        f"{spec['length']:.2f} m" + (f" in game, {spec['length'] / s:.2f} m in spec units at scale "
                                     f"{s:g}" + (" (fitted to the bench)" if info.get("scale_fit") else "")
                                     + ". Reports are in game metres." if s != 1 else "."),
        "Deck height at every metre: deck_profile.",
    ]
    fit = info.get("smoothing_report")
    if fit:
        old, new = fit["original"], fit["refined"]
        lines.append(f"V2 smoothing selected {fit['selected']} fit; mismatched partial joints "
                     f"{old['mismatched_joints']} original / {new['mismatched_joints']} refined. "
                     "Shape-error guard: " + fit["shape_error_allowance"] + ".")
        corners = fit.get("corners")
        if corners and corners["replacements"]:
            lines.append(f"Corner closeouts: {corners['replacements']} local replacements; final "
                         f"mismatched partial joints {corners['after']['mismatched_joints']}. "
                         "Neither sampled shape error nor joint count increased.")
    if spec.get("deck") == "open":
        floors = (spec.get("interior") or {}).get("decks") or []
        if floors:
            floor = max(floors)
            drops = [form.deck(s) / VOX - floor for s in (0.0, 0.5, 1.0)]
            lines.append(f"Open-deck walking floor requested at {floor:.2f} m above keel; "
                         "drop from rim at stern / midship / bow: "
                         + " / ".join(f"{h:.2f}" for h in drops) + " m. "
                         "Use analyze_hull to check actual support and floor surfaces.")
        else:
            lines.append("Open deck: no interior.decks walking floor specified; the visible "
                         "floor follows the bottom skin. Set its height above keel separately "
                         "from hull depth; check analyze_hull before saving.")
    overlaps = info.get("overlaps") or []
    if overlaps:
        lines.append(f"Overlapping superstructure ({len(overlaps)} pairs; the earlier box in the list "
                     "owns shared blocks, check each is intended):")
        lines += [f"  - {a} & {b}: {n} blocks" for a, b, n in overlaps[:25]]
        if len(overlaps) > 25:
            lines.append(f"  ... and {len(overlaps) - 25} more")
    lines += [f"! {w}" for w in info.get("warnings") or []]
    lines += ["Components: " + row for row in info.get("components", [])]
    lines += [f"Tank {t['name']}: {t['usable_litres']:.1f} geometric litres, {t['fluid']}, "
              f"{t['fill'] * 100:g}% fill; {t['status']}. External pipe connections are user work."
              for t in info.get("tank_validation", [])]
    lines.append("Procedural geometry: " + ("cache reused." if info.get("cache_hit") else "rebuilt."))
    lines += spawn_limit_lines(placed, info)
    lines += interior_summary(info)
    lines += fit_lines(spec.get("bench"), lo, hi)
    return "\n".join(lines)


def interior_summary(info):
    plan = info.get("interior")
    if plan is None or not (plan.rooms or plan.warnings):
        return []
    lines = ["Interior:"]
    for r in plan.rooms:
        if not r.air:
            lines.append(f"  ! {r.name}: no usable room air after access construction")
            continue
        ys = [v[1] for v in r.air]
        xs = [v[0] for v in r.air]
        zs = [v[2] for v in r.air]
        clear_h = (max(ys) - min(ys) + 1) / VOX
        extra = []
        if r.doors:
            extra.append("doors " + ", ".join(r.doors))
        if r.engines:
            extra.append("engines " + ", ".join(r.engines))
        floor_y = min(ys)
        low = [v[0] for v in r.air if v[1] == floor_y]
        floor_w = (max(low) - min(low) + 1) / VOX
        lines.append(f"  - {r.name} ({r.kind}): floor {r.ylo / VOX:.2f} m, clear "
                     f"{(max(zs) - min(zs) + 1) / VOX:.2f} L x {(max(xs) - min(xs) + 1) / VOX:.2f} W "
                     f"(floor {floor_w:.2f} W) x "
                     f"{clear_h:.2f} H m" + ("; " + "; ".join(extra) if extra else "")
                     + (" (under 2 m headroom)" if clear_h < 2.0 else ""))
    lines += [f"  ! {w}" for w in plan.warnings]
    return lines
