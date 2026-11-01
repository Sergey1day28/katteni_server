from datetime import timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone

from farm_core.models import SbcAssignment, SbcAttempt, SbcSet


def clear_assignment(account):
    now = timezone.now()
    return SbcAssignment.objects.filter(
        account=account,
        state=SbcAssignment.STATE_ACTIVE,
    ).update(state=SbcAssignment.STATE_FINISHED, finished_at=now)


def clear_set_assignments(sbc_set):
    now = timezone.now()
    return SbcAssignment.objects.filter(
        sbc_set=sbc_set,
        state=SbcAssignment.STATE_ACTIVE,
    ).update(state=SbcAssignment.STATE_FINISHED, finished_at=now)


def default_sbc_set():
    return SbcSet.objects.filter(common=True).first() or SbcSet.objects.order_by('id').first()


def assign_set(account, sbc_set, run=None):
    now = timezone.now()
    with transaction.atomic():
        SbcAssignment.objects.filter(
            account=account,
            state=SbcAssignment.STATE_ACTIVE,
        ).update(state=SbcAssignment.STATE_REPLACED, finished_at=now)
        return SbcAssignment.objects.create(
            account=account,
            sbc_set=sbc_set,
            set_version=sbc_set.version,
            run=run,
            state=SbcAssignment.STATE_ACTIVE,
        )


def record_attempt(
    account,
    client_event_id,
    sbc_name,
    outcome,
    occurred_at,
    priority=False,
    reason='',
    challenge_id='',
    assignment=None,
    template=None,
):
    try:
        with transaction.atomic():
            return SbcAttempt.objects.create(
                account=account,
                client_event_id=client_event_id,
                sbc_name=sbc_name,
                outcome=outcome,
                occurred_at=occurred_at,
                priority=priority,
                reason=reason,
                challenge_id=challenge_id,
                assignment=assignment,
                template=template,
            ), True
    except IntegrityError:
        existing = SbcAttempt.objects.get(client_event_id=client_event_id)
        return existing, False


def attach_week_sbc(accounts, now=None):
    now = now or timezone.now()
    week = now - timedelta(days=7)
    ids = [account.id for account in accounts]
    names = {}
    for assignment in (
        SbcAssignment.objects.filter(
            account_id__in=ids,
            state=SbcAssignment.STATE_ACTIVE,
        ).select_related('sbc_set')
    ):
        names[assignment.account_id] = assignment.sbc_set.name
    last_by_name = {}
    tried = {}
    for attempt in SbcAttempt.objects.filter(
        account_id__in=ids,
        occurred_at__gte=week,
    ).order_by('occurred_at', 'id'):
        tried[attempt.account_id] = tried.get(attempt.account_id, 0) + 1
        last_by_name[(attempt.account_id, attempt.sbc_name)] = attempt.outcome
    collected = {}
    failed = {}
    for (account_id, sbc_name), outcome in last_by_name.items():
        if outcome == SbcAttempt.OUTCOME_COLLECTED:
            collected.setdefault(account_id, []).append(sbc_name)
        elif outcome == SbcAttempt.OUTCOME_FAILED:
            failed.setdefault(account_id, []).append(sbc_name)
    for account in accounts:
        account.sbc_set_name = names.get(account.id) or ''
        account.sbc_tried = tried.get(account.id, 0)
        account.sbc_collected = collected.get(account.id, [])
        account.sbc_failed = failed.get(account.id, [])
    return accounts
