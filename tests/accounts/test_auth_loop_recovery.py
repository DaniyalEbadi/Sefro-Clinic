"""Regression tests for the intermittent 401 loop.

Failure modes these guard against:

* A stale body refresh token (rotated by another tab or kept in client
  storage) used to hard-fail even though the ``refresh_token`` cookie held
  the valid rotated successor.
* A definitively dead refresh cookie was never cleared on refresh failure,
  so the browser replayed the same blacklisted token forever.
* Logout 401'd when the access token had expired, so the one request meant
  to clear the dead session never ran.
* Zero JWT leeway rejected freshly issued tokens under clock skew.
"""
import time

from django.conf import settings
from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from tests.helpers import ADMIN_PASSWORD, ADMIN_USERNAME, login, make_admin


class RefreshLoopRecoveryTests(TestCase):
    def setUp(self):
        self.user = make_admin()
        self.client = APIClient()
        login(self.client, ADMIN_USERNAME, ADMIN_PASSWORD)

    def _rotate_via_cookie(self):
        """Refresh using the cookie; returns the token that is now stale."""
        stale = self.client.cookies['refresh_token'].value
        response = self.client.post('/api/auth/token/refresh/', {}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertNotEqual(self.client.cookies['refresh_token'].value, stale)
        return stale

    def test_stale_body_refresh_falls_back_to_rotated_cookie(self):
        stale = self._rotate_via_cookie()
        rotated = self.client.cookies['refresh_token'].value

        response = self.client.post(
            '/api/auth/token/refresh/', {'refresh': stale}, format='json',
        )

        self.assertEqual(response.status_code, 200)
        successor = self.client.cookies['refresh_token'].value
        self.assertNotEqual(successor, stale)
        self.assertNotEqual(successor, rotated)

    def test_empty_body_refresh_recovers_from_cookie(self):
        response = self.client.post(
            '/api/auth/token/refresh/', {'refresh': ''}, format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(self.client.cookies['refresh_token'].value)

    def test_dead_refresh_cookie_is_cleared_not_replayed(self):
        stale = self._rotate_via_cookie()
        # Force a replay of the blacklisted token as the only credential.
        self.client.cookies['refresh_token'] = stale

        response = self.client.post('/api/auth/token/refresh/', {}, format='json')

        self.assertEqual(response.status_code, 401)
        self.assertIn('refresh_token', response.cookies)
        self.assertEqual(response.cookies['refresh_token'].value, '')
        self.assertIn('access_token', response.cookies)
        self.assertEqual(response.cookies['access_token'].value, '')

    def test_failed_refresh_without_cookies_does_not_emit_set_cookie(self):
        client = APIClient()
        response = client.post(
            '/api/auth/token/refresh/', {'refresh': 'forged-token'}, format='json',
        )
        self.assertEqual(response.status_code, 401)
        self.assertNotIn('refresh_token', response.cookies)
        self.assertNotIn('access_token', response.cookies)


class LogoutEscapeHatchTests(TestCase):
    def test_logout_clears_cookies_despite_expired_access_token(self):
        user = make_admin()
        client = APIClient()
        login(client, ADMIN_USERNAME, ADMIN_PASSWORD)
        client.credentials()  # cookie-only client: no Authorization header

        expired = AccessToken.for_user(user)
        expired.payload['exp'] = int(time.time()) - 3600
        client.cookies['access_token'] = str(expired)

        response = client.post('/api/auth/logout/', {}, format='json')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.cookies['refresh_token'].value, '')
        self.assertEqual(response.cookies['access_token'].value, '')

        # The session is a clean terminal state: refresh can never revive it.
        follow_up = client.post('/api/auth/token/refresh/', {}, format='json')
        self.assertIn(follow_up.status_code, (400, 401))


class ClockSkewLeewayTests(TestCase):
    def test_leeway_is_configured(self):
        leeway = settings.SIMPLE_JWT['LEEWAY']
        self.assertGreaterEqual(leeway.total_seconds(), 1)

    def test_token_expired_within_leeway_is_accepted(self):
        user = make_admin()
        leeway = settings.SIMPLE_JWT['LEEWAY'].total_seconds()
        token = AccessToken.for_user(user)
        token.payload['exp'] = int(time.time()) - int(leeway // 2)
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')
        self.assertEqual(client.get('/api/auth/me/').status_code, 200)

    def test_token_expired_beyond_leeway_is_rejected(self):
        user = make_admin()
        leeway = settings.SIMPLE_JWT['LEEWAY'].total_seconds()
        token = AccessToken.for_user(user)
        token.payload['exp'] = int(time.time()) - int(leeway) - 60
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')
        self.assertEqual(client.get('/api/auth/me/').status_code, 401)
