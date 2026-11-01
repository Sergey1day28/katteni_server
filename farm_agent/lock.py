import os
from pathlib import Path


class InstanceLock:
    def __init__(self, path):
        self._path = Path(path)
        self._handle = None

    def acquire(self):
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if self._path.exists():
            old_pid = self._read_pid()
            if old_pid and _pid_alive(old_pid):
                return False
        self._handle = open(self._path, 'w', encoding='utf-8')
        self._handle.write(str(os.getpid()))
        self._handle.flush()
        return True

    def release(self):
        if self._handle is not None:
            self._handle.close()
            self._handle = None
        if self._path.exists():
            self._path.unlink()

    def _read_pid(self):
        text = self._path.read_text(encoding='utf-8').strip()
        if not text.isdigit():
            return None
        return int(text)


def _pid_alive(pid):
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True
