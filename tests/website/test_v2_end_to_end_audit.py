"""Cross-endpoint Site API v2 journeys using the isolated Django test database."""

from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from rest_framework.test import APIClient

from tests.helpers import WEBSITE_PASSWORD, make_admin, make_website_manager
from tests.website.test_models import make_package, make_product, make_service
from website.models import ContactMessage, SitePackagePriceOption, SiteSettings, TeamMember, Testimonial
from website.services.sync import sync_website_prices


class SiteV2EndToEndAuditTests(TestCase):
    def test_public_content_and_intake_journey(self):
        client = APIClient()
        service = make_service(source_url='https://barancliniccenter.com/services/botox')
        package = make_package()
        package.services.add(service)
        option = SitePackagePriceOption.objects.create(
            package=package, label='سه جلسه', session_count=3,
            price=Decimal('5000000'), price_usd=Decimal('50'),
        )
        product = make_product()
        TeamMember.objects.create(name='پزشک سایت', role='پزشک')
        Testimonial.objects.create(customer_name='مراجع', text='تجربه خوب بود')

        for url in (
            '/api/v2/services/', '/api/v2/services/botox/',
            '/api/v2/packages/', '/api/v2/packages/rejuvenation/',
            '/api/v2/products/', '/api/v2/products/vitamin-c-serum/',
            '/api/v2/team/', '/api/v2/testimonials/',
        ):
            with self.subTest(url=url):
                self.assertEqual(client.get(url).status_code, 200)

        detail = client.get(f'/api/v2/services/{service.slug}/').data
        self.assertEqual(detail['source_url'], service.source_url)
        self.assertEqual(detail['price'], '2500000.00')
        package_detail = client.get(f'/api/v2/packages/{package.slug}/').data
        self.assertEqual(package_detail['price_options'][0]['id'], option.pk)
        self.assertEqual(package_detail['services'][0]['slug'], service.slug)
        self.assertEqual(client.get(f'/api/v2/products/{product.slug}/').data['slug'], product.slug)
        self.assertEqual(client.get('/api/v2/team/').data[0]['name'], 'پزشک سایت')
        self.assertEqual(client.get('/api/v2/testimonials/').data[0]['customer_name'], 'مراجع')
        self.assertEqual(client.get('/api/v2/site/info/').status_code, 401)

        response = client.post('/api/v2/contact/', {
            'full_name': 'مراجع جدید', 'phone': '09121234567', 'message': 'مشاوره می‌خواهم',
        }, format='json')
        self.assertEqual(response.status_code, 201)
        self.assertEqual(ContactMessage.objects.get(phone='09121234567').full_name, 'مراجع جدید')

    @patch('website.views.get_current_usd_to_toman_rate', return_value=Decimal('100000'))
    def test_cookie_dashboard_edits_flow_to_public_and_sync_status(self, _rate):
        credential = make_website_manager(user=make_admin())
        client = APIClient(enforce_csrf_checks=True)
        login = client.post('/api/v2/site-dashboard/login/', {
            'username': credential.username, 'password': WEBSITE_PASSWORD,
        }, format='json')
        self.assertEqual(login.status_code, 200, login.data)
        self.assertTrue(login.cookies['website_dashboard_session']['httponly'])
        self.assertNotIn('access', login.data)
        self.assertEqual(client.get('/api/v2/site-dashboard/me/').status_code, 200)
        self.assertEqual(client.get('/api/auth/me/').status_code, 401)
        empty_sync = client.get('/api/v2/site-dashboard/price-sync/status/')
        self.assertEqual(empty_sync.status_code, 200)
        self.assertEqual(empty_sync.data['status'], 'never_run')

        service_url = '/api/v2/site-dashboard/services/'
        payload = {'name': 'بوتاکس صورت', 'slug': 'botox-face', 'category': 'face',
                   'description': 'توضیح کامل خدمت', 'price': '799.001'}
        self.assertEqual(client.post(service_url, payload, format='json').status_code, 403)
        csrf = {'HTTP_X_CSRFTOKEN': client.cookies['csrftoken'].value}
        created = client.post(service_url, payload, format='json', **csrf)
        self.assertEqual(created.status_code, 201, created.data)
        self.assertEqual(created.data['price'], '800.00')
        detail_url = f'{service_url}botox-face/'
        edited = client.patch(detail_url, {'description': 'توضیح ویرایش شده'}, format='json', **csrf)
        self.assertEqual(edited.status_code, 200, edited.data)
        self.assertEqual(client.get(detail_url).data['description'], 'توضیح ویرایش شده')

        package = make_package()
        product = make_product()
        package_url = f'/api/v2/site-dashboard/packages/{package.slug}/'
        product_url = f'/api/v2/site-dashboard/products/{product.slug}/'
        self.assertEqual(client.get('/api/v2/site-dashboard/packages/').status_code, 200)
        self.assertEqual(client.get(package_url).status_code, 200)
        self.assertEqual(client.get('/api/v2/site-dashboard/products/').status_code, 200)
        self.assertEqual(client.get(product_url).status_code, 200)
        self.assertEqual(client.patch(package_url, {'price_usd': '10'}, format='json', **csrf).status_code, 200)
        self.assertEqual(client.patch(product_url, {'price': '900.1'}, format='json', **csrf).status_code, 200)

        options_url = '/api/v2/site-dashboard/package-price-options/'
        option = client.post(options_url, {
            'package': package.pk, 'label': 'دو جلسه', 'session_count': 2, 'price': '2000000',
        }, format='json', **csrf)
        self.assertEqual(option.status_code, 201, option.data)
        option_url = f"{options_url}{option.data['id']}/"
        self.assertEqual(client.get(options_url).status_code, 200)
        self.assertEqual(client.get(option_url).status_code, 200)
        self.assertEqual(client.patch(option_url, {'gift_session_count': 1}, format='json', **csrf).status_code, 200)

        settings_url = '/api/v2/site-dashboard/settings/'
        self.assertEqual(client.get(settings_url).status_code, 200)
        self.assertEqual(client.patch(settings_url, {'about_title': 'کلینیک باران'}, format='json', **csrf).status_code, 200)
        self.assertEqual(SiteSettings.objects.get(singleton_key='default').about_title, 'کلینیک باران')

        public = APIClient()
        self.assertEqual(public.get('/api/v2/services/botox-face/').data['description'], 'توضیح ویرایش شده')
        self.assertEqual(public.get(f'/api/v2/products/{product.slug}/').data['price'], '901.00')
        self.assertEqual(public.get(f'/api/v2/packages/{package.slug}/').data['price'], '1000000.00')

        with patch('website.services.sync.fetch_website_rate', return_value=(Decimal('200000'), 'test')):
            sync_website_prices()
        self.assertEqual(public.get('/api/v2/services/botox-face/').data['price'], '1600.00')
        sync_status = client.get('/api/v2/site-dashboard/price-sync/status/')
        self.assertEqual(sync_status.status_code, 200)
        self.assertEqual(sync_status.data['status'], 'succeeded')
        self.assertEqual(sync_status.data['rate'], '200000.000000')
        self.assertEqual(client.get('/api/v2/schema/').status_code, 200)
        self.assertEqual(client.get('/api/v2/docs/').status_code, 200)
