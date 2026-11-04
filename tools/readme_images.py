"""Render the README screenshots into docs/images (or another folder).

    uv run tools/readme_images.py [out_dir] [image ...]

Every image is a render of something the server builds, lit the way previews are. Run it after
a change that alters how vehicles look, then look at each PNG before committing it. The Humvee,
engine and diagnostics images need the game's part definitions.
"""
import io
import math
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

from swhull.build import build, resolve_spec  # noqa: E402
from swhull.pieces import BY_NAME  # noqa: E402
from swhull.render import LABEL, _camera, _draw_view, _scene, design_ruler, render_interior, render_png  # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), "..")


def shot(placed, yaw=35.0, pitch=22.0, w=1200, h=700, zoom=1.0, focus=None):
    """One lit view with no caption. yaw/pitch/zoom/focus work like inspect_view."""
    faces, lit = _scene(placed, None, "closed")
    yr, pr = math.radians(yaw), math.radians(pitch)
    cam = _camera((math.cos(pr) * math.cos(yr), -math.sin(pr), -math.cos(pr) * math.sin(yr)))
    target = None
    if focus is not None:
        pts = [q for pts, _, _, _ in faces for q in pts]
        lo = [min(q[i] for q in pts) for i in range(3)]
        hi = [max(q[i] for q in pts) for i in range(3)]
        f = [1 - focus[0], focus[1], focus[2]]
        target = tuple(lo[i] + (hi[i] - lo[i]) * f[i] for i in range(3))
    img, _ = _draw_view(faces, cam, w, h, "", zoom=zoom, focus=target, lit=lit)
    return img


def font(size):
    return ImageFont.load_default(size=size)


def caption(img, text, size=22):
    dr = ImageDraw.Draw(img)
    dr.text((16, 12), text, fill=LABEL, font=font(size))
    return img


def sheet(tiles, cols, gap=4):
    """Tiles of equal size in a grid, separated by thin lines."""
    w, h = tiles[0].size
    rows = (len(tiles) + cols - 1) // cols
    out = Image.new("RGB", (cols * w + (cols - 1) * gap, rows * h + (rows - 1) * gap), (24, 29, 37))
    for i, t in enumerate(tiles):
        out.paste(t, ((i % cols) * (w + gap), (i // cols) * (h + gap)))
    return out


def hull(spec=None, preset=None):
    placed, info = build(resolve_spec(spec or {}, preset=preset))
    return placed, info


# A 32 m coast guard cutter designed for the README: hull, stacked deckhouse and bridge, funnel,
# lattice mast and a livery with a hull number.
CUTTER = {
    "length": 32.0, "beam": 6.5, "depth": 3.25, "bench": "L",
    "bow": {"entry": 0.42, "fullness": 1.3, "rake": 2.0, "rake_curve": 1.5, "flare": 0.1, "deadrise": 40},
    "stern": {"run": 0.03, "transom_width": 0.9},
    "sheer": {"bow": 1.0, "stern": 0.1},
    "section": {"deadrise": 14, "bilge_radius": 0.5, "flare": 0.0, "keel_width": 0.25},
    "livery": {"name": "coast_guard", "number": "47"},
    "superstructure": [
        {"name": "deckhouse", "z": 10.0, "length": 10.5, "width": 5.0, "height": 2.5,
         "band": {"from": 1.25, "to": 1.75, "color": "1A2530"}},
        {"name": "bridge", "on": "deckhouse", "z": 14.5, "length": 5.5, "width": 4.75, "height": 2.25,
         "rake_front": 0.6, "band": {"from": 1.0, "to": 1.75, "color": "1A2530"}},
        {"name": "funnel", "on": "deckhouse", "z": 11.0, "length": 2.25, "width": 2.0, "height": 2.0,
         "rake_back": 0.25, "rake_front": 0.25},
        # not named "mast": the livery would cap it in black like a funnel
        {"name": "tower", "on": "bridge", "z": 16.0, "length": 1.0, "width": 1.0, "height": 3.5,
         "shape": "lattice"},
        {"name": "yard", "y": "tower-1", "z": 16.25, "length": 0.5, "width": 3.5, "height": 0.25,
         "overlap_ok": True},
        {"name": "radome", "on": "tower", "z": 15.75, "length": 1.5, "width": 1.5, "height": 1.5,
         "shape": "sphere"},
    ],
    "paint": [
        {"shape": "circle", "on": "deck", "box": "hull", "z": 4.5, "x": 0, "radius": 2.25,
         "thickness": 0.25, "color": "F0F0F0"},
        {"shape": "text", "text": "H", "on": "deck", "box": "hull", "z": 4.5, "x": 0, "height": 1.25,
         "color": "F2B705"},
    ],
}


# Each image: a function returning a PIL image.

def hero():
    placed, _ = hull(CUTTER)
    return shot(placed, yaw=32, pitch=16, w=1400, h=560, zoom=1.0)


def hull_presets():
    names = ["runabout", "fishing_trawler", "tugboat", "motor_yacht", "patrol_boat", "catamaran",
             "lifeboat", "landing_craft", "barge"]
    tiles = []
    for n in names:
        placed, _ = hull(preset=n)
        tiles.append(caption(shot(placed, yaw=35, pitch=24, w=600, h=380, zoom=0.95), n))
    return sheet(tiles, 3)


def liveries():
    tiles = []
    for name in ["navy", "coast_guard", "workboat", "research", "yacht", "dazzle"]:
        spec = {**CUTTER, "livery": {"name": name, "number": "47"}, "paint": []}
        placed, _ = hull(spec)
        tiles.append(caption(shot(placed, yaw=25, pitch=14, w=600, h=300, zoom=1.05), name))
    return sheet(tiles, 3)


def preview_panels():
    """The standard five-view preview the assistant checks after every change."""
    placed, info = hull(CUTTER)
    png = render_png(placed, title="coast guard cutter", ruler=design_ruler(info, info["scale"]))
    return Image.open(io.BytesIO(png))


def interior():
    placed, info = hull(preset="patrol_boat")
    png = render_interior(placed, info, title="patrol_boat", ruler=design_ruler(info, info["scale"]))
    return Image.open(io.BytesIO(png))


def powertrain():
    """Fishing trawler built through the powertrain stage, with the near half of the hull and
    the railings left out so the engine room shows."""
    placed, info = hull({"fitout": {"stage": "powertrain"}}, preset="fishing_trawler")
    cut_x = -info["shift"][0]
    kept = [p for p in placed
            if not p.piece.d.startswith("railing")
            and (p.origin[0] <= cut_x or p.piece.d not in BY_NAME and p.origin[0] <= cut_x + 4)]
    img = shot(kept, yaw=25, pitch=30, w=1200, h=640, zoom=1.7, focus=(0.5, 0.25, 0.19))
    return img.crop((60, 0, 1080, 640))   # just the engine room


def humvee():
    from swhull.drafts import materialize  # noqa: PLC0415
    from swhull.jobs import land_draft  # noqa: PLC0415
    record, _, _ = land_draft({"preset": "humvee_4x4"}, "humvee_4x4")
    parts, _ = materialize(record, centred=True)
    return shot(parts, yaw=125, pitch=16, w=1000, h=640, zoom=0.95)


def modular_engines():
    """Two engines from place_modular_engine: a 3x3 boxer and the compact 1x1 ring."""
    from swhull.drafts import materialize  # noqa: PLC0415
    from swhull.jobs import land_draft, place_engine  # noqa: PLC0415
    base, _, _ = land_draft({"preset": "empty"}, "engine")
    old = {p.uid for p in materialize(base)[0]}
    engines = [("3x3 boxer, 6 cylinders", {"size": 3, "cylinders": 6, "banks": ["left", "right"],
                                          "alternators": 1, "flywheel": True}),
               ("1x1 ring, 8 cylinders", {"size": 1, "cylinders": 8, "banks": ["top", "bottom", "left", "right"],
                                         "alternators": 1})]
    tiles = []
    for label, opts in engines:
        op = {"op": "engine", "position": [0, 2, 2], "output": "+z", "top": "+y", "coolant": True,
              "temperature_sensor": False, "air_rams": False, "flywheel": False, **opts}
        proposed, _, _, _ = place_engine(base, op, "engine")
        new = [p for p in materialize(proposed, centred=True)[0] if p.uid not in old]
        tiles.append(caption(shot(new, yaw=40, pitch=28, w=700, h=520, zoom=0.9), label))
    return sheet(tiles, 2)


def diagnostics():
    """The Humvee with its front-left steering input wired to the wrong seat axis, and the
    repair plan's proposed wire (the steering case of tools/diagnostic_milestone.py)."""
    from swhull.diagnostic_view import preview  # noqa: PLC0415
    from swhull.drafts import materialize  # noqa: PLC0415
    from swhull.networks import edited as wire_edit, ports, template_wires, wires  # noqa: PLC0415
    from swhull.repairs import plan, repair  # noqa: PLC0415
    record = {"kind": "land", "spec": {"preset": "humvee_4x4", "bench": "S"}, "generation": 0}
    parts, _ = materialize(record)
    record["base_connections"] = template_wires(record, parts)
    wheel = next(p for p in parts if p.name == "front left wheel")
    node = next(n for n in ports(wheel) if n["label"] == "Steering")
    link = next(lk for lk in wires(record, parts) if lk.get("to") == {"part_id": wheel.uid, "port": node["index"]})
    driver = next(p for p in parts if p.name == "driver")
    axis = next(n for n in ports(driver) if n["label"].startswith("Axis 1"))
    broken = wire_edit(record, [{"op": "disconnect", "link_id": link["link_id"]},
                                {"op": "connect", "from": {"part_id": driver.uid, "port": axis["index"]},
                                 "to": link["to"]}], parts)
    proposal = plan(broken)
    ids = [f["finding_id"] for f in proposal["findings"] if f["repair_status"] == "available"]
    fixed, _ = repair(broken, proposal["plan_id"], ids)
    png, _ = preview(broken, "steering fault and repair", fixed, yaw=115, pitch=15, layer="all")
    return Image.open(io.BytesIO(png))


IMAGES = {
    "hero": hero,
    "hull-presets": hull_presets,
    "liveries": liveries,
    "preview-panels": preview_panels,
    "interior-plan": interior,
    "engine-room": powertrain,
    "humvee": humvee,
    "modular-engines": modular_engines,
    "diagnostics": diagnostics,
}


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "docs", "images")
    wanted = sys.argv[2:] or list(IMAGES)
    os.makedirs(out, exist_ok=True)
    for name in wanted:
        t0 = time.time()
        img = IMAGES[name]()
        path = os.path.join(out, f"{name}.png")
        img.save(path, "PNG", optimize=True)
        print(f"{path}  {img.size[0]}x{img.size[1]}  {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
