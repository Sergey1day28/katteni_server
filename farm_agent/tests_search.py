import tempfile
import unittest
from pathlib import Path

from farm_agent.search import find_shortcut


class SearchTests(unittest.TestCase):
    def test_ярлык_email_тире_chrome(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            target = root / 'koluchiylosos@gmail.com - Chrome.lnk'
            target.write_text('', encoding='utf-8')
            result = find_shortcut(root, 'koluchiylosos@gmail.com')
            self.assertEqual(result.path, target)
            self.assertIsNone(result.error)

    def test_один_файл_в_корне(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            target = root / 'user@mail.com.lnk'
            target.write_text('', encoding='utf-8')
            result = find_shortcut(root, 'user@mail.com')
            self.assertEqual(result.path, target)
            self.assertIsNone(result.error)

    def test_один_файл_в_подкаталоге(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            nested = root / 'folder'
            nested.mkdir()
            target = nested / 'acc-user@mail.com'
            target.write_text('', encoding='utf-8')
            result = find_shortcut(root, 'user@mail.com')
            self.assertEqual(result.path, target)
            self.assertIsNone(result.error)

    def test_нет_файла(self):
        with tempfile.TemporaryDirectory() as raw:
            result = find_shortcut(Path(raw), 'user@mail.com')
            self.assertIsNone(result.path)
            self.assertEqual(result.error, 'не найден ярлык')

    def test_несколько_файлов(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            first = root / 'user@mail.com.lnk'
            second = root / 'sub'
            second.mkdir()
            extra = second / 'copy-user@mail.com.bat'
            first.write_text('', encoding='utf-8')
            extra.write_text('', encoding='utf-8')
            result = find_shortcut(root, 'user@mail.com')
            self.assertIsNone(result.path)
            self.assertEqual(result.error, 'несколько ярлыков')
            self.assertEqual(sorted(result.names), sorted([first.name, extra.name]))

    def test_не_заходит_глубже_одного_уровня(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            deep = root / 'a' / 'b'
            deep.mkdir(parents=True)
            (deep / 'user@mail.com.lnk').write_text('', encoding='utf-8')
            result = find_shortcut(root, 'user@mail.com')
            self.assertEqual(result.error, 'не найден ярлык')


if __name__ == '__main__':
    unittest.main()
