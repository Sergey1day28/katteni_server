from datetime import timedelta

from django.db.models import Max
from django.utils import timezone

from farm_core.models import (
    Account,
    DailyMetric,
    FolderManual,
    FolderMember,
    FolderRun,
    RunEntry,
    SbcAssignment,
    SbcAttempt,
    SbcSetItem,
)


def default_filter():
    return []


def evaluate_folder(folder, now=None):
    now = now or timezone.now()
    selected = []
    missing = 0
    accounts = list(Account.objects.all())
    include_ids = set(
        FolderManual.objects.filter(folder=folder, kind=FolderManual.KIND_INCLUDE).values_list(
            'account_id', flat=True
        )
    )
    exclude_ids = set(
        FolderManual.objects.filter(folder=folder, kind=FolderManual.KIND_EXCLUDE).values_list(
            'account_id', flat=True
        )
    )
    conditions = list(folder.filter or [])
    for account in accounts:
        if account.id in exclude_ids:
            continue
        if account.id in include_ids:
            selected.append(account)
            continue
        if not conditions:
            selected.append(account)
            continue
        matched, has_data = _match_all(account, conditions, now)
        if not has_data:
            missing += 1
            continue
        if matched:
            selected.append(account)
    return selected, missing


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


def filter_template(name, extra=''):
    if name == 'unlinked':
        return [{'field': 'linked', 'op': 'eq', 'value': False}]
    if name == 'market_open':
        return [{'field': 'market_open', 'op': 'eq', 'value': True}]
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

