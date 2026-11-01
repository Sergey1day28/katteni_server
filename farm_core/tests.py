from django.apps import apps
from django.test import SimpleTestCase


class SkeletonTests(SimpleTestCase):
    def test_приложения_подключены(self):
        self.assertTrue(apps.is_installed('farm_core'))
        self.assertTrue(apps.is_installed('farm_agent_api'))
        self.assertTrue(apps.is_installed('farm_api'))
        self.assertTrue(apps.is_installed('farm_console'))

    def test_проверка_здоровья_отвечает(self):
        response = self.client.get('/health/')
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body.get('ok'))
        self.assertEqual(body.get('data', {}).get('service'), 'katteni_server')
