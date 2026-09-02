from django.test import TestCase, override_settings
from rest_framework import status
from rest_framework.test import APIClient

from tests.helpers import admin_client


class LegacySurfaceTests(TestCase):
    def test_unversioned_endpoints_still_mounted(self):
        anon = APIClient()
        self.assertEqual(anon.get('/api/customers/').status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(anon.post('/api/auth/token/', {}, format='json').status_code, status.HTTP_400_BAD_REQUEST)

    def test_removed_v1_alias_is_gone(self):
        anon = APIClient()
        self.assertEqual(anon.get('/api/v1/customers/').status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(anon.post('/api/v1/auth/token/', {}, format='json').status_code, status.HTTP_404_NOT_FOUND)


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
    def test_v2_schema_is_isolated_and_self_described(self):
        body = admin_client().get('/api/v2/schema/').content.decode()
        self.assertIn('/api/v2/site/info/', body)
        self.assertNotIn('/api/customers/', body)
        self.assertNotIn('/api/reports/', body)
        self.assertIn('Sefro Clinic Site API', body)
        self.assertIn('2.0.0', body)
        self.assertNotIn('"Employees"', body)

    def test_legacy_schema_shows_dashboard_api_only(self):
        body = admin_client().get('/api/schema/').content.decode()
        self.assertIn('/api/customers/', body)
        self.assertIn('/api/logs/', body)
        self.assertNotIn('/api/v2/', body)

    def test_legacy_schema_includes_new_pricing_and_category(self):
        body = admin_client().get('/api/schema/').content.decode()
        self.assertIn('/api/service-categories/', body)
        self.assertIn('/api/services/', body)
        self.assertIn('estimated_cost_usd', body)
        self.assertIn('estimated_gross_profit_usd', body)
        self.assertIn('estimated_margin_percent', body)
        self.assertIn('price_toman', body)
        self.assertIn('/api/finance/service-items/', body)

    def test_service_category_not_in_v2_schema(self):
        body = admin_client().get('/api/v2/schema/').content.decode()
        self.assertNotIn('/api/service-categories/', body)
        self.assertNotIn('estimated_cost_usd', body)

    def test_versioned_docs_gated_like_legacy(self):
        with override_settings(DOCS_PUBLIC=False):
            anon = APIClient()
            self.assertEqual(anon.get('/api/docs/').status_code, status.HTTP_401_UNAUTHORIZED)
            self.assertEqual(anon.get('/api/v2/docs/').status_code, status.HTTP_401_UNAUTHORIZED)
        client = admin_client()
        self.assertEqual(client.get('/api/docs/').status_code, status.HTTP_200_OK)
        self.assertEqual(client.get('/api/v2/docs/').status_code, status.HTTP_200_OK)

    def test_docs_pages_render_version_switcher(self):
        client = admin_client()
        for url in ['/api/docs/', '/api/v2/docs/']:
            body = client.get(url).content.decode()
            self.assertIn('version-switcher', body, url)
            self.assertIn('/api/v2/docs/', body, url)
