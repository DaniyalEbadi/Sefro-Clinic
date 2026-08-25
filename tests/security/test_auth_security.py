import base64
import hashlib
import hmac
import json
import time
from datetime import timedelta

from django.conf import settings
from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APIClient
from rest_framework_simplejwt.settings import api_settings as jwt_settings
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken

from tests.helpers import ADMIN_PASSWORD, ADMIN_USERNAME, make_admin

LOGIN_URL = '/api/auth/token/'


def _b64(raw: bytes) -> bytes:
    return base64.urlsafe_b64encode(raw).rstrip(b'=')


def hs256_token(key: bytes, payload: dict) -> str:
    header = _b64(json.dumps({'alg': 'HS256', 'typ': 'JWT'}).encode())
    body = _b64(json.dumps(payload).encode())
    signing_input = header + b'.' + body
    signature = _b64(hmac.new(key, signing_input, hashlib.sha256).digest())
    return (signing_input + b'.' + signature).decode()


class CredentialHandlingTests(TestCase):
    def setUp(self):
        make_admin()
        self.client = APIClient()

    def test_wrong_password_rejected(self):
        response = self.client.post(LOGIN_URL, {
            'username': ADMIN_USERNAME, 'password': 'totally-wrong',
        }, format='json')
        self.assertEqual(response.status_code, 401)

    def test_nonexistent_user_and_wrong_password_are_indistinguishable(self):
        missing_user = self.client.post(LOGIN_URL, {
            'username': 'ghost-user', 'password': 'whatever-pass',
        }, format='json')
        wrong_password = self.client.post(LOGIN_URL, {
            'username': ADMIN_USERNAME, 'password': 'wrong-pass',
        }, format='json')
        self.assertEqual(missing_user.status_code, wrong_password.status_code)
        self.assertEqual(
            missing_user.json()['detail'] if hasattr(missing_user, 'json') else missing_user.data['detail'],
            wrong_password.data['detail'],
        )

    def test_missing_fields_rejected(self):
        self.assertEqual(self.client.post(LOGIN_URL, {}, format='json').status_code, 400)
        self.assertEqual(
            self.client.post(LOGIN_URL, {'username': ADMIN_USERNAME}, format='json').status_code,
            400,
        )

    def test_successful_login_sets_token_cookies(self):
        response = self.client.post(LOGIN_URL, {
            'username': ADMIN_USERNAME, 'password': ADMIN_PASSWORD,
        }, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertIn('access_token', response.cookies)
        self.assertIn('refresh_token', response.cookies)


class TokenValidationTests(TestCase):
    def setUp(self):
        self.user = make_admin()
        self.client = APIClient()

    def _auth(self, token):
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')

    def test_garbage_token_rejected(self):
        self._auth('not.a.token')
        self.assertEqual(self.client.get('/api/auth/me/').status_code, 401)

    def test_empty_bearer_rejected(self):
        self.client.credentials(HTTP_AUTHORIZATION='Bearer ')
        self.assertEqual(self.client.get('/api/auth/me/').status_code, 401)

    def test_tampered_signature_rejected(self):
        token = str(AccessToken.for_user(self.user))
        tampered = token[:-3] + ('xxx' if not token.endswith('xxx') else 'yyy')
        self._auth(tampered)
        self.assertEqual(self.client.get('/api/auth/me/').status_code, 401)

    def test_expired_token_rejected(self):
        token = AccessToken.for_user(self.user)
        token.payload['exp'] = int(time.time()) - 3600
        self._auth(str(token))
        self.assertEqual(self.client.get('/api/auth/me/').status_code, 401)

    def test_token_signed_with_different_key_rejected(self):
        payload = {
            'token_type': 'access',
            'exp': int(time.time()) + 600,
            'jti': 'forged-jti',
            'user_id': self.user.pk,
        }
        foreign = hs256_token(b'some-other-signing-key', payload)
        self._auth(foreign)
        self.assertEqual(self.client.get('/api/auth/me/').status_code, 401)

    def test_matching_key_signature_is_accepted(self):
        real_key = str(jwt_settings.SIGNING_KEY).encode()
        payload = {
            'token_type': 'access',
            'exp': int(time.time()) + 600,
            'jti': 'honest-jti',
            'user_id': self.user.pk,
        }
        honest = hs256_token(real_key, payload)
        self._auth(honest)
        self.assertEqual(self.client.get('/api/auth/me/').status_code, 200)

    def test_blacklisted_refresh_token_cannot_be_replayed(self):
        refresh = RefreshToken.for_user(self.user)
        refresh.blacklist()
        client = APIClient()
        response = client.post('/api/auth/token/refresh/', {'refresh': str(refresh)}, format='json')
        self.assertEqual(response.status_code, 401)

    def test_access_token_lifetime_matches_configuration(self):
        self.assertEqual(settings.SIMPLE_JWT['ACCESS_TOKEN_LIFETIME'], timedelta(minutes=30))
        self.assertTrue(settings.SIMPLE_JWT['ROTATE_REFRESH_TOKENS'])
        self.assertTrue(settings.SIMPLE_JWT['BLACKLIST_AFTER_ROTATION'])


class BruteForceProtectionTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_login_rate_limited_after_allowed_attempts(self):
        from rest_framework.throttling import ScopedRateThrottle

        make_admin()
        client = APIClient()
        original_rates = ScopedRateThrottle.THROTTLE_RATES
        ScopedRateThrottle.THROTTLE_RATES = {**original_rates, 'auth': '2/min'}
        try:
            statuses = []
            for _ in range(4):
                response = client.post(LOGIN_URL, {
                    'username': ADMIN_USERNAME, 'password': 'bad-pass',
                }, format='json')
                statuses.append(response.status_code)
        finally:
            ScopedRateThrottle.THROTTLE_RATES = original_rates
        self.assertEqual(statuses[0], 401)
        self.assertEqual(statuses[1], 401)
        self.assertEqual(statuses[2], 429)
        self.assertEqual(statuses[3], 429)
        cache.clear()
