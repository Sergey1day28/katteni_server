from django.db import IntegrityError, transaction
from django.utils import timezone

from farm_core.models import SbcAssignment, SbcAttempt


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
