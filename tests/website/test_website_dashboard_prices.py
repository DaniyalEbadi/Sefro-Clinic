from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase, override_settings
from rest_framework import status
from rest_framework.test import APIClient

from finance.models import ExchangeRate
from tests.helpers import website_manager_client
from tests.website.test_models import make_package, make_product, make_service
from website.models import SitePackagePriceOption, WebsitePriceSyncRun
from website.services.pricing import toman_price_from_usd
from website.services.sync import sync_website_prices


class WebsiteDashboardPriceTests(TestCase):
    @override_settings(FINANCE_DEFAULT_USD_TO_TOMAN_RATE=Decimal('79999.9'))
    @patch('website.views.get_current_usd_to_toman_rate', return_value=Decimal('79999.9'))
    def test_employee_can_update_service_price_with_whole_toman_ceiling(self, rate):
        service = make_service(price_usd='0.00')

        response = website_manager_client().patch(
            f'/api/v2/site-dashboard/services/{service.slug}/',
            {'price_usd': '0.01'}, format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        service.refresh_from_db()
        self.assertEqual(service.price_usd, Decimal('0.01'))
        self.assertEqual(service.price, Decimal('800.00'))

    @override_settings(FINANCE_DEFAULT_USD_TO_TOMAN_RATE=Decimal('100000'))
    @patch('website.views.get_current_usd_to_toman_rate', return_value=Decimal('100000'))
    def test_package_updates_current_and_original_prices(self, rate):
        package = make_package(price_usd='10.00', original_price_usd='12.00')

        response = website_manager_client().patch(
            f'/api/v2/site-dashboard/packages/{package.slug}/',
            {'price_usd': '10.01', 'original_price_usd': '12.01'}, format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        package.refresh_from_db()
        self.assertEqual(package.price, Decimal('1001000.00'))
        self.assertEqual(package.original_price, Decimal('1201000.00'))

    def test_website_catalog_public_mutation_remains_blocked(self):
        service = make_service()
        response = self.client.patch(
            f'/api/v2/site-dashboard/services/{service.slug}/',
            {'price_usd': '1.00'}, format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_dashboard_accepts_content_only_edits(self):
        service = make_service()
        response = website_manager_client().patch(
            f'/api/v2/site-dashboard/services/{service.slug}/',
            {'name': 'تغییر نام'}, format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        service.refresh_from_db()
        self.assertEqual(service.name, 'تغییر نام')


class WebsitePriceSyncTests(TestCase):
    @patch('website.services.sync.BrsApiExchangeRateProvider.get_usd_to_toman_rate', return_value=None)
    @patch('website.services.sync.ExternalExchangeRateProvider.get_usd_to_toman_rate', return_value=None)
    def test_failed_provider_refresh_keeps_existing_prices(self, primary, backup):
        service = make_service(price='799.99', price_usd='0.01')

        run = sync_website_prices()

        self.assertEqual(run.status, WebsitePriceSyncRun.Status.FAILED)
        service.refresh_from_db()
        self.assertEqual(service.price, Decimal('799.99'))
        self.assertEqual(primary.call_count, 1)
        self.assertEqual(backup.call_count, 1)

    @patch('website.services.sync.BrsApiExchangeRateProvider.get_usd_to_toman_rate', return_value=None)
    @patch('website.services.sync.ExternalExchangeRateProvider.get_usd_to_toman_rate', return_value=Decimal('79999.9'))
    def test_successful_refresh_rounds_prices_up_to_whole_toman(self, primary, backup):
        service = make_service(price_usd='0.01')
        package = make_package(price_usd='1.23', original_price_usd='2.35')
        product = make_product(price_usd='0.01')

        run = sync_website_prices()

        self.assertEqual(run.status, WebsitePriceSyncRun.Status.SUCCEEDED)
        self.assertEqual(run.provider, 'tindex')
        service.refresh_from_db()
        package.refresh_from_db()
        product.refresh_from_db()
        self.assertEqual(service.price, Decimal('800.00'))
        self.assertEqual(package.price, Decimal('98400.00'))
        self.assertEqual(package.original_price, Decimal('188000.00'))
        self.assertEqual(product.price, Decimal('800.00'))
        self.assertEqual(backup.call_count, 0)


@patch('website.views.get_current_usd_to_toman_rate', return_value=Decimal('264280'))
class WebsiteTomanPriceTests(TestCase):
    def setUp(self):
        self.client = website_manager_client()
        self.service = make_service()
        self.product = make_product()
        self.package = make_package()
        self.option = SitePackagePriceOption.objects.create(
            package=self.package, label='تک جلسه', session_count=1,
            price=Decimal('1500000'), price_usd=Decimal('5'),
        )
        self.targets = [
            (self.service, f'/api/v2/site-dashboard/services/{self.service.slug}/'),
            (self.product, f'/api/v2/site-dashboard/products/{self.product.slug}/'),
            (self.package, f'/api/v2/site-dashboard/packages/{self.package.slug}/'),
            (self.option, f'/api/v2/site-dashboard/package-price-options/{self.option.pk}/'),
        ]

    def test_toman_edits_store_exact_price_and_precise_usd_base_for_every_catalog_type(self, rate):
        finance_rates_before = ExchangeRate.objects.count()
        for obj, url in self.targets:
            with self.subTest(url=url):
                response = self.client.patch(url, {'price': '1800001'}, format='json')
                self.assertEqual(response.status_code, 200, response.data)
                self.assertEqual(response.data['price'], '1800001.00')
                obj.refresh_from_db()
                self.assertEqual(obj.price, Decimal('1800001'))
                self.assertEqual(toman_price_from_usd(obj.price_usd, rate.return_value), obj.price)
        self.assertEqual(ExchangeRate.objects.count(), finance_rates_before)

    def test_toman_edit_survives_same_rate_sync_and_follows_new_rate(self, rate):
        self.client.patch(self.targets[0][1], {'price': '1800001'}, format='json')
        self.service.refresh_from_db()
        usd_base = self.service.price_usd
        with patch('website.services.sync.fetch_website_rate', return_value=(rate.return_value, 'test')):
            sync_website_prices()
        self.service.refresh_from_db()
        self.assertEqual(self.service.price, Decimal('1800001'))
        with patch('website.services.sync.fetch_website_rate', return_value=(Decimal('300000'), 'test')):
            sync_website_prices()
        self.service.refresh_from_db()
        self.assertEqual(self.service.price, toman_price_from_usd(usd_base, Decimal('300000')))

    def test_fractional_toman_rounds_up_and_zero_is_allowed(self, rate):
        for value, expected in [('799.999', '800.00'), ('0', '0.00')]:
            response = self.client.patch(self.targets[0][1], {'price': value}, format='json')
            self.assertEqual(response.status_code, 200, response.data)
            self.assertEqual(response.data['price'], expected)

    def test_rejects_both_currencies_for_same_price_without_saving(self, rate):
        for obj, url in self.targets:
            original = Decimal(str(obj.price))
            response = self.client.patch(url, {'price': '100', 'price_usd': '1'}, format='json')
            self.assertEqual(response.status_code, 400, response.data)
            obj.refresh_from_db()
            self.assertEqual(obj.price, original)

    def test_invalid_negative_null_and_overflow_prices_are_rejected(self, rate):
        for value in ['-1', None, 'NaN', 'Infinity', 'text', '10000000000', '9999999999.1', '1e999']:
            with self.subTest(value=value):
                response = self.client.patch(self.targets[0][1], {'price': value}, format='json')
                self.assertEqual(response.status_code, 400, response.data)

    def test_usd_conversion_cannot_overflow_the_toman_column(self, rate):
        response = self.client.patch(self.targets[0][1], {'price_usd': '999999999999'}, format='json')
        self.assertEqual(response.status_code, 400, response.data)

    def test_toman_conversion_cannot_overflow_the_usd_column(self, rate):
        rate.return_value = Decimal('0.000001')
        response = self.client.patch(self.targets[2][1], {'price': '999999999999'}, format='json')
        self.assertEqual(response.status_code, 400, response.data)

    def test_package_supports_mixed_currencies_for_distinct_price_pairs(self, rate):
        response = self.client.patch(self.targets[2][1], {
            'price': '2000000', 'original_price_usd': '10',
        }, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.package.refresh_from_db()
        self.assertEqual(self.package.price, Decimal('2000000'))
        self.assertEqual(self.package.original_price, Decimal('2642800'))

    def test_package_original_price_can_be_edited_or_cleared_in_toman(self, rate):
        current_price = Decimal(str(self.package.price))
        response = self.client.patch(self.targets[2][1], {'original_price': '9000000.1'}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.package.refresh_from_db()
        self.assertEqual(self.package.price, current_price)
        self.assertEqual(self.package.original_price, Decimal('9000001'))
        response = self.client.patch(self.targets[2][1], {'original_price': None}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.package.refresh_from_db()
        self.assertIsNone(self.package.original_price)
        self.assertIsNone(self.package.original_price_usd)

    def test_original_price_cannot_be_submitted_in_both_currencies(self, rate):
        response = self.client.patch(self.targets[2][1], {
            'original_price': '9000000', 'original_price_usd': '10',
        }, format='json')
        self.assertEqual(response.status_code, 400, response.data)

    def test_new_package_option_can_be_created_with_toman_price(self, rate):
        response = self.client.post('/api/v2/site-dashboard/package-price-options/', {
            'package': self.package.pk, 'label': '۴ جلسه', 'session_count': 4, 'price': '4000001',
        }, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        option = SitePackagePriceOption.objects.get(pk=response.data['id'])
        self.assertEqual(option.price, Decimal('4000001'))
        self.assertEqual(toman_price_from_usd(option.price_usd, rate.return_value), option.price)

    def test_package_option_metadata_patch_preserves_prices(self, rate):
        response = self.client.patch(self.targets[3][1], {'is_active': False}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.option.refresh_from_db()
        self.assertFalse(self.option.is_active)
        self.assertEqual(self.option.price, Decimal('1500000'))

    def test_toman_edits_require_authentication(self, rate):
        for obj, url in self.targets:
            response = APIClient().patch(url, {'price': '1000'}, format='json')
            self.assertEqual(response.status_code, 401, response.data)

    def test_swagger_exposes_writable_toman_fields(self, rate):
        response = self.client.get('/api/v2/schema/')
        self.assertEqual(response.status_code, 200)
        schemas = response.data['components']['schemas']
        for name in [
            'PatchedSiteServiceDashboard', 'PatchedSiteProductDashboard',
            'PatchedSitePackageDashboard', 'PatchedSitePackagePriceOptionDashboard',
        ]:
            price = schemas[name]['properties']['price']
            self.assertFalse(price.get('readOnly', False), name)
        original_price = schemas['PatchedSitePackageDashboard']['properties']['original_price']
        self.assertFalse(original_price.get('readOnly', False))

    def test_missing_or_invalid_rate_returns_503_without_saving(self, rate):
        for value in [None, Decimal('0'), Decimal('-1')]:
            rate.return_value = value
            response = self.client.patch(self.targets[0][1], {'price': '1000'}, format='json')
            self.assertEqual(response.status_code, 503, response.data)
        self.service.refresh_from_db()
        self.assertEqual(self.service.price, Decimal('2500000'))
