from datetime import timedelta

from django.db.models import Max
from django.utils import timezone

from farm_core.models import (
    Account,
    DailyMetric,
    FolderMember,
    FolderRun,
    RunEntry,
    SbcAssignment,
    SbcAttempt,
    SbcSetItem,
)


OPEN_RULE_ALL = 'all'
OPEN_RULE_SNIPE = 'unfinished_snipe'
OPEN_RULE_SBC = 'uncollected_sbc'

OPEN_RULES = [
    {'key': OPEN_RULE_ALL, 'title': 'Всех из списка'},
    {'key': OPEN_RULE_SNIPE, 'title': 'Не закончили снайп'},
    {'key': OPEN_RULE_SBC, 'title': 'Не собрали СБЧ'},
]

OPEN_RULE_FILTERS = {
    OPEN_RULE_SNIPE: [{'field': 'market_searches_today', 'op': 'lt', 'value': 350}],
    OPEN_RULE_SBC: [{'field': 'has_sbc_set', 'op': 'eq', 'value': True}],
}


def default_filter():
    return []


def match_accounts(conditions, accounts=None, now=None):
    now = now or timezone.now()
    if accounts is None:
        accounts = list(Account.objects.all())
    if not conditions:
        return list(accounts), 0
    selected = []
    missing = 0
    for account in accounts:
        matched, has_data = _match_all(account, conditions, now)
        if not has_data:
            missing += 1
            continue
        if matched:
            selected.append(account)
    return selected, missing


def search_accounts(conditions, now=None):
    if not conditions:
        return [], 0
    return match_accounts(conditions, now=now)


def evaluate_folder(folder, now=None):
    return search_accounts(folder.filter or [], now=now)


def folder_accounts(folder):
    return [
        member.account
        for member in folder.members.select_related('account').order_by('account__email', 'account_id')
    ]


def replace_members(folder, accounts):
    FolderMember.objects.filter(folder=folder).delete()
    now = timezone.now()
    seen = set()
    rows = []
    for account in accounts:
        if account.id in seen:
            continue
        seen.add(account.id)
        rows.append(
            FolderMember(
                folder=folder,
                account=account,
                source='picked',
                snapshot_at=now,
            )
        )
    FolderMember.objects.bulk_create(rows)
    return folder_accounts(folder)


def accounts_for_start(folder, now=None):
    members = folder_accounts(folder)
    rule = folder.open_rule or OPEN_RULE_ALL
    conditions = OPEN_RULE_FILTERS.get(rule)
    if not conditions:
        return members, 0
    return match_accounts(conditions, accounts=members, now=now)


def accounts_in_other_active_run(account_ids, except_run=None):
    query = RunEntry.objects.filter(
        account_id__in=account_ids,
        state__in=[RunEntry.STATE_WAITING, RunEntry.STATE_QUEUED, RunEntry.STATE_OPENED],
        run__state=FolderRun.STATE_ACTIVE,
    )
    if except_run is not None:
        query = query.exclude(run=except_run)
    return set(query.values_list('account_id', flat=True))


def _match_all(account, conditions, now):
    for condition in conditions:
        matched, has_data = _match_one(account, condition, now)
        if not has_data:
            return False, False
        if not matched:
            return False, True
    return True, True


def _match_one(account, condition, now):
    field = condition.get('field')
    op = condition.get('op') or 'eq'
    value = condition.get('value')
    reader = FIELD_READERS.get(field)
    if reader is None:
        return False, False
    actual, has_data = reader(account, now, value)
    if not has_data:
        return False, False
    return _compare(actual, op, value), True


def _compare(actual, op, value):
    if op == 'eq':
        return actual == value
    if op == 'ne':
        return actual != value
    if op == 'lt':
        return actual < value
    if op == 'lte':
        return actual <= value
    if op == 'gt':
        return actual > value
    if op == 'gte':
        return actual >= value
    if op == 'contains':
        needle = str(value or '').strip().lower()
        hay = str(actual or '').lower()
        if not needle:
            return False
        return needle in hay
    return False


def _read_ban(account, now, value):
    del now, value
    return account.ban, True


def _read_snipe_allowed(account, now, value):
    del now, value
    return account.snipe_allowed, True


def _read_balance(account, now, value):
    del now, value
    return account.balance, True


def _read_has_email(account, now, value):
    del now, value
    email = (account.email or '').strip()
    return bool(email) and email.lower() != 'none', True


def _read_email(account, now, value):
    del now, value
    return (account.email or '').strip(), True


def _read_linked(account, now, value):
    del now, value
    return account.linked_at is not None, True


def _read_market_open(account, now, value):
    del now, value
    if account.market_open is None:
        return None, False
    return account.market_open, True


def _read_market_today(account, now, value):
    del value
    metric = DailyMetric.objects.filter(
        account=account,
        date=timezone.localtime(now).date(),
        name='market_searches',
    ).first()
    if metric is None:
        return None, False
    return metric.value, True


def _read_preview_older_hours(account, now, value):
    del value
    if account.preview_pack_opened_at is None:
        return None, False
    hours = (now - account.preview_pack_opened_at).total_seconds() / 3600
    return hours, True


def _read_has_sbc_set(account, now, value):
    del now, value
    exists = SbcAssignment.objects.filter(
        account=account,
        state=SbcAssignment.STATE_ACTIVE,
    ).exists()
    return exists, True


def _read_priority_uncollected(account, now, value):
    del value
    week = now - timedelta(days=7)
    if _priority_failed_open(account, week):
        return True, True
    if _priority_assigned_without_collected(account, week):
        return True, True
    return False, True


def _priority_failed_open(account, week):
    names = (
        SbcAttempt.objects.filter(account=account, priority=True, occurred_at__gte=week)
        .values('sbc_name')
        .annotate(last_at=Max('occurred_at'))
    )
    for row in names:
        last = (
            SbcAttempt.objects.filter(
                account=account,
                priority=True,
                sbc_name=row['sbc_name'],
                occurred_at=row['last_at'],
            )
            .order_by('-id')
            .first()
        )
        if last is not None and last.outcome == SbcAttempt.OUTCOME_FAILED:
            return True
    return False


def _priority_assigned_without_collected(account, week):
    assignment = SbcAssignment.objects.filter(
        account=account,
        state=SbcAssignment.STATE_ACTIVE,
    ).select_related('sbc_set').first()
    if assignment is None:
        return False
    items = SbcSetItem.objects.filter(sbc_set=assignment.sbc_set, priority=True).select_related('template')
    if not items:
        return False
    for item in items:
        collected = SbcAttempt.objects.filter(
            account=account,
            sbc_name=item.template.name,
            outcome=SbcAttempt.OUTCOME_COLLECTED,
            occurred_at__gte=week,
        ).exists()
        if not collected:
            return True
    return False


def _read_sbc_name_uncollected(account, now, value):
    name = value
    week = now - timedelta(days=7)
    collected = SbcAttempt.objects.filter(
        account=account,
        sbc_name=name,
        outcome=SbcAttempt.OUTCOME_COLLECTED,
        occurred_at__gte=week,
    ).exists()
    if collected:
        return False, True
    failed = SbcAttempt.objects.filter(
        account=account,
        sbc_name=name,
        outcome=SbcAttempt.OUTCOME_FAILED,
        occurred_at__gte=week,
    ).exists()
    assigned = False
    assignment = SbcAssignment.objects.filter(
        account=account,
        state=SbcAssignment.STATE_ACTIVE,
    ).first()
    if assignment is not None:
        assigned = SbcSetItem.objects.filter(
            sbc_set=assignment.sbc_set,
            template__name=name,
        ).exists()
    return failed or assigned, True


def _read_nonpriority_collected_lt(account, now, value):
    week = now - timedelta(days=7)
    count = SbcAttempt.objects.filter(
        account=account,
        priority=False,
        outcome=SbcAttempt.OUTCOME_COLLECTED,
        occurred_at__gte=week,
    ).count()
    return count, True


def _read_in_folder(account, now, value):
    del now
    exists = FolderMember.objects.filter(folder_id=value, account=account).exists()
    return exists, True


def _read_not_opened_days(account, now, value):
    last = (
        RunEntry.objects.filter(account=account, closed_at__isnull=False)
        .order_by('-closed_at')
        .first()
    )
    if last is None:
        return None, False
    days = (now - last.closed_at).total_seconds() / 86400
    return days, True


FIELD_READERS = {
    'ban': _read_ban,
    'snipe_allowed': _read_snipe_allowed,
    'balance': _read_balance,
    'has_email': _read_has_email,
    'email': _read_email,
    'linked': _read_linked,
    'market_open': _read_market_open,
    'market_searches_today': _read_market_today,
    'preview_pack_older_hours': _read_preview_older_hours,
    'has_sbc_set': _read_has_sbc_set,
    'priority_sbc_uncollected': _read_priority_uncollected,
    'sbc_name_uncollected': _read_sbc_name_uncollected,
    'nonpriority_collected_lt': _read_nonpriority_collected_lt,
    'in_folder': _read_in_folder,
    'not_opened_days': _read_not_opened_days,
}

FILTER_FIELDS = [
    {'key': 'ban', 'title': 'бан'},
    {'key': 'snipe_allowed', 'title': 'снайп разрешён'},
    {'key': 'balance', 'title': 'баланс'},
    {'key': 'has_email', 'title': 'есть email'},
    {'key': 'email', 'title': 'email'},
    {'key': 'linked', 'title': 'связывался с сервером'},
    {'key': 'market_open', 'title': 'рынок открыт'},
    {'key': 'market_searches_today', 'title': 'запросы рынка сегодня'},
    {'key': 'preview_pack_older_hours', 'title': 'пак предпросмотра старше, ч'},
    {'key': 'has_sbc_set', 'title': 'назначен набор СБЧ'},
    {'key': 'priority_sbc_uncollected', 'title': 'не собрал приоритет'},
    {'key': 'sbc_name_uncollected', 'title': 'не собрал СБЧ (имя)'},
    {'key': 'nonpriority_collected_lt', 'title': 'неприоритетных сдач за 7 дней'},
    {'key': 'in_folder', 'title': 'состоит в папке (id)'},
    {'key': 'not_opened_days', 'title': 'давно не открывался, дней'},
]

FILTER_OPS = [
    ('eq', '='),
    ('ne', '≠'),
    ('lt', '<'),
    ('lte', '≤'),
    ('gt', '>'),
    ('gte', '≥'),
]

FILTER_PRESETS = [
    {'key': 'unlinked', 'title': 'Не связывался'},
    {'key': 'market_open', 'title': 'Рынок открыт'},
]

ACCOUNT_FILTER_PRESETS = FILTER_PRESETS + [
    {'key': 'sbc_assigned', 'title': 'Не собрали СБЧ'},
]


def filter_template(name, extra=''):
    if name == 'unlinked':
        return [{'field': 'linked', 'op': 'eq', 'value': False}]
    if name == 'market_open':
        return [{'field': 'market_open', 'op': 'eq', 'value': True}]
    if name == 'email':
        text = (extra or '').strip()
        if not text:
            return None
        return [{'field': 'email', 'op': 'contains', 'value': text}]
    if name == 'snipe':
        return [{'field': 'market_searches_today', 'op': 'lt', 'value': 350}]
    if name == 'sbc_assigned':
        return [{'field': 'has_sbc_set', 'op': 'eq', 'value': True}]
    if name == 'preview':
        return [{'field': 'preview_pack_older_hours', 'op': 'gt', 'value': 24}]
    if name == 'priority':
        return [{'field': 'priority_sbc_uncollected', 'op': 'eq', 'value': True}]
    if name == 'sbc_name':
        title = (extra or '').strip()
        if not title:
            return None
        return [{'field': 'sbc_name_uncollected', 'op': 'eq', 'value': title}]
    if name == 'nonpriority':
        try:
            limit = int(extra or '3')
        except ValueError:
            limit = 3
        return [{'field': 'nonpriority_collected_lt', 'op': 'lt', 'value': limit}]
    return None


def conditions_from_keys(keys, extras=None):
    extras = extras or {}
    result = []
    for key in keys or []:
        extra = extras.get(key) or ''
        added = filter_template(key, extra)
        if added is None:
            continue
        for item in added:
            if item not in result:
                result.append(item)
    return result


def append_filter(existing, name, extra=''):
    added = filter_template(name, extra)
    if added is None:
        return None
    result = list(existing or [])
    for item in added:
        if item not in result:
            result.append(item)
    return result


def drop_filter(existing, index):
    result = list(existing or [])
    if 0 <= index < len(result):
        result.pop(index)
    return result


def describe_filters(conditions):
    rows = []
    for index, item in enumerate(conditions or []):
        field = item.get('field')
        value = item.get('value')
        title, value_text = _describe_condition(field, value)
        rows.append({
            'index': index,
            'title': title,
            'value_text': value_text,
        })
    return rows


def _describe_condition(field, value):
    if field == 'linked':
        return ('Не связывался' if value is False else 'Связывался', '')
    if field == 'market_open':
        return ('Рынок открыт' if value else 'Рынок закрыт', '')
    if field == 'email':
        return ('По email', '' if value in (None, True, False) else str(value))
    if field == 'preview_pack_older_hours':
        return ('Добрать паки', '')
    if field == 'priority_sbc_uncollected':
        return ('Не собрал приоритет', '')
    if field == 'sbc_name_uncollected':
        return ('Не собрал СБЧ', '' if value in (None, True, False) else str(value))
    if field == 'nonpriority_collected_lt':
        return ('Неприоритет меньше', '' if value in (None, True, False) else str(value))
    title = next((item['title'] for item in FILTER_FIELDS if item['key'] == field), field)
    if value in (None, True, False):
        return (title, '')
    return (title, str(value))

