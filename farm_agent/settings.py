import json
import os
import sys
from pathlib import Path


class AgentSettings:
    def __init__(self, data, path):
        self.path = Path(path)
        self.server_url = data.get('server_url') or 'http://127.0.0.1:8000'
        self.worker_id = data.get('worker_id') or 'this-pc'
        self.token = data.get('token') or ''
        self._profiles_dir_saved = data.get('profiles_dir') or ''
        self.profiles_dir = self._profiles_dir_saved
        self.log_path = data.get('log_path') or ''
        self.journal_path = data.get('journal_path') or ''
        self.lock_path = data.get('lock_path') or ''

    def as_dict(self):
        return {
            'server_url': self.server_url,
            'worker_id': self.worker_id,
            'token': self.token,
            'profiles_dir': self._profiles_dir_saved,
            'log_path': self.log_path,
            'journal_path': self.journal_path,
            'lock_path': self.lock_path,
        }

    def save(self):
        self.path.write_text(
            json.dumps(self.as_dict(), ensure_ascii=False, indent=2) + '\n',
            encoding='utf-8',
        )


def desktop_dir():
    if sys.platform == 'win32':
        for candidate in (_known_folder_desktop(), _userprofile_desktop()):
            if candidate is not None and candidate.is_dir():
                return candidate
    fallback = Path.home() / 'Desktop'
    if fallback.is_dir():
        return fallback
    return Path.home()


def load_settings(path, resolve_desktop=None):
    path = Path(path)
    data = {}
    if path.exists():
        data = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(data, dict):
            raise ValueError('farm_agent.local.json должен быть объектом JSON.')
    settings = AgentSettings(data, path)
    if not settings.profiles_dir:
        resolver = resolve_desktop or desktop_dir
        settings.profiles_dir = str(resolver())
    return settings


def _userprofile_desktop():
    root = os.environ.get('USERPROFILE')
    if not root:
        return None
    return Path(root) / 'Desktop'


def _known_folder_desktop():
    if sys.platform != 'win32':
        return None
    try:
        import ctypes
        from ctypes import wintypes
    except ImportError:
        return None

    class GUID(ctypes.Structure):
        _fields_ = [
            ('Data1', wintypes.DWORD),
            ('Data2', wintypes.WORD),
            ('Data3', wintypes.WORD),
            ('Data4', wintypes.BYTE * 8),
        ]

    folder = GUID()
    folder.Data1 = 0xB4BFCC3A
    folder.Data2 = 0xDB2C
    folder.Data3 = 0x424C
    folder.Data4[:] = (0xB0, 0x29, 0x7F, 0xE9, 0x9A, 0x87, 0xC6, 0x41)
    path_ptr = ctypes.c_wchar_p()
    getter = ctypes.windll.shell32.SHGetKnownFolderPath
    getter.restype = ctypes.HRESULT
    status = getter(ctypes.byref(folder), 0, None, ctypes.byref(path_ptr))
    if status != 0 or not path_ptr.value:
        return None
    value = path_ptr.value
    ctypes.windll.ole32.CoTaskMemFree(path_ptr)
    return Path(value)
