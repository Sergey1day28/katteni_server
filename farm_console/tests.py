import json
from datetime import time
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.utils import timezone

from farm_core.models import (
    Account,
    AgentCommand,
    Folder,
    MarketFilter,
    SbcAssignment,
    SbcAttempt,
    SbcSet,
    Schedule,
    Worker,
)
from farm_core.circle import start_folder
from farm_core.folder_filter import default_filter, replace_members
from farm_core.tokens import hash_token


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

    def test_карточка_папки_удаляет_папку(self):
        folder = Folder.objects.create(name='Свои', filter=default_filter())
        farm = self.client.get('/farm/')
        self.assertNotContains(farm, 'value="delete"')
        page = self.client.get('/farm/folders/%s/' % folder.id)
        self.assertContains(page, 'value="delete"')
        self.assertContains(page, 'Удалить')
        response = self.client.post('/farm/folders/%s/' % folder.id, {'action': 'delete'}, follow=True)
        self.assertRedirects(response, '/farm/folders/new/')
        self.assertContains(response, 'Папка удалена')
        self.assertFalse(Folder.objects.filter(id=folder.id).exists())
        self.assertTrue(Account.objects.filter(email='a@b.com').exists())

    def test_расписание_правится_и_время_24ч(self):
        folder = Folder.objects.create(name='Свои', filter=default_filter())
        created = self.client.post('/farm/schedule/', {
            'action': 'create',
            'name': 'утро',
            'folder_id': str(folder.id),
            'schedule_action': 'start',
            'days': ['0', '2'],
            'start_time': '09:30',
            'stop_time': '23:00',
            'enabled': '1',
        })
        self.assertEqual(created.status_code, 200)
        self.assertContains(created, 'Расписание создано')
        self.assertContains(created, '09:30')
        self.assertContains(created, '23:00')
        self.assertContains(created, 'пн')
        self.assertContains(created, 'ср')
        self.assertNotContains(created, 'p.m.')
        self.assertNotContains(created, 'a.m.')
        self.assertNotContains(created, 'type="time"')
        self.assertNotContains(created, 'гасить Chrome')
        self.assertContains(created, 'Кого открывать')
        self.assertContains(created, 'Распространить СБЧ на аккаунты')
        self.assertTrue(Schedule.objects.get(name='утро').kill_chrome_before)
        self.assertContains(created, 'schedule-summary')
        self.assertContains(created, '<th>Старт</th>')
        schedule = Schedule.objects.get(name='утро')
        saved = self.client.post('/farm/schedule/', {
            'action': 'save',
            'schedule_id': str(schedule.id),
            'name': 'вечер',
            'folder_id': str(folder.id),
            'schedule_action': 'continue',
            'days': ['1'],
            'start_time': '16:00',
            'stop_time': '22:15',
            'enabled': '1',
            'open_rule': 'uncollected_sbc',
            'assign_sbc': '1',
        })
        self.assertContains(saved, 'Расписание сохранено')
        schedule.refresh_from_db()
        self.assertEqual(schedule.name, 'вечер')
        self.assertEqual(schedule.action, Schedule.ACTION_CONTINUE)
        self.assertEqual(schedule.days, [1])
        self.assertEqual(schedule.start_time.strftime('%H:%M'), '16:00')
        self.assertEqual(schedule.stop_time.strftime('%H:%M'), '22:15')
        self.assertTrue(schedule.kill_chrome_before)
        self.assertEqual(schedule.open_rule, 'uncollected_sbc')
        self.assertTrue(schedule.assign_sbc)
        self.assertContains(saved, '16:00')
        self.assertContains(saved, 'value="save"')
        farm = self.client.get('/farm/')
        self.assertNotContains(farm, '16:00')
        self.assertNotContains(farm, 'Свои')
        deleted = self.client.post('/farm/schedule/', {
            'action': 'delete',
            'schedule_id': str(schedule.id),
        })
        self.assertContains(deleted, 'Расписание удалено')
        self.assertFalse(Schedule.objects.filter(id=schedule.id).exists())

    def test_расписание_дни_подпись(self):
        folder = Folder.objects.create(name='Свои', filter=default_filter())
        empty = self.client.post('/farm/schedule/', {
            'action': 'create',
            'name': 'пусто',
            'folder_id': str(folder.id),
            'schedule_action': 'start',
            'start_time': '09:00',
            'stop_time': '23:00',
            'enabled': '1',
        })
        self.assertContains(empty, '<td>нет дней</td>', html=True)
        all_days = self.client.post('/farm/schedule/', {
            'action': 'create',
            'name': 'все',
            'folder_id': str(folder.id),
            'schedule_action': 'start',
            'days': ['0', '1', '2', '3', '4', '5', '6'],
            'start_time': '10:00',
            'stop_time': '22:00',
            'enabled': '1',
        })
        self.assertContains(all_days, '<td>каждый день</td>', html=True)

    def test_аккаунты_видны(self):
        Account.objects.create(email='rich@x.com', balance=9000)
        Account.objects.create(email='poor@x.com', balance=10)
        response = self.client.get('/farm/accounts/')
        self.assertContains(response, 'a@b.com')
        self.assertNotContains(response, 'http-equiv="refresh"')
        self.assertNotContains(response, 'EA id')
        self.assertNotContains(response, '>Бан<')
        self.assertNotContains(response, '<th>Имя</th>')
        self.assertContains(response, '>Фильтр<')
        self.assertContains(response, 'data-filter-key="unlinked"')
        self.assertContains(response, 'data-filter-key="market_open"')
        self.assertContains(response, 'data-filter-key="sbc_assigned"')
        self.assertContains(response, 'Не собрали СБЧ')
        self.assertContains(response, 'id="email-query"')
        self.assertContains(response, 'id="email-search"')
        self.assertContains(response, '(рынок нет данных')
        self.assertContains(response, 'набор не назначен')
        self.assertContains(response, 'Открыть')
        self.assertContains(response, 'Открыть выбранные')
        self.assertContains(response, 'id="delete-selected"')
        self.assertContains(response, 'data-delete-url')
        self.assertContains(response, 'data-open-url')
        self.assertContains(response, 'Закрыть')
        self.assertContains(response, 'data-close-url')
        self.assertNotContains(response, 'data-filter-key="preview"')
        self.assertNotContains(response, 'data-filter-key="priority"')
        self.assertNotContains(response, 'data-filter-key="sbc_name"')
        self.assertNotContains(response, 'data-filter-key="nonpriority"')
        html = response.content.decode('utf-8')
        self.assertLess(html.index('rich@x.com'), html.index('poor@x.com'))
        self.assertLess(html.index('poor@x.com'), html.index('a@b.com'))

    def test_папка_создаётся_без_фильтра(self):
        response = self.client.post('/farm/folders/new/', {'name': 'Свои'})
        self.assertEqual(response.status_code, 302)
        folder = Folder.objects.get(name='Свои')
        self.assertEqual(folder.filter, default_filter())
        self.assertEqual(folder.modes, [{'key': 'freeAccountSolving', 'value': None}])

    def test_страница_папок_показывает_список_и_форму(self):
        Folder.objects.create(name='Свои', filter=default_filter())
        response = self.client.get('/farm/folders/new/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '>Папки<')
        self.assertContains(response, 'Свои')
        self.assertContains(response, 'Новая папка')
        self.assertContains(response, 'name="name"')
        self.assertNotContains(response, '>Новая папка</a>')

    def test_главный_экран_запускает_круг(self):
        folder = Folder.objects.create(name='Свои', filter=default_filter(), open_at_a_time=1)
        account = Account.objects.get(email='a@b.com')
        self.client.post(
            '/farm/folders/%s/' % folder.id,
            {'action': 'add_selected', 'account_id': str(account.id)},
        )
        response = self.client.post('/farm/', {'action': 'start', 'folder_id': str(folder.id)})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'команд')
        self.assertTrue(folder.runs.exists())

    def test_ферма_рисует_только_запущенный_скрипт(self):
        folder = Folder.objects.create(name='Свои', filter=default_filter(), open_at_a_time=1)
        account = Account.objects.get(email='a@b.com')
        self.client.post(
            '/farm/folders/%s/' % folder.id,
            {'action': 'add_selected', 'account_id': str(account.id)},
        )
        morning = Schedule.objects.create(
            name='утро',
            folder=folder,
            days=[0, 1, 2, 3, 4, 5, 6],
            start_time=time(4, 17),
            stop_time=time(5, 18),
            enabled=True,
        )
        Schedule.objects.create(
            name='вечер',
            folder=folder,
            days=[0, 1, 2, 3, 4, 5, 6],
            start_time=time(19, 41),
            stop_time=time(20, 42),
            enabled=True,
        )
        idle = self.client.get('/farm/')
        self.assertContains(idle, 'нет активного открытия')
        self.assertNotContains(idle, 'Свои')
        self.assertNotContains(idle, '04:17')
        self.assertNotContains(idle, '19:41')
        start_folder(folder, started_by='schedule', schedule=morning)
        live = self.client.get('/farm/')
        self.assertContains(live, 'утро')
        self.assertContains(live, '04:17')
        self.assertNotContains(live, '19:41')

    def test_лимит_запросов_не_неизвестный_мод(self):
        folder = Folder.objects.create(
            name='test',
            filter=default_filter(),
            modes=[{'key': 'За  часа можно сделать запросов', 'value': '24650'}],
            modes_text='За 24 часа можно сделать запросов650+',
        )
        replace_members(folder, [Account.objects.get(email='a@b.com')])
        start_folder(folder, started_by='op')
        response = self.client.get('/farm/')
        self.assertContains(response, 'test')
        self.assertNotContains(response, 'неизвестный мод')

    def test_поиск_и_добавить_прикрепляет_аккаунты(self):
        folder = Folder.objects.create(name='Свои', filter=default_filter())
        account = Account.objects.get(email='a@b.com')
        account.market_open = True
        account.save(update_fields=['market_open'])
        found = self.client.post(
            '/farm/folders/%s/search/' % folder.id,
            {'filter_key': 'market_open'},
        )
        self.assertEqual(found.status_code, 200)
        self.assertContains(found, 'Выбрать все')
        self.assertContains(found, 'a@b.com')
        folder.refresh_from_db()
        self.assertEqual(folder.filter, default_filter())
        page = self.client.get('/farm/folders/%s/' % folder.id)
        self.assertContains(page, 'Выбрать все')
        self.assertContains(page, 'a@b.com')
        self.assertNotContains(page, 'Кого открывать')
        add = self.client.post(
            '/farm/folders/%s/' % folder.id,
            {'action': 'add_selected', 'account_id': str(account.id)},
        )
        self.assertEqual(add.status_code, 200)
        self.assertEqual(
            list(folder.members.values_list('account__email', flat=True)),
            ['a@b.com'],
        )
        self.assertContains(add, 'В папке')
        self.assertContains(add, 'рынок открыт')
        self.assertNotContains(add, 'без бана')
        self.assertContains(add, 'Снять все')

    def test_добавить_не_стирает_уже_в_папке(self):
        folder = Folder.objects.create(name='Свои', filter=default_filter())
        first = Account.objects.get(email='a@b.com')
        second = Account.objects.create(ea_account_id=2, email='c@d.com')
        self.client.post(
            '/farm/folders/%s/' % folder.id,
            {'action': 'add_selected', 'account_id': str(first.id)},
        )
        self.client.post(
            '/farm/folders/%s/' % folder.id,
            {'action': 'add_selected', 'account_id': str(second.id)},
        )
        emails = list(folder.members.values_list('account__email', flat=True).order_by('account__email'))
        self.assertEqual(emails, ['a@b.com', 'c@d.com'])
        again = self.client.post(
            '/farm/folders/%s/' % folder.id,
            {'action': 'add_selected', 'account_id': str(first.id)},
        )
        self.assertEqual(again.status_code, 200)
        self.assertEqual(folder.members.count(), 2)
        self.assertContains(again, 'В папку добавлено: 0')

    def test_добавить_тот_же_email_молча_пропускает(self):
        folder = Folder.objects.create(name='Свои', filter=default_filter())
        first = Account.objects.get(email='a@b.com')
        twin = Account.objects.create(ea_account_id=9, email='A@B.com', name='клон')
        self.client.post(
            '/farm/folders/%s/' % folder.id,
            {'action': 'add_selected', 'account_id': str(first.id)},
        )
        response = self.client.post(
            '/farm/folders/%s/' % folder.id,
            {'action': 'add_selected', 'account_id': str(twin.id)},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'В папку добавлено: 0')
        self.assertEqual(folder.members.count(), 1)
        self.assertEqual(folder.members.get().account_id, first.id)

    def test_снять_все_очищает_папку(self):
        folder = Folder.objects.create(name='Свои', filter=default_filter())
        account = Account.objects.get(email='a@b.com')
        account.ban = True
        account.market_open = False
        account.save(update_fields=['ban', 'market_open'])
        self.client.post(
            '/farm/folders/%s/' % folder.id,
            {'action': 'add_selected', 'account_id': str(account.id)},
        )
        page = self.client.get('/farm/folders/%s/' % folder.id)
        self.assertContains(page, 'рынок не открыт')
        self.assertContains(page, 'аккаунт забанен')
        self.assertNotContains(page, 'без бана')
        cleared = self.client.post(
            '/farm/folders/%s/' % folder.id,
            {'action': 'clear_members'},
        )
        self.assertEqual(cleared.status_code, 200)
        self.assertEqual(folder.members.count(), 0)
        self.assertContains(cleared, 'список пуст')

    def test_экран_папки_фильтр_локальный(self):
        folder = Folder.objects.create(name='Свои', filter=default_filter())
        page = self.client.get('/farm/folders/%s/' % folder.id)
        self.assertContains(page, '>Фильтр<')
        self.assertContains(page, 'Искать')
        self.assertContains(page, 'data-filter-key="unlinked"')
        self.assertContains(page, 'data-filter-key="market_open"')
        self.assertContains(page, 'id="email-query"')
        self.assertContains(page, 'id="email-search"')
        self.assertNotContains(page, 'data-filter-key="email"')
        self.assertNotContains(page, 'data-filter-key="preview"')
        self.assertNotContains(page, 'data-filter-key="priority"')
        self.assertNotContains(page, 'data-filter-key="sbc_assigned"')
        self.assertNotContains(page, 'data-filter-key="sbc_name"')
        self.assertNotContains(page, 'data-filter-key="nonpriority"')
        self.assertNotContains(page, 'Добрать паки')
        self.assertNotContains(page, 'Не собрал приоритет')
        self.assertNotContains(page, 'Добавить фильтр')
        self.assertNotContains(page, 'Сбросить фильтры')
        self.assertNotContains(page, 'name="filter_field"')
        self.assertNotContains(page, 'name="filter_op"')
        self.assertNotContains(page, 'name="add_filter"')

    def test_удаление_выбранных_аккаунтов(self):
        keep = Account.objects.get(email='a@b.com')
        drop = Account.objects.create(email='gone@x.com')
        response = self.client.post('/farm/accounts/delete/', {'account_id': [str(drop.id)]})
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body['ok'])
        self.assertEqual(body['ids'], [drop.id])
        self.assertFalse(Account.objects.filter(id=drop.id).exists())
        self.assertTrue(Account.objects.filter(id=keep.id).exists())
        empty = self.client.post('/farm/accounts/delete/', {})
        self.assertFalse(empty.json()['ok'])

    def test_поиск_по_email(self):
        folder = Folder.objects.create(name='Свои', filter=default_filter())
        Account.objects.create(email='other@x.com')
        found = self.client.post(
            '/farm/folders/%s/search/' % folder.id,
            {'email': 'a@b', 'filter_key': 'market_open'},
        )
        self.assertEqual(found.status_code, 200)
        self.assertContains(found, 'a@b.com')
        self.assertNotContains(found, 'other@x.com')
        self.assertContains(found, 'рынок нет данных')
        self.assertNotContains(found, 'без бана')

    def test_пустой_поиск_не_меняет_найденных(self):
        folder = Folder.objects.create(name='Свои', filter=default_filter())
        account = Account.objects.get(email='a@b.com')
        account.market_open = True
        account.save(update_fields=['market_open'])
        self.client.post(
            '/farm/folders/%s/search/' % folder.id,
            {'filter_key': 'market_open'},
        )
        empty = self.client.post('/farm/folders/%s/search/' % folder.id, {})
        self.assertEqual(empty.status_code, 204)
        page = self.client.get('/farm/folders/%s/' % folder.id)
        self.assertContains(page, 'a@b.com')
        self.assertContains(page, 'Выбрать все')

    def test_поиск_аккаунтов_не_собрали_сбч(self):
        assigned = Account.objects.get(email='a@b.com')
        assigned.market_open = True
        assigned.save(update_fields=['market_open'])
        Account.objects.create(email='other@x.com')
        sbc_set = SbcSet.objects.create(name='Общий')
        SbcAssignment.objects.create(account=assigned, sbc_set=sbc_set)
        now = timezone.now()
        SbcAttempt.objects.create(
            account=assigned,
            client_event_id='e1',
            sbc_name='Gold Upgrade',
            outcome=SbcAttempt.OUTCOME_FAILED,
            occurred_at=now,
            priority=True,
        )
        SbcAttempt.objects.create(
            account=assigned,
            client_event_id='e2',
            sbc_name='83 Rated',
            outcome=SbcAttempt.OUTCOME_COLLECTED,
            occurred_at=now,
        )
        found = self.client.post(
            '/farm/accounts/search/',
            {'filter_key': 'sbc_assigned'},
        )
        self.assertEqual(found.status_code, 200)
        self.assertContains(found, 'a@b.com')
        self.assertNotContains(found, 'other@x.com')
        self.assertContains(found, 'Общий')
        self.assertContains(found, 'попыток 2')
        self.assertContains(found, 'Gold Upgrade')
        self.assertContains(found, '83 Rated')
        self.assertContains(found, 'сданы')
        self.assertContains(found, 'не сданы')
        self.assertContains(found, 'рынок открыт')

    def test_поиск_аккаунтов_по_папке(self):
        inside = Account.objects.get(email='a@b.com')
        Account.objects.create(email='other@x.com')
        folder = Folder.objects.create(name='Свои', filter=default_filter())
        Folder.objects.create(name='Чужие', filter=default_filter())
        replace_members(folder, [inside])
        page = self.client.get('/farm/accounts/')
        self.assertContains(page, '>Папка<')
        self.assertContains(page, 'data-filter-key="in_folder"')
        self.assertContains(page, 'data-filter-extra="%s"' % folder.id)
        self.assertContains(page, 'Свои')
        self.assertContains(page, 'Чужие')
        found = self.client.post('/farm/accounts/search/', {
            'filter_key': 'in_folder',
            'extra_in_folder': str(folder.id),
        })
        self.assertEqual(found.status_code, 200)
        self.assertContains(found, 'a@b.com')
        self.assertNotContains(found, 'other@x.com')
        empty = self.client.post('/farm/accounts/search/', {
            'filter_key': 'in_folder',
            'extra_in_folder': 'нет',
        })
        self.assertEqual(empty.status_code, 204)

    def test_поиск_аккаунтов_по_email(self):
        Account.objects.create(email='other@x.com')
        found = self.client.post(
            '/farm/accounts/search/',
            {'email': 'a@b', 'filter_key': 'sbc_assigned'},
        )
        self.assertEqual(found.status_code, 200)
        self.assertContains(found, 'a@b.com')
        self.assertNotContains(found, 'other@x.com')
        self.assertContains(found, 'рынок нет данных')
        self.assertContains(found, 'набор не назначен')

    def test_пустой_поиск_аккаунтов_не_меняет_список(self):
        empty = self.client.post('/farm/accounts/search/', {})
        self.assertEqual(empty.status_code, 204)

    def test_открытие_аккаунта_с_пульта(self):
        account = Account.objects.get(email='a@b.com')
        response = self.client.post(
            '/farm/accounts/open/',
            {'account_id': str(account.id)},
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body['ok'])
        self.assertIn('a@b.com', body['message'])
        commands = list(AgentCommand.objects.filter(action=AgentCommand.ACTION_OPEN))
        self.assertEqual(len(commands), 1)
        self.assertEqual(commands[0].email, 'a@b.com')
        self.assertIsNone(commands[0].run_id)
        self.assertFalse(
            AgentCommand.objects.filter(action=AgentCommand.ACTION_STOP).exists()
        )

    def test_открытие_выбранных_аккаунтов(self):
        first = Account.objects.get(email='a@b.com')
        other = Account.objects.create(email='other@x.com')
        response = self.client.post('/farm/accounts/open/', {
            'account_id': [str(first.id), str(other.id)],
        })
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['ok'])
        emails = list(
            AgentCommand.objects.filter(action=AgentCommand.ACTION_OPEN)
            .values_list('email', flat=True)
        )
        self.assertEqual(sorted(emails), ['a@b.com', 'other@x.com'])

    def test_открытие_при_выключенном_пк(self):
        Worker.objects.update(enabled=False)
        account = Account.objects.get(email='a@b.com')
        response = self.client.post(
            '/farm/accounts/open/',
            {'account_id': str(account.id)},
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertFalse(body['ok'])
        self.assertIn('ПК выключен', body['message'])
        self.assertFalse(AgentCommand.objects.exists())

    def test_закрытие_аккаунта_с_пульта(self):
        account = Account.objects.get(email='a@b.com')
        response = self.client.post(
            '/farm/accounts/close/',
            {'account_id': str(account.id)},
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body['ok'])
        self.assertIn('a@b.com', body['message'])
        commands = list(AgentCommand.objects.filter(action=AgentCommand.ACTION_CLOSE))
        self.assertEqual(len(commands), 1)
        self.assertEqual(commands[0].email, 'a@b.com')
        self.assertIsNone(commands[0].run_id)
        self.assertFalse(AgentCommand.objects.filter(action=AgentCommand.ACTION_OPEN).exists())

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
            '/farm/folders/%s/modes/' % folder.id,
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

    def test_карточка_папки_без_автообновления_и_textarea(self):
        folder = Folder.objects.create(
            name='Свои',
            filter=default_filter(),
            modes=[{'key': 'collectSBC', 'value': None}],
            modes_text='Собрать СБЧ+',
        )
        response = self.client.get('/farm/folders/%s/' % folder.id)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'http-equiv="refresh"')
        self.assertNotContains(response, 'name="modes_text"')
        self.assertNotContains(response, 'name="play_mode"')
        self.assertNotContains(response, 'SBCmode')
        self.assertNotContains(response, 'Набор СБЧ')
        self.assertNotContains(response, 'Гасить Chrome')
        self.assertNotContains(response, 'Распространить СБЧ на аккаунты')
        self.assertNotContains(response, 'Кого открывать')
        self.assertContains(response, 'Редактировать моды')
        self.assertContains(response, 'Выбор аккаунтов')
        self.assertContains(response, 'Собрать СБЧ')
        self.assertContains(response, 'mode-pill')
        self.assertContains(response, '/farm/folders/%s/modes/' % folder.id)

    def test_сохранение_папки_не_затирает_моды(self):
        folder = Folder.objects.create(
            name='Свои',
            filter=default_filter(),
            modes=[{'key': 'collectSBC', 'value': None}],
            modes_text='Собрать СБЧ+',
        )
        response = self.client.post('/farm/folders/%s/' % folder.id, {
            'action': 'save',
            'name': 'Свои',
            'open_at_a_time': '1',
            'order': 'email',
        })
        self.assertEqual(response.status_code, 200)
        folder.refresh_from_db()
        self.assertEqual(folder.modes, [{'key': 'collectSBC', 'value': None}])

    def test_сохранение_папки_обновляет_активный_круг(self):
        folder = Folder.objects.create(
            name='Свои',
            filter=default_filter(),
            open_at_a_time=1,
            modes=[{'key': 'collectSBC', 'value': None}],
        )
        account = Account.objects.get(email='a@b.com')
        replace_members(folder, [account])
        start_folder(folder, worker=Worker.objects.get(worker_id='this-pc'))
        response = self.client.post('/farm/folders/%s/' % folder.id, {
            'action': 'save',
            'name': 'Свои',
            'open_at_a_time': '3',
            'order': 'email',
        })
        self.assertEqual(response.status_code, 200)
        run = folder.runs.get(state='active')
        self.assertEqual(run.open_at_a_time, 3)
        self.assertEqual(run.modes, [{'key': 'collectSBC', 'value': None}])

    def test_экран_модов_пишет_очередь(self):
        folder = Folder.objects.create(name='Свои', filter=default_filter())
        page = self.client.get('/farm/folders/%s/modes/' % folder.id)
        self.assertEqual(page.status_code, 200)
        self.assertNotContains(page, 'http-equiv="refresh"')
        self.assertContains(page, 'Собрать СБЧ')
        self.assertContains(page, 'Собрать все сбч')
        self.assertNotContains(page, 'не выбран')
        self.assertContains(page, 'Открыть паки')
        self.assertContains(page, 'Проверить открылся ли рынок')
        self.assertContains(page, 'Собрать задания')
        self.assertContains(page, 'Разобрать нераспределенные')
        self.assertContains(page, 'class="mode-conditions-wrap"')
        self.assertContains(page, 'Ещё раз')
        self.assertContains(page, 'Перетащить')
        self.assertNotContains(page, '>Вверх<')
        self.assertNotContains(page, '>Вниз<')
        response = self.client.post('/farm/folders/%s/modes/' % folder.id, {
            'mode_collectSBC': '1',
            'mode_useBronze200ForSbc': '1',
            'mode_openPacks': '1',
            'mode_openTradablePacks': '1',
            'mode_openBronzePacksFromStore': '1',
            'mode_value_openBronzePacksFromStore': '1',
            'mode_startSnipe': '1',
            'mode_resetRequests': '1',
            'mode_value_resetRequests': '3',
            'mode_requests24hours': '1',
            'mode_value_requests24hours': '650',
            'mode_freeAccountSolving': '1',
            'mode_firstLoginToWeb': '1',
        })
        self.assertEqual(response.status_code, 302)
        folder.refresh_from_db()
        keys = [item['key'] for item in folder.modes]
        self.assertEqual(keys[0], 'firstLoginToWeb')
        self.assertEqual(keys[-1], 'freeAccountSolving')
        self.assertIn('collectAllSbc', keys)
        self.assertIn('openBronzePacksFromStore', keys)
        self.assertEqual(
            [item['value'] for item in folder.modes if item['key'] == 'resetRequests'][0],
            3,
        )
        self.assertIn('Собрать СБЧ+', folder.modes_text)

    def test_сохранение_модов_обновляет_активный_круг(self):
        folder = Folder.objects.create(name='Свои', filter=default_filter(), open_at_a_time=1)
        account = Account.objects.get(email='a@b.com')
        replace_members(folder, [account])
        start_folder(folder, worker=Worker.objects.get(worker_id='this-pc'))
        response = self.client.post('/farm/folders/%s/modes/' % folder.id, {
            'mode_collectSBC': '1',
        })
        self.assertEqual(response.status_code, 302)
        folder.refresh_from_db()
        run = folder.runs.get(state='active')
        self.assertEqual(run.modes, folder.modes)
        self.assertIn('collectSBC', [item['key'] for item in run.modes])

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
