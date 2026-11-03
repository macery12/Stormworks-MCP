import hashlib
from datetime import date

from tools import winget_manifest


def test_manifests_point_at_the_release_installer_with_its_hash():
    data = b"synthetic installer bytes"
    files = winget_manifest.manifests("0.3.0", data, date(2026, 11, 3))
    assert sorted(files) == ["macery12.StormworksMCP.installer.yaml", "macery12.StormworksMCP.locale.en-US.yaml",
                             "macery12.StormworksMCP.yaml"]
    installer = files["macery12.StormworksMCP.installer.yaml"]
    url = ("https://github.com/macery12/Stormworks-MCP/releases/download/v0.3.0/"
           "stormworks-mcp-0.3.0-windows-x64-setup.exe")
    assert installer.count(url) == 2 and installer.count(hashlib.sha256(data).hexdigest().upper()) == 2
    assert "Scope: user" in installer and "Scope: machine" in installer and "InstallerType: inno" in installer
    # Silent winget installs never rewrite client settings.
    assert installer.count("/MERGETASKS=!clientclaude,!clientcodex") == 2
    assert "ProductCode: '{20748683-2FB1-4BC7-9C12-7CA37ABA71FF}_is1'" in installer
    assert all("PackageVersion: 0.3.0" in text for text in files.values())
