import logging
import sys
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

from farm_agent.client import AgentClient
from farm_agent.journal import CommandJournal
from farm_agent.launch import Launcher
from farm_agent.lock import InstanceLock
from farm_agent.loop import AgentLoop
from farm_agent.search import find_shortcut
from farm_agent.settings import load_settings
from farm_agent.stop import ChromeStopper


def log_handlers(log_path, stdout=None):
    handlers = []
    if stdout is not None:
        handlers.append(logging.StreamHandler(stdout))
    if log_path:
        Path(log_path).parent.mkdir(parents=True, exist_ok=True)
        handlers.append(
            RotatingFileHandler(log_path, maxBytes=1024 * 1024, backupCount=3, encoding='utf-8')
        )
    return handlers


def _configure_log(log_path):
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(levelname)s %(message)s',
        handlers=log_handlers(log_path, stdout=sys.stdout),
    )


def main(argv=None):
    del argv
    root = Path(__file__).resolve().parent.parent
    settings_path = root / 'farm_agent.local.json'
    settings = load_settings(settings_path)
    if not settings.log_path:
        settings.log_path = str(root / 'logs' / 'farm_agent.log')
    if not settings.journal_path:
        settings.journal_path = str(root / 'logs' / 'farm_agent.journal.json')
    if not settings.lock_path:
        settings.lock_path = str(root / 'logs' / 'farm_agent.lock')
    settings.save()
    _configure_log(settings.log_path)
    lock = InstanceLock(settings.lock_path)
    if not lock.acquire():
        logging.info('Агент уже запущен на этом ПК.')
        return 1
    try:
        logging.info('Агент запущен, worker_id=%s, стол %s', settings.worker_id, settings.profiles_dir)
        loop = AgentLoop(
            settings=settings,
            client=AgentClient(settings.server_url, settings.token),
            find_shortcut=find_shortcut,
            launcher=Launcher(),
            stopper=ChromeStopper(),
            journal=CommandJournal(settings.journal_path),
            sleeper=time.sleep,
        )
        loop.run_forever()
    finally:
        lock.release()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
