import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Previews in the general suite use the fast, deterministic flat renderer; tests/test_raster.py
# covers the lit renderers. Worker processes inherit this.
os.environ.setdefault("SW_RENDERER", "flat")
