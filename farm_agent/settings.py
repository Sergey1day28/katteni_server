import json
from pathlib import Path


class AgentSettings:
    def __init__(self, data, path):
        self.path = Path(path)
        self.server_url = data.get('server_url') or 'http://127.0.0.1:8000'
        self.worker_id = data.get('worker_id') or 'this-pc'
        self.token = data.get('token') or ''
        self.profiles_dir = data.get('profiles_dir') or ''
        self.log_path = data.get('log_path') or ''
        self.journal_path = data.get('journal_path') or ''
        self.lock_path = data.get('lock_path') or ''

    def as_dict(self):
        return {
            'server_url': self.server_url,
            'worker_id': self.worker_id,
            'token': self.token,
            'profiles_dir': self.profiles_dir,
            'log_path': self.log_path,
            'journal_path': self.journal_path,
            'lock_path': self.lock_path,
        }

    def save(self):
        self.path.write_text(
            json.dumps(self.as_dict(), ensure_ascii=False, indent=2) + '\n',
            encoding='utf-8',
        )


def load_settings(path, ask_profiles_dir=None):
    path = Path(path)
    data = {}
    if path.exists():
        data = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(data, dict):
            raise ValueError('farm_agent.local.json должен быть объектом JSON.')
    settings = AgentSettings(data, path)
    if not settings.profiles_dir:
        if ask_profiles_dir is None:
            raise ValueError('Нет каталога профилей. Укажите profiles_dir.')
        settings.profiles_dir = ask_profiles_dir('Каталог профилей Chrome (подсказка D:\\): ')
        settings.save()
    return settings
