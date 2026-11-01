import json

from django.http import JsonResponse


def read_json(request):
    if not request.body:
        return {}
    return json.loads(request.body.decode('utf-8'))


def ok(data, status=200):
    return JsonResponse({'ok': True, 'data': data}, status=status)


def fail(code, message, status=200):
    return JsonResponse(
        {'ok': False, 'error': {'code': code, 'message': message}},
        status=status,
    )
