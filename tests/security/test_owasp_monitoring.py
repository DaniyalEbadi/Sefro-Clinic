from django.test import TestCase
from rest_framework.test import APIClient

from tests.helpers import ADMIN_PASSWORD, ADMIN_USERNAME, make_admin


class AuthEventMonitoringTests(TestCase):
    def test_failed_login_produces_detectable_warning_log(self):
        make_admin()
        client = APIClient()
        with self.assertLogs('django.request', level='WARNING') as captured:
            client.post('/api/auth/token/', {
                'username': ADMIN_USERNAME, 'password': ADMIN_PASSWORD[::-1],
            }, format='json')
        joined = '\n'.join(captured.output)
        self.assertTrue(
            'Unauthorized' in joined or 'Bad Request' in joined,
            f'failed login left no security log trace: {captured.output}',
        )

    def test_token_refresh_failure_is_logged(self):
        client = APIClient()
        with self.assertLogs('django.request', level='WARNING') as captured:
            client.post('/api/auth/token/refresh/', {'refresh': 'forged-token'}, format='json')
        self.assertIn('Unauthorized', '\n'.join(captured.output))
