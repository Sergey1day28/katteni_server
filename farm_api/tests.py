import json
from pathlib import Path
from unittest.mock import patch

import pyotp
from django.test import TestCase

from farm_core.folder_filter import default_filter, replace_members
from farm_core.models import (
    Account,
    AccountLoginSecret,
    DailyMetric,
    Folder,
    NotifyOutbox,
    RunEntry,
    Worker,
)
from farm_core.circle import start_folder
from farm_core.tokens import hash_token


CONTRACT = Path(__file__).resolve().parent.parent / 'contract' / 'v1'


class ApiV1Tests(TestCase):
    def setUp(self):
        self.worker = Worker.objects.create(
            worker_id='pc-1',
            token_hash=hash_token('secret'),
            enabled=True,
        )
        self.account = Account.objects.create(
            ea_account_id=10011,
            email='a@b.com',
            name='Player',
        )
        self.folder = Folder.objects.create(
            name='Свои',
            filter=default_filter(),
            open_at_a_time=1,
            modes=[{'key': 'collectSBC', 'value': None}],
            play_mode='SBCmode',
        )
        replace_members(self.folder, [self.account])

    def _post(self, route, payload):
        return self.client.post(
            '/api/v1/%s' % route,
            data=json.dumps(payload),
            content_type='application/json',
        )

    def test_конверт_отказа_http_200(self):
        expected = json.loads((CONTRACT / 'session-start.unknown-session.json').read_text(encoding='utf-8'))
        response = self._post('session/heartbeat', expected['request'])
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertFalse(body['ok'])
        self.assertEqual(body['error']['code'], expected['response']['error']['code'])

    def test_session_start_и_метрика(self):
        start_folder(self.folder, worker=self.worker)
        RunEntry.objects.filter(email='a@b.com').update(state=RunEntry.STATE_QUEUED)
        response = self._post('session/start', {
            'email': 'a@b.com',
            'ea_account_id': 10011,
            'client': {'engine': 'core-v2', 'version': '1', 'known_modes': ['collectSBC']},
            'snipe_settings_version': 0,
        })
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body['ok'])
        self.assertEqual(body['data']['heartbeat_sec'], 60)
        self.assertEqual(body['data']['steps'][0]['key'], 'collectSBC')
        session = body['data']['session']
        pushed = self._post('events/push', {
            'session': session,
            'events': [{
                'id': 'evt-1',
                'type': 'metric.day',
                'at': '2026-10-31T12:00:00+03:00',
                'data': {'date': '2026-10-31', 'name': 'market_searches', 'value': 12},
            }],
        })
        self.assertTrue(pushed.json()['ok'])
        self.assertEqual(DailyMetric.objects.get().value, 12)
        finish = self._post('session/finish', {'session': session, 'reason': 'done', 'text': ''})
        self.assertTrue(finish.json()['ok'])
        self.assertEqual(finish.json()['data']['action'], 'close_browser')
        again = self._post('session/finish', {'session': session, 'reason': 'done'})
        self.assertEqual(again.json()['data']['action'], 'close_browser')

    def test_notify_кладёт_очередь(self):
        response = self._post('notify', {
            'email': 'a@b.com',
            'channel': 'important',
            'text': 'не удалось прогрузить',
            'dedup_key': 'page-a@b.com',
        })
        self.assertTrue(response.json()['ok'])
        self.assertTrue(NotifyOutbox.objects.filter(dedup_key='page-a@b.com').exists())

    def test_notify_auto_buy_уходит_в_телеграм(self):
        sent = []
        with patch('farm_core.bot_api.send_auto_buy', side_effect=lambda text: sent.append(text) or True):
            response = self._post('notify', {
                'email': 'a@b.com',
                'channel': 'auto_buy',
                'text': 'не удалось прогрузить',
                'dedup_key': 'page-a@b.com',
            })
        self.assertTrue(response.json()['ok'])
        self.assertEqual(sent, ['a@b.com не удалось прогрузить'])
        note = NotifyOutbox.objects.get(dedup_key='page-a@b.com')
        self.assertEqual(note.channel, 'auto_buy')
        self.assertEqual(note.state, NotifyOutbox.STATE_SENT)

    def test_credentials_отдаёт_email(self):
        start_folder(self.folder, worker=self.worker)
        RunEntry.objects.filter(email='a@b.com').update(state=RunEntry.STATE_QUEUED)
        started = self._post('session/start', {
            'email': 'a@b.com',
            'client': {'engine': 'core-v2', 'version': '1', 'known_modes': []},
        })
        session = started.json()['data']['session']
        response = self._post('session/credentials', {'session': session})
        self.assertTrue(response.json()['ok'])
        self.assertEqual(response.json()['data']['email'], 'a@b.com')
        self.assertIn('code_ea', response.json()['data'])

    def test_рынок_чтение_форма_как_в_контракте(self):
        expected = json.loads((CONTRACT / 'market-filters.ok.json').read_text(encoding='utf-8'))
        response = self._post('market/filters', expected['request'])
        self.assertTrue(response.json()['ok'])
        self.assertIn('version', response.json()['data'])
        self.assertIn('items', response.json()['data'])

    def _start_run_session(self, email, ea_account_id=None):
        account = Account.objects.filter(email=email).first()
        if account is not None:
            replace_members(self.folder, [account])
        start_folder(self.folder, worker=self.worker)
        RunEntry.objects.filter(email=email).update(state=RunEntry.STATE_QUEUED)
        payload = {
            'email': email,
            'client': {'engine': 'core-v2', 'version': '1', 'known_modes': []},
        }
        if ea_account_id is not None:
            payload['ea_account_id'] = ea_account_id
        started = self._post('session/start', payload)
        self.assertTrue(started.json()['ok'], started.json())
        return started.json()['data']['session']

    def test_start_находит_аккаунт_без_ea_id(self):
        pending = Account.objects.create(email='csv@x.com', name='CSV')
        self.assertIsNone(pending.ea_account_id)
        start_folder(self.folder, worker=self.worker)
        RunEntry.objects.filter(email='csv@x.com').update(state=RunEntry.STATE_QUEUED)
        response = self._post('session/start', {
            'email': 'csv@x.com',
            'client': {'engine': 'core-v2', 'version': '1', 'known_modes': []},
        })
        self.assertTrue(response.json()['ok'])
        self.assertTrue(response.json()['data']['account']['known'])
        self.assertEqual(response.json()['data']['account']['id'], pending.id)

    def test_bind_дописывает_id_к_строке_по_email(self):
        pending = Account.objects.create(email='csv@x.com', name='CSV')
        session = self._start_run_session('csv@x.com')
        response = self._post('session/bind', {
            'session': session,
            'ea_account_id': 55501,
            'account_name': 'CSV',
            'coins': 1200,
        })
        self.assertTrue(response.json()['ok'], response.json())
        pending.refresh_from_db()
        self.assertEqual(pending.ea_account_id, 55501)
        self.assertEqual(pending.balance, 1200)
        self.assertEqual(Account.objects.filter(email='csv@x.com').count(), 1)

    def test_bind_не_плодит_дубль_если_id_уже_есть(self):
        session = self._start_run_session('a@b.com', 10011)
        response = self._post('session/bind', {
            'session': session,
            'ea_account_id': 10011,
            'account_name': 'Player',
            'coins': 50,
        })
        self.assertTrue(response.json()['ok'])
        self.assertEqual(Account.objects.filter(ea_account_id=10011).count(), 1)
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, 50)

    def test_bind_конфликт_если_у_email_уже_другой_id(self):
        Account.objects.create(email='other@x.com', ea_account_id=70001)
        session = self._start_run_session('other@x.com', 70001)
        response = self._post('session/bind', {
            'session': session,
            'ea_account_id': 70002,
        })
        self.assertFalse(response.json()['ok'])
        self.assertEqual(response.json()['error']['code'], 'conflict')
        self.assertEqual(Account.objects.filter(email='other@x.com').count(), 1)
        self.assertEqual(Account.objects.get(email='other@x.com').ea_account_id, 70001)

    def test_bind_конфликт_если_id_занят_другим_email(self):
        Account.objects.create(email='fresh@x.com')
        session = self._start_run_session('fresh@x.com')
        response = self._post('session/bind', {
            'session': session,
            'ea_account_id': 10011,
        })
        self.assertFalse(response.json()['ok'])
        self.assertEqual(response.json()['error']['code'], 'conflict')
        self.assertIsNone(Account.objects.get(email='fresh@x.com').ea_account_id)

    def test_bind_ставит_linked_at_один_раз(self):
        pending = Account.objects.create(email='oldid@x.com', ea_account_id=90001)
        self.assertIsNone(pending.linked_at)
        session = self._start_run_session('oldid@x.com', 90001)
        first = self._post('session/bind', {'session': session, 'ea_account_id': 90001})
        self.assertTrue(first.json()['ok'])
        pending.refresh_from_db()
        first_at = pending.linked_at
        self.assertIsNotNone(first_at)
        again = self._post('session/bind', {'session': session, 'ea_account_id': 90001})
        self.assertTrue(again.json()['ok'])
        pending.refresh_from_db()
        self.assertEqual(pending.linked_at, first_at)

    def test_рынок_открыт_потом_закрыт_это_бан(self):
        session = self._start_run_session('a@b.com', 10011)
        opened = self._post('events/push', {
            'session': session,
            'events': [{'id': 'm-open', 'type': 'account.flag', 'data': {'market_open': True}}],
        })
        self.assertTrue(opened.json()['ok'])
        self.account.refresh_from_db()
        self.assertTrue(self.account.market_open)
        self.assertTrue(self.account.market_seen_open)
        self.assertFalse(self.account.ban)
        closed = self._post('events/push', {
            'session': session,
            'events': [{'id': 'm-close', 'type': 'account.flag', 'data': {'market_open': False}}],
        })
        self.assertTrue(closed.json()['ok'])
        self.account.refresh_from_db()
        self.assertFalse(self.account.market_open)
        self.assertTrue(self.account.ban)

    def test_рынок_сразу_закрыт_не_бан(self):
        session = self._start_run_session('a@b.com', 10011)
        self._post('events/push', {
            'session': session,
            'events': [{'id': 'm-first', 'type': 'account.flag', 'data': {'market_open': False}}],
        })
        self.account.refresh_from_db()
        self.assertFalse(self.account.market_open)
        self.assertFalse(self.account.ban)

    def test_credentials_по_email_без_id_отдаёт_totp(self):
        pending = Account.objects.create(email='csv@x.com')
        seed = 'JBSWY3DPEHPK3PXP'
        AccountLoginSecret.objects.create(account=pending, totp_seed=seed)
        session = self._start_run_session('csv@x.com')
        response = self._post('session/credentials', {'session': session})
        self.assertTrue(response.json()['ok'])
        self.assertEqual(response.json()['data']['email'], 'csv@x.com')
        self.assertTrue(pyotp.TOTP(seed).verify(response.json()['data']['code_ea'], valid_window=1))
