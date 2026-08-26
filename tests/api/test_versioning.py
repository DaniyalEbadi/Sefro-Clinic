from django.test import TestCase, override_settings
from rest_framework import status
from rest_framework.test import APIClient

from tests.helpers import admin_client


class LegacySurfaceTests(TestCase):
    def test_unversioned_endpoints_still_mounted(self):
        anon = APIClient()
        self.assertEqual(anon.get('/api/customers/').status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(anon.post('/api/auth/token/', {}, format='json').status_code, status.HTTP_400_BAD_REQUEST)


class V1AliasTests(TestCase):
    def test_v1_alias_requires_auth_and_serves_same_api(self):
        anon = APIClient()
        self.assertEqual(anon.get('/api/v1/auth/me/').status_code, status.HTTP_401_UNAUTHORIZED)
        client = admin_client()
        response = client.get('/api/v1/customers/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_v1_token_login_works(self):
        from tests.helpers import ADMIN_PASSWORD, ADMIN_USERNAME, make_admin

        make_admin()
        client = APIClient()
        response = client.post('/api/v1/auth/token/', {
            'username': ADMIN_USERNAME, 'password': ADMIN_PASSWORD,
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)


class V2ScaffoldTests(TestCase):
    def test_site_info_requires_authentication(self):
        response = APIClient().get('/api/v2/site/info/')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_site_info_returns_version_payload(self):
        response = admin_client().get('/api/v2/site/info/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['version'], 'v2')
        self.assertIn('name', response.data)


class SplitSchemaTests(TestCase):
    def test_v2_schema_excludes_dashboard_endpoints(self):
        body = admin_client().get('/api/v2/schema/').content.decode()
        self.assertIn('/api/v2/site/info/', body)
        self.assertNotIn('/api/customers/', body)
        self.assertNotIn('/api/reports/', body)

    def test_v1_schema_excludes_site_endpoints(self):
        body = admin_client().get('/api/v1/schema/').content.decode()
        self.assertIn('/api/v1/customers/', body)
        self.assertIn('/api/v1/auth/token/', body)
        self.assertNotIn('/api/v2/', body)

    def test_legacy_docs_point_at_dashboard_schema(self):
        body = admin_client().get('/api/schema/').content.decode()
        self.assertIn('/api/customers/', body)
        self.assertNotIn('/api/v2/', body)

    def test_versioned_docs_gated_like_legacy(self):
        with override_settings(DOCS_PUBLIC=False):
            anon = APIClient()
            self.assertEqual(anon.get('/api/v1/docs/').status_code, status.HTTP_401_UNAUTHORIZED)
            self.assertEqual(anon.get('/api/v2/docs/').status_code, status.HTTP_401_UNAUTHORIZED)
        client = admin_client()
        self.assertEqual(client.get('/api/v1/docs/').status_code, status.HTTP_200_OK)
        self.assertEqual(client.get('/api/v2/docs/').status_code, status.HTTP_200_OK)
