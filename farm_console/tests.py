import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from farm_core.models import Account, Folder, MarketFilter, SbcAssignment, SbcSet
from farm_core.folder_filter import default_filter
from farm_core.tokens import hash_token
from farm_core.models import Worker


class ConsoleTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('op', password='pass')
        Worker.objects.create(worker_id='this-pc', token_hash=hash_token('x'), enabled=True)
        Account.objects.create(ea_account_id=1, email='a@b.com')
        self.client.force_login(self.user)

    def test_экран_пк_ставит_open(self):
        response = self.client.post('/farm/pc/', {'action': 'open', 'email': 'a@b.com'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'a@b.com')
        self.assertContains(response, 'open')

    def test_экран_фермы_сохраняет_порог_зависания(self):
        previous = (
            getattr(settings, 'STALL_MINUTES', 5),
            getattr(settings, 'STALL_KILL_CHROME', False),
            getattr(settings, 'PAGE_NOT_LOADED_CLOSE', False),
        )
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / 'farm.local.json'
            path.write_text(json.dumps({
                'stall_minutes': 5,
                'stall_kill_chrome': False,
                'page_not_loaded_close': False,
            }), encoding='utf-8')
            try:
                with patch('farm_console.views.LOCAL_SETTINGS_PATH', path):
                    response = self.client.post('/farm/', {
                        'action': 'stall',
                        'stall_minutes': '7',
                        'stall_kill_chrome': '1',
                    })
                saved = json.loads(path.read_text(encoding='utf-8'))
            finally:
                settings.STALL_MINUTES = previous[0]
                settings.STALL_KILL_CHROME = previous[1]
                settings.PAGE_NOT_LOADED_CLOSE = previous[2]
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Порог зависания сохранён')
        self.assertEqual(saved['stall_minutes'], 7)
        self.assertTrue(saved['stall_kill_chrome'])

    def test_аккаунты_видны(self):
        Account.objects.create(email='rich@x.com', balance=9000)
        Account.objects.create(email='poor@x.com', balance=10)
        response = self.client.get('/farm/accounts/')
        self.assertContains(response, 'a@b.com')
        self.assertContains(response, 'http-equiv="refresh"')
        self.assertContains(response, 'content="60"')
        self.assertNotContains(response, 'EA id')
        self.assertNotContains(response, '>Бан<')
        self.assertNotContains(response, '<th>Имя</th>')
        html = response.content.decode('utf-8')
        self.assertLess(html.index('rich@x.com'), html.index('poor@x.com'))
        self.assertLess(html.index('poor@x.com'), html.index('a@b.com'))

    def test_папка_создаётся_без_фильтра(self):
        response = self.client.post('/farm/folders/new/', {'name': 'Свои'})
        self.assertEqual(response.status_code, 302)
        folder = Folder.objects.get(name='Свои')
        self.assertEqual(folder.filter, default_filter())

    def test_главный_экран_запускает_круг(self):
        folder = Folder.objects.create(name='Свои', filter=default_filter(), open_at_a_time=1)
        response = self.client.post('/farm/', {'action': 'start', 'folder_id': str(folder.id)})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'команд')
        self.assertTrue(folder.runs.exists())

    def test_шаблон_не_связывался_пишет_фильтр(self):
        folder = Folder.objects.create(name='Свои', filter=default_filter())
        response = self.client.post(
            '/farm/folders/%s/' % folder.id,
            {'action': 'template', 'template': 'unlinked'},
        )
        self.assertEqual(response.status_code, 200)
        folder.refresh_from_db()
        self.assertEqual(folder.filter, [{'field': 'linked', 'op': 'eq', 'value': False}])

    def test_шаблон_приоритета_пишет_фильтр(self):
        folder = Folder.objects.create(name='Свои', filter=default_filter())
        response = self.client.post(
            '/farm/folders/%s/' % folder.id,
            {'action': 'template', 'template': 'priority'},
        )
        self.assertEqual(response.status_code, 200)
        folder.refresh_from_db()
        self.assertEqual(folder.filter[-1]['field'], 'priority_sbc_uncollected')

    def test_карточка_снимает_назначение_сбч(self):
        account = Account.objects.get(email='a@b.com')
        sbc_set = SbcSet.objects.create(name='Набор')
        SbcAssignment.objects.create(account=account, sbc_set=sbc_set)
        response = self.client.post(
            '/farm/accounts/%s/' % account.id,
            {'action': 'unassign'},
        )
        self.assertContains(response, 'Набор СБЧ снят')
        self.assertFalse(
            SbcAssignment.objects.filter(account=account, state=SbcAssignment.STATE_ACTIVE).exists()
        )

    def test_фильтры_заменяют_рынок(self):
        response = self.client.post('/farm/filters/', {
            'action': 'replace_market',
            'market_json': '[{"title": "gold", "payload": {"min": 1}}]',
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Список рынка заменён')
        self.assertTrue(MarketFilter.objects.filter(title='gold').exists())

    def test_сбч_неделя_создаёт_папку(self):
        response = self.client.post('/farm/sbc/', {
            'action': 'priority',
            'name': 'Не собрали приоритет',
        })
        self.assertEqual(response.status_code, 302)
        folder = Folder.objects.get(name='Не собрали приоритет')
        self.assertEqual(folder.filter[-1]['field'], 'priority_sbc_uncollected')

    def test_экран_ошибок_открывается(self):
        response = self.client.get('/farm/errors/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Ошибки за 7 дней')
        self.assertNotContains(response, 'http-equiv="refresh"')

    def test_все_экраны_пульта_открываются(self):
        folder = Folder.objects.create(name='Свои', filter=default_filter())
        account = Account.objects.get(email='a@b.com')
        pages = [
            '/farm/',
            '/farm/folders/%s/' % folder.id,
            '/farm/schedule/',
            '/farm/pc/',
            '/farm/accounts/',
            '/farm/accounts/%s/' % account.id,
            '/farm/filters/',
            '/farm/sbc/',
            '/farm/errors/',
            '/farm/import/',
        ]
        for url in pages:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200, url)

    def test_импорт_csv_с_экрана(self):
        page = self.client.get('/farm/import/')
        self.assertContains(page, 'type="file"')
        self.assertNotContains(page, 'http-equiv="refresh"')
        empty = self.client.post('/farm/import/', {'import_kind': 'csv'})
        self.assertContains(empty, 'Выберите файл CSV')
        self.assertEqual(Account.objects.filter(email='ui@x.com').count(), 0)
        uploaded = SimpleUploadedFile(
            'accs.csv',
            b'email,totp\nui@x.com,JBSWY3DPEHPK3PXP\n',
            content_type='text/csv',
        )
        response = self.client.post('/farm/import/', {'csv_file': uploaded})
        self.assertEqual(response.status_code, 200)
        account = Account.objects.get(email='ui@x.com')
        self.assertIsNone(account.ea_account_id)
        self.assertEqual(account.login_secret.totp_seed, 'JBSWY3DPEHPK3PXP')
        self.assertContains(response, 'Импорт завершён')
        self.assertContains(response, 'accs.csv')
