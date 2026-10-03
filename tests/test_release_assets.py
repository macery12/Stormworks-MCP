import hashlib
import json

import pytest

from tools import release_assets


@pytest.fixture(autouse=True)
def release_project(tmp_path, monkeypatch):
    # Keep tag validation independent of the repository's next release version.
    monkeypatch.setattr(release_assets, "ROOT", tmp_path)
    monkeypatch.setattr(release_assets, "__version__", "0.1.0")
    (tmp_path / "pyproject.toml").write_text('[project]\nversion="0.1.0"\n')


@pytest.mark.parametrize("tag", ["v0.1", "v0.1.0"])
def test_tag_matches_package_version(tag):
    assert release_assets.validate_version(tag) == "0.1.0"


@pytest.mark.parametrize("tag", ["v0.2.0", "v0.1.1", "0.1.0", "v0.1.0-extra"])
def test_mistagged_source_cannot_be_released(tag):
    with pytest.raises(ValueError, match="does not match"):
        release_assets.validate_version(tag)


def test_project_and_runtime_version_must_agree():
    (release_assets.ROOT / "pyproject.toml").write_text('[project]\nversion="0.2.0"\n')
    with pytest.raises(ValueError, match="versions disagree"):
        release_assets.validate_version("v0.1.0")


def test_release_assets_match_binary_and_record_source(tmp_path, monkeypatch):
    monkeypatch.setattr(release_assets, "ROOT", tmp_path)
    (tmp_path / "pyproject.toml").write_text('[project]\nversion="0.1.0"\n')
    (tmp_path / "uv.lock").write_text("locked dependencies")
    (tmp_path / "LICENSE").write_text("MIT")
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "stormworks-mcp.exe").write_bytes(b"synthetic server bytes")
    release_assets.assemble("v0.1.0", "source-commit", "owner/repo")
    output = dist / "release"
    metadata = json.loads((output / "build-info.json").read_text())
    assert metadata["commit"] == "source-commit" and metadata["tag"] == "v0.1.0"
    binary = output / "stormworks-mcp-0.1.0-windows-x64.exe"
    assert binary.read_bytes() == (dist / "stormworks-mcp.exe").read_bytes()
    assert metadata["client_mode"] == "--connect"
    assert sorted(path.suffix for path in output.iterdir()) == [".exe", ".json", ".txt"]
    for line in (output / "SHA256SUMS.txt").read_text().splitlines():
        digest, filename = line.split("  ", 1)
        assert hashlib.sha256((output / filename).read_bytes()).hexdigest() == digest
    with pytest.raises(ValueError, match="must be empty"):
        release_assets.assemble("v0.1.0", "other-commit", "owner/repo")
