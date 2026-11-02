import logging
import urllib.error


class AgentLoop:
    def __init__(
        self,
        settings,
        client,
        find_shortcut,
        launcher,
        stopper,
        closer,
        journal,
        sleeper,
        poll_sec=4,
        max_backoff_sec=60,
        agent_version='1',
    ):
        self._settings = settings
        self._client = client
        self._find_shortcut = find_shortcut
        self._launcher = launcher
        self._stopper = stopper
        self._closer = closer
        self._journal = journal
        self._sleeper = sleeper
        self._poll_sec = poll_sec
        self._max_backoff_sec = max_backoff_sec
        self._agent_version = agent_version
        self._backoff_sec = poll_sec

    def step(self):
        payload = self._client.poll(self._settings.worker_id, self._agent_version)
        self._backoff_sec = int(payload.get('poll_after_sec') or self._poll_sec)
        commands = list(payload.get('commands') or [])
        for command in commands:
            self._handle(command)
        return self._backoff_sec

    def run_forever(self):
        while True:
            try:
                pause = self.step()
                self._sleeper(pause)
            except (OSError, urllib.error.URLError) as error:
                logging.info('Опрос агента не удался: %s', error)
                self._backoff_sec = min(self._backoff_sec * 2, self._max_backoff_sec)
                self._sleeper(self._backoff_sec)

    def _handle(self, command):
        command_id = str(command.get('id') or '')
        action = command.get('action')
        remembered = self._journal.get(command_id)
        if remembered:
            logging.info('Повтор итога команды %s без запуска', command_id)
            self._client.result(
                command_id,
                remembered.get('state'),
                remembered.get('error_text') or '',
            )
            return
        self._client.ack(command_id)
        if action == 'open':
            state, error_text = self._open(command.get('email') or '')
        elif action == 'stop_chrome':
            ok, error_text = self._stopper.stop()
            state = 'opened' if ok else 'failed'
        elif action == 'close':
            state, error_text = self._close(command.get('email') or '')
        else:
            state = 'failed'
            error_text = 'команда не поддерживается'
        self._journal.remember(command_id, state, error_text)
        logging.info(
            'Команда %s действие %s email %s итог %s %s',
            command_id,
            action,
            command.get('email') or '',
            state,
            error_text,
        )
        self._client.result(command_id, state, error_text)

    def _open(self, email):
        path, error_text = self._shortcut(email)
        if error_text:
            return 'failed', error_text
        ok, error_text = self._launcher.open_file(path)
        if ok:
            return 'opened', ''
        return 'failed', error_text

    def _close(self, email):
        path, error_text = self._shortcut(email)
        if error_text:
            return 'failed', error_text
        ok, error_text = self._closer.close(path)
        if ok:
            return 'opened', ''
        return 'failed', error_text

    def _shortcut(self, email):
        found = self._find_shortcut(self._settings.profiles_dir, email)
        if found.error:
            names = ', '.join(found.names)
            text = found.error
            if names:
                text = '%s: %s' % (found.error, names)
            logging.info('Поиск ярлыка %s: %s', email, text)
            return None, text
        logging.info('Найден ярлык %s: %s', email, found.path)
        return found.path, ''
