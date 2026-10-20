from django.test import TestCase, override_settings
from rest_framework import status
from rest_framework.test import APIClient

from tests.helpers import ADMIN_PASSWORD, ADMIN_USERNAME, admin_client, make_admin


class WebsiteDashboardLoginTests(TestCase):
    def setUp(self):
        make_admin()

    @override_settings(RETURN_TOKENS_IN_BODY=True)
    def test_website_login_sets_httponly_cookies_without_returning_tokens(self):
        response = APIClient().post('/api/v2/site-dashboard/login/', {
            'username': ADMIN_USERNAME,
            'password': ADMIN_PASSWORD,
        }, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertNotIn('access', response.data)
        self.assertNotIn('refresh', response.data)
        for name in ('access_token', 'refresh_token'):
            self.assertIn(name, response.cookies)
            self.assertTrue(response.cookies[name]['httponly'])

    def test_website_dashboard_tags_are_split_in_schema(self):
        body = admin_client().get('/api/v2/schema/').content.decode()

        for tag in (
            'Website Dashboard - Login',
            'Website Dashboard - Services',
            'Website Dashboard - Packages',
            'Website Dashboard - Products',
            'Website Dashboard - Sync',
        ):
            self.assertIn(tag, body)
