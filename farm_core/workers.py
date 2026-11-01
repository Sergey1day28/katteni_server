from django.conf import settings
from django.utils import timezone

from farm_core.models import Worker
from farm_core.tokens import hash_token, token_matches


def ensure_configured_worker():
    worker_id = getattr(settings, 'AGENT_WORKER_ID', 'this-pc')
    token = getattr(settings, 'AGENT_TOKEN', '')
    title = getattr(settings, 'AGENT_TITLE', 'Этот ПК')
    worker, created = Worker.objects.get_or_create(
        worker_id=worker_id,
        defaults={
            'title': title,
            'token_hash': hash_token(token),
            'enabled': True,
        },
    )
    if token and not token_matches(worker.token_hash, token):
        worker.token_hash = hash_token(token)
        worker.title = title or worker.title
        worker.save(update_fields=['token_hash', 'title'])
    elif created:
        worker.title = title
        worker.save(update_fields=['title'])
    return worker


def touch_worker(worker, agent_version=''):
    worker.last_poll_at = timezone.now()
    if agent_version:
        worker.agent_version = agent_version
    worker.save(update_fields=['last_poll_at', 'agent_version'])


def find_worker_by_token(worker_id, token):
    try:
        worker = Worker.objects.get(worker_id=worker_id, enabled=True)
    except Worker.DoesNotExist:
        return None
    if not token_matches(worker.token_hash, token):
        return None
    return worker
