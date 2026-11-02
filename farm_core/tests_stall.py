from datetime import timedelta

from django.test import TestCase, override_settings
from django.utils import timezone

from farm_core.bot_api import mark_stalled, session_finish
from farm_core.circle import on_command_finished, start_folder
from farm_core.clock_tick import _fire_stop
from farm_core.folder_filter import default_filter, replace_members
from farm_core.models import (
    Account,
    AgentCommand,
    Folder,
    FolderRun,
    RunEntry,
    Schedule,
    Worker,
)
from farm_core.tokens import hash_token


@override_settings(STALL_KILL_CHROME=False, STALL_MINUTES=5, PAGE_NOT_LOADED_CLOSE=False)
class StallTests(TestCase):
    def setUp(self):
        self.folder = Folder.objects.create(name='Свои', filter=default_filter())
        self.run = FolderRun.objects.create(folder=self.folder, state=FolderRun.STATE_ACTIVE)
        self.entry = RunEntry.objects.create(
            run=self.run,
            email='a@b.com',
            state=RunEntry.STATE_QUEUED,
            queued_at=timezone.now() - timedelta(minutes=10),
        )

    def test_тишина_без_сигнала_закрывает_круг(self):
        with self.assertLogs('farm_journal', level='INFO') as captured:
            emails = mark_stalled()
        self.run.refresh_from_db()
        self.assertEqual(emails, ['a@b.com'])
        self.assertEqual(self.run.state, FolderRun.STATE_STOPPED)
        self.assertIn('Папка Свои зависла, аккаунт a@b.com', captured.output[0])
        self.assertIn('нет сигнала', captured.output[0])
        self.assertIn('круг закрыт', captured.output[0])

    def test_свежий_запуск_не_закрывается(self):
        self.entry.queued_at = timezone.now()
        self.entry.save(update_fields=['queued_at'])
        self.assertEqual(mark_stalled(), [])
        self.run.refresh_from_db()
        self.assertEqual(self.run.state, FolderRun.STATE_ACTIVE)

    def test_свежий_сигнал_не_закрывает(self):
        self.entry.last_seen_at = timezone.now()
        self.entry.save(update_fields=['last_seen_at'])
        self.assertEqual(mark_stalled(), [])
        self.run.refresh_from_db()
        self.assertEqual(self.run.state, FolderRun.STATE_ACTIVE)

    def test_команда_без_итога_пишется_отдельно(self):
        worker = Worker.objects.create(worker_id='pc-1', token_hash=hash_token('secret'), enabled=True)
        command = AgentCommand.objects.create(
            worker=worker,
            action=AgentCommand.ACTION_OPEN,
            email='a@b.com',
            run=self.run,
            entry=self.entry,
            state=AgentCommand.STATE_PENDING,
        )
        self.entry.last_command = command
        self.entry.save(update_fields=['last_command'])
        with self.assertLogs('farm_journal', level='INFO') as captured:
            mark_stalled()
        self.assertIn('команда открытия без итога', captured.output[0])


@override_settings(PAGE_NOT_LOADED_CLOSE=False)
class StallEventTests(TestCase):
    def setUp(self):
        self.worker = Worker.objects.create(
            worker_id='pc-1',
            token_hash=hash_token('secret'),
            enabled=True,
        )
        self.account = Account.objects.create(ea_account_id=1, email='a@b.com')
        self.folder = Folder.objects.create(
            name='Свои',
            filter=default_filter(),
            open_at_a_time=1,
        )
        replace_members(self.folder, [self.account])

    def test_неоткрытие_пишется_в_журнал(self):
        start_folder(self.folder, worker=self.worker)
        command = AgentCommand.objects.get(action=AgentCommand.ACTION_OPEN)
        command.state = AgentCommand.STATE_FAILED
        command.error_text = 'не найден ярлык'
        command.save()
        with self.assertLogs('farm_journal', level='INFO') as captured:
            on_command_finished(command)
        self.assertIn('не открылся: не найден ярлык', captured.output[0])

    def test_страница_не_загрузилась_пишется_в_журнал(self):
        with self.assertLogs('farm_journal', level='INFO') as captured:
            session_finish({'email': 'a@b.com', 'reason': 'page_not_loaded'})
        self.assertIn('page_not_loaded', captured.output[0])
        self.assertIn('оставлю открытым', captured.output[0])

    def test_стоп_по_расписанию_пишется_в_журнал(self):
        start_folder(self.folder, worker=self.worker)
        now = timezone.localtime()
        schedule = Schedule.objects.create(
            name='вечер',
            folder=self.folder,
            action=Schedule.ACTION_START,
            days=[now.weekday()],
            start_time=now.time().replace(microsecond=0),
            stop_time=now.time().replace(microsecond=0),
        )
        with self.assertLogs('farm_journal', level='INFO') as captured:
            _fire_stop(schedule, now.date(), now)
        self.assertIn('круг закрыт по расписанию вечер', captured.output[0])
