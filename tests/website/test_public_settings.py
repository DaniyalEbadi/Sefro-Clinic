from django.test import TestCase
from rest_framework.test import APIClient

from tests.helpers import admin_client, website_manager_client
from website.models import SiteSettings


class PublicSiteSettingsTests(TestCase):
    URL = '/api/v2/site/settings/'

    def test_anonymous_read_returns_singleton_and_dashboard_edits(self):
        public = APIClient()
        initial = public.get(self.URL)
        self.assertEqual(initial.status_code, 200)
        self.assertEqual(initial.data['clinic_name'], '')
        self.assertEqual(initial.data['social_links'], {})
        self.assertEqual(SiteSettings.objects.count(), 1)

        manager = website_manager_client()
        edited = manager.patch('/api/v2/site-dashboard/settings/', {
            'clinic_name': 'کلینیک باران',
            'logo_url': 'https://cdn.example.com/logo.png',
            'address': 'تهران',
            'phone_numbers': ['02112345678'],
            'contact_email': 'hello@example.com',
            'social_links': {'instagram': 'https://instagram.com/baran'},
            'working_hours': 'شنبه تا پنجشنبه',
        }, format='json')
        self.assertEqual(edited.status_code, 200, edited.data)
        published = public.get(self.URL)
        self.assertEqual(published.status_code, 200, published.data)
        for field in ('clinic_name', 'logo_url', 'address', 'phone_numbers',
                      'contact_email', 'social_links', 'working_hours'):
            self.assertEqual(published.data[field], edited.data[field])
        self.assertEqual(SiteSettings.objects.count(), 1)

    def test_public_cannot_modify_settings_and_dashboard_validates_links(self):
        public = APIClient()
        self.assertEqual(public.patch(self.URL, {'clinic_name': 'bad'}, format='json').status_code, 405)
        manager = website_manager_client()
        invalid = manager.patch('/api/v2/site-dashboard/settings/', {
            'social_links': {'instagram': 'javascript:alert(1)'},
        }, format='json')
        self.assertEqual(invalid.status_code, 400)

    def test_settings_route_and_schema_stay_out_of_financial_api(self):
        client = admin_client()
        self.assertIn(self.URL, client.get('/api/v2/schema/').content.decode())
        self.assertNotIn(self.URL, client.get('/api/schema/').content.decode())
        self.assertEqual(client.get('/api/site/settings/').status_code, 404)
