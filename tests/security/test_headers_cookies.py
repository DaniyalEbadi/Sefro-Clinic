from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from tests.helpers import ADMIN_PASSWORD, ADMIN_USERNAME, make_admin


class SecurityHeaderTests(TestCase):
    def setUp(self):
        make_admin()
        login = APIClient()
        resp = login.post('/api/auth/token/', {
            'username': ADMIN_USERNAME, 'password': ADMIN_PASSWORD,
        }, format='json')
        self.access = resp.data['access']

    def _client(self):
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.access}')
        return client

    def test_x_frame_options_deny(self):
        response = self._client().get('/api/dashboard/')
        self.assertEqual(response['X-Frame-Options'], 'DENY')

    def test_content_type_nosniff_present(self):
        response = self._client().get('/api/dashboard/')
        self.assertEqual(response['X-Content-Type-Options'], 'nosniff')

    def test_referrer_policy_same_origin(self):
        response = self._client().get('/api/dashboard/')
        self.assertEqual(response['Referrer-Policy'], 'same-origin')

    def test_no_server_stack_banner_leakage(self):
        response = self._client().get('/api/dashboard/')
        self.assertNotIn('WSGIServer', response.get('Server', ''))


class CookieSecurityTests(TestCase):
    def setUp(self):
        make_admin()
        self.client = APIClient()

    def _login(self):
        return self.client.post('/api/auth/token/', {
            'username': ADMIN_USERNAME, 'password': ADMIN_PASSWORD,
        }, format='json')

    def test_tokens_are_httponly_and_lax_by_default(self):
        response = self._login()
        for name in ['access_token', 'refresh_token']:
            cookie = response.cookies[name]
            self.assertTrue(cookie['httponly'], name)
            self.assertEqual(cookie['samesite'], 'Lax', name)

    def test_access_cookie_lifetime_matches_token_lifetime(self):
        response = self._login()
        self.assertEqual(int(response.cookies['access_token']['max-age']), 24 * 60 * 60)
        self.assertEqual(int(response.cookies['refresh_token']['max-age']), 7 * 24 * 3600)

    def test_cookies_not_secure_in_local_http_mode(self):
        response = self._login()
        self.assertFalse(response.cookies['access_token']['secure'])

    @override_settings(JWT_AUTH_COOKIE_SECURE=True)
    def test_cookies_secure_flag_when_configured(self):
        response = self._login()
        self.assertTrue(response.cookies['access_token']['secure'])
        self.assertTrue(response.cookies['refresh_token']['secure'])


class TransportSecurityTests(TestCase):
    @override_settings(SECURE_SSL_REDIRECT=True)
    def test_http_requests_redirect_to_https(self):
        response = APIClient().get('/api/auth/me/')
        self.assertEqual(response.status_code, 301)
        self.assertTrue(response['Location'].startswith('https://'))

    @override_settings(SECURE_HSTS_SECONDS=31536000)
    def test_hsts_header_when_enabled(self):
        client = APIClient()
        response = client.get('/api/auth/me/', secure=True)
        self.assertEqual(response['Strict-Transport-Security'], 'max-age=31536000')

    def test_no_hsts_header_by_default(self):
        response = APIClient().get('/api/auth/me/')
        self.assertIsNone(response.get('Strict-Transport-Security'))
