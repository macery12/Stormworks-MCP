"""One lock over stored designs, shared by every running server (each client starts its own)."""

import sys
import threading
import time
from pathlib import Path

# Sections under the lock are short reads and writes; a wait this long means a stuck process.
WAIT = 30.0


class DesignLock:
    """Reentrant within a thread like threading.RLock, and held across processes through an
    OS lock on a file in the designs folder. The OS releases it if a server crashes."""

    def __init__(self, folder):
        self.folder = folder  # a callable, so SW_DESIGNS_DIR is read at each use
        self.local = threading.RLock()
        self.depth = 0
        self.file = None

    def __enter__(self):
        self.local.acquire()
        if self.depth == 0:
            try:
                self.file = _lock_file(Path(self.folder()) / ".lock")
            except BaseException:
                self.local.release()
                raise
        self.depth += 1
        return self

    def __exit__(self, *_):
        self.depth -= 1
        if self.depth == 0:
            file, self.file = self.file, None
            _unlock_file(file)
        self.local.release()


def _lock_file(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    file = path.open("a+b")
    deadline = time.monotonic() + WAIT
    while True:
        try:
            if sys.platform == "win32":
                import msvcrt  # noqa: PLC0415

                file.seek(0)
                msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl  # noqa: PLC0415

                fcntl.flock(file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return file
        except OSError:
            if time.monotonic() > deadline:
                file.close()
                raise OSError("another AI client is still saving designs; try again in a moment") from None
            time.sleep(0.02)


def _unlock_file(file):
    try:
        if sys.platform == "win32":
            import msvcrt  # noqa: PLC0415

            file.seek(0)
            msvcrt.locking(file.fileno(), msvcrt.LK_UNLCK, 1)
    finally:
        file.close()  # closing also releases a POSIX flock
