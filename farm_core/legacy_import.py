import json
import sqlite3
from datetime import datetime
from pathlib import Path

from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime

from farm_core.metrics import put_daily_metric
from farm_core.mode_labels import parse_modes_text
from farm_core.models import (
    Account,
    AccountLoginSecret,
    Folder,
    ImportReport,
    MarketFilter,
    MarketFilterList,
    Schedule,
    SbcAssignment,
    SbcSet,
    SbcSetItem,
    SbcTemplate,
    SnipeSettingsDoc,
)
from farm_core.sbc import assign_set


METRIC_COLUMNS = (
    ('requests', 'market_searches'),
    ('purchased', 'purchased'),
    ('profit', 'profit'),
    ('captcha', 'captcha'),
    ('won', 'won'),
    ('draw', 'draw'),
    ('loss', 'loss'),
)


def import_legacy(sqlite_path):
    path = Path(sqlite_path)
    connection = sqlite3.connect(str(path))
    connection.row_factory = sqlite3.Row
    unresolved = []
    summary = {
        'accounts': 0,
        'metrics': 0,
        'sbc_sets': 0,
        'assignments': 0,
        'market_filters': 0,
        'folders': 0,
        'schedules': 0,
    }
    try:
        accounts = _import_accounts(connection, unresolved)
        summary['accounts'] = len(accounts)
        summary['metrics'] = _import_metrics(connection, accounts, unresolved)
        summary['sbc_sets'] = _import_sbc_and_market(connection, unresolved)
        summary['assignments'] = _import_assignments(connection, accounts, unresolved)
        summary['folders'] = _import_folders(connection, unresolved)
        summary['schedules'] = _import_schedules(connection, unresolved)
        _import_snipe_settings(accounts, unresolved)
        summary['market_filters'] = MarketFilter.objects.count()
    finally:
        connection.close()
    report = ImportReport.objects.create(
        source_path=str(path),
        summary=summary,
        unresolved=unresolved,
    )
    return report


def _import_accounts(connection, unresolved):
    rows = connection.execute(
        'SELECT * FROM fifawebaccounts_fifawebaccounts'
    ).fetchall()
    mapped = {}
    for row in rows:
        email = _clean_email(row['account_email'])
        account, _created = Account.objects.update_or_create(
            ea_account_id=row['account_id'],
            defaults={
                'name': row['account_name'] or '',
                'email': email,
                'ban': bool(row['ban']),
                'snipe_allowed': bool(row['snipe_allowed']),
                'balance': row['balance'] or 0,
                'our_part': row['our_part'] or 0,
                'coins_transferred': row['coins_transferred'] or 0,
                'owner_label': row['owner_name'] or '',
                'preview_pack_opened_at': _parse_dt(row['preview_pack_opened_time']),
                'fix_player_at': row['fix_player_date'] or '',
            },
        )
        reserves = row['code_reserves'] or ''
        if reserves and reserves != 'None':
            AccountLoginSecret.objects.update_or_create(
                account=account,
                defaults={'code_reserves': reserves},
            )
        account.legacy_settings = row['settings'] or ''
        mapped[row['account_id']] = account
        if not email:
            unresolved.append({'kind': 'account_no_email', 'ea_account_id': row['account_id']})
    return mapped


def _import_metrics(connection, accounts, unresolved):
    rows = connection.execute(
        'SELECT * FROM fifawebaccounts_accountstatsperday'
    ).fetchall()
    by_key = {}
    for row in rows:
        account = accounts.get(row['account_id_id'])
        if account is None:
            unresolved.append({'kind': 'metric_unknown_account', 'row_id': row['id']})
            continue
        day = parse_date(str(row['date']))
        key = (account.id, day)
        if key in by_key:
            unresolved.append({
                'kind': 'metric_duplicate_date',
                'ea_account_id': account.ea_account_id,
                'date': str(day),
            })
            continue
        by_key[key] = row
        for column, name in METRIC_COLUMNS:
            put_daily_metric(account, day, name, row[column] or 0)
    return len(by_key)


def _import_sbc_and_market(connection, unresolved):
    rows = connection.execute('SELECT * FROM filters_filtermodel').fetchall()
    created = 0
    for row in rows:
        pk = row['id']
        kind, payload = classify_filter_payload(row['filters'])
        if pk == 5:
            unresolved.append({'kind': 'blacklist_skipped', 'pk': 5})
            continue
        if pk == 2 and kind == 'market':
            unresolved.append({'kind': 'signals_skipped', 'pk': 2})
            continue
        if pk == 4 or (kind == 'market' and pk not in (2, 5)):
            if pk == 4:
                _import_market_list(payload)
            elif kind == 'market':
                unresolved.append({'kind': 'market_not_live', 'pk': pk})
            continue
        if kind != 'sbc':
            unresolved.append({'kind': 'filter_unknown', 'pk': pk})
            continue
        name = {1: 'sbc', 6: 'common', 2: 'PlayUT', 3: 'прочие'}.get(pk, 'set-%s' % pk)
        _import_sbc_set(name, payload, common=(pk == 6), unresolved=unresolved)
        created += 1
    return created


def _import_market_list(payload):
    listing, _created = MarketFilterList.objects.get_or_create(pk=1, defaults={'version': 1})
    listing.version = listing.version + 1
    listing.save(update_fields=['version', 'updated_at'])
    for position, (key, item) in enumerate(payload.items()):
        title = item.get('title') or key
        MarketFilter.objects.update_or_create(
            title=title,
            defaults={'payload': item, 'position': position, 'enabled': True},
        )


def _import_sbc_set(name, payload, common, unresolved):
    sbc_set, _created = SbcSet.objects.update_or_create(
        name=name,
        defaults={'common': common},
    )
    for position, (raw_name, item) in enumerate(payload.items()):
        template_name = str(raw_name)
        existing = SbcTemplate.objects.filter(name=template_name).first()
        if existing is not None and existing.payload != item:
            template_name = '%s (%s)' % (raw_name, name)
            unresolved.append({
                'kind': 'sbc_name_conflict',
                'name': str(raw_name),
                'set': name,
            })
        template, _created = SbcTemplate.objects.update_or_create(
            name=template_name,
            defaults={'payload': item},
        )
        SbcSetItem.objects.update_or_create(
            sbc_set=sbc_set,
            template=template,
            defaults={'priority': not common, 'position': position},
        )
    return sbc_set


def _import_assignments(connection, accounts, unresolved):
    rows = connection.execute('SELECT * FROM filters_sbcfilter').fetchall()
    count = 0
    for row in rows:
        account = accounts.get(row['account_id_id'])
        if account is None:
            unresolved.append({'kind': 'assignment_unknown_account', 'row_id': row['id']})
            continue
        raw = str(row['filters'] or '').strip()
        if raw in ('', 'null', 'None'):
            continue
        if not raw.isdigit():
            unresolved.append({'kind': 'assignment_bad_pk', 'value': raw})
            continue
        set_name = {1: 'sbc', 6: 'common', 2: 'PlayUT', 3: 'прочие'}.get(int(raw), 'set-%s' % raw)
        sbc_set = SbcSet.objects.filter(name=set_name).first()
        if sbc_set is None:
            unresolved.append({'kind': 'assignment_missing_set', 'pk': raw})
            continue
        active = SbcAssignment.objects.filter(
            account=account,
            state=SbcAssignment.STATE_ACTIVE,
        ).first()
        if active and active.sbc_set_id == sbc_set.id:
            continue
        assign_set(account, sbc_set)
        count += 1
    return count


def _import_folders(connection, unresolved):
    rows = connection.execute('SELECT * FROM foldermanager_folder').fetchall()
    count = 0
    for row in rows:
        modes = parse_modes_text(row['modes'] if row['modes'] != 'None' else '')
        Folder.objects.update_or_create(
            name=row['folder_name'],
            defaults={
                'filter': [],
                'refresh_on_start': False,
                'play_mode': row['play_mode'] if row['play_mode'] != 'None' else 'SBCmode',
                'modes': [{'key': item['key'], 'value': item['value']} for item in modes],
                'modes_text': row['modes'] if row['modes'] != 'None' else '',
                'open_at_a_time': row['open_at_a_time'] or 1,
            },
        )
        unresolved.append({'kind': 'folder_members_unknown', 'folder': row['folder_name']})
        count += 1
    return count


def _import_schedules(connection, unresolved):
    try:
        rows = connection.execute('SELECT * FROM scheduledscripts_script').fetchall()
    except sqlite3.OperationalError:
        unresolved.append({'kind': 'schedules_table_missing'})
        return 0
    count = 0
    for row in rows:
        if row['type'] != 'run_folder_script':
            continue
        folder = Folder.objects.filter(name=row['folder_name']).first()
        if folder is None:
            unresolved.append({'kind': 'schedule_missing_folder', 'folder': row['folder_name']})
            continue
        days = row['run_days']
        if isinstance(days, str):
            days = json.loads(days or '[]')
        Schedule.objects.update_or_create(
            name=row['name'],
            defaults={
                'folder': folder,
                'action': Schedule.ACTION_START,
                'days': days,
                'start_time': _parse_time(row['scheduled_time']),
                'stop_time': _parse_time(row['stop_scheduled_time']),
                'enabled': False,
            },
        )
        count += 1
    return count


def _import_snipe_settings(accounts, unresolved):
    items = []
    for account in accounts.values():
        settings = getattr(account, 'legacy_settings', '') or ''
        if settings in ('', 'None'):
            continue
        items.append((account.updated_at, settings, account.ea_account_id))
    if not items:
        return
    newest = sorted(items, key=lambda item: item[0] or timezone.now(), reverse=True)
    payloads = {item[1] for item in items}
    if len(payloads) > 1:
        unresolved.append({
            'kind': 'snipe_settings_conflict',
            'taken_account': newest[0][2],
        })
    SnipeSettingsDoc.write(newest[0][1])


def classify_filter_payload(raw):
    try:
        data = json.loads(raw or '{}')
    except json.JSONDecodeError:
        return 'unknown', {}
    if isinstance(data, dict) and data:
        values = list(data.values())
        if all(isinstance(item, dict) and 'title' in item for item in values):
            return 'market', data
        return 'sbc', data
    if isinstance(data, list):
        return 'sbc', {str(index): item for index, item in enumerate(data)}
    return 'unknown', data


def _clean_email(value):
    text = (value or '').strip()
    if text in ('', 'None'):
        return None
    return text


def _parse_dt(value):
    if not value:
        return None
    parsed = parse_datetime(str(value))
    if parsed is None:
        return None
    if timezone.is_naive(parsed):
        return timezone.make_aware(parsed, timezone.get_current_timezone())
    return parsed


def _parse_time(value):
    if value is None:
        return datetime.strptime('00:00:00', '%H:%M:%S').time()
    text = str(value)
    for fmt in ('%H:%M:%S.%f', '%H:%M:%S', '%H:%M'):
        try:
            return datetime.strptime(text, fmt).time()
        except ValueError:
            continue
    return datetime.strptime('00:00:00', '%H:%M:%S').time()
