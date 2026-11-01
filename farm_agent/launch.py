import ctypes
import logging
import os
import time

SW_SHOWNORMAL = 1
SW_RESTORE = 9
GA_ROOT = 2
WINDOW_WIDTH = 1024
WINDOW_HEIGHT = 768


class Launcher:
    def __init__(
        self,
        start=None,
        sleep=None,
        pause_after_sec=10,
        restore_chrome=None,
        list_chrome=None,
    ):
        self._start = start or _start_normal
        self._sleep = sleep or _default_sleep
        self._pause_after_sec = pause_after_sec
        self._list_chrome = list_chrome or list_chrome_hwnds
        if restore_chrome is None:
            self._restore_chrome = place_new_chrome
        else:
            self._restore_chrome = restore_chrome

    def open_file(self, path):
        before = self._list_chrome()
        try:
            self._start(str(path), show_cmd=SW_SHOWNORMAL)
        except OSError as error:
            logging.info('Запуск файла не удался: %s %s', path, error)
            return False, str(error)
        logging.info('Файл запущен: %s', path)
        for _ in range(6):
            self._sleep(0.5)
            self._restore_chrome(before)
        self._sleep(self._pause_after_sec)
        return True, ''


def _start_normal(path, show_cmd=SW_SHOWNORMAL):
    os.startfile(path, show_cmd=show_cmd)


def list_chrome_hwnds():
    user32 = ctypes.windll.user32
    found = set()
    buf = ctypes.create_unicode_buffer(256)

    def callback(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        if user32.GetAncestor(hwnd, GA_ROOT) != hwnd:
            return True
        user32.GetClassNameW(hwnd, buf, 256)
        if buf.value == 'Chrome_WidgetWin_1':
            found.add(int(hwnd))
        return True

    enum_proc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    user32.EnumWindows(enum_proc(callback), 0)
    return found


def window_rect(screen_w, screen_h, width=WINDOW_WIDTH, height=WINDOW_HEIGHT):
    width = min(int(width), int(screen_w))
    height = min(int(height), int(screen_h))
    left = max(0, (int(screen_w) - width) // 2)
    top = max(0, (int(screen_h) - height) // 2)
    return left, top, width, height


def place_new_chrome(before):
    user32 = ctypes.windll.user32
    left, top, width, height = window_rect(
        user32.GetSystemMetrics(0),
        user32.GetSystemMetrics(1),
    )
    before = before or set()
    for hwnd in list_chrome_hwnds() - before:
        handle = ctypes.c_void_p(hwnd)
        if user32.IsZoomed(handle):
            user32.ShowWindow(handle, SW_RESTORE)
        user32.MoveWindow(handle, left, top, width, height, True)
        logging.info(
            'Окно Chrome %s: %sx%s @ %s,%s',
            hwnd,
            width,
            height,
            left,
            top,
        )


def _default_sleep(seconds):
    time.sleep(seconds)
