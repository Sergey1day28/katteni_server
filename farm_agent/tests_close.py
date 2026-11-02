import json
import tempfile
import unittest
from pathlib import Path

from farm_agent.close import ProfileCloser, list_chrome_processes
from farm_agent.journal import CommandJournal
from farm_agent.loop import AgentLoop
from farm_agent.search import find_shortcut
from farm_agent.shortcut import (
    app_model_id,
    command_matches,
    is_shared_chrome_dir,
    profile_directory,
    read_lnk_text,
    read_shortcut_arguments,
    user_data_dir,
)


def _completed(code, stdout='', stderr=''):
    return type('R', (), {'returncode': code, 'stdout': stdout, 'stderr': stderr})()


class ShortcutTests(unittest.TestCase):
    def test_каталог_в_кавычках_и_без(self):
        self.assertEqual(
            user_data_dir('--user-data-dir="C:\\profiles\\a " --profile-directory="Profile"'),
            r'C:\profiles\a',
        )
        self.assertEqual(
            user_data_dir('--user-data-dir=C:/profiles/a/'),
            'C:/profiles/a',
        )
        self.assertEqual(user_data_dir('--profile-directory=Profile'), '')
        self.assertEqual(profile_directory('--profile-directory="Profile 20"'), 'Profile 20')
        self.assertEqual(app_model_id('x Chrome.UserData.Profile20 y', 'Profile 1'), 'Chrome.UserData.Profile20')
        self.assertEqual(app_model_id('', 'Profile 20'), 'Chrome.UserData.Profile20')

    def test_общий_каталог_только_user_data(self):
        shared = r'C:\Users\a\AppData\Local\Google\Chrome\User Data'
        own = shared + r'\AutoCreatedProfile1'
        self.assertTrue(is_shared_chrome_dir(shared))
        self.assertFalse(is_shared_chrome_dir(own))

    def test_совпадение_не_цепляет_более_длинное_имя(self):
        directory = r'C:\data\AutoCreatedProfile1'
        own = r'chrome.exe --user-data-dir="C:\data\AutoCreatedProfile1"'
        longer = r'chrome.exe --user-data-dir="C:\data\AutoCreatedProfile10"'
        child = r'chrome.exe --user-data-dir=C:\data\AutoCreatedProfile1\Default'
        self.assertTrue(command_matches(own, directory))
        self.assertFalse(command_matches(longer, directory))
        self.assertTrue(command_matches(child, directory))
        self.assertFalse(command_matches('', directory))

    def test_чтение_аргументов_ярлыка(self):
        seen = {}

        def run(cmd, capture_output=True, text=True):
            del capture_output, text
            seen['cmd'] = cmd
            return _completed(0, stdout=' --user-data-dir="D:\\p" \n')

        arguments = read_shortcut_arguments(r"D:\a'b.lnk", run)
        self.assertEqual(arguments, '--user-data-dir="D:\\p"')
        self.assertIn("D:\\a''b.lnk", seen['cmd'][3])

        def fail(cmd, capture_output=True, text=True):
            del cmd, capture_output, text
            return _completed(1, stderr='нет')

        with self.assertRaises(OSError):
            read_shortcut_arguments(r'D:\a.lnk', fail)

    def test_текст_ярлыка_utf16(self):
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / 'a.lnk'
            path.write_bytes('--profile-directory="Profile 20"'.encode('utf-16le'))
            text = read_lnk_text(path)
            self.assertIn('Profile 20', profile_directory(text))


class ProcessListTests(unittest.TestCase):
    def test_пустой_один_и_список(self):
        def run_empty(cmd, capture_output=True, text=True):
            del cmd, capture_output, text
            return _completed(0, stdout='  ')

        self.assertEqual(list_chrome_processes(run_empty), [])

        def run_one(cmd, capture_output=True, text=True):
            del cmd, capture_output, text
            body = json.dumps({'ProcessId': 4, 'CommandLine': 'chrome --a'})
            return _completed(0, stdout=body)

        self.assertEqual(list_chrome_processes(run_one), [(4, 'chrome --a')])

        def run_many(cmd, capture_output=True, text=True):
            del cmd, capture_output, text
            body = json.dumps([
                {'ProcessId': 1, 'CommandLine': None},
                {'ProcessId': 2, 'CommandLine': 'x'},
            ])
            return _completed(0, stdout=body)

        self.assertEqual(list_chrome_processes(run_many), [(1, ''), (2, 'x')])

    def test_сбой_powershell_и_не_json(self):
        def fail(cmd, capture_output=True, text=True):
            del cmd, capture_output, text
            return _completed(1, stderr='ошибка')

        with self.assertRaises(OSError):
            list_chrome_processes(fail)

        def bad(cmd, capture_output=True, text=True):
            del cmd, capture_output, text
            return _completed(0, stdout='не json')

        with self.assertRaises(OSError):
            list_chrome_processes(bad)


class CloserTests(unittest.TestCase):
    def test_убивает_только_свой_каталог(self):
        killed = []

        def run(cmd, capture_output=True, text=True):
            del capture_output, text
            killed.append(cmd)
            return _completed(0)

        closer = ProfileCloser(
            run=run,
            read_arguments=lambda path: '--user-data-dir="C:\\profiles\\a"',
            list_processes=lambda: [
                (9, r'--user-data-dir="C:\profiles\a"'),
                (10, r'--user-data-dir="C:\profiles\b"'),
            ],
        )
        ok, text = closer.close(r'D:\a.lnk')
        self.assertTrue(ok)
        self.assertEqual(text, '')
        self.assertEqual(killed, [['taskkill', '/PID', '9', '/T', '/F']])

    def test_общий_каталог_не_вызывает_taskkill(self):
        killed = []
        listed = []

        def run(cmd, capture_output=True, text=True):
            del capture_output, text
            killed.append(cmd)
            return _completed(0)

        def list_processes():
            listed.append(1)
            return [(1, 'chrome')]

        closer = ProfileCloser(
            run=run,
            read_arguments=lambda path: (
                r'--user-data-dir="C:\Users\a\AppData\Local\Google\Chrome\User Data"'
            ),
            list_processes=list_processes,
        )
        ok, text = closer.close(r'D:\a.lnk')
        self.assertFalse(ok)
        self.assertEqual(text, 'общий каталог Chrome')
        self.assertEqual(killed, [])
        self.assertEqual(listed, [])

    def test_уже_закрыт_нет_ярлыка_и_коды(self):
        closer = ProfileCloser(
            run=lambda cmd, **_kw: _completed(0),
            read_arguments=lambda path: '--user-data-dir="C:\\profiles\\a"',
            list_processes=lambda: [],
        )
        ok, text = closer.close(r'D:\a.lnk')
        self.assertTrue(ok)
        self.assertEqual(text, '')

        ok, text = closer.close(r'D:\a.url')
        self.assertFalse(ok)
        self.assertEqual(text, 'не ярлык Chrome')

        def boom(path):
            del path
            raise OSError(1, 'нет')

        closer = ProfileCloser(read_arguments=boom, list_processes=lambda: [])
        ok, text = closer.close(r'D:\a.lnk')
        self.assertEqual(text, 'не прочитаны аргументы ярлыка')

        closer = ProfileCloser(
            read_arguments=lambda path: '--no-profile',
            list_processes=lambda: [],
        )
        ok, text = closer.close(r'D:\a.lnk')
        self.assertEqual(text, 'в ярлыке нет профиля Chrome')

        closed = []
        closer = ProfileCloser(
            read_arguments=lambda path: 'Chrome.UserData.Profile20 --profile-directory="Profile 20"',
            list_processes=lambda: (_ for _ in ()).throw(AssertionError('процессы')),
            list_windows=lambda: [
                (5, 'Chrome.UserData.Profile20'),
                (6, 'Chrome.UserData.Profile1'),
            ],
            close_window=closed.append,
        )
        ok, text = closer.close(r'D:\a.lnk')
        self.assertTrue(ok)
        self.assertEqual(text, '')
        self.assertEqual(closed, [5])

        def fail_list():
            raise OSError(1, 'cim')

        closer = ProfileCloser(
            read_arguments=lambda path: '--user-data-dir="C:\\profiles\\a"',
            list_processes=fail_list,
        )
        ok, text = closer.close(r'D:\a.lnk')
        self.assertEqual(text, 'не прочитан список процессов')

        codes = []

        def run(cmd, capture_output=True, text=True):
            del cmd, capture_output, text
            code = 1 if not codes else 5
            codes.append(code)
            return _completed(code)

        closer = ProfileCloser(
            run=run,
            read_arguments=lambda path: '--user-data-dir="C:\\profiles\\a"',
            list_processes=lambda: [
                (1, r'--user-data-dir="C:\profiles\a"'),
                (2, r'--user-data-dir="C:\profiles\a"'),
            ],
        )
        ok, text = closer.close(r'D:\a.lnk')
        self.assertFalse(ok)
        self.assertEqual(text, 'код 1')
        self.assertEqual(len(codes), 2)

        closer = ProfileCloser(
            run=lambda cmd, **_kw: _completed(128),
            read_arguments=lambda path: '--user-data-dir="C:\\profiles\\a"',
            list_processes=lambda: [(3, r'--user-data-dir="C:\profiles\a"')],
        )
        ok, text = closer.close(r'D:\a.lnk')
        self.assertTrue(ok)
        self.assertEqual(text, '')


class FakeSettings:
    def __init__(self, profiles_dir):
        self.profiles_dir = profiles_dir
        self.worker_id = 'pc-1'


class FakeClient:
    def __init__(self, commands):
        self.commands = commands
        self.acks = []
        self.results = []

    def poll(self, worker_id, agent_version):
        del worker_id, agent_version
        return {'commands': self.commands, 'poll_after_sec': 4}

    def ack(self, command_id):
        self.acks.append(command_id)

    def result(self, command_id, state, error_text=''):
        self.results.append((command_id, state, error_text))


class LoopCloseTests(unittest.TestCase):
    def _loop(self, root, client, closer):
        return AgentLoop(
            settings=FakeSettings(str(root)),
            client=client,
            find_shortcut=find_shortcut,
            launcher=type('L', (), {'open_file': lambda _self, path: (True, '')})(),
            stopper=type('S', (), {'stop': lambda _self: (True, '')})(),
            closer=closer,
            journal=CommandJournal(root / 'j.json'),
            sleeper=lambda _sec: None,
        )

    def test_закрытие_и_повтор_без_второго_taskkill(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / 'a@b.com.lnk').write_text('', encoding='utf-8')
            killed = []

            def run(cmd, capture_output=True, text=True):
                del capture_output, text
                killed.append(list(cmd))
                return _completed(0)

            closer = ProfileCloser(
                run=run,
                read_arguments=lambda path: '--user-data-dir="C:\\profiles\\a"',
                list_processes=lambda: [(9, r'--user-data-dir="C:\profiles\a"')],
            )
            client = FakeClient([
                {'id': 'c1', 'action': 'close', 'email': 'a@b.com'},
            ])
            loop = self._loop(root, client, closer)
            loop.step()
            self.assertEqual(killed, [['taskkill', '/PID', '9', '/T', '/F']])
            self.assertEqual(client.results[0][:2], ('c1', 'opened'))
            client.commands = [{'id': 'c1', 'action': 'close', 'email': 'a@b.com'}]
            loop.step()
            self.assertEqual(len(killed), 1)
            self.assertEqual(len(client.results), 2)
            self.assertEqual(client.results[1][1], 'opened')

    def test_нет_ярлыка_и_два_ярлыка(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / 'a@b.com.1.lnk').write_text('', encoding='utf-8')
            (root / 'a@b.com.2.lnk').write_text('', encoding='utf-8')
            called = []
            closer = ProfileCloser(
                read_arguments=lambda path: called.append(path) or '',
                list_processes=lambda: [],
            )
            client = FakeClient([
                {'id': 'c1', 'action': 'close', 'email': 'a@b.com'},
                {'id': 'c2', 'action': 'close', 'email': 'none@x.com'},
            ])
            loop = self._loop(root, client, closer)
            loop.step()
            self.assertEqual(called, [])
            self.assertIn('несколько ярлыков', client.results[0][2])
            self.assertEqual(client.results[1][2], 'не найден ярлык')

    def test_общий_каталог_в_цикле(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / 'a@b.com.lnk').write_text('', encoding='utf-8')
            closer = ProfileCloser(
                run=lambda cmd, **_kw: _completed(0),
                read_arguments=lambda path: (
                    r'--user-data-dir="C:\Users\a\AppData\Local\Google\Chrome\User Data"'
                ),
                list_processes=lambda: [(1, 'chrome')],
            )
            client = FakeClient([
                {'id': 'c1', 'action': 'close', 'email': 'a@b.com'},
            ])
            loop = self._loop(root, client, closer)
            loop.step()
            self.assertEqual(client.results[0][1], 'failed')
            self.assertEqual(client.results[0][2], 'общий каталог Chrome')
