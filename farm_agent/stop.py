import logging
import subprocess


class ChromeStopper:
    def __init__(self, run=None):
        self._run = run or subprocess.run

    def stop(self):
        completed = self._run(
            ['taskkill', '/im', 'chrome.exe', '/f'],
            capture_output=True,
            text=True,
        )
        code = completed.returncode
        if code in (0, 128):
            logging.info('Chrome остановлен, код %s', code)
            return True, ''
        logging.info('Не удалось остановить Chrome, код %s', code)
        return False, 'код %s' % code
