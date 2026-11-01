from django.db import transaction
from django.utils import timezone

from farm_core.agent_queue import cancel_pending, enqueue_open, enqueue_stop_chrome
from farm_core.folder_filter import accounts_for_start, accounts_in_other_active_run
from farm_core.models import (
    AgentCommand,
    FolderRun,
    NotifyOutbox,
    RunEntry,
)
from farm_core.sbc import assign_set, default_sbc_set
from farm_core.workers import ensure_configured_worker


def start_folder(folder, started_by='operator', worker=None, kill_chrome=False):
    worker = worker or ensure_configured_worker()
    now = timezone.now()
    if FolderRun.objects.filter(folder=folder, state=FolderRun.STATE_ACTIVE).exists():
        return {'ok': False, 'error': {'code': 'running', 'message': 'Круг этой папки уже идёт'}}
    if not worker.enabled:
        return {'ok': False, 'error': {'code': 'worker_disabled', 'message': 'ПК выключен'}}
    selected, missing = _members_for_start(folder, now)
    if not selected:
        return {
            'ok': False,
            'error': {'code': 'empty', 'message': '0 аккаунтов'},
            'missing_data': missing,
        }
    busy = accounts_in_other_active_run([account.id for account in selected])
    ready = [account for account in selected if account.id not in busy]
    skipped = [account for account in selected if account.id in busy]
    if not ready:
        return {
            'ok': False,
            'error': {'code': 'all_busy', 'message': 'Все аккаунты уже в другом круге'},
            'skipped': [account.email for account in skipped],
        }
    with transaction.atomic():
        run = FolderRun.objects.create(
            folder=folder,
            state=FolderRun.STATE_ACTIVE,
            play_mode=folder.play_mode,
            modes=list(folder.modes or []),
            open_at_a_time=folder.open_at_a_time,
            started_by=started_by,
        )
        entries = []
        for index, account in enumerate(_ordered(ready, folder.order)):
            entries.append(
                RunEntry.objects.create(
                    run=run,
                    email=(account.email or '').strip(),
                    account=account,
                    position=index,
                    state=RunEntry.STATE_WAITING,
                )
            )
            if folder.assign_sbc:
                sbc_set = default_sbc_set()
                if sbc_set is not None:
                    assign_set(account, sbc_set, run=run)
        enqueue_stop_chrome(worker, run=run)
        opened = _queue_next(run, worker, folder.open_at_a_time)
    return {
        'ok': True,
        'data': {
            'run_id': run.id,
            'queued': opened,
            'total': len(entries),
            'skipped': [account.email for account in skipped],
            'missing_data': missing,
        },
    }


def continue_folder(folder, started_by='operator', worker=None):
    worker = worker or ensure_configured_worker()
    run = (
        FolderRun.objects.filter(folder=folder)
        .exclude(state=FolderRun.STATE_ACTIVE)
        .order_by('-started_at')
        .first()
    )
    if run is None:
        return {'ok': False, 'error': {'code': 'no_run', 'message': 'Нет круга для продолжения'}}
    open_states = [RunEntry.STATE_WAITING, RunEntry.STATE_QUEUED, RunEntry.STATE_OPENED]
    leftovers = list(run.entries.filter(state__in=open_states).order_by('position'))
    if not leftovers:
        return {'ok': False, 'error': {'code': 'nothing', 'message': 'Нет незакрытых записей'}}
    with transaction.atomic():
        run.state = FolderRun.STATE_ACTIVE
        run.ended_at = None
        run.end_reason = ''
        run.started_by = started_by
        run.save(update_fields=['state', 'ended_at', 'end_reason', 'started_by'])
        queued = _queue_next(run, worker, run.open_at_a_time)
    return {'ok': True, 'data': {'run_id': run.id, 'queued': queued, 'total': len(leftovers)}}


def stop_run(run):
    now = timezone.now()
    with transaction.atomic():
        run.state = FolderRun.STATE_STOPPED
        run.ended_at = now
        run.end_reason = 'stopped'
        run.save(update_fields=['state', 'ended_at', 'end_reason'])
        run.entries.filter(state__in=[RunEntry.STATE_WAITING, RunEntry.STATE_QUEUED]).update(
            state=RunEntry.STATE_CANCELLED,
            closed_at=now,
        )
        cancel_pending(run=run)
    return {'ok': True, 'data': {'run_id': run.id}}


def confirm_opened(email):
    entry = _active_entry(email)
    if entry is None:
        return None
    if entry.state != RunEntry.STATE_OPENED:
        entry.state = RunEntry.STATE_OPENED
        entry.confirmed_at = timezone.now()
        entry.last_seen_at = timezone.now()
        entry.save(update_fields=['state', 'confirmed_at', 'last_seen_at'])
    else:
        entry.last_seen_at = timezone.now()
        entry.save(update_fields=['last_seen_at'])
    return entry


def finish_entry(email, reason='done'):
    entry = _active_entry(email) or _entry_by_email(email)
    if entry is None:
        return {'action': 'ok', 'moved': False}
    if entry.state in (RunEntry.STATE_CLOSED, RunEntry.STATE_EXTRA):
        return {'action': 'close_browser', 'moved': False}
    now = timezone.now()
    if entry.state not in (RunEntry.STATE_CLOSED, RunEntry.STATE_FAILED, RunEntry.STATE_CANCELLED):
        entry.state = RunEntry.STATE_CLOSED
        entry.closed_at = now
        entry.last_seen_at = now
        entry.save(update_fields=['state', 'closed_at', 'last_seen_at'])
        run = entry.run
        if run.state == FolderRun.STATE_ACTIVE:
            worker = None
            if entry.last_command_id:
                worker = entry.last_command.worker
            worker = worker or ensure_configured_worker()
            _queue_next(run, worker, 1)
            _maybe_finish(run)
    del reason
    return {'action': 'close_browser', 'moved': True}


def _active_entry(email):
    text = (email or '').strip()
    if not text:
        return None
    return (
        RunEntry.objects.filter(
            email__iexact=text,
            run__state=FolderRun.STATE_ACTIVE,
            state__in=[
                RunEntry.STATE_WAITING,
                RunEntry.STATE_QUEUED,
                RunEntry.STATE_OPENED,
            ],
        )
        .select_related('run', 'run__folder', 'account', 'last_command')
        .order_by('-id')
        .first()
    )


def _entry_by_email(email):
    text = (email or '').strip()
    if not text:
        return None
    return (
        RunEntry.objects.filter(email__iexact=text)
        .select_related('run', 'account')
        .order_by('-id')
        .first()
    )


def on_command_finished(command):
    if command.action != AgentCommand.ACTION_OPEN or command.entry_id is None:
        return
    entry = command.entry
    run = command.run
    if entry is None or run is None:
        return
    if command.state == AgentCommand.STATE_FAILED:
        entry.state = RunEntry.STATE_FAILED
        entry.error_text = command.error_text
        entry.closed_at = timezone.now()
        entry.save(update_fields=['state', 'error_text', 'closed_at'])
        _notify_failed(run, entry)
        if command.worker_id:
            _queue_next(run, command.worker, 1)
        _maybe_finish(run)
        return
    if command.state == AgentCommand.STATE_OPENED:
        entry.state = RunEntry.STATE_QUEUED
        entry.save(update_fields=['state'])


def _members_for_start(folder, now):
    return accounts_for_start(folder, now=now)


def _ordered(accounts, order):
    if order == 'last_opened':
        return sorted(accounts, key=lambda account: account.id)
    return sorted(accounts, key=lambda account: (account.email or '', account.id))


def _queue_next(run, worker, count):
    waiting = list(
        run.entries.filter(state=RunEntry.STATE_WAITING).order_by('position')[:count]
    )
    now = timezone.now()
    queued = 0
    for entry in waiting:
        command = enqueue_open(worker, entry.email, run=run, entry=entry)
        entry.state = RunEntry.STATE_QUEUED
        entry.queued_at = now
        entry.last_command = command
        entry.save(update_fields=['state', 'queued_at', 'last_command'])
        queued += 1
    return queued


def _maybe_finish(run):
    open_states = [RunEntry.STATE_WAITING, RunEntry.STATE_QUEUED, RunEntry.STATE_OPENED]
    if run.entries.filter(state__in=open_states).exists():
        return
    run.state = FolderRun.STATE_FINISHED
    run.ended_at = timezone.now()
    run.end_reason = 'finished'
    run.save(update_fields=['state', 'ended_at', 'end_reason'])


def _notify_failed(run, entry):
    key = 'run-%s-fail' % run.id
    text = 'Круг «%s»: не открылись %s (%s)' % (
        run.folder.name,
        entry.email,
        entry.error_text,
    )
    NotifyOutbox.objects.get_or_create(
        dedup_key=key,
        defaults={'channel': 'important', 'text': text},
    )
    outbox = NotifyOutbox.objects.get(dedup_key=key)
    if entry.email not in outbox.text:
        outbox.text = outbox.text + '; ' + entry.email
        outbox.save(update_fields=['text'])
