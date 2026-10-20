"""Measure how a vehicle is built and compare it with reference builds.

The numbers describe construction habits: slope piece sizes, pyramid pairing, ballast,
sub-bodies, detail parts and paint. A value outside the references' range is a prompt to
look closer, not a defect: references differ in size and purpose, and a handful of them
gives a range, not a distribution.
"""
import statistics
from collections import Counter, deque

from . import definitions
from .land import road_wheel
from .part_policy import PREBUILT_ENGINES
from .pieces import BY_NAME, DIRS
from .reference import read_bodies

KINDS = ("boat", "land", "other")
# Inventory order in the game's part menu; a definition's `category` indexes it.
CATEGORIES = ("blocks", "vehicle_control", "mechanics", "propulsion", "specialist", "logic",
              "displays", "sensors", "decorative", "fluid", "electric", "jet_engines", "weapons",
              "modular_engines", "industry", "windows")
SLOPE_SIZE = {"02_wedge": "1x1", "03_pyramid": "1x1", "04_invpyramid": "1x1",
              "05_wedge_2": "1x2", "06_pyramid_2": "1x2", "07_invpyramid_2": "1x2",
              "11_pyramid_2x2": "2x2", "14_invpyramid_2x2": "2x2",
              "08_wedge_4": "1x4", "09_pyramid_4": "1x4", "10_invpyramid_4": "1x4",
              "12_pyramid_2x4": "2x4", "15_invpyramid_2x4": "2x4",
              "13_pyramid_4x4": "4x4", "16_invpyramid_4x4": "4x4"}
PYRAMIDS = {"03_pyramid", "06_pyramid_2", "09_pyramid_4", "11_pyramid_2x2", "12_pyramid_2x4", "13_pyramid_4x4"}
INVERSE = {"04_invpyramid", "07_invpyramid_2", "10_invpyramid_4", "14_invpyramid_2x2",
           "15_invpyramid_2x4", "16_invpyramid_4x4"}
WEIGHT = "01_block_weight"
# Parts experienced builders also use as sub-block geometry. Pipes and door parts can be
# working parts too; pipes are split by whether they reach equipment.
DETAIL = {"pipes": ("trans_",), "plates": ("sign",), "door_parts": ("door_panel", "door_frame"),
          "rails": ("connector_slider_track", "linear_compact_module", "linear_module", "railing"),
          "handles": ("handle",)}
MARINE = ("propeller", "large_propeller", "rudder", "water_jet")
JOINTS = {"pivot": ("pivot",), "hinge": ("hinge",), "slider": ("connector_slider",),
          "piston": ("piston", "linear_base", "linear_compact_base", "linear_matic"),
          "connector": ("connector_hardpoint", "connector_electric", "connector_water",
                        "connector_small", "connector_large", "connector_torque")}

# Size-independent metrics compared against references; counts are reported but not scored.
SCORED = {
    "component_share": ("Share of parts that are components, not blocks or slopes",
                        "Add equipment and detail parts; references spend part budget beyond plain blocks.",
                        "Most of the part budget is components; check the bodywork is complete."),
    "slope_share": ("Share of structural parts that are slopes",
                    "Smooth more edges with slopes.", "Many slopes; check flat panels stay flat."),
    "slope_small_share": ("Share of slopes that are 1x1 pieces",
                          "Use 1x1 wedges and 1x1 pyramid/inverse pairs at corners, edges and short runs.",
                          "Mostly 1x1 slopes; long smooth runs may suit 1x2 or 1x4 pieces."),
    "slope_large_share": ("Share of slopes that are 1x4, 2x4 or 4x4 pieces",
                          "Long shallow runs can use 1x4 pieces.",
                          "Too many long slopes: keep 1x4 for long smooth runs, use 1x1/1x2 elsewhere."),
    "pyramid_paired_share": ("Share of pyramids touching an inverse pyramid",
                             "Pyramids sit alone against blocks; pair each with an inverse pyramid to continue the face.",
                             None),
    "ballast_per_1k": ("Weight blocks per 1,000 structural cells",
                       "Add weight blocks low in the hull for ballast and trim.",
                       "Heavy ballast; check the vehicle still floats with freeboard."),
    "ballast_height": ("Median weight-block height, as a fraction of the main body's height",
                       None, "Ballast sits high; move it to the bottom of the hull."),
    "detail_per_1k": ("Detail parts (pipes, signs, door parts, rails, handles) per 1,000 structural cells",
                      "Add railings, sign plates, handles and trim along deck edges and superstructure.",
                      None),
    "decor_pipes_per_1k": ("Pipes not reaching equipment (estimated decoration) per 1,000 structural cells",
                           "References use a few unconnected pipes as rods and rigging.", None),
    "plates_per_1k": ("Paintable signs per 1,000 structural cells",
                      "Use paintable signs as thin plates and panel detail.", None),
    "paint_variants_per_1k": ("Distinct block paint patterns per 1,000 structural cells",
                              "Paint is plain; add bands, panel lines and per-face colour.", None),
    "multi_colour_share": ("Share of structural parts painted with more than one colour",
                           "Paint faces individually where colours meet.", None),
    "logic_per_1k_parts": ("Microprocessors per 1,000 parts",
                           "References run their systems through microprocessors.", None),
}


def structural(d):
    return d in BY_NAME or d.startswith("01_block")


def _family(d):
    return next((name for name, prefixes in DETAIL.items() if d.startswith(prefixes)), None)


def _category(d):
    try:
        index = int((definitions.metadata(d) or {}).get("properties", {}).get("category", "-1"))
    except ValueError:
        index = -1
    return CATEGORIES[index] if 0 <= index < len(CATEGORIES) else "unknown"


def _ratio(n, d, per=1):
    return round(n * per / d, 4) if d else None


def _neighbours(cell):
    return [(cell[0] + d[0], cell[1] + d[1], cell[2] + d[2]) for d in DIRS]


def _body_cells(body):
    owner, cells_of = {}, {}
    for p in body["parts"]:
        cells = p.voxels()
        cells_of[p.uid] = cells
        for c in cells:
            owner[tuple(c)] = p
    return owner, cells_of


def _pipe_groups(body, owner, cells_of, name):
    """Pipe parts split by whether their connected run touches equipment.

    Adjacency stands in for real pipe openings, so this is an estimate: a decorative rail
    resting against a light counts as working, and a sealed run inside equipment as decor.
    """
    pipes = {p.uid: p for p in body["parts"] if _family(name[p.uid]) == "pipes"}
    seen, working, decor = set(), 0, 0
    for uid in pipes:
        if uid in seen:
            continue
        group, queue, touches = [], deque([uid]), False
        seen.add(uid)
        while queue:
            current = queue.popleft()
            group.append(current)
            for cell in cells_of[current]:
                for n in _neighbours(tuple(cell)):
                    other = owner.get(n)
                    if other is None or other.uid == current:
                        continue
                    if other.uid in pipes:
                        if other.uid not in seen:
                            seen.add(other.uid)
                            queue.append(other.uid)
                    elif not structural(name[other.uid]) and _family(name[other.uid]) is None:
                        touches = True
        working += len(group) if touches else 0
        decor += 0 if touches else len(group)
    return working, decor


def _paint(body, name):
    variants, colours, multi = set(), set(), 0
    for p in body["parts"]:
        if not structural(name[p.uid]):
            continue
        sc = body["details"][p.uid]["settings"].get("sc", "")
        variants.add(sc)
        faces = {c.upper() for c in sc.split(",")[1:] if len(c) == 6}
        colours |= faces
        multi += len(faces) > 1
    return variants, colours, multi


def detect_kind(counts):
    wheels = sum(n for d, n in counts.items() if road_wheel(d) or d.startswith("wheel_tank"))
    marine = any(d.startswith(MARINE) for d in counts)
    return "land" if wheels >= 3 and not marine else "boat"


def study_text(text, kind=None):
    """Construction metrics for one saved vehicle (every body)."""
    _, bodies, _ = read_bodies(text, tolerate_transforms=True)
    parts = [p for b in bodies for p in b["parts"]]
    if not parts:
        raise ValueError("vehicle has no readable parts")
    # The saved definition: parts without an installed definition read back as plain blocks.
    name = {p.uid: b["details"][p.uid]["definition"] for b in bodies for p in b["parts"]}
    counts = Counter(name[p.uid] for p in parts)
    if kind is not None and kind not in KINDS:
        raise ValueError(f"kind must be one of {', '.join(KINDS)}")
    kind = kind or detect_kind(counts)

    struct = sum(n for d, n in counts.items() if structural(d))
    slopes = {d: n for d, n in counts.items() if d in SLOPE_SIZE}
    slope_total = sum(slopes.values())
    sizes = Counter()
    for d, n in slopes.items():
        sizes[SLOPE_SIZE[d]] += n

    paired = pyramids = 0
    working_pipes = decor_pipes = 0
    variants, colours, multi = set(), set(), 0
    for body in bodies:
        owner, cells_of = _body_cells(body)
        inverse_cells = {c for c, p in owner.items() if name[p.uid] in INVERSE}
        for p in body["parts"]:
            if name[p.uid] in PYRAMIDS:
                pyramids += 1
                own = {tuple(c) for c in cells_of[p.uid]}
                paired += any(n in inverse_cells and n not in own
                              for c in own for n in _neighbours(c))
        working, decor = _pipe_groups(body, owner, cells_of, name)
        working_pipes += working
        decor_pipes += decor
        v, c, m = _paint(body, name)
        variants |= v
        colours |= c
        multi += m

    main = max(bodies, key=lambda b: len(b["parts"]))
    heights = [p.origin[1] for p in main["parts"] if structural(name[p.uid])]
    weights = [p.origin[1] for p in main["parts"] if name[p.uid] == WEIGHT]
    lo, hi = (min(heights), max(heights)) if heights else (0, 0)
    ballast_height = (round(statistics.median((y - lo) / (hi - lo) for y in weights), 3)
                      if weights and hi > lo else None)

    detail = Counter()
    for d, n in counts.items():
        if (family := _family(d)) is not None:
            detail[family] += n
    categories = Counter()
    for d, n in counts.items():
        if not structural(d):
            categories[_category(d)] += n
    joints = Counter()
    for d, n in counts.items():
        for name, fragments in JOINTS.items():
            if any(f in d for f in fragments):
                joints[name] += n
                break
    modular = sum(n for d, n in counts.items() if d.startswith("modular_engine") and "gearbox" not in d)

    metrics = {
        "component_share": _ratio(len(parts) - struct, len(parts)),
        "slope_share": _ratio(slope_total, struct),
        "slope_small_share": _ratio(sizes["1x1"], slope_total),
        "slope_large_share": _ratio(sizes["1x4"] + sizes["2x4"] + sizes["4x4"], slope_total),
        "pyramid_paired_share": _ratio(paired, pyramids),
        "ballast_per_1k": _ratio(counts.get(WEIGHT, 0), struct, 1000),
        "ballast_height": ballast_height,
        "detail_per_1k": _ratio(sum(detail.values()), struct, 1000),
        "decor_pipes_per_1k": _ratio(decor_pipes, struct, 1000),
        "plates_per_1k": _ratio(detail["plates"], struct, 1000),
        "paint_variants_per_1k": _ratio(len(variants), struct, 1000),
        "multi_colour_share": _ratio(multi, struct),
        "logic_per_1k_parts": _ratio(counts.get("microprocessor", 0), len(parts), 1000),
    }
    return {
        "kind": kind,
        "metrics": metrics,
        "counts": {
            "parts": len(parts), "structural": struct, "components": len(parts) - struct,
            "bodies": len(bodies), "largest_bodies": sorted((len(b["parts"]) for b in bodies), reverse=True)[:8],
            "slopes_by_size": dict(sizes.most_common()), "slopes": dict(Counter(slopes).most_common()),
            "pyramids": pyramids, "weight_blocks": counts.get(WEIGHT, 0),
            "detail": dict(detail.most_common()),
            "pipes_reaching_equipment": working_pipes, "pipes_decorative_estimate": decor_pipes,
            "paint_colours": len(colours), "joints": dict(joints.most_common()),
            "component_categories": dict(categories.most_common()),
            "microprocessors": counts.get("microprocessor", 0), "modular_engine_parts": modular,
            "prebuilt_engines": sum(n for d, n in counts.items() if d in PREBUILT_ENGINES),
            "road_wheels": sum(n for d, n in counts.items() if road_wheel(d)),
        },
        "top_components": [[d, n] for d, n in counts.most_common() if not structural(d)][:15],
    }


def ranges(studies, kind):
    """Per-metric min/median/max over the references of one kind."""
    same = [s for s in studies if s["kind"] == kind]
    out = {}
    for metric in SCORED:
        values = [s["metrics"][metric] for s in same if s["metrics"].get(metric) is not None]
        if values:
            out[metric] = {"min": min(values), "median": round(statistics.median(values), 4),
                           "max": max(values), "references": len(values)}
    return out


def scorecard(study, references, kind=None):
    """Compare one study with reference studies of the same kind."""
    kind = kind or study["kind"]
    bounds = ranges(references, kind)
    if not bounds:
        kinds = sorted({s["kind"] for s in references})
        raise ValueError(f"no references of kind {kind!r} (the set has {', '.join(kinds) or 'none'}); "
                         "pass kind explicitly or study references of this kind")
    rows, within = [], 0
    for metric, (label, low_hint, high_hint) in SCORED.items():
        value, bound = study["metrics"].get(metric), bounds.get(metric)
        if bound is None:
            continue
        if value is None:
            status, hint = "not_applicable", None
        elif value < bound["min"]:
            status, hint = "below", low_hint
        elif value > bound["max"]:
            status, hint = "above", high_hint
        else:
            status, hint = "within", None
        within += status == "within"
        rows.append({"metric": metric, "label": label, "value": value, "status": status,
                     "reference_min": bound["min"], "reference_median": bound["median"],
                     "reference_max": bound["max"], **({"hint": hint} if hint else {})})
    scored = sum(r["status"] != "not_applicable" for r in rows)
    return {"kind": kind, "within": within, "scored": scored,
            "summary": f"{within} of {scored} construction metrics are inside the {kind} reference range",
            "metrics": rows,
            "note": "Ranges come from a few hand-picked builds of different sizes; read a miss as "
                    "where to look, then check the vehicle itself."}
