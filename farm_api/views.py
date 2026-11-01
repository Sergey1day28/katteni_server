import logging

from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from farm_agent_api.http import fail, ok, read_json
from farm_core.bot_api import (
    ApiError,
    account_snapshot,
    events_push,
    market_filters,
    market_filters_remove,
    market_filters_save,
    notify,
    sbc_finish,
    sbc_list,
    sbc_save,
    sbc_sets,
    session_bind,
    session_credentials,
    session_finish,
    session_heartbeat,
    session_start,
    snipe_settings_save,
    solver_solve,
    solver_solutions,
)


HANDLERS = {
    'session/start': session_start,
    'session/bind': session_bind,
    'session/credentials': session_credentials,
    'session/heartbeat': session_heartbeat,
    'session/finish': session_finish,
    'events/push': events_push,
    'account/snapshot': account_snapshot,
    'sbc/list': sbc_list,
    'sbc/finish': sbc_finish,
    'sbc/sets': sbc_sets,
    'sbc/save': sbc_save,
    'market/filters': market_filters,
    'market/filters/save': market_filters_save,
    'market/filters/remove': market_filters_remove,
    'snipe-settings/save': snipe_settings_save,
    'notify': notify,
    'solver/solve': solver_solve,
    'solver/solutions': solver_solutions,
}


@csrf_exempt
@require_POST
def api_v1(request, route):
    handler = HANDLERS.get(route)
    if handler is None:
        logging.info('Неизвестный путь API %s', route)
        return fail('not_found', 'Нет такого вызова', status=200)
    try:
        body = read_json(request)
    except ValueError:
        return fail('bad_request', 'Тело не JSON', status=400)
    try:
        data = handler(body)
    except ApiError as error:
        logging.info('Отказ API %s: %s', error.code, error.message)
        return fail(error.code, error.message)
    return ok(data)
