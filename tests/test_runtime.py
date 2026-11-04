"""The stdio runtime's shared log file, its data folder and the cross-process design lock."""
import logging
import subprocess
import sys
import textwrap

import pytest

from swhull import design_lock, runtime


@pytest.fixture(autouse=True)
def isolated_data(monkeypatch, tmp_path):
    monkeypatch.setenv("SW_MCP_DATA_DIR", str(tmp_path / "data"))


def test_log_file_lives_in_the_data_folder(tmp_path):
    assert runtime.log_path() == tmp_path / "data" / "logs" / "log.txt"


def test_log_lines_name_the_client_and_process(monkeypatch):
    handler = runtime.SharedLogFile(runtime.log_path())
    handler.setFormatter(logging.Formatter("%(client)s[%(process)d] %(message)s"))
    handler.addFilter(runtime._ClientTag())
    monkeypatch.setitem(runtime.CLIENT, "name", "claude-ai")
    logger = logging.getLogger("stormworks.test-runtime")
    logger.addHandler(handler)
    try:
        logger.warning("hello")
    finally:
        logger.removeHandler(handler)
        handler.close()
    assert runtime.log_path().read_text(encoding="utf-8").strip().startswith("claude-ai[")


def test_an_oversized_log_moves_aside(monkeypatch):
    monkeypatch.setattr(runtime, "LOG_LIMIT", 100)
    monkeypatch.setattr(runtime, "ROLL_CHECK_EVERY", 1)
    path = runtime.log_path()
    path.parent.mkdir(parents=True)
    path.write_text("x" * 200)
    handler = runtime.SharedLogFile(path)
    assert (path.parent / "log.old.txt").read_text() == "x" * 200
    record = logging.LogRecord("t", logging.INFO, __file__, 1, "y" * 150, None, None)
    handler.emit(record)
    handler.close()
    assert "y" * 150 in (path.parent / "log.old.txt").read_text()
    assert not path.exists() or path.stat().st_size == 0


def test_design_lock_is_reentrant_and_released(tmp_path):
    lock = design_lock.DesignLock(lambda: tmp_path)
    with lock, lock:
        assert lock.depth == 2
    assert lock.depth == 0 and lock.file is None
    with lock:
        pass


def test_design_lock_waits_for_another_process(tmp_path, monkeypatch):
    holder = subprocess.Popen([sys.executable, "-c", textwrap.dedent(f"""
        import sys, time
        from swhull.design_lock import DesignLock
        with DesignLock(lambda: {str(tmp_path)!r}):
            print("held", flush=True)
            sys.stdin.readline()
        """)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    try:
        assert holder.stdout.readline().strip() == "held"
        monkeypatch.setattr(design_lock, "WAIT", 0.3)
        with pytest.raises(OSError, match="another AI client"), design_lock.DesignLock(lambda: tmp_path):
            pass
    finally:
        holder.stdin.close()
        holder.wait(timeout=30)
    with design_lock.DesignLock(lambda: tmp_path):
        pass
