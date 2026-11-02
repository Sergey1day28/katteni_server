import logging
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from farm_core.agent_queue import enqueue_close
from farm_core.circle import finish_entry
from farm_core.models import AgentCommand, FolderRun, NotifyOutbox, RunEntry
from farm_core.telegram_send import send_auto_buy

logger = logging.getLogger(__name__)


def release_profiles_without_session(now=None, send=None):
    now = now or timezone.now()
    grace = int(getattr(settings, 'OPEN_GRACE_SEC', 120))
    limit = now - timedelta(seconds=grace)
    entries = RunEntry.objects.filter(
        run__state=FolderRun.STATE_ACTIVE,
        state=RunEntry.STATE_QUEUED,
        last_command__action=AgentCommand.ACTION_OPEN,
        last_command__state=AgentCommand.STATE_OPENED,
        last_command__finished_at__lte=limit,
    ).select_related('run', 'last_command', 'last_command__worker')
    released = []
    for entry in entries:
        if _close_already_pending(entry.email):
            continue
        worker = entry.last_command.worker
        enqueue_close(worker, entry.email, run=entry.run)
        finish_entry(entry.email)
        _notify(entry, send)
        logger.info('Профиль без вкладки EA, закрываю %s', entry.email)
        released.append(entry.email)
    return released


def _close_already_pending(email):
    return AgentCommand.objects.filter(
        email__iexact=email,
        action=AgentCommand.ACTION_CLOSE,
        state__in=(AgentCommand.STATE_PENDING, AgentCommand.STATE_ACKED),
    ).exists()


def _notify(entry, send):
    text = '%s вкладка EA не открылась' % entry.email
    key = 'ea-tab-%s' % entry.id
    outbox, _created = NotifyOutbox.objects.get_or_create(
        dedup_key=key,
        defaults={'channel': 'auto_buy', 'text': text},
    )
    sender = send or send_auto_buy
    if sender(text):
        outbox.state = NotifyOutbox.STATE_SENT
        outbox.sent_at = timezone.now()
        outbox.save(update_fields=['state', 'sent_at'])
