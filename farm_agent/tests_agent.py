import io
import json
import tempfile
import unittest
from logging import StreamHandler
from logging.handlers import RotatingFileHandler
from pathlib import Path
from urllib.request import Request

from farm_agent.__main__ import log_handlers
from farm_agent.client import AgentClient
from farm_agent.journal import CommandJournal
from farm_agent.launch import Launcher, window_rect
from farm_agent.lock import InstanceLock
from farm_agent.loop import AgentLoop
from farm_agent.search import find_shortcut
from farm_agent.settings import AgentSettings, desktop_dir, load_settings
from farm_agent.stop import ChromeStopper


class IdleCloser:
    def close(self, path):
        del path
        return True, ''


class FakeSettings:
    def __init__(self, profiles_dir, worker_id='pc-1'):
        self.profiles_dir = profiles_dir
        self.worker_id = worker_id


class FakeClient:
    def __init__(self, commands):
        self.commands = commands
        self.acks = []
        self.results = []
        self.polls = 0

    def poll(self, worker_id, agent_version):
        del worker_id, agent_version
        self.polls += 1
        return {'commands': list(self.commands), 'poll_after_sec': 4}

    def ack(self, command_id):
        self.acks.append(command_id)

    def result(self, command_id, state, error_text=''):
        self.results.append((command_id, state, error_text))


class AgentUnitTests(unittest.TestCase):
    def test_журнал_помнит_итог(self):
        with tempfile.TemporaryDirectory() as raw:
            journal = CommandJournal(Path(raw) / 'j.json')
            journal.remember('c1', 'failed', 'не найден ярлык')
            saved = journal.get('c1')
            self.assertEqual(saved['state'], 'failed')
            self.assertEqual(saved['error_text'], 'не найден ярлык')

    def test_замок_второй_экземпляр(self):
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / 'lock'
            first = InstanceLock(path)
            second = InstanceLock(path)
            self.assertTrue(first.acquire())
            self.assertFalse(second.acquire())
            first.release()
            self.assertTrue(second.acquire())
            second.release()

    def test_замок_мёртвый_pid_не_держит(self):
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / 'lock'
            path.write_text('999999', encoding='utf-8')
            lock = InstanceLock(path)
            self.assertTrue(lock.acquire())
            lock.release()

    def test_запуск_ярлыка_через_startfile(self):
        calls = []
        restores = []

        def fake_start(path, show_cmd=None):
            calls.append((path, show_cmd))

        launcher = Launcher(
            start=fake_start,
            sleep=lambda _sec: None,
            restore_chrome=lambda before: restores.append(before),
            list_chrome=lambda: {7},
        )
        ok, text = launcher.open_file(r'D:\mail@x.com - Chrome.lnk')
        self.assertTrue(ok)
        self.assertEqual(text, '')
        self.assertEqual(calls, [(r'D:\mail@x.com - Chrome.lnk', 1)])
        self.assertEqual(restores[0], {7})
        self.assertEqual(len(restores), 6)

    def test_окно_центр_1024(self):
        self.assertEqual(window_rect(1920, 1080), (448, 156, 1024, 768))
        self.assertEqual(window_rect(800, 600), (0, 0, 800, 600))

    def test_запуск_ошибка_startfile(self):
        def fake_start(path, show_cmd=None):
            del path, show_cmd
            raise OSError(2, 'не найден')

        launcher = Launcher(start=fake_start, sleep=lambda _sec: None)
        ok, text = launcher.open_file(r'D:\a.lnk')
        self.assertFalse(ok)
        self.assertIn('не найден', text)

    def test_стоп_коды_0_и_128(self):
        for code in (0, 128):
            stopper = ChromeStopper(run=lambda _cmd, **_kwargs: type('R', (), {'returncode': code})())
            ok, text = stopper.stop()
            self.assertTrue(ok)
            self.assertEqual(text, '')
        stopper = ChromeStopper(run=lambda _cmd, **_kwargs: type('R', (), {'returncode': 1})())
        ok, text = stopper.stop()
        self.assertFalse(ok)

    def test_клиент_шлёт_токен(self):
        seen = {}

        def fake_open(request, timeout=20):
            del timeout
            seen['url'] = request.full_url
            seen['token'] = request.headers.get('X-agent-token') or request.headers.get('X-Agent-Token')
            return FakeHttp(json.dumps({'ok': True, 'data': {'commands': []}}))

        client = AgentClient('http://127.0.0.1:8000', 'secret', opener=fake_open)
        payload = client.poll('pc-1', '1')
        self.assertTrue(seen['url'].endswith('/agent/v1/poll'))
        self.assertEqual(seen['token'], 'secret')
        self.assertEqual(payload.get('commands'), [])
        self.assertIsInstance(Request('http://example'), Request)

    def test_клиент_достаёт_data(self):
        def fake_open(request, timeout=20):
            del request, timeout
            return FakeHttp(json.dumps({
                'ok': True,
                'data': {
                    'commands': [{'id': '1', 'action': 'open', 'email': 'a@b.com'}],
                    'poll_after_sec': 4,
                },
            }))

        client = AgentClient('http://127.0.0.1:8000', 'secret', opener=fake_open)
        payload = client.poll('pc-1', '1')
        self.assertEqual(payload['commands'][0]['email'], 'a@b.com')
        self.assertEqual(payload['poll_after_sec'], 4)

    def test_лог_без_консоли_только_файл(self):
        with tempfile.TemporaryDirectory() as raw:
            log_path = str(Path(raw) / 'agent.log')
            handlers = log_handlers(log_path, stdout=None)
            self.assertEqual(len(handlers), 1)
            self.assertIsInstance(handlers[0], RotatingFileHandler)
            for handler in handlers:
                handler.close()

    def test_лог_с_консолью_два_обработчика(self):
        with tempfile.TemporaryDirectory() as raw:
            log_path = str(Path(raw) / 'agent.log')
            handlers = log_handlers(log_path, stdout=io.StringIO())
            kinds = [type(handler) for handler in handlers]
            self.assertEqual(len(handlers), 2)
            self.assertIn(StreamHandler, kinds)
            for handler in handlers:
                handler.close()

    def test_пустой_каталог_это_рабочий_стол(self):
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / 'farm_agent.local.json'
            desktop = Path(raw) / 'Desktop'
            desktop.mkdir()
            settings = load_settings(path, resolve_desktop=lambda: desktop)
            self.assertEqual(Path(settings.profiles_dir), desktop)
            settings.save()
            saved = json.loads(path.read_text(encoding='utf-8'))
            self.assertEqual(saved.get('profiles_dir') or '', '')
            self.assertTrue(desktop_dir().is_absolute())
            self.assertIsInstance(AgentSettings({}, path).worker_id, str)

    def test_явный_каталог_не_подменяем_столом(self):
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / 'farm_agent.local.json'
            path.write_text(json.dumps({'profiles_dir': 'D:\\profiles'}), encoding='utf-8')
            desktop = Path(raw) / 'Desktop'
            desktop.mkdir()
            settings = load_settings(path, resolve_desktop=lambda: desktop)
            self.assertEqual(settings.profiles_dir, 'D:\\profiles')

    def test_цикл_open_успех_и_повтор_без_запуска(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            shortcut = root / 'a@b.com.lnk'
            shortcut.write_text('', encoding='utf-8')
            launched = []
            client = FakeClient([
                {'id': 'c1', 'action': 'open', 'email': 'a@b.com'},
            ])
            loop = AgentLoop(
                settings=FakeSettings(str(root)),
                client=client,
                find_shortcut=find_shortcut,
                launcher=type('L', (), {'open_file': lambda _self, path: launched.append(path) or (True, '')})(),
                stopper=ChromeStopper(run=lambda _cmd, **_kw: type('R', (), {'returncode': 0})()),
                closer=IdleCloser(),
                journal=CommandJournal(root / 'j.json'),
                sleeper=lambda _sec: None,
            )
            loop.step()
            self.assertEqual(client.acks, ['c1'])
            self.assertEqual(client.results[0][:2], ('c1', 'opened'))
            self.assertEqual(launched, [shortcut])
            client.commands = [{'id': 'c1', 'action': 'open', 'email': 'a@b.com'}]
            loop.step()
            self.assertEqual(len(launched), 1)
            self.assertEqual(len(client.results), 2)

    def test_цикл_нет_файла_и_два_файла(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / 'a@b.com.1').write_text('', encoding='utf-8')
            (root / 'a@b.com.2').write_text('', encoding='utf-8')
            launched = []
            client = FakeClient([
                {'id': 'c1', 'action': 'open', 'email': 'a@b.com'},
                {'id': 'c2', 'action': 'open', 'email': 'none@x.com'},
            ])
            loop = AgentLoop(
                settings=FakeSettings(str(root)),
                client=client,
                find_shortcut=find_shortcut,
                launcher=type('L', (), {'open_file': lambda _self, path: launched.append(path) or (True, '')})(),
                stopper=ChromeStopper(run=lambda _cmd, **_kw: type('R', (), {'returncode': 0})()),
                closer=IdleCloser(),
                journal=CommandJournal(root / 'j.json'),
                sleeper=lambda _sec: None,
            )
            loop.step()
            self.assertEqual(launched, [])
            self.assertEqual(client.results[0][1], 'failed')
            self.assertIn('несколько ярлыков', client.results[0][2])
            self.assertEqual(client.results[1][2], 'не найден ярлык')

    def test_цикл_обрыв_сети_растёт_пауза(self):
        sleeps = []

        class BrokenClient:
            def poll(self, worker_id, agent_version):
                del worker_id, agent_version
                raise OSError('сеть')

        class StopLoop(Exception):
            pass

        def sleeper(sec):
            sleeps.append(sec)
            raise StopLoop()

        loop = AgentLoop(
            settings=FakeSettings('.'),
            client=BrokenClient(),
            find_shortcut=find_shortcut,
            launcher=Launcher(start=lambda _path, show_cmd=None: None, sleep=lambda _s: None),
            stopper=ChromeStopper(run=lambda _c, **_k: type('R', (), {'returncode': 0})()),
            closer=IdleCloser(),
            journal=CommandJournal(Path(tempfile.gettempdir()) / 'unused-journal.json'),
            sleeper=sleeper,
            poll_sec=4,
            max_backoff_sec=60,
        )
        with self.assertRaises(StopLoop):
            loop.run_forever()
        self.assertEqual(sleeps[0], 8)


class FakeHttp:
    def __init__(self, body):
        self._body = body.encode('utf-8')

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        del exc_type, exc, tb
        return False


if __name__ == '__main__':
    unittest.main()
