"""Write the winget manifests (version, installer, default locale) for a release's installer.

The installer URL is the GitHub release asset, so run this on the exact bytes that release
uploads (CI does, after assembling dist/release). Submit the folder to microsoft/winget-pkgs,
for example with `wingetcreate submit --token <PAT> <folder>`; docs/releases.md explains.
"""
import argparse
import hashlib
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from swhull._version import __version__  # noqa: E402

IDENTIFIER = "macery12.StormworksMCP"
REPOSITORY = "macery12/Stormworks-MCP"
SCHEMA = "1.6.0"
# The installer's AppId; winget matches the installed app through its uninstall entry.
PRODUCT_CODE = "{20748683-2FB1-4BC7-9C12-7CA37ABA71FF}_is1"
# winget installs silently; leave client settings alone (MCP > Set up in the app does that).
NO_CLIENT_SETUP = "/MERGETASKS=!clientclaude,!clientcodex"


def _header(version, kind):
    return (f"# yaml-language-server: $schema=https://aka.ms/winget-manifest.{kind}.{SCHEMA}.schema.json\n"
            f"PackageIdentifier: {IDENTIFIER}\nPackageVersion: {version}\n")


def manifests(version, installer_bytes, released=None):
    """{file name: text} for the three manifests."""
    url = (f"https://github.com/{REPOSITORY}/releases/download/v{version}/"
           f"stormworks-mcp-{version}-windows-x64-setup.exe")
    sha = hashlib.sha256(installer_bytes).hexdigest().upper()
    installers = "".join(
        f"- Architecture: x64\n  Scope: {scope}\n  InstallerUrl: {url}\n  InstallerSha256: {sha}\n"
        f"  InstallerSwitches:\n    Custom: {switch} {NO_CLIENT_SETUP}\n"
        for scope, switch in (("user", "/CURRENTUSER"), ("machine", "/ALLUSERS")))
    return {
        f"{IDENTIFIER}.yaml": _header(version, "version") + f"DefaultLocale: en-US\nManifestType: version\nManifestVersion: {SCHEMA}\n",
        f"{IDENTIFIER}.installer.yaml": _header(version, "installer")
        + f"InstallerType: inno\nUpgradeBehavior: install\nProductCode: '{PRODUCT_CODE}'\n"
        + f"ReleaseDate: {(released or date.today()).isoformat()}\nInstallers:\n{installers}"
        + f"ManifestType: installer\nManifestVersion: {SCHEMA}\n",
        f"{IDENTIFIER}.locale.en-US.yaml": _header(version, "defaultLocale")
        + "PackageLocale: en-US\nPublisher: macery12\n"
        + f"PublisherUrl: https://github.com/macery12\nPublisherSupportUrl: https://github.com/{REPOSITORY}/issues\n"
        + f"PackageName: Stormworks MCP\nPackageUrl: https://github.com/{REPOSITORY}\nLicense: MIT\n"
        + f"LicenseUrl: https://github.com/{REPOSITORY}/blob/main/LICENSE\n"
        + "ShortDescription: Build Stormworks vehicles with an AI client (Claude Desktop, ChatGPT / Codex) over MCP.\n"
        + "Tags:\n- stormworks\n- mcp\n- claude\n- codex\n"
        + f"ReleaseNotesUrl: https://github.com/{REPOSITORY}/releases/tag/v{version}\n"
        + f"ManifestType: defaultLocale\nManifestVersion: {SCHEMA}\n",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", default=__version__)
    parser.add_argument("--installer", type=Path, help="default: the assembled release installer in dist/release")
    parser.add_argument("--out", type=Path, default=ROOT / "dist" / "winget")
    args = parser.parse_args()
    installer = args.installer or ROOT / "dist" / "release" / f"stormworks-mcp-{args.version}-windows-x64-setup.exe"
    if not installer.is_file():
        raise SystemExit(f"missing installer {installer}; assemble the release first (tools/release_assets.py)")
    folder = args.out / args.version
    folder.mkdir(parents=True, exist_ok=True)
    for name, text in manifests(args.version, installer.read_bytes()).items():
        (folder / name).write_text(text, encoding="utf-8", newline="\n")
    print(folder)


if __name__ == "__main__":
    main()
