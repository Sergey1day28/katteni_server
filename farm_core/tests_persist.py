import json
import sqlite3
import tempfile
from datetime import date, timedelta
from pathlib import Path

from django.db import IntegrityError
from django.test import TestCase
from django.utils import timezone

from farm_core.csv_import import import_csv
from farm_core.legacy_import import import_legacy
from farm_core.metrics import put_daily_metric
from farm_core.models import (
    Account,
    AccountLoginSecret,
    DailyMetric,
    SbcAssignment,
    SbcAttempt,
    SbcSet,
    SbcTemplate,
)
from farm_core.sbc import assign_set, record_attempt


class PersistTests(TestCase):
    def setUp(self):
        self.account = Account.objects.create(ea_account_id=1, email='a@b.com', name='A')

    def test_метрика_повтор_затирает(self):
        day = date(2026, 10, 31)
        put_daily_metric(self.account, day, 'market_searches', 10)
        put_daily_metric(self.account, day, 'market_searches', 3)
        self.assertEqual(DailyMetric.objects.count(), 1)
        self.assertEqual(DailyMetric.objects.get().value, 3)

    def test_второе_активное_назначение_нельзя(self):
        first = SbcSet.objects.create(name='one')
        second = SbcSet.objects.create(name='two')
        assign_set(self.account, first)
        assign_set(self.account, second)
        self.assertEqual(
            SbcAssignment.objects.filter(account=self.account, state=SbcAssignment.STATE_ACTIVE).count(),
            1,
        )
        self.assertEqual(
            SbcAssignment.objects.get(account=self.account, state=SbcAssignment.STATE_ACTIVE).sbc_set,
            second,
        )
        with self.assertRaises(IntegrityError):
            SbcAssignment.objects.create(
                account=self.account,
                sbc_set=first,
                state=SbcAssignment.STATE_ACTIVE,
            )

    def test_попытка_дедуп_и_collected_после_failed(self):
        now = timezone.now()
        first, created = record_attempt(
            self.account,
            'evt-1',
            'Gold Upgrade',
            SbcAttempt.OUTCOME_FAILED,
            now,
            priority=True,
        )
        again, created_again = record_attempt(
            self.account,
            'evt-1',
            'Gold Upgrade',
            SbcAttempt.OUTCOME_COLLECTED,
            now,
            priority=True,
        )
        self.assertTrue(created)
        self.assertFalse(created_again)
        self.assertEqual(first.id, again.id)
        self.assertEqual(SbcAttempt.objects.count(), 1)
        later, _created = record_attempt(
            self.account,
            'evt-2',
            'Gold Upgrade',
            SbcAttempt.OUTCOME_COLLECTED,
            now + timedelta(minutes=1),
            priority=True,
        )
        last = (
            SbcAttempt.objects.filter(account=self.account, sbc_name='Gold Upgrade')
            .order_by('-occurred_at')
            .first()
        )
        self.assertEqual(last.id, later.id)
        self.assertEqual(last.outcome, SbcAttempt.OUTCOME_COLLECTED)

    def test_аккаунт_без_ea_id_и_два_null_не_конфликтуют(self):
        first = Account.objects.create(email='one@x.com')
        second = Account.objects.create(email='two@x.com')
        self.assertIsNone(first.ea_account_id)
        self.assertIsNone(second.ea_account_id)
        self.assertEqual(Account.objects.filter(ea_account_id__isnull=True).count(), 2)

    def test_csv_импорт_по_заголовкам_и_повтор(self):
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / 'accs.csv'
            path.write_text(
                'email,name,totp,password,ea_account_id\n'
                'csv@x.com,CSV,JBSWY3DPEHPK3PXP,secret-pass,\n',
                encoding='utf-8',
            )
            first = import_csv(path)
            second = import_csv(path)
            self.assertEqual(Account.objects.filter(email='csv@x.com').count(), 1)
            account = Account.objects.get(email='csv@x.com')
            self.assertIsNone(account.ea_account_id)
            self.assertEqual(account.name, 'CSV')
            secret = AccountLoginSecret.objects.get(account=account)
            self.assertEqual(secret.totp_seed, 'JBSWY3DPEHPK3PXP')
            self.assertNotIn('secret-pass', json.dumps(secret.__dict__, default=str))
            self.assertEqual(first.summary['accounts'], 1)
            self.assertEqual(second.summary['accounts'], 1)
            self.assertEqual(first.unresolved, [])

    def test_csv_позиционный_как_лист_акки_еа(self):
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / 'sheet.csv'
            cols = [''] * 11
            cols[0] = 'pos@x.com'
            cols[6] = 'discard-pass'
            cols[10] = 'JBSWY3DPEHPK3PXP'
            path.write_text(','.join(cols) + '\n', encoding='utf-8')
            report = import_csv(path)
            account = Account.objects.get(email='pos@x.com')
            self.assertIsNone(account.ea_account_id)
            self.assertEqual(account.login_secret.totp_seed, 'JBSWY3DPEHPK3PXP')
            self.assertEqual(report.unresolved, [])

    def test_csv_заголовок_name_не_становится_аккаунтом(self):
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / 'sheet.csv'
            header = ['Name'] + [''] * 9 + ['TOTP']
            data = ['real@x.com'] + [''] * 9 + ['JBSWY3DPEHPK3PXP']
            junk = ['Name'] + [''] * 10
            path.write_text(
                ','.join(header) + '\n' + ','.join(data) + '\n' + ','.join(junk) + '\n',
                encoding='utf-8',
            )
            report = import_csv(path)
            self.assertFalse(Account.objects.filter(email__iexact='Name').exists())
            account = Account.objects.get(email='real@x.com')
            self.assertEqual(account.login_secret.totp_seed, 'JBSWY3DPEHPK3PXP')
            self.assertEqual(report.summary['accounts'], 1)
            self.assertEqual(len(report.unresolved), 1)
            self.assertEqual(report.unresolved[0]['kind'], 'account_no_email')

    def test_csv_без_email_в_спорные(self):
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / 'bad.csv'
            path.write_text('email,totp\n,JBSWY3DPEHPK3PXP\n', encoding='utf-8')
            report = import_csv(path)
            self.assertEqual(Account.objects.filter(email__isnull=False).exclude(email='').count(), 1)
            self.assertTrue(any(item.get('kind') == 'account_no_email' for item in report.unresolved))

    def test_импорт_повтор_без_дублей(self):
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / 'db.sqlite3'
            self._create_sqlite(path)
            first = import_legacy(path)
            second = import_legacy(path)
            self.assertEqual(Account.objects.filter(ea_account_id=10).count(), 1)
            self.assertEqual(DailyMetric.objects.filter(name='market_searches').count(), 1)
            self.assertEqual(SbcTemplate.objects.count(), 1)
            self.assertEqual(first.summary['accounts'], 1)
            self.assertEqual(second.summary['accounts'], 1)

    def _create_sqlite(self, path):
        connection = sqlite3.connect(str(path))
        connection.executescript(
            '''
            CREATE TABLE fifawebaccounts_fifawebaccounts (
                id INTEGER PRIMARY KEY,
                owner_id_id INTEGER,
                account_id INTEGER,
                account_name TEXT,
                date_added TEXT,
                account_email TEXT,
                ban INTEGER,
                rent INTEGER,
                snipe_allowed INTEGER,
                our_part INTEGER,
                balance INTEGER,
                coins_transferred INTEGER,
                owner_name TEXT,
                code_reserves TEXT,
                proxy TEXT,
                settings TEXT,
                fix_player_date TEXT,
                players_from_board_to_buy TEXT,
                preview_pack_opened_time TEXT
            );
            CREATE TABLE fifawebaccounts_accountstatsperday (
                id INTEGER PRIMARY KEY,
                date TEXT,
                requests INTEGER,
                purchased INTEGER,
                profit INTEGER,
                captcha INTEGER,
                won INTEGER,
                draw INTEGER,
                loss INTEGER,
                reset_condition INTEGER,
                account_id_id INTEGER
            );
            CREATE TABLE filters_filtermodel (
                id INTEGER PRIMARY KEY,
                filters TEXT,
                date TEXT
            );
            CREATE TABLE filters_sbcfilter (
                id INTEGER PRIMARY KEY,
                filters TEXT,
                account_id_id INTEGER
            );
            CREATE TABLE foldermanager_folder (
                id INTEGER PRIMARY KEY,
                opened_accounts TEXT,
                closed_accounts TEXT,
                next_to_open_accounts TEXT,
                folder_name TEXT,
                in_opening_process INTEGER,
                opened_accounts_length INTEGER,
                closed_accounts_length INTEGER,
                open_at_a_time INTEGER,
                play_mode TEXT,
                modes TEXT
            );
            '''
        )
        connection.execute(
            '''INSERT INTO fifawebaccounts_fifawebaccounts
            (id, owner_id_id, account_id, account_name, date_added, account_email, ban, rent,
             snipe_allowed, our_part, balance, coins_transferred, owner_name, code_reserves,
             proxy, settings, fix_player_date, players_from_board_to_buy, preview_pack_opened_time)
            VALUES (1,1,10,'Acc','2026-01-01','imp@x.com',0,0,1,0,100,0,'o','None','None','None','None','None',NULL)'''
        )
        connection.execute(
            '''INSERT INTO fifawebaccounts_accountstatsperday
            (id,date,requests,purchased,profit,captcha,won,draw,loss,reset_condition,account_id_id)
            VALUES (1,'2026-10-30',12,1,2,0,0,0,0,0,10)'''
        )
        connection.execute(
            '''INSERT INTO filters_filtermodel (id,filters,date)
            VALUES (1,'{"Gold Upgrade": {"times": 1}}','2026-10-30')'''
        )
        connection.execute(
            '''INSERT INTO filters_filtermodel (id,filters,date)
            VALUES (4,'{"Cheap": {"title": "Cheap", "minBuy": 200}}','2026-10-30')'''
        )
        connection.execute(
            '''INSERT INTO filters_filtermodel (id,filters,date)
            VALUES (5,'{"Bad": {"title": "Bad"}}','2026-10-30')'''
        )
        connection.execute(
            "INSERT INTO filters_sbcfilter (id,filters,account_id_id) VALUES (1,'1',10)"
        )
        connection.execute(
            '''INSERT INTO foldermanager_folder
            (id,opened_accounts,closed_accounts,next_to_open_accounts,folder_name,in_opening_process,
             opened_accounts_length,closed_accounts_length,open_at_a_time,play_mode,modes)
            VALUES (1,'[]','[]','[]','Farm',0,0,0,2,'SBCmode','Собрать СБЧ')'''
        )
        connection.commit()
        connection.close()
