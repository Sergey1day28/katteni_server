import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'farm_site.settings')
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import django

django.setup()

from farm_agent.lock import InstanceLock
from farm_core.clock_tick import run_loop


def _attach_log(log_path):
    log_path = Path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    target = str(log_path.resolve())
    root = logging.getLogger()
    for handler in root.handlers:
        if isinstance(handler, RotatingFileHandler) and Path(handler.baseFilename) == Path(target):
            return
    handler = RotatingFileHandler(target, maxBytes=1024 * 1024, backupCount=3, encoding='utf-8')
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
    root.addHandler(handler)
    root.setLevel(logging.INFO)


def main():
    root = Path(__file__).resolve().parent.parent
    log_path = root / 'logs' / 'farm_clock.log'
    _attach_log(log_path)
    lock = InstanceLock(root / 'logs' / 'farm_clock.lock')
    if not lock.acquire():
        logging.info('Часы уже запущены на этом ПК.')
        return 1
    try:
        logging.info('Часы фермы запущены')
        run_loop()
    finally:
        lock.release()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
