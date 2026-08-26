from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from tests.helpers import admin_client


class ApiDocsGatingTests(TestCase):
    def test_anonymous_docs_blocked_by_default(self):
        with override_settings(DOCS_PUBLIC=False):
            self.assertEqual(APIClient().get('/api/docs/').status_code, 401)

    def test_anonymous_schema_blocked_by_default(self):
        with override_settings(DOCS_PUBLIC=False):
            self.assertEqual(APIClient().get('/api/schema/').status_code, 401)

    def test_authenticated_user_can_read_docs_and_schema(self):
        client = admin_client()
        self.assertEqual(client.get('/api/docs/').status_code, 200)
        response = client.get('/api/schema/')
        self.assertEqual(response.status_code, 200)
        schema_text = response.content.decode()
        self.assertIn('/api/customers/', schema_text)

    @override_settings(DOCS_PUBLIC=True)
    def test_docs_public_when_explicitly_enabled(self):
        self.assertEqual(APIClient().get('/api/docs/').status_code, 200)


class RemovedSurfaceTests(TestCase):
    def test_django_admin_is_gone(self):
        response = APIClient().get('/admin/')
        self.assertEqual(response.status_code, 404)

    def test_inventory_endpoints_require_authentication(self):
        for url in [
            '/api/inventory/products/',
        ]:
            response = APIClient().get(url)
            self.assertEqual(response.status_code, 401, url)


class ErrorDisclosureTests(TestCase):
    def test_404_response_has_no_stack_trace(self):
        client = admin_client()
        response = client.get('/api/customers/999999/')
        self.assertEqual(response.status_code, 404)
        self.assertNotIn('Traceback', str(response.content))

    def test_validation_errors_do_not_leak_internal_paths(self):
        client = admin_client()
        response = client.post('/api/customers/', {'first_name': 'x'}, format='json')
        self.assertEqual(response.status_code, 400)
        body = response.content.decode()
        self.assertNotIn('C:\\', body)
        self.assertNotIn('Traceback', body)

    def test_method_not_allowed_is_clean(self):
        client = admin_client()
        response = client.delete('/api/dashboard/')
        self.assertIn(response.status_code, [405, 403])
