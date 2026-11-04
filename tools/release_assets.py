"""Validate release versions, assemble download assets, and record their source build."""

import argparse
import hashlib
import json
import re
import shutil
import sys
import zipfile
from pathlib import Path

import tomlkit

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from swhull._version import __version__  # noqa: E402


def validate_version(tag=None):
    version = tomlkit.parse((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    if version != __version__:
        raise ValueError("pyproject.toml and swhull/_version.py versions disagree")
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ValueError("release versions must be MAJOR.MINOR.PATCH")
    if tag:
        match = re.fullmatch(r"v(\d+\.\d+)(\.\d+)?", tag)
        normalized = (match[1] + (match[2] or ".0")) if match else None
        if normalized != version:
            raise ValueError(f"tag {tag!r} does not match version {version}; use v{version}")
    return version


def portable(folder, target):
    """Zip the server folder under one top folder, so extracting it never scatters files."""
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(folder.rglob("*")):
            if path.is_file():
                archive.write(path, Path("Stormworks MCP") / path.relative_to(folder))
        archive.write(ROOT / "LICENSE", "Stormworks MCP/LICENSE")


def assemble(tag, commit, repository):
    version = validate_version(tag)
    dist = ROOT / "dist"
    output = dist / "release"
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise ValueError("dist/release must be empty; move the previous artifacts before assembling")
    folder = dist / "stormworks-mcp"
    if not (folder / "stormworks-mcp.exe").is_file():
        raise ValueError(f"missing build artifact: {folder / 'stormworks-mcp.exe'}")
    installer = dist / "stormworks-mcp-setup.exe"
    if not installer.is_file():
        raise ValueError(f"missing installer: {installer} (tools/build_installer.py)")
    portable(folder, output / f"stormworks-mcp-{version}-windows-x64-portable.zip")
    shutil.copyfile(installer, output / f"stormworks-mcp-{version}-windows-x64-setup.exe")
    (output / "build-info.json").write_text(json.dumps({
        "version": version, "tag": tag, "commit": commit, "repository": repository,
        "platform": "windows-x64", "python": sys.version.split()[0],
        "entry_point": "launcher.py", "client_mode": "--stdio", "default_mode": "console setup menu",
        "installer": "Inno Setup; per-user by default, all users optional; upgrades in place",
        "uv_lock_sha256": hashlib.sha256((ROOT / "uv.lock").read_bytes()).hexdigest(),
        "workflow": f"https://github.com/{repository}/actions/workflows/release.yml",
        "source": f"https://github.com/{repository}/tree/{commit}",
    }, indent=2) + "\n", encoding="utf-8")
    hashes = [f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}"
              for path in sorted(output.iterdir())]
    (output / "SHA256SUMS.txt").write_text("\n".join(hashes) + "\n", encoding="utf-8")
    print(output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--commit", default="local")
    parser.add_argument("--repository", default="macery12/Stormworks-MCP")
    args = parser.parse_args()
    if args.check:
        print(validate_version(args.tag))
    else:
        assemble(args.tag, args.commit, args.repository)


if __name__ == "__main__":
    main()
