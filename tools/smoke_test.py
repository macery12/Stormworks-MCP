"""Build every preset, write its XML + preview PNG to an output folder, print summaries.

    uv run tools/smoke_test.py [out_dir] [preset ...]
"""
import os
import re
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from swhull.build import build, resolve_spec, summary  # noqa: E402
from swhull.presets import PRESETS  # noqa: E402
from swhull.render import design_ruler, render_png  # noqa: E402
from swhull.vehicle import read_components, to_xml  # noqa: E402

out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), "..", "out")
names = sys.argv[2:] or list(PRESETS)
os.makedirs(out, exist_ok=True)
for preset, mode in [(n, m) for n in names for m in ("blocks", "wedges")]:
    t0 = time.time()
    spec = resolve_spec({"smoothing": mode}, preset=preset)
    placed, info = build(spec)
    name = f"{preset}_{mode}"
    xml = to_xml(placed)
    xml_path = os.path.join(out, f"{name}.xml")
    with open(xml_path, "w", encoding="utf-8") as f:
        f.write(xml)
    # round trip: every piece we wrote reads back with the same definition and position
    back = list(read_components(xml_path))
    assert len(back) == len(placed), (len(back), len(placed))
    for (d, origin, Q, _), p in zip(back, placed):
        assert d == p.piece.d and origin == p.origin and Q == p.Q, (d, origin, p)
    # no two pieces may claim the same voxel
    seen = set()
    for p in placed:
        for v in p.voxels():
            assert v not in seen, f"overlap at {v}"
            seen.add(v)
    assert not re.search(r' \d\d=', xml)
    png = render_png(placed, title=name, ruler=design_ruler(info))
    with open(os.path.join(out, f"{name}.png"), "wb") as f:
        f.write(png)
    print(f"== {name}  ({time.time() - t0:.1f}s)\n{summary(spec, placed, info)}\n")
