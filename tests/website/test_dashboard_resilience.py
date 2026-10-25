from decimal import Decimal
from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase
from rest_framework.test import APIClient

from finance.models import ExchangeRate
from tests.helpers import WEBSITE_PASSWORD, make_admin, make_website_manager
from tests.website.test_models import make_package, make_product, make_service
from website.models import ContactMessage, SitePackagePriceOption, TeamMember, Testimonial, WebsitePriceSyncRun


def website_client(username, password):
    client = APIClient()
    response = client.post('/api/v2/site-dashboard/login/', {
        'username': username, 'password': password,
    }, format='json')
    assert response.status_code == 200, response.data
    return client


class WebsiteDashboardResilienceTests(TestCase):
    def setUp(self):
        cache.clear()
        user = make_admin()
        self.first = make_website_manager(user=user, website_username='first_manager')
        self.second = make_website_manager(user=user, website_username='second_manager')

    def test_logged_in_dashboard_and_public_reads_ignore_financial_global_buckets(self):
        client = website_client(self.first.username, WEBSITE_PASSWORD)
        service = make_service()
        package = make_package()
        option = SitePackagePriceOption.objects.create(
            package=package, label='تک جلسه', session_count=1,
            price=Decimal('100000'), price_usd=Decimal('1'),
        )
        product = make_product()
        team = TeamMember.objects.create(name='پزشک')
        testimonial = Testimonial.objects.create(customer_name='مراجع', text='عالی')
        contact = ContactMessage.objects.create(full_name='مراجع', phone='09121234567', message='سلام')
        dashboard_urls = (
            '/api/v2/site-dashboard/me/',
            '/api/v2/site-dashboard/services/',
            f'/api/v2/site-dashboard/services/{service.slug}/',
            '/api/v2/site-dashboard/packages/',
            f'/api/v2/site-dashboard/packages/{package.slug}/',
            '/api/v2/site-dashboard/package-price-options/',
            f'/api/v2/site-dashboard/package-price-options/{option.pk}/',
            '/api/v2/site-dashboard/products/',
            f'/api/v2/site-dashboard/products/{product.slug}/',
            '/api/v2/site-dashboard/settings/',
            '/api/v2/site-dashboard/team/',
            f'/api/v2/site-dashboard/team/{team.pk}/',
            '/api/v2/site-dashboard/testimonials/',
            f'/api/v2/site-dashboard/testimonials/{testimonial.pk}/',
            '/api/v2/site-dashboard/contact-messages/',
            f'/api/v2/site-dashboard/contact-messages/{contact.pk}/',
            '/api/v2/site-dashboard/price-sync/status/',
        )
        public_urls = (
            '/api/v2/services/', '/api/v2/packages/', '/api/v2/products/',
            '/api/v2/team/', '/api/v2/testimonials/',
        )
        with patch('rest_framework.throttling.UserRateThrottle.get_rate', return_value='1/min'), patch(
            'rest_framework.throttling.AnonRateThrottle.get_rate', return_value='1/min',
        ):
            for url in dashboard_urls:
                with self.subTest(url=url):
                    response = client.get(url)
                    self.assertEqual(response.status_code, 200, response.data)
            for url in public_urls:
                with self.subTest(url=url):
                    response = APIClient().get(url)
                    self.assertEqual(response.status_code, 200, response.data)

    def test_website_credential_buckets_are_independent(self):
        first = website_client(self.first.username, WEBSITE_PASSWORD)
        second = website_client(self.second.username, WEBSITE_PASSWORD)
        url = '/api/v2/site-dashboard/me/'
        with patch('website.throttling.WebsiteDashboardThrottle.get_rate', return_value='2/min'):
            self.assertEqual(first.get(url).status_code, 200)
            self.assertEqual(first.get(url).status_code, 200)
            self.assertEqual(first.get(url).status_code, 429)
            self.assertEqual(second.get(url).status_code, 200)

    def test_failed_auto_sync_is_cached_and_manual_rate_recovers_price_edits(self):
        client = website_client(self.first.username, WEBSITE_PASSWORD)
        service = make_service(price_usd=Decimal('2'))
        finance_rates_before = ExchangeRate.objects.count()
        url = '/api/v2/site-dashboard/price-sync/run/'
        with patch('website.services.sync.fetch_website_rate', return_value=(None, '')) as provider:
            failed = client.post(url, {}, format='json')
            repeated = client.post(url, {}, format='json')
        self.assertEqual(failed.status_code, 503, failed.data)
        self.assertEqual(repeated.status_code, 503, repeated.data)
        self.assertFalse(failed.data['cached'])
        self.assertTrue(repeated.data['cached'])
        self.assertEqual(provider.call_count, 1)
        self.assertEqual(WebsitePriceSyncRun.objects.count(), 1)
        status = client.get('/api/v2/site-dashboard/price-sync/status/')
        self.assertEqual(status.status_code, 200)
        self.assertEqual(status.data['status'], 'failed')
        self.assertIsNone(status.data['effective_rate'])

        self.assertEqual(client.post(url, {'rate': '0'}, format='json').status_code, 400)
        manual = client.post(url, {'rate': '100000'}, format='json')
        self.assertEqual(manual.status_code, 200, manual.data)
        self.assertEqual(manual.data['provider'], 'manual')
        service.refresh_from_db()
        self.assertEqual(service.price, Decimal('200000'))
        updated = client.patch(
            f'/api/v2/site-dashboard/services/{service.slug}/',
            {'price_usd': '3'}, format='json',
        )
        self.assertEqual(updated.status_code, 200, updated.data)
        service.refresh_from_db()
        self.assertEqual(service.price, Decimal('300000'))
        status = client.get('/api/v2/site-dashboard/price-sync/status/')
        self.assertEqual(status.data['effective_rate'], '100000.000000')
        self.assertEqual(ExchangeRate.objects.count(), finance_rates_before)

    def test_sync_status_schema_documents_empty_and_effective_rate(self):
        client = website_client(self.first.username, WEBSITE_PASSWORD)
        schema = client.get('/api/v2/schema/')
        self.assertEqual(schema.status_code, 200)
        properties = schema.data['components']['schemas']['WebsitePriceSyncStatus']['properties']
        self.assertIn('effective_rate', properties)
        self.assertIn('status', properties)
        self.assertIn('started_at', properties)
