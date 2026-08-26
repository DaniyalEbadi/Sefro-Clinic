from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient


class PublicCatalogAccessTests(TestCase):
    """v2 site endpoints are public and return empty catalogs until content is added."""

    ENDPOINTS = [
        '/api/v2/services/',
        '/api/v2/packages/',
        '/api/v2/products/',
        '/api/v2/team/',
        '/api/v2/testimonials/',
    ]

    def test_all_catalog_endpoints_public_and_empty(self):
        client = APIClient()
        for url in self.ENDPOINTS:
            response = client.get(url)
            self.assertEqual(response.status_code, status.HTTP_200_OK, url)
            data = response.data
            results = data['results'] if isinstance(data, dict) and 'results' in data else data
            self.assertEqual(list(results), [], url)

    def test_service_detail_unknown_slug_returns_404(self):
        response = APIClient().get('/api/v2/services/nothing-here/')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_category_filter_param_accepted(self):
        response = APIClient().get('/api/v2/services/?category=face')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['results'], [])

    def test_site_info_still_requires_authentication(self):
        self.assertEqual(
            APIClient().get('/api/v2/site/info/').status_code,
            status.HTTP_401_UNAUTHORIZED,
        )


class SurfaceSeparationTests(TestCase):
    def test_website_paths_absent_from_dashboard_schema(self):
        from tests.helpers import admin_client

        body = admin_client().get('/api/schema/').content.decode()
        self.assertNotIn('/api/v2/', body)
        self.assertNotIn('site-services', body)

    def test_v2_schema_lists_website_endpoints_not_dashboard_ones(self):
        from tests.helpers import admin_client

        body = admin_client().get('/api/v2/schema/').content.decode()
        for expected in ['/api/v2/services/', '/api/v2/packages/', '/api/v2/contact/']:
            self.assertIn(expected, body)
        self.assertNotIn('/api/customers/', body)
        self.assertNotIn('/api/inventory/', body)
