import pytest

from swhull import build as builder, cache
from swhull.build import resolve_spec
from swhull.vehicle import to_xml


def test_cache_key_changes_across_packaged_releases(monkeypatch):
    spec = resolve_spec(preset="rowboat")
    first = cache.key(spec)
    monkeypatch.setattr(cache, "__version__", cache.__version__ + "-changed")
    assert cache.key(spec) != first


def test_cache_reuses_geometry_and_overlays_without_rebuild(tmp_path, monkeypatch):
    monkeypatch.setenv("SW_BUILD_CACHE_DIR", str(tmp_path))
    spec = resolve_spec(preset="rowboat")
    first, info = builder.build(spec)
    assert not info["cache_hit"]
    monkeypatch.setattr(builder, "_build_base", lambda _s: (_ for _ in ()).throw(AssertionError("rebuilt")))
    second, info = builder.build(spec)
    assert info["cache_hit"]
    assert to_xml(second) == to_xml(first)
    spec["edits"] = [{"op": "paint", "select": {"ids": [first[0].uid]}, "color": "ABCDEF"}]
    third, info = builder.build(spec)
    assert info["cache_hit"]
    assert third[0].color == "ABCDEF"
    cells = {tuple(v[i] + info["shift"][i] for i in range(3)) for p in third for v in p.voxels()}
    neighbour = next((x + 1, y, z) for x, y, z in sorted(cells) if (x + 1, y, z) not in cells)
    spec["components"] = [{"name": "mounted block", "definition": "01_block",
                           "position": [n / 4 for n in neighbour]}]
    _, info = builder.build(spec)
    assert info["cache_hit"]


def test_failed_build_publishes_no_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("SW_BUILD_CACHE_DIR", str(tmp_path))
    def fail(_s):
        raise ValueError("build failed")
    monkeypatch.setattr(builder, "_build_base", fail)
    with pytest.raises(ValueError, match="failed"):
        builder.build(resolve_spec())
    assert not list(tmp_path.iterdir())


def test_cache_prunes_entries(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "MAX_ENTRIES", 2)
    for i in range(4):
        (tmp_path / f"{i}.npz").write_bytes(b"test")
    cache.prune(tmp_path)
    assert len(list(tmp_path.glob("*.npz"))) == 2


def test_corrupt_cache_rebuilds_and_cancelled_worker_leaves_no_partial_state(tmp_path, monkeypatch):
    import anyio  # noqa: PLC0415
    from functools import partial  # noqa: PLC0415
    from swhull.jobs import run_job  # noqa: PLC0415
    monkeypatch.setenv("SW_BUILD_CACHE_DIR", str(tmp_path))
    spec = resolve_spec(preset="rowboat")
    (tmp_path / f"{cache.key(spec)}.npz").write_bytes(b"PK corrupted archive")
    _, info = builder.build(spec)
    assert not info["cache_hit"]
    # Cancellation while constructing the hull must not publish a half-built entry.
    big = resolve_spec({"length": 65, "beam": 13, "depth": 7, "smoothing": "wedges"})
    with pytest.raises(ValueError, match="gave up"):
        anyio.run(partial(run_job, "preview", big, "cancelled", timeout=.5))
    assert not (tmp_path / f"{cache.key(big)}.npz").exists()


def _slow_cache_publication(directory, ready):
    import os  # noqa: PLC0415
    import time  # noqa: PLC0415
    import numpy as np  # noqa: PLC0415
    from swhull.interior import InteriorPlan  # noqa: PLC0415
    from swhull.pieces import BLOCK, Placed  # noqa: PLC0415
    os.environ["SW_BUILD_CACHE_DIR"] = directory
    def incomplete(file, **_kwargs):
        file.write(b"unfinished archive")
        file.flush()
        ready.set()
        time.sleep(30)
    np.savez_compressed = incomplete
    cache.write("cancelled", [Placed(BLOCK, (0, 0, 0))],
                {"region": {(0, 0, 0): "hull"}, "interior": InteriorPlan()})


def test_killed_publication_is_never_read_and_worker_cleanup_removes_partial(tmp_path, monkeypatch):
    import multiprocessing  # noqa: PLC0415
    monkeypatch.setenv("SW_BUILD_CACHE_DIR", str(tmp_path))
    ctx = multiprocessing.get_context("spawn")
    ready = ctx.Event()
    process = ctx.Process(target=_slow_cache_publication, args=(str(tmp_path), ready))
    process.start()
    try:
        assert ready.wait(10), "worker did not reach publication"
        assert list(tmp_path.glob("*.part"))
        assert cache.read("cancelled") is None
    finally:
        if process.is_alive():
            process.kill()
        process.join(5)
        cache.discard_worker(process.pid)
    assert not list(tmp_path.iterdir())
