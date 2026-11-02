import ctypes
import json
import logging
import subprocess
from ctypes import HRESULT, POINTER, byref, c_void_p, wintypes
from pathlib import Path

from farm_agent.shortcut import (
    app_model_id,
    command_matches,
    is_shared_chrome_dir,
    profile_directory,
    read_lnk_text,
    user_data_dir,
)

WM_CLOSE = 0x0010
COINIT_APARTMENTTHREADED = 2
VT_LPWSTR = 31


def list_chrome_processes(run):
    script = (
        "Get-CimInstance Win32_Process -Filter \"Name = 'chrome.exe'\" "
        '| Select-Object ProcessId,CommandLine | ConvertTo-Json -Compress'
    )
    completed = run(
        ['powershell', '-NoProfile', '-Command', script],
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or '').strip()
        raise OSError(completed.returncode, detail)
    text = (completed.stdout or '').strip().lstrip('\ufeff')
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as error:
        raise OSError(0, 'не JSON') from error
    if isinstance(parsed, dict):
        parsed = [parsed]
    if not isinstance(parsed, list):
        raise OSError(0, 'не список')
    found = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        pid = item.get('ProcessId')
        if pid is None:
            continue
        found.append((int(pid), item.get('CommandLine') or ''))
    return found


def _hidden_run(cmd, capture_output=True, text=True):
    return subprocess.run(
        cmd,
        capture_output=capture_output,
        text=text,
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
    )


class _Guid(ctypes.Structure):
    _fields_ = [
        ('Data1', ctypes.c_ulong),
        ('Data2', ctypes.c_ushort),
        ('Data3', ctypes.c_ushort),
        ('Data4', ctypes.c_ubyte * 8),
    ]


class _PropertyKey(ctypes.Structure):
    _fields_ = [
        ('fmtid', _Guid),
        ('pid', wintypes.DWORD),
    ]


class _PropVariant(ctypes.Structure):
    _fields_ = [
        ('vt', ctypes.c_ushort),
        ('r1', ctypes.c_ushort),
        ('r2', ctypes.c_ushort),
        ('r3', ctypes.c_ushort),
        ('val', ctypes.c_ulonglong),
    ]


def _app_user_model_key():
    return _PropertyKey(
        _Guid(
            0x9F4C2855,
            0x9F79,
            0x4B39,
            (ctypes.c_ubyte * 8)(0xA8, 0xD0, 0xE1, 0xD4, 0x2D, 0xE1, 0xD5, 0xF3),
        ),
        5,
    )


def _property_store_iid():
    return _Guid(
        0x886D8EEB,
        0x8CF2,
        0x4446,
        (ctypes.c_ubyte * 8)(0x8D, 0x02, 0xCD, 0xBA, 0x1D, 0xBD, 0xCF, 0x99),
    )


def _window_app_id(shell32, ole32, hwnd):
    store = c_void_p()
    iid = _property_store_iid()
    hr = shell32.SHGetPropertyStoreForWindow(hwnd, byref(iid), byref(store))
    if hr != 0 or not store:
        return ''
    table = ctypes.cast(store, POINTER(POINTER(c_void_p)))[0]
    get_value = ctypes.WINFUNCTYPE(
        HRESULT,
        c_void_p,
        POINTER(_PropertyKey),
        POINTER(_PropVariant),
    )(table[5])
    release = ctypes.WINFUNCTYPE(ctypes.c_ulong, c_void_p)(table[2])
    key = _app_user_model_key()
    var = _PropVariant()
    text = ''
    try:
        if get_value(store, byref(key), byref(var)) == 0 and var.vt == VT_LPWSTR and var.val:
            text = ctypes.wstring_at(var.val)
    finally:
        ole32.PropVariantClear(byref(var))
        release(store)
    return text


def list_chrome_windows():
    user32 = ctypes.windll.user32
    shell32 = ctypes.windll.shell32
    ole32 = ctypes.windll.ole32
    ole32.CoInitializeEx(None, COINIT_APARTMENTTHREADED)
    shell32.SHGetPropertyStoreForWindow.argtypes = [wintypes.HWND, POINTER(_Guid), POINTER(c_void_p)]
    shell32.SHGetPropertyStoreForWindow.restype = HRESULT
    ole32.PropVariantClear.argtypes = [POINTER(_PropVariant)]
    ole32.PropVariantClear.restype = HRESULT
    found = []
    buf = ctypes.create_unicode_buffer(256)

    def callback(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        if user32.GetAncestor(hwnd, 2) != hwnd:
            return True
        user32.GetClassNameW(hwnd, buf, 256)
        if buf.value == 'Chrome_WidgetWin_1':
            found.append((int(hwnd), _window_app_id(shell32, ole32, hwnd)))
        return True

    enum_proc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    user32.EnumWindows(enum_proc(callback), 0)
    return found


def post_close(hwnd):
    ctypes.windll.user32.PostMessageW(int(hwnd), WM_CLOSE, 0, 0)


class ProfileCloser:
    def __init__(self, run=None, read_arguments=None, list_processes=None, list_windows=None, close_window=None):
        self._run = run or _hidden_run
        self._read_arguments = read_arguments or read_lnk_text
        if list_processes is None:
            self._list_processes = lambda: list_chrome_processes(self._run)
        else:
            self._list_processes = list_processes
        self._list_windows = list_windows or list_chrome_windows
        self._close_window = close_window or post_close

    def close(self, path):
        if Path(path).suffix.lower() != '.lnk':
            return False, 'не ярлык Chrome'
        try:
            arguments = self._read_arguments(path)
        except OSError as error:
            logging.info('Аргументы ярлыка не прочитаны: %s %s', path, error)
            return False, 'не прочитаны аргументы ярлыка'
        directory = user_data_dir(arguments)
        profile = profile_directory(arguments)
        if directory and not is_shared_chrome_dir(directory):
            return self._kill_directory(directory)
        if directory and is_shared_chrome_dir(directory) and not profile:
            logging.info('Ярлык без своего каталога Chrome: %s', directory)
            return False, 'общий каталог Chrome'
        app_id = app_model_id(arguments, profile)
        if not app_id:
            logging.info('В ярлыке нет профиля Chrome: %s', path)
            return False, 'в ярлыке нет профиля Chrome'
        return self._close_app(app_id)

    def _close_app(self, app_id):
        try:
            windows = self._list_windows()
        except OSError as error:
            logging.info('Окна Chrome не прочитаны: %s', error)
            return False, 'не прочитаны окна Chrome'
        matched = [
            hwnd for hwnd, found in windows
            if (found or '').lower() == app_id.lower()
        ]
        if not matched:
            logging.info('Окон профиля нет, %s', app_id)
            return True, ''
        logging.info('Закрываю профиль %s', app_id)
        for hwnd in matched:
            self._close_window(hwnd)
            logging.info('Окно профиля закрыто, hwnd %s', hwnd)
        return True, ''

    def _kill_directory(self, directory):
        try:
            processes = self._list_processes()
        except OSError as error:
            logging.info('Список процессов Chrome не прочитан: %s', error)
            return False, 'не прочитан список процессов'
        matched = [
            pid for pid, command_line in processes
            if command_matches(command_line, directory)
        ]
        if not matched:
            logging.info('Процессов профиля нет, каталог %s', directory)
            return True, ''
        logging.info('Закрываю профиль, каталог %s', directory)
        failed_code = None
        for pid in matched:
            completed = self._run(
                ['taskkill', '/PID', str(pid), '/T', '/F'],
                capture_output=True,
                text=True,
            )
            code = completed.returncode
            if code in (0, 128):
                logging.info('Профиль остановлен, pid %s, код %s', pid, code)
                continue
            logging.info('Не удалось остановить профиль, pid %s, код %s', pid, code)
            if failed_code is None:
                failed_code = code
        if failed_code is not None:
            return False, 'код %s' % failed_code
        return True, ''
