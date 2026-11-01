import json
from pathlib import Path


class CommandJournal:
    def __init__(self, path):
        self._path = Path(path)

    def _load(self):
        if not self._path.exists():
            return {}
        return json.loads(self._path.read_text(encoding='utf-8'))

    def _save(self, data):
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding='utf-8',
        )

    def get(self, command_id):
        return self._load().get(str(command_id))

    def remember(self, command_id, state, error_text=''):
        data = self._load()
        data[str(command_id)] = {
            'state': state,
            'error_text': error_text,
        }
        self._save(data)
