import logging
import os
import sys
import time
from pathlib import Path

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'farm_site.settings')
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import django

django.setup()

from farm_core.clock_tick import tick


def main():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    logging.info('Часы фермы запущены')
    while True:
        fires = tick()
        for fire in fires:
            logging.info(
                'Сработал скрипт %s %s: %s %s',
                fire.schedule_id,
                fire.kind,
                fire.result,
                fire.error,
            )
        time.sleep(10)


if __name__ == '__main__':
    raise SystemExit(main())
