from django.test import TestCase

from farm_core.agent_queue import enqueue_open
from farm_core.models import AgentCommand, Worker
from farm_core.tokens import hash_token


class AgentApiTests(TestCase):
    def setUp(self):
        self.worker = Worker.objects.create(
            worker_id='pc-1',
            token_hash=hash_token('secret'),
            enabled=True,
        )

    def _headers(self):
        return {'HTTP_X_AGENT_TOKEN': 'secret'}

    def test_poll_ack_result_opened(self):
        command = enqueue_open(self.worker, 'a@b.com')
        poll = self.client.post(
            '/agent/v1/poll',
            data='{"worker_id":"pc-1","agent_version":"1"}',
            content_type='application/json',
            **self._headers(),
        )
        self.assertEqual(poll.status_code, 200)
        body = poll.json()
        self.assertTrue(body['ok'])
        self.assertEqual(body['data']['commands'][0]['email'], 'a@b.com')
        ack = self.client.post(
            '/agent/v1/commands/%s/ack' % command.id,
            data='{"worker_id":"pc-1"}',
            content_type='application/json',
            **self._headers(),
        )
        self.assertTrue(ack.json()['ok'])
        command.refresh_from_db()
        self.assertEqual(command.state, AgentCommand.STATE_ACKED)
        result = self.client.post(
            '/agent/v1/commands/%s/result' % command.id,
            data='{"worker_id":"pc-1","state":"opened"}',
            content_type='application/json',
            **self._headers(),
        )
        self.assertTrue(result.json()['ok'])
        command.refresh_from_db()
        self.assertEqual(command.state, AgentCommand.STATE_OPENED)

    def test_повтор_ack_и_итога_не_меняет(self):
        command = enqueue_open(self.worker, 'a@b.com')
        self.client.post(
            '/agent/v1/commands/%s/ack' % command.id,
            data='{"worker_id":"pc-1"}',
            content_type='application/json',
            **self._headers(),
        )
        self.client.post(
            '/agent/v1/commands/%s/result' % command.id,
            data='{"worker_id":"pc-1","state":"failed","error_text":"не найден ярлык"}',
            content_type='application/json',
            **self._headers(),
        )
        self.client.post(
            '/agent/v1/commands/%s/ack' % command.id,
            data='{"worker_id":"pc-1"}',
            content_type='application/json',
            **self._headers(),
        )
        self.client.post(
            '/agent/v1/commands/%s/result' % command.id,
            data='{"worker_id":"pc-1","state":"opened"}',
            content_type='application/json',
            **self._headers(),
        )
        command.refresh_from_db()
        self.assertEqual(command.state, AgentCommand.STATE_FAILED)
        self.assertEqual(command.error_text, 'не найден ярлык')

    def test_чужой_токен_отказ(self):
        response = self.client.post(
            '/agent/v1/poll',
            data='{"worker_id":"pc-1"}',
            content_type='application/json',
            HTTP_X_AGENT_TOKEN='wrong',
        )
        self.assertEqual(response.status_code, 403)
