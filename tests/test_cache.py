import pytest

from swhull import build as builder, cache
from swhull.build import resolve_spec
from swhull.vehicle import to_xml


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
