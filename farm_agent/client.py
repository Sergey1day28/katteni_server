import json
import logging
import urllib.error
import urllib.request


class AgentClient:
    def __init__(self, base_url, token, opener=None):
        self._base_url = base_url.rstrip('/')
        self._token = token
        self._opener = opener or urllib.request.urlopen

    def poll(self, worker_id, agent_version):
        return self._post(
            '/agent/v1/poll',
            {'worker_id': worker_id, 'agent_version': agent_version},
        )

    def ack(self, command_id):
        return self._post('/agent/v1/commands/%s/ack' % command_id, {})

    def result(self, command_id, state, error_text=''):
        return self._post(
            '/agent/v1/commands/%s/result' % command_id,
            {'state': state, 'error_text': error_text},
        )

    def _post(self, path, payload):
        body = json.dumps(payload).encode('utf-8')
        request = urllib.request.Request(
            self._base_url + path,
            data=body,
            method='POST',
            headers={
                'Content-Type': 'application/json',
                'X-Agent-Token': self._token,
            },
        )
        try:
            with self._opener(request, timeout=20) as response:
                raw = response.read().decode('utf-8')
        except urllib.error.URLError as error:
            logging.info('Сеть агента недоступна: %s', error)
            raise
        return _payload(json.loads(raw))


def _payload(parsed):
    if not isinstance(parsed, dict):
        return {}
    if parsed.get('ok') is False:
        error = parsed.get('error') or {}
        logging.info('Ответ агента не ok: %s', error.get('message') or error)
        return {}
    data = parsed.get('data')
    if isinstance(data, dict):
        return data
    return parsed
