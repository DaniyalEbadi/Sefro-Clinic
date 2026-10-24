from django.test import TestCase, override_settings
from rest_framework import status
from rest_framework.test import APIClient

from tests.helpers import WEBSITE_PASSWORD, admin_client, make_admin, make_website_manager


class WebsiteDashboardLoginTests(TestCase):
    def setUp(self):
        self.credential = make_website_manager(user=make_admin())

    @override_settings(RETURN_TOKENS_IN_BODY=True)
    def test_website_login_sets_httponly_cookies_without_returning_tokens(self):
        response = APIClient().post('/api/v2/site-dashboard/login/', {
            'username': self.credential.username,
            'password': WEBSITE_PASSWORD,
        }, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertNotIn('access', response.data)
        self.assertNotIn('refresh', response.data)
        self.assertIn('website_dashboard_session', response.cookies)
        self.assertTrue(response.cookies['website_dashboard_session']['httponly'])
        self.assertNotIn('access_token', response.cookies)
        self.assertNotIn('refresh_token', response.cookies)

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
