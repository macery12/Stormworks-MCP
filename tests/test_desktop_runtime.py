import json

import pytest

from swhull import desktop_runtime as runtime


@pytest.fixture(autouse=True)
def isolated_runtime(monkeypatch, tmp_path):
    monkeypatch.setenv("SW_MCP_RUNTIME_DIR", str(tmp_path))


def test_os_lock_rejects_duplicates_and_recovers_after_close():
    with runtime.InstanceLock("desktop"), pytest.raises(ValueError, match="already running"):
        runtime.InstanceLock("desktop").acquire()
    with runtime.InstanceLock("desktop"):
        pass


@pytest.mark.parametrize("record", [{"host": "example.com", "port": 38473, "token": "secret"},
                                   {"host": "127.0.0.1", "port": 80, "token": "secret"},
                                   {"host": "127.0.0.1", "port": 38473, "token": ""}, {}])
def test_discovery_never_redirects_off_machine(tmp_path, record):
    (tmp_path / "connection.json").write_text(json.dumps(record))
    with pytest.raises(ValueError, match="press Start"):
        runtime.read_connection()


def test_missing_discovery_gives_actionable_error():
    with pytest.raises(ValueError, match="press Start"):
        runtime.running_connection()


def test_stale_server_record_gives_actionable_error(tmp_path, monkeypatch):
    (tmp_path / "connection.json").write_text(json.dumps({"host": "127.0.0.1", "port": 38473, "token": "test"}))
    monkeypatch.setattr(runtime, "request", lambda *_: {"instance": "different"})
    with pytest.raises(ValueError, match="stopped"):
        runtime.running_connection()


def test_frozen_command_never_uses_temporary_extraction_path(monkeypatch):
    monkeypatch.setattr(runtime.sys, "frozen", True, raising=False)
    monkeypatch.setattr(runtime.sys, "executable", "C:/permanent folder/Stormworks MCP.exe")
    assert runtime.launch_command("--serve") == ["C:/permanent folder/Stormworks MCP.exe", "--serve"]


@pytest.mark.parametrize("value", ["80", "99999", "invalid"])
def test_invalid_ports_are_rejected(monkeypatch, value):
    monkeypatch.setenv("SW_MCP_PORT", value)
    with pytest.raises(ValueError):
        runtime.port()
