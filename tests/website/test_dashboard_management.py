import os
from datetime import timedelta
from decimal import Decimal
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import ClinicUser
from finance.models import ExchangeRate
from tests.helpers import (
    ADMIN_PASSWORD,
    ADMIN_USERNAME,
    WEBSITE_PASSWORD,
    admin_client,
    make_admin,
    make_employee,
    make_website_manager,
    website_manager_client,
)
from tests.website.test_models import make_package, make_product, make_service
from tests.website.test_website_importer import ABOUT_HTML, HOME_HTML, PACKAGES_HTML, PRODUCTS_HTML, SERVICES_HTML
from website.models import (
    ContactMessage,
    SitePackage,
    SitePackagePriceOption,
    SiteProduct,
    SiteSettings,
    TeamMember,
    Testimonial,
    WebsiteDashboardSession,
    WebsiteManagerCredential,
)
from website.services.importer import import_website_catalog


class WebsiteSessionIsolationTests(TestCase):
    def setUp(self):
        self.user = make_admin()
        self.credential = make_website_manager(user=self.user)

    def test_website_credentials_and_cookie_do_not_authenticate_financial_api(self):
        client = APIClient(enforce_csrf_checks=True)
        self.assertEqual(client.post('/api/v2/site-dashboard/login/', {
            'username': ADMIN_USERNAME, 'password': ADMIN_PASSWORD,
        }, format='json').status_code, 401)
        login = client.post('/api/v2/site-dashboard/login/', {
            'username': self.credential.username, 'password': WEBSITE_PASSWORD,
        }, format='json')
        self.assertEqual(login.status_code, 200)
        cookie = login.cookies['website_dashboard_session']
        self.assertTrue(cookie['httponly'])
        self.assertEqual(cookie['path'], '/api/v2/site-dashboard/')
        self.assertNotIn('access_token', login.cookies)
        self.assertEqual(client.get('/api/v2/site-dashboard/me/').status_code, 200)
        self.assertEqual(client.get('/api/auth/me/').status_code, 401)
        self.assertEqual(admin_client().get('/api/v2/site-dashboard/me/').status_code, 401)

        settings_url = '/api/v2/site-dashboard/settings/'
        self.assertEqual(client.patch(settings_url, {'about_title': 'جدید'}, format='json').status_code, 403)
        csrf = {'HTTP_X_CSRFTOKEN': client.cookies['csrftoken'].value}
        self.assertEqual(client.patch(settings_url, {'about_title': 'جدید'}, format='json', **csrf).status_code, 200)
        self.assertEqual(client.post('/api/v2/site-dashboard/logout/', {}, format='json', **csrf).status_code, 200)
        self.assertEqual(client.get('/api/v2/site-dashboard/me/').status_code, 401)

    def test_expired_revoked_and_inactive_sessions_are_rejected(self):
        client = website_manager_client(user=self.user)
        session = WebsiteDashboardSession.objects.get(credential=self.credential)
        session.expires_at = timezone.now() - timedelta(seconds=1)
        session.save(update_fields=['expires_at'])
        self.assertEqual(client.get('/api/v2/site-dashboard/me/').status_code, 401)
        session.expires_at = timezone.now() + timedelta(hours=1)
        session.revoked_at = timezone.now()
        session.save(update_fields=['expires_at', 'revoked_at'])
        self.assertEqual(client.get('/api/v2/site-dashboard/me/').status_code, 401)
        session.revoked_at = None
        session.save(update_fields=['revoked_at'])
        self.credential.is_active = False
        self.credential.save(update_fields=['is_active'])
        self.assertEqual(client.get('/api/v2/site-dashboard/me/').status_code, 401)

    def test_provisioning_command_hashes_password_and_revokes_old_sessions(self):
        employee = make_employee(username='site_staff')
        with patch.dict(os.environ, {'WEBSITE_TEST_PASSWORD': WEBSITE_PASSWORD}):
            call_command(
                'set_website_manager', '--clinic-username', employee.username,
                '--website-username', 'site_staff_web', '--password-env', 'WEBSITE_TEST_PASSWORD',
                stdout=StringIO(),
            )
        credential = WebsiteManagerCredential.objects.get(user=employee)
        self.assertTrue(credential.check_password(WEBSITE_PASSWORD))
        self.assertNotEqual(credential.password_hash, WEBSITE_PASSWORD)
        client = APIClient()
        self.assertEqual(client.post('/api/v2/site-dashboard/login/', {
            'username': credential.username, 'password': WEBSITE_PASSWORD,
        }, format='json').status_code, 200)
        self.assertEqual(credential.sessions.count(), 1)
        with patch.dict(os.environ, {'WEBSITE_TEST_PASSWORD': 'Another-Website-Password-2026!'}):
            call_command(
                'set_website_manager', '--clinic-username', employee.username,
                '--website-username', 'site_staff_web', '--password-env', 'WEBSITE_TEST_PASSWORD',
                stdout=StringIO(),
            )
        self.assertEqual(credential.sessions.count(), 0)
        self.assertEqual(client.get('/api/v2/site-dashboard/me/').status_code, 401)

    def test_second_website_login_keeps_first_and_cannot_login_to_financial_dashboard(self):
        financial_users_before = ClinicUser.objects.count()
        with patch.dict(os.environ, {'WEBSITE_TEST_PASSWORD': 'BaranAdmin1234'}):
            call_command(
                'set_website_manager', '--clinic-username', self.user.username,
                '--website-username', 'admin', '--password-env', 'WEBSITE_TEST_PASSWORD',
                stdout=StringIO(),
            )
        self.assertEqual(ClinicUser.objects.count(), financial_users_before)
        self.assertEqual(WebsiteManagerCredential.objects.filter(user=self.user).count(), 2)
        for username, password in [('web_manager', WEBSITE_PASSWORD), ('admin', 'BaranAdmin1234')]:
            with self.subTest(username=username):
                client = APIClient()
                login = client.post('/api/v2/site-dashboard/login/', {
                    'username': username, 'password': password,
                }, format='json')
                self.assertEqual(login.status_code, 200, login.data)
                self.assertEqual(client.get('/api/v2/site-dashboard/me/').status_code, 200)
        self.assertEqual(APIClient().post('/api/auth/token/', {
            'username': 'admin', 'password': 'BaranAdmin1234',
        }, format='json').status_code, 401)


class WebsiteDashboardContentTests(TestCase):
    def setUp(self):
        self.client = website_manager_client()

    def test_team_testimonials_and_contact_management(self):
        team = self.client.post('/api/v2/site-dashboard/team/', {
            'name': 'دکتر تست', 'role': 'پزشک', 'sort_order': 2,
        }, format='json')
        self.assertEqual(team.status_code, 201, team.data)
        self.assertTrue(TeamMember.objects.get(pk=team.data['id']).is_manually_managed)
        testimonial = self.client.post('/api/v2/site-dashboard/testimonials/', {
            'customer_name': 'مراجع', 'text': 'تجربه خوب',
        }, format='json')
        self.assertEqual(testimonial.status_code, 201, testimonial.data)
        self.assertTrue(Testimonial.objects.get(pk=testimonial.data['id']).is_manually_managed)
        self.assertEqual(self.client.patch(
            f"/api/v2/site-dashboard/testimonials/{testimonial.data['id']}/",
            {'is_active': False}, format='json',
        ).status_code, 200)
        self.assertEqual(len(APIClient().get('/api/v2/testimonials/').data), 0)
        self.assertEqual(self.client.delete(f"/api/v2/site-dashboard/team/{team.data['id']}/").status_code, 405)

        message = ContactMessage.objects.create(full_name='Visitor', phone='09121234567', message='Private note')
        detail = f'/api/v2/site-dashboard/contact-messages/{message.pk}/'
        self.assertEqual(self.client.get(detail).data['message'], 'Private note')
        self.assertEqual(self.client.patch(detail, {'message': 'Altered'}, format='json').status_code, 400)
        self.assertEqual(self.client.patch(detail, {'is_handled': True}, format='json').status_code, 200)
        message.refresh_from_db()
        self.assertEqual(message.message, 'Private note')
        self.assertTrue(message.is_handled)
        self.assertEqual(APIClient().get(detail).status_code, 401)

    @patch('website.views.get_current_usd_to_toman_rate', return_value=None)
    def test_catalog_content_edits_work_without_rate_and_keep_slugs_stable(self, _rate):
        product = make_product()
        service = make_service()
        package = make_package()
        package_url = f'/api/v2/site-dashboard/packages/{package.slug}/'
        product_url = f'/api/v2/site-dashboard/products/{product.slug}/'
        self.assertEqual(self.client.patch(product_url, {
            'name': 'سروم جدید', 'image_url': 'https://example.com/a.jpg',
            'short_description': 'توضیح', 'sort_order': 3,
        }, format='json').status_code, 200)
        self.assertEqual(self.client.patch(package_url, {
            'tagline': 'پکیج ویژه', 'service_ids': [service.pk], 'is_active': False,
        }, format='json').status_code, 200)
        product.refresh_from_db()
        package.refresh_from_db()
        self.assertTrue(product.is_manually_managed)
        self.assertTrue(package.is_manually_managed)
        self.assertEqual(package.services.get().pk, service.pk)
        self.assertEqual(self.client.patch(product_url, {'slug': 'new-slug'}, format='json').status_code, 400)
        self.assertEqual(self.client.patch(package_url, {'price': '1000'}, format='json').status_code, 503)

    @patch('website.views.get_current_usd_to_toman_rate', return_value=Decimal('100000'))
    def test_creating_product_and_package_accepts_toman_and_relationships(self, _rate):
        service = make_service()
        product = self.client.post('/api/v2/site-dashboard/products/', {
            'name': 'محصول جدید', 'slug': 'new-product', 'price': '799.001',
        }, format='json')
        self.assertEqual(product.status_code, 201, product.data)
        self.assertEqual(SiteProduct.objects.get(slug='new-product').price, Decimal('800'))
        package = self.client.post('/api/v2/site-dashboard/packages/', {
            'name': 'پکیج جدید', 'slug': 'new-package', 'price_usd': '10',
            'service_ids': [service.pk],
        }, format='json')
        self.assertEqual(package.status_code, 201, package.data)
        self.assertEqual(SitePackage.objects.get(slug='new-package').services.get().pk, service.pk)

    @patch('website.views.get_current_usd_to_toman_rate', return_value=None)
    def test_price_option_visibility_edit_does_not_require_rate(self, _rate):
        package = make_package()
        option = SitePackagePriceOption.objects.create(
            package=package, label='تک جلسه', session_count=1,
            price=Decimal('100000'), price_usd=Decimal('1'),
        )
        response = self.client.patch(
            f'/api/v2/site-dashboard/package-price-options/{option.pk}/',
            {'is_active': False}, format='json',
        )
        self.assertEqual(response.status_code, 200, response.data)
        option.refresh_from_db()
        package.refresh_from_db()
        self.assertFalse(option.is_active)
        self.assertTrue(package.is_manually_managed)

    @patch('website.services.sync.BrsApiExchangeRateProvider.get_usd_to_toman_rate', return_value=None)
    @patch('website.services.sync.ExternalExchangeRateProvider.get_usd_to_toman_rate', return_value=Decimal('100000'))
    def test_manual_price_sync_updates_website_only(self, primary, backup):
        service = make_service(price_usd=Decimal('2'))
        finance_before = ExchangeRate.objects.count()
        response = self.client.post('/api/v2/site-dashboard/price-sync/run/', {}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['provider'], 'tindex')
        service.refresh_from_db()
        self.assertEqual(service.price, Decimal('200000'))
        self.assertEqual(ExchangeRate.objects.count(), finance_before)
        self.assertEqual(self.client.get('/api/v2/site-dashboard/price-sync/status/').data['rate'], '100000.000000')
        self.assertEqual(backup.call_count, 0)

    @patch('website.services.importer.fetch_website_rate', return_value=(Decimal('100000'), 'test'))
    @patch('website.services.importer._fetch')
    def test_import_keeps_dashboard_edits(self, fetch, _rate):
        pages = {
            '/services': SERVICES_HTML, '/packages': PACKAGES_HTML,
            '/products': PRODUCTS_HTML, '/about': ABOUT_HTML, '/': HOME_HTML,
        }
        fetch.side_effect = lambda path: pages[path]
        import_website_catalog()
        package = SitePackage.objects.get()
        product = SiteProduct.objects.get()
        team = TeamMember.objects.get()
        testimonial = Testimonial.objects.first()
        self.assertEqual(self.client.patch(f'/api/v2/site-dashboard/packages/{package.slug}/', {
            'name': 'پکیج ویرایش شده',
        }, format='json').status_code, 200)
        self.assertEqual(self.client.patch(f'/api/v2/site-dashboard/products/{product.slug}/', {
            'name': 'محصول ویرایش شده',
        }, format='json').status_code, 200)
        self.assertEqual(self.client.patch(f'/api/v2/site-dashboard/team/{team.pk}/', {
            'name': 'پزشک ویرایش شده',
        }, format='json').status_code, 200)
        self.assertEqual(self.client.patch(f'/api/v2/site-dashboard/testimonials/{testimonial.pk}/', {
            'text': 'نظر ویرایش شده',
        }, format='json').status_code, 200)
        self.assertEqual(self.client.patch('/api/v2/site-dashboard/settings/', {
            'about_title': 'درباره جدید',
        }, format='json').status_code, 200)
        import_website_catalog()
        package.refresh_from_db()
        product.refresh_from_db()
        team.refresh_from_db()
        testimonial.refresh_from_db()
        self.assertEqual(package.name, 'پکیج ویرایش شده')
        self.assertEqual(product.name, 'محصول ویرایش شده')
        self.assertEqual(team.name, 'پزشک ویرایش شده')
        self.assertEqual(testimonial.text, 'نظر ویرایش شده')
        self.assertEqual(SiteSettings.objects.get().about_title, 'درباره جدید')
        self.assertEqual(TeamMember.objects.count(), 1)
        self.assertEqual(Testimonial.objects.count(), 3)

    def test_schema_contains_dashboard_management_only_in_v2(self):
        v2 = admin_client().get('/api/v2/schema/').content.decode()
        v1 = admin_client().get('/api/schema/').content.decode()
        for path in ('/api/v2/site-dashboard/team/', '/api/v2/site-dashboard/testimonials/',
                     '/api/v2/site-dashboard/contact-messages/', '/api/v2/site-dashboard/price-sync/run/'):
            self.assertIn(path, v2)
            self.assertNotIn(path, v1)
