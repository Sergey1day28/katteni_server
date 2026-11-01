from django.utils import timezone

from farm_core.models import AgentCommand, Worker


def enqueue_open(worker, email, run=None, entry=None):
    return AgentCommand.objects.create(
        worker=worker,
        action=AgentCommand.ACTION_OPEN,
        email=email,
        run=run,
        entry=entry,
        state=AgentCommand.STATE_PENDING,
    )


def enqueue_stop_chrome(worker, run=None):
    return AgentCommand.objects.create(
        worker=worker,
        action=AgentCommand.ACTION_STOP,
        run=run,
        state=AgentCommand.STATE_PENDING,
    )


def pending_for(worker):
    return list(
        AgentCommand.objects.filter(
            worker=worker,
            state=AgentCommand.STATE_PENDING,
        ).order_by('created_at')
    )


def ack_command(command):
    if command.state != AgentCommand.STATE_PENDING:
        return command
    command.state = AgentCommand.STATE_ACKED
    command.acked_at = timezone.now()
    command.save(update_fields=['state', 'acked_at'])
    return command


def finish_command(command, state, error_text=''):
    if command.state in (AgentCommand.STATE_OPENED, AgentCommand.STATE_FAILED, AgentCommand.STATE_CANCELLED):
        return command
    if state not in (AgentCommand.STATE_OPENED, AgentCommand.STATE_FAILED):
        state = AgentCommand.STATE_FAILED
    command.state = state
    command.error_text = error_text or ''
    command.finished_at = timezone.now()
    command.save(update_fields=['state', 'error_text', 'finished_at'])
    return command


def cancel_pending(worker=None, run=None):
    query = AgentCommand.objects.filter(state=AgentCommand.STATE_PENDING)
    if worker is not None:
        query = query.filter(worker=worker)
    if run is not None:
        query = query.filter(run=run)
    return query.update(state=AgentCommand.STATE_CANCELLED, finished_at=timezone.now())


def default_worker():
    return Worker.objects.filter(enabled=True).order_by('id').first()
