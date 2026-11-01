import logging
import subprocess
import time


class Launcher:
    def __init__(self, popen=None, sleep=None, check_after_sec=3, pause_after_sec=10):
        self._popen = popen or subprocess.Popen
        self._sleep = sleep or _default_sleep
        self._check_after_sec = check_after_sec
        self._pause_after_sec = pause_after_sec

    def open_file(self, path):
        process = self._popen(['cmd', '/c', str(path)])
        self._sleep(self._check_after_sec)
        code = process.poll()
        if code not in (None, 0):
            logging.info('Запуск файла завершился кодом %s: %s', code, path)
            return False, 'код %s' % code
        logging.info('Файл запущен: %s', path)
        self._sleep(self._pause_after_sec)
        return True, ''


def _default_sleep(seconds):
    time.sleep(seconds)
