from datetime import time

from django.test import TestCase
from django.utils import timezone

from farm_core.circle import on_command_finished, start_folder, stop_run
from farm_core.clock_tick import tick
from farm_core.folder_filter import (
    accounts_for_start,
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

    def test_старт_без_состава_пустой(self):
        replace_members(self.folder, [])
        result = start_folder(self.folder, worker=self.worker)
        self.assertFalse(result['ok'])
        self.assertEqual(result['error']['code'], 'empty')

    def test_открывать_только_не_собравших_сбч(self):
        sbc_set = SbcSet.objects.create(name='набор')
        assign_set(self.left, sbc_set)
        self.folder.open_rule = 'uncollected_sbc'
        self.folder.save(update_fields=['open_rule'])
        selected, missing = accounts_for_start(self.folder)
        self.assertEqual([account.email for account in selected], ['a@b.com'])
        self.assertEqual(missing, 0)
        result = start_folder(self.folder, worker=self.worker)
        self.assertTrue(result['ok'])
        self.assertEqual(result['data']['total'], 1)
        self.assertEqual(
            list(self.folder.members.values_list('account__email', flat=True)),
            ['a@b.com', 'c@d.com'],
        )

    def test_открывать_не_закончивших_снайп(self):
        put_daily_metric(self.left, timezone.localdate(), 'market_searches', 10)
        put_daily_metric(self.right, timezone.localdate(), 'market_searches', 400)
        self.folder.open_rule = 'unfinished_snipe'
        self.folder.save(update_fields=['open_rule'])
        selected, missing = accounts_for_start(self.folder)
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

    def test_аккаунт_не_в_двух_кругах(self):
        replace_members(self.folder, [self.left])
        other = Folder.objects.create(name='Два', filter=default_filter(), open_at_a_time=1)
        replace_members(other, [self.left, self.right])
        first = start_folder(self.folder, worker=self.worker)
        second = start_folder(other, worker=self.worker)
        self.assertTrue(first['ok'])
        self.assertTrue(second['ok'])
        self.assertIn('a@b.com', second['data']['skipped'])
        self.assertEqual(
            RunEntry.objects.filter(
                account=self.left,
                state__in=[RunEntry.STATE_WAITING, RunEntry.STATE_QUEUED, RunEntry.STATE_OPENED],
            ).count(),
            1,
        )

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

    def test_назначить_сбч_вешает_общий_набор(self):
        common = SbcSet.objects.create(name='общие', common=True)
        self.folder.assign_sbc = True
        self.folder.save(update_fields=['assign_sbc'])
        start_folder(self.folder, worker=self.worker)
        assigned = SbcAssignment.objects.filter(
            account=self.left,
            state=SbcAssignment.STATE_ACTIVE,
        ).first()
        self.assertIsNotNone(assigned)
        self.assertEqual(assigned.sbc_set_id, common.id)

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
