"""Bounded, atomic, cross-process geometry cache. JSON/NumPy only, never pickle."""
import hashlib
import json
import os
import tempfile
import time
import zipfile
from pathlib import Path

import numpy as np

from . import definitions
from ._version import __version__
from .hull import HullShape
from .interior import InteriorPlan, Room
from .pieces import BY_NAME, Placed

MAX_BYTES = 512 * 1024 * 1024
MAX_ENTRIES = 20


def cache_dir():
    return Path(os.environ.get("SW_BUILD_CACHE_DIR", Path(tempfile.gettempdir()) / "stormworks-mcp-builds"))


def key(spec):
    digest = hashlib.sha256(json.dumps(spec, sort_keys=True, separators=(",", ":")).encode())
    digest.update(b"geometry-cache-v1")
    # Frozen distributions have no loose .py files; keep their caches distinct across releases too.
    digest.update(__version__.encode())
    for path in sorted(Path(__file__).parent.glob("*.py")):
        digest.update(path.read_bytes())
    base = definitions.definitions_dir()
    digest.update(str(base).encode())
    if base:
        for path in sorted(Path(base).glob("*.xml")):
            stat = path.stat()
            digest.update(f"{path.name}:{stat.st_mtime_ns}:{stat.st_size}".encode())
    return digest.hexdigest()


def _plan_data(plan):
    return {"blocks": [[*v, c] for v, c in plan.blocks.items()], "carve": list(plan.carve),
            "rooms": [{k: list(v) if isinstance(v, set) else v for k, v in vars(r).items()}
                      for r in plan.rooms], "levels": plan.levels, "warnings": plan.warnings,
            "reserved": list(plan.reserved)}


def _plan(data, components):
    plan = InteriorPlan()
    plan.blocks = {tuple(v[:3]): v[3] for v in data["blocks"]}
    plan.carve = {tuple(v) for v in data["carve"]}
    plan.rooms = [Room(**{**r, "air": {tuple(v) for v in r["air"]}}) for r in data["rooms"]]
    plan.levels, plan.warnings, plan.components = data["levels"], data["warnings"], components
    plan.reserved = {tuple(v) for v in data["reserved"]}
    return plan


def read(cache_key):
    path = cache_dir() / f"{cache_key}.npz"
    try:
        with np.load(path, allow_pickle=False) as archive:
            meta = json.loads(str(archive["metadata"]))
            coords, tags = archive["coords"], archive["tags"]
        parts = []
        for row in meta["parts"]:
            d, origin, q, color, uid, name, settings = row
            piece = BY_NAME.get(d) or definitions.load(d)
            if piece is None:
                return None
            parts.append(Placed(piece, tuple(origin), tuple(tuple(r) for r in q), color, uid, name, settings))
        shape = HullShape(meta["info"]["spec"])
        info = meta["info"]
        info["region"] = {tuple(int(n) for n in v): "hull" if t == 0 else f"box{int(t) - 1}"
                          for v, t in zip(coords, tags)}
        info["shape"], info["form"] = shape, shape.form
        info["shift"] = tuple(info["shift"])
        info["interior"] = _plan(meta["interior"], [p for p in parts if p.piece.d not in BY_NAME])
        info["cache_hit"] = True
        return parts, info
    except (OSError, ValueError, KeyError, TypeError, EOFError, zipfile.BadZipFile):
        return None


def write(cache_key, parts, info):
    directory = cache_dir()
    temporary = None
    try:
        directory.mkdir(parents=True, exist_ok=True)
        meta = {"parts": [[p.piece.d, p.origin, p.Q, p.color, p.uid, p.name, p.settings] for p in parts],
                "info": {k: v for k, v in info.items() if k not in ("shape", "form", "region", "interior")},
                "interior": _plan_data(info["interior"])}
        coords = np.asarray(list(info["region"]), dtype=np.int32)
        tags = np.asarray([0 if t == "hull" else int(t[3:]) + 1 for t in info["region"].values()],
                          dtype=np.int32)
        with tempfile.NamedTemporaryFile(dir=directory, prefix=f"worker-{os.getpid()}-",
                                         suffix=".part", delete=False) as f:
            temporary = Path(f.name)
            np.savez_compressed(f, metadata=json.dumps(meta, separators=(",", ":")), coords=coords, tags=tags)
        if temporary.stat().st_size <= MAX_BYTES:
            os.replace(temporary, directory / f"{cache_key}.npz")
        prune(directory)
    except OSError:
        pass  # caching is optional; never lose a successful build to a cache failure
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def prune(directory):
    files = sorted(directory.glob("*.npz"), key=lambda p: p.stat().st_mtime, reverse=True)
    total = 0
    for i, path in enumerate(files):
        total += path.stat().st_size
        if i >= MAX_ENTRIES or total > MAX_BYTES:
            path.unlink(missing_ok=True)
    for path in directory.glob("*.part"):
        if time.time() - path.stat().st_mtime > 3600:
            path.unlink(missing_ok=True)


def discard_worker(pid):
    """Remove unpublished files left by a killed worker; never touch completed entries."""
    try:
        for path in cache_dir().glob(f"worker-{pid}-*.part"):
            path.unlink(missing_ok=True)
    except OSError:
        pass
