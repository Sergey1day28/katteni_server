from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from farm_core.folder_filter import default_filter
from farm_core.models import Account, AgentCommand, Folder, FolderRun, NotifyOutbox, RunEntry, Worker
from farm_core.tokens import hash_token
from farm_core.unopened import release_profiles_without_session


class UnopenedTests(TestCase):
    def setUp(self):
        self.worker = Worker.objects.create(
            worker_id='pc-1',
            token_hash=hash_token('secret'),
            enabled=True,
        )
        self.folder = Folder.objects.create(name='Свои', filter=default_filter(), open_at_a_time=1)
        self.run = FolderRun.objects.create(folder=self.folder, state=FolderRun.STATE_ACTIVE)
        self.now = timezone.now()

    def _queued(self, email, finished_at, state=RunEntry.STATE_QUEUED):
        account = Account.objects.create(email=email)
        entry = RunEntry.objects.create(
            run=self.run,
            email=email,
            account=account,
            position=RunEntry.objects.filter(run=self.run).count(),
            state=state,
        )
        command = AgentCommand.objects.create(
            worker=self.worker,
            run=self.run,
            entry=entry,
            action=AgentCommand.ACTION_OPEN,
            email=email,
            state=AgentCommand.STATE_OPENED,
            finished_at=finished_at,
        )
        entry.last_command = command
        entry.save(update_fields=['last_command'])
        return entry

    def test_без_вкладки_закрывает_и_открывает_следующего(self):
        stale = self._queued('a@b.com', self.now - timedelta(minutes=3))
        RunEntry.objects.create(
            run=self.run,
            email='c@d.com',
            account=Account.objects.create(email='c@d.com'),
            position=1,
            state=RunEntry.STATE_WAITING,
        )
        sent = []
        with patch('farm_core.unopened.send_auto_buy', side_effect=lambda text: sent.append(text) or True):
            released = release_profiles_without_session(now=self.now)
        self.assertEqual(released, ['a@b.com'])
        stale.refresh_from_db()
        self.assertEqual(stale.state, RunEntry.STATE_CLOSED)
        close = AgentCommand.objects.get(action=AgentCommand.ACTION_CLOSE)
        self.assertEqual(close.email, 'a@b.com')
        self.assertEqual(close.state, AgentCommand.STATE_PENDING)
        opened = AgentCommand.objects.filter(action=AgentCommand.ACTION_OPEN, email='c@d.com')
        self.assertEqual(opened.count(), 1)
        self.assertEqual(sent, ['a@b.com вкладка EA не открылась'])
        note = NotifyOutbox.objects.get(dedup_key='ea-tab-%s' % stale.id)
        self.assertEqual(note.channel, 'auto_buy')
        self.assertEqual(note.state, NotifyOutbox.STATE_SENT)

    def test_две_минуты_ещё_не_вышли(self):
        self._queued('a@b.com', self.now - timedelta(seconds=30))
        with patch('farm_core.unopened.send_auto_buy') as send:
            released = release_profiles_without_session(now=self.now)
        self.assertEqual(released, [])
        self.assertFalse(AgentCommand.objects.filter(action=AgentCommand.ACTION_CLOSE).exists())
        send.assert_not_called()

    def test_сессия_уже_подтверждена(self):
        self._queued('a@b.com', self.now - timedelta(minutes=3), state=RunEntry.STATE_OPENED)
        with patch('farm_core.unopened.send_auto_buy') as send:
            released = release_profiles_without_session(now=self.now)
        self.assertEqual(released, [])
        send.assert_not_called()
