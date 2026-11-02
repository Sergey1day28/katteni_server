from datetime import time, timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from farm_core.circle import (
    confirm_opened,
    continue_folder,
    on_command_finished,
    start_folder,
    stop_run,
)
from farm_core.clock_tick import run_loop, tick
from farm_core.folder_filter import (
    accounts_for_start,
    add_members,
    default_filter,
    folder_accounts,
    replace_members,
    search_accounts,
)
from farm_core.metrics import put_daily_metric
from farm_core.models import (
    Account,
    AgentCommand,
    Folder,
    FolderRun,
    RunEntry,
    SbcAssignment,
    Schedule,
    ScheduleFire,
    SbcSet,
    SbcSetItem,
    SbcTemplate,
    Worker,
)
from farm_core.sbc import assign_set
from farm_core.tokens import hash_token


class CircleTests(TestCase):
    def setUp(self):
        self.worker = Worker.objects.create(
            worker_id='pc-1',
            token_hash=hash_token('secret'),
            enabled=True,
        )
        self.left = Account.objects.create(ea_account_id=1, email='a@b.com')
        self.right = Account.objects.create(ea_account_id=2, email='c@d.com')
        self.folder = Folder.objects.create(
            name='Свои',
            filter=default_filter(),
            open_at_a_time=1,
        )
        replace_members(self.folder, [self.left, self.right])

    def test_пустой_поиск_никого_не_берёт(self):
        selected, missing = search_accounts([])
        self.assertEqual(selected, [])
        self.assertEqual(missing, 0)

    def test_добавить_заменяет_состав(self):
        replace_members(self.folder, [self.left])
        emails = [account.email for account in folder_accounts(self.folder)]
        self.assertEqual(emails, ['a@b.com'])
        replace_members(self.folder, [self.right])
        emails = [account.email for account in folder_accounts(self.folder)]
        self.assertEqual(emails, ['c@d.com'])

    def test_добавить_тот_же_email_не_дублирует(self):
        replace_members(self.folder, [self.left])
        twin = Account.objects.create(ea_account_id=8, email='A@B.com')
        members, added = add_members(self.folder, [twin, self.right])
        self.assertEqual(added, 1)
        emails = [account.email for account in members]
        self.assertEqual(emails, ['a@b.com', 'c@d.com'])

    def test_старт_без_состава_пустой(self):
        replace_members(self.folder, [])
        result = start_folder(self.folder, worker=self.worker)
        self.assertFalse(result['ok'])
        self.assertEqual(result['error']['code'], 'empty')

    def test_открывать_только_не_собравших_сбч(self):
        sbc_set = SbcSet.objects.create(name='набор')
        assign_set(self.left, sbc_set)
        selected, missing = accounts_for_start(self.folder, open_rule='uncollected_sbc')
        self.assertEqual([account.email for account in selected], ['a@b.com'])
        self.assertEqual(missing, 0)
        result = start_folder(self.folder, worker=self.worker, open_rule='uncollected_sbc')
        self.assertTrue(result['ok'])
        self.assertEqual(result['data']['total'], 1)
        self.assertEqual(
            list(self.folder.members.values_list('account__email', flat=True)),
            ['a@b.com', 'c@d.com'],
        )

    def test_открывать_не_закончивших_снайп(self):
        put_daily_metric(self.left, timezone.localdate(), 'market_searches', 10)
        put_daily_metric(self.right, timezone.localdate(), 'market_searches', 400)
        selected, missing = accounts_for_start(self.folder, open_rule='unfinished_snipe')
        self.assertEqual([account.email for account in selected], ['a@b.com'])
        self.assertEqual(missing, 0)

    def test_не_связывался_берёт_даже_с_ea_id(self):
        folder = Folder.objects.create(
            name='Новые',
            filter=[{'field': 'linked', 'op': 'eq', 'value': False}],
        )
        selected, missing = search_accounts(folder.filter)
        emails = {account.email for account in selected}
        self.assertEqual(emails, {'a@b.com', 'c@d.com'})
        self.assertEqual(missing, 0)
        self.left.linked_at = timezone.now()
        self.left.save(update_fields=['linked_at'])
        selected, _missing = search_accounts(folder.filter)
        self.assertEqual([account.email for account in selected], ['c@d.com'])

    def test_поиск_по_куску_email(self):
        selected, missing = search_accounts([
            {'field': 'email', 'op': 'contains', 'value': 'A@B'},
        ])
        self.assertEqual([account.email for account in selected], ['a@b.com'])
        self.assertEqual(missing, 0)

    def test_рынок_открыт_без_снимка_не_берёт(self):
        folder = Folder.objects.create(
            name='Рынок',
            filter=[{'field': 'market_open', 'op': 'eq', 'value': True}],
        )
        selected, missing = search_accounts(folder.filter)
        self.assertEqual(selected, [])
        self.assertEqual(missing, 2)
        self.left.market_open = True
        self.left.save(update_fields=['market_open'])
        selected, missing = search_accounts(folder.filter)
        self.assertEqual([account.email for account in selected], ['a@b.com'])
        self.assertEqual(missing, 1)

    def test_приоритет_без_попытки_входит(self):
        sbc_set = SbcSet.objects.create(name='prio')
        template = SbcTemplate.objects.create(name='Gold')
        SbcSetItem.objects.create(sbc_set=sbc_set, template=template, priority=True)
        assign_set(self.left, sbc_set)
        folder = Folder.objects.create(
            name='Не собрали',
            filter=[{'field': 'priority_sbc_uncollected', 'op': 'eq', 'value': True}],
        )
        selected, _missing = search_accounts(folder.filter)
        self.assertEqual([account.email for account in selected], ['a@b.com'])

    def test_повторный_старт_перезапускает_круг(self):
        first = start_folder(self.folder, worker=self.worker)
        self.assertTrue(first['ok'])
        old_id = first['data']['run_id']
        second = start_folder(self.folder, worker=self.worker)
        self.assertTrue(second['ok'])
        self.assertNotEqual(second['data']['run_id'], old_id)
        old = FolderRun.objects.get(id=old_id)
        self.assertEqual(old.state, FolderRun.STATE_STOPPED)
        self.assertEqual(FolderRun.objects.filter(state=FolderRun.STATE_ACTIVE).count(), 1)
        self.assertTrue(
            AgentCommand.objects.filter(
                run_id=second['data']['run_id'],
                action=AgentCommand.ACTION_STOP,
            ).exists()
        )

    def test_старт_по_скрипту_пишет_schedule_на_круг(self):
        schedule = Schedule.objects.create(
            name='утро',
            folder=self.folder,
            days=[0, 1, 2, 3, 4, 5, 6],
            start_time=time(9, 0),
            stop_time=time(23, 0),
            enabled=True,
        )
        result = start_folder(self.folder, worker=self.worker, schedule=schedule)
        self.assertTrue(result['ok'])
        run = FolderRun.objects.get(id=result['data']['run_id'])
        self.assertEqual(run.schedule_id, schedule.id)

    def test_старт_второй_папки_гасит_первую(self):
        replace_members(self.folder, [self.left])
        other = Folder.objects.create(name='Два', filter=default_filter(), open_at_a_time=1)
        replace_members(other, [self.left, self.right])
        first = start_folder(self.folder, worker=self.worker)
        second = start_folder(other, worker=self.worker)
        self.assertTrue(first['ok'])
        self.assertTrue(second['ok'])
        old = FolderRun.objects.get(id=first['data']['run_id'])
        self.assertEqual(old.state, FolderRun.STATE_STOPPED)
        active = FolderRun.objects.get(state=FolderRun.STATE_ACTIVE)
        self.assertEqual(active.folder_id, other.id)
        self.assertEqual(second['data']['skipped'], [])
        self.assertEqual(active.entries.count(), 2)
        self.assertEqual(
            RunEntry.objects.filter(
                account=self.left,
                state__in=[RunEntry.STATE_WAITING, RunEntry.STATE_QUEUED, RunEntry.STATE_OPENED],
            ).count(),
            1,
        )

    def test_остановка_снимает_opened(self):
        start_folder(self.folder, worker=self.worker)
        confirm_opened('a@b.com')
        run = FolderRun.objects.get(state=FolderRun.STATE_ACTIVE)
        opened = run.entries.get(email='a@b.com')
        self.assertEqual(opened.state, RunEntry.STATE_OPENED)
        stop_run(run)
        opened.refresh_from_db()
        self.assertEqual(opened.state, RunEntry.STATE_CANCELLED)
        again = start_folder(self.folder, worker=self.worker)
        self.assertTrue(again['ok'])
        self.assertEqual(again['data']['total'], 2)

    def test_итог_агента_после_стопа_не_оживляет_запись(self):
        start_folder(self.folder, worker=self.worker)
        command = AgentCommand.objects.get(
            action=AgentCommand.ACTION_OPEN,
            state=AgentCommand.STATE_PENDING,
        )
        run = FolderRun.objects.get(state=FolderRun.STATE_ACTIVE)
        stop_run(run)
        command.state = AgentCommand.STATE_OPENED
        command.save(update_fields=['state'])
        on_command_finished(command)
        command.entry.refresh_from_db()
        self.assertEqual(command.entry.state, RunEntry.STATE_CANCELLED)

    def test_часы_стартуют_с_новыми_модами(self):
        self.folder.modes = [{'key': 'collectSBC', 'value': None}]
        self.folder.open_at_a_time = 2
        self.folder.save(update_fields=['modes', 'open_at_a_time'])
        now = timezone.localtime()
        Schedule.objects.create(
            name='утро',
            folder=self.folder,
            action=Schedule.ACTION_START,
            days=[now.weekday()],
            start_time=time(now.hour, now.minute, now.second),
            stop_time=time(23, 59),
            enabled=True,
        )
        fires = tick(now=now)
        self.assertEqual(len(fires), 1)
        self.assertEqual(fires[0].result, 'ok')
        run = FolderRun.objects.get(state=FolderRun.STATE_ACTIVE)
        self.assertEqual(run.modes, [{'key': 'collectSBC', 'value': None}])
        self.assertEqual(run.open_at_a_time, 2)

    def test_продолжение_берёт_настройки_папки(self):
        start_folder(self.folder, worker=self.worker)
        run = FolderRun.objects.get(state=FolderRun.STATE_ACTIVE)
        run.state = FolderRun.STATE_STOPPED
        run.save(update_fields=['state'])
        self.folder.modes = [{'key': 'collectSBC', 'value': None}]
        self.folder.open_at_a_time = 2
        self.folder.save(update_fields=['modes', 'open_at_a_time'])
        result = continue_folder(self.folder, worker=self.worker)
        self.assertTrue(result['ok'])
        run.refresh_from_db()
        self.assertEqual(run.state, FolderRun.STATE_ACTIVE)
        self.assertEqual(run.modes, [{'key': 'collectSBC', 'value': None}])
        self.assertEqual(run.open_at_a_time, 2)

    def test_часы_перезапускают_идущий_круг(self):
        started = start_folder(self.folder, worker=self.worker)
        old_id = started['data']['run_id']
        now = timezone.localtime()
        Schedule.objects.create(
            name='утро',
            folder=self.folder,
            action=Schedule.ACTION_START,
            days=[now.weekday()],
            start_time=time(now.hour, now.minute, now.second),
            stop_time=time(23, 59),
            enabled=True,
        )
        fires = tick(now=now)
        self.assertEqual(len(fires), 1)
        self.assertEqual(fires[0].result, 'ok')
        old = FolderRun.objects.get(id=old_id)
        self.assertEqual(old.state, FolderRun.STATE_STOPPED)
        self.assertEqual(FolderRun.objects.filter(state=FolderRun.STATE_ACTIVE).count(), 1)
        self.assertNotEqual(FolderRun.objects.get(state=FolderRun.STATE_ACTIVE).id, old_id)

    def test_рестарт_не_теряет_очередь(self):
        start_folder(self.folder, worker=self.worker)
        run = FolderRun.objects.get(state=FolderRun.STATE_ACTIVE)
        waiting = run.entries.filter(state=RunEntry.STATE_WAITING).count()
        queued = run.entries.filter(state=RunEntry.STATE_QUEUED).count()
        self.assertGreater(waiting + queued, 0)
        run_id = run.id
        again = FolderRun.objects.get(id=run_id)
        self.assertEqual(again.entries.count(), run.entries.count())
        self.assertEqual(again.state, FolderRun.STATE_ACTIVE)

    def test_старт_всегда_гасит_chrome(self):
        start_folder(self.folder, worker=self.worker)
        self.assertTrue(
            AgentCommand.objects.filter(
                action=AgentCommand.ACTION_STOP,
                state=AgentCommand.STATE_PENDING,
            ).exists()
        )

    def test_старт_без_гашения_не_ставит_stop_chrome(self):
        start_folder(self.folder, worker=self.worker, kill_chrome=False)
        self.assertFalse(
            AgentCommand.objects.filter(action=AgentCommand.ACTION_STOP).exists()
        )

    def test_назначить_сбч_вешает_общий_набор(self):
        common = SbcSet.objects.create(name='общие', common=True)
        start_folder(self.folder, worker=self.worker, assign_sbc=True)
        assigned = SbcAssignment.objects.filter(
            account=self.left,
            state=SbcAssignment.STATE_ACTIVE,
        ).first()
        self.assertIsNotNone(assigned)
        self.assertEqual(assigned.sbc_set_id, common.id)

    def test_старт_по_расписанию_берёт_правило_скрипта(self):
        source = SbcSet.objects.create(name='набор')
        assign_set(self.left, source)
        common = SbcSet.objects.create(name='общие', common=True)
        schedule = Schedule.objects.create(
            name='утро',
            folder=self.folder,
            start_time=time(9, 0),
            stop_time=time(23, 0),
            open_rule='uncollected_sbc',
            assign_sbc=True,
        )
        result = start_folder(self.folder, worker=self.worker, schedule=schedule)
        self.assertTrue(result['ok'])
        self.assertEqual(result['data']['total'], 1)
        assigned = SbcAssignment.objects.get(
            account=self.left,
            state=SbcAssignment.STATE_ACTIVE,
        )
        self.assertEqual(assigned.sbc_set_id, common.id)
        self.assertFalse(
            SbcAssignment.objects.filter(
                account=self.right,
                state=SbcAssignment.STATE_ACTIVE,
            ).exists()
        )

    def test_без_галки_сбч_не_назначает(self):
        SbcSet.objects.create(name='общие', common=True)
        start_folder(self.folder, worker=self.worker)
        self.assertFalse(
            SbcAssignment.objects.filter(
                account=self.left,
                state=SbcAssignment.STATE_ACTIVE,
            ).exists()
        )

    def test_failed_открывает_следующего(self):
        start_folder(self.folder, worker=self.worker)
        command = AgentCommand.objects.get(
            action=AgentCommand.ACTION_OPEN,
            state=AgentCommand.STATE_PENDING,
        )
        command.state = AgentCommand.STATE_FAILED
        command.error_text = 'не найден ярлык'
        command.save()
        on_command_finished(command)
        self.assertEqual(RunEntry.objects.filter(state=RunEntry.STATE_FAILED).count(), 1)
        self.assertEqual(AgentCommand.objects.filter(action='open').count(), 2)

    def test_остановка_отменяет_pending(self):
        start_folder(self.folder, worker=self.worker)
        run = FolderRun.objects.get(state=FolderRun.STATE_ACTIVE)
        stop_run(run)
        self.assertEqual(run.entries.filter(state=RunEntry.STATE_CANCELLED).count(), 2)
        self.assertFalse(AgentCommand.objects.filter(state=AgentCommand.STATE_PENDING).exists())

    def test_часы_пишут_schedule_fire_один_раз(self):
        now = timezone.localtime()
        Schedule.objects.create(
            name='утро',
            folder=self.folder,
            action=Schedule.ACTION_START,
            days=[now.weekday()],
            start_time=now.timetz().replace(tzinfo=None) if False else time(now.hour, now.minute, now.second),
            stop_time=time(23, 59),
            enabled=True,
        )
        first = tick(now=now)
        second = tick(now=now)
        self.assertEqual(len(first), 1)
        self.assertEqual(len(second), 0)
        self.assertEqual(FolderRun.objects.filter(state=FolderRun.STATE_ACTIVE).count(), 1)
        with self.assertLogs('farm_core.clock_tick', level='INFO') as captured:
            tick(now=now)
        self.assertTrue(any('уже в этом окне' in line for line in captured.output))

    def test_часы_после_смены_времени_стреляют_снова(self):
        now = timezone.localtime()
        later = now + timedelta(minutes=2)
        schedule = Schedule.objects.create(
            name='утро',
            folder=self.folder,
            action=Schedule.ACTION_START,
            days=[now.weekday()],
            start_time=time(now.hour, now.minute, now.second),
            stop_time=time(23, 59),
            enabled=True,
        )
        first = tick(now=now)
        self.assertEqual(len(first), 1)
        schedule.start_time = time(later.hour, later.minute, later.second)
        schedule.save(update_fields=['start_time'])
        second = tick(now=later)
        self.assertEqual(len(second), 1)
        self.assertEqual(second[0].result, 'ok')
        self.assertEqual(
            ScheduleFire.objects.filter(
                schedule=schedule,
                kind=ScheduleFire.KIND_START,
            ).count(),
            2,
        )

    def test_часы_стоп_после_смены_времени_стреляют_снова(self):
        start_folder(self.folder, worker=self.worker)
        now = timezone.localtime()
        later = now + timedelta(minutes=2)
        schedule = Schedule.objects.create(
            name='вечер',
            folder=self.folder,
            action=Schedule.ACTION_START,
            days=[now.weekday()],
            start_time=time(0, 0),
            stop_time=time(now.hour, now.minute, now.second),
            enabled=True,
        )
        first = tick(now=now)
        self.assertEqual(len(first), 1)
        self.assertEqual(first[0].kind, ScheduleFire.KIND_STOP)
        schedule.stop_time = time(later.hour, later.minute, later.second)
        schedule.save(update_fields=['stop_time'])
        second = tick(now=later)
        self.assertEqual(len(second), 1)
        self.assertEqual(second[0].kind, ScheduleFire.KIND_STOP)

    def test_часы_пишут_пропуск_по_дню(self):
        now = timezone.localtime()
        other = (now.weekday() + 1) % 7
        Schedule.objects.create(
            name='не сегодня',
            folder=self.folder,
            action=Schedule.ACTION_START,
            days=[other],
            start_time=time(now.hour, now.minute, now.second),
            stop_time=time(23, 59),
            enabled=True,
        )
        with self.assertLogs('farm_core.clock_tick', level='INFO') as captured:
            fires = tick(now=now)
        self.assertEqual(fires, [])
        self.assertTrue(any('не в днях' in line for line in captured.output))

    def test_часы_без_дней_не_стреляют(self):
        now = timezone.localtime()
        Schedule.objects.create(
            name='без дней',
            folder=self.folder,
            action=Schedule.ACTION_START,
            days=[],
            start_time=time(now.hour, now.minute, now.second),
            stop_time=time(23, 59),
            enabled=True,
        )
        with self.assertLogs('farm_core.clock_tick', level='INFO') as captured:
            fires = tick(now=now)
        self.assertEqual(fires, [])
        self.assertTrue(any('не в днях' in line for line in captured.output))

    def test_часы_все_дни_стреляют(self):
        now = timezone.localtime()
        Schedule.objects.create(
            name='все дни',
            folder=self.folder,
            action=Schedule.ACTION_START,
            days=[0, 1, 2, 3, 4, 5, 6],
            start_time=time(now.hour, now.minute, now.second),
            stop_time=time(23, 59),
            enabled=True,
        )
        fires = tick(now=now)
        self.assertEqual(len(fires), 1)
        self.assertEqual(fires[0].result, 'ok')

    def test_цикл_часов_не_умирает_на_ошибке(self):
        calls = {'n': 0}

        def flaky(now=None):
            del now
            calls['n'] += 1
            if calls['n'] == 1:
                raise RuntimeError('нет базы')
            return []

        with patch('farm_core.clock_tick.close_old_connections'):
            with self.assertLogs('farm_core.clock_tick', level='INFO') as captured:
                run_loop(do_tick=flaky, sleeper=lambda _sec: None, max_ticks=2)
        joined = '\n'.join(captured.output)
        self.assertGreaterEqual(calls['n'], 1)
        self.assertIn('Тик часов упал', joined)
