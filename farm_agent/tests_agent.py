import json
import tempfile
import unittest
from pathlib import Path
from urllib.request import Request

from farm_agent.client import AgentClient
from farm_agent.journal import CommandJournal
from farm_agent.launch import Launcher
from farm_agent.lock import InstanceLock
from farm_agent.loop import AgentLoop
from farm_agent.search import find_shortcut
from farm_agent.settings import AgentSettings, load_settings
from farm_agent.stop import ChromeStopper


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


class FakeProcess:
    def __init__(self, code):
        self._code = code

    def poll(self):
        return self._code


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

    def test_запуск_ненулевой_код_это_ошибка(self):
        calls = []

        def fake_popen(command):
            calls.append(command)
            return FakeProcess(1)

        launcher = Launcher(popen=fake_popen, sleep=lambda _sec: None)
        ok, text = launcher.open_file('D:\\a.lnk')
        self.assertFalse(ok)
        self.assertEqual(text, 'код 1')
        self.assertEqual(calls[0][:2], ['cmd', '/c'])

    def test_запуск_процесс_жив_это_успех(self):
        launcher = Launcher(popen=lambda _command: FakeProcess(None), sleep=lambda _sec: None)
        ok, text = launcher.open_file('D:\\a.lnk')
        self.assertTrue(ok)
        self.assertEqual(text, '')

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
        client.poll('pc-1', '1')
        self.assertTrue(seen['url'].endswith('/agent/v1/poll'))
        self.assertEqual(seen['token'], 'secret')
        self.assertIsInstance(Request('http://example'), Request)

    def test_настройки_спрашивают_каталог_один_раз(self):
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / 'farm_agent.local.json'
            asked = []

            def ask(_prompt):
                asked.append(True)
                return 'D:\\profiles'

            first = load_settings(path, ask_profiles_dir=ask)
            second = load_settings(path, ask_profiles_dir=ask)
            self.assertEqual(first.profiles_dir, 'D:\\profiles')
            self.assertEqual(second.profiles_dir, 'D:\\profiles')
            self.assertEqual(len(asked), 1)
            self.assertIsInstance(AgentSettings({}, path).worker_id, str)

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
            launcher=Launcher(popen=lambda _c: FakeProcess(None), sleep=lambda _s: None),
            stopper=ChromeStopper(run=lambda _c, **_k: type('R', (), {'returncode': 0})()),
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
