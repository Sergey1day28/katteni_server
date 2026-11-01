import logging

from django.conf import settings
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from farm_agent_api.http import fail, ok, read_json
from farm_core.agent_queue import ack_command, finish_command, pending_for
from farm_core.circle import on_command_finished
from farm_core.models import AgentCommand
from farm_core.workers import ensure_configured_worker, find_worker_by_token, touch_worker


def _worker(request, body):
    token = request.headers.get('X-Agent-Token') or ''
    worker_id = body.get('worker_id') or ''
    if not worker_id:
        worker_id = getattr(settings, 'AGENT_WORKER_ID', '')
    worker = find_worker_by_token(worker_id, token)
    if worker is None:
        ensure_configured_worker()
        worker = find_worker_by_token(worker_id, token)
    return worker


@csrf_exempt
@require_POST
def poll(request):
    try:
        body = read_json(request)
    except ValueError:
        return fail('bad_json', 'Тело не JSON', status=400)
    worker = _worker(request, body)
    if worker is None:
        return fail('forbidden', 'Неверный токен агента', status=403)
    touch_worker(worker, body.get('agent_version') or '')
    commands = []
    for command in pending_for(worker):
        commands.append({
            'id': str(command.id),
            'action': command.action,
            'email': command.email,
        })
    logging.info('Опрос агента %s, команд %s', worker.worker_id, len(commands))
    return ok({
        'commands': commands,
        'poll_after_sec': getattr(settings, 'AGENT_POLL_SEC', 4),
    })


@csrf_exempt
@require_POST
def ack(request, command_id):
    command, worker, error = _load_command(request, command_id)
    if error is not None:
        return error
    del worker
    ack_command(command)
    logging.info('Агент подтвердил команду %s', command.id)
    return ok({'id': str(command.id), 'state': command.state})


@csrf_exempt
@require_POST
def result(request, command_id):
    command, worker, error = _load_command(request, command_id)
    if error is not None:
        return error
    try:
        body = read_json(request)
    except ValueError:
        return fail('bad_json', 'Тело не JSON', status=400)
    finish_command(command, body.get('state') or '', body.get('error_text') or '')
    command.refresh_from_db()
    on_command_finished(command)
    logging.info(
        'Итог команды %s: %s %s',
        command.id,
        command.state,
        command.error_text,
    )
    del worker
    return ok({'id': str(command.id), 'state': command.state})


def _load_command(request, command_id):
    try:
        body = read_json(request)
    except ValueError:
        return None, None, fail('bad_json', 'Тело не JSON', status=400)
    worker = _worker(request, body)
    if worker is None:
        return None, None, fail('forbidden', 'Неверный токен агента', status=403)
    try:
        command = AgentCommand.objects.get(id=command_id, worker=worker)
    except (AgentCommand.DoesNotExist, ValueError):
        return None, None, fail('not_found', 'Команда не найдена', status=200)
    return command, worker, None
