from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase, override_settings
from rest_framework import status

from tests.helpers import employee_client
from tests.website.test_models import make_package, make_product, make_service
from website.models import WebsitePriceSyncRun
from website.services.sync import sync_website_prices


class WebsiteDashboardPriceTests(TestCase):
    @override_settings(FINANCE_DEFAULT_USD_TO_TOMAN_RATE=Decimal('79999.9'))
    @patch('website.views.get_current_usd_to_toman_rate', return_value=Decimal('79999.9'))
    def test_employee_can_update_service_price_with_whole_toman_ceiling(self, rate):
        service = make_service(price_usd='0.00')

        response = employee_client().patch(
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

        response = employee_client().patch(
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

    def test_dashboard_rejects_content_only_edits(self):
        service = make_service()
        response = employee_client().patch(
            f'/api/v2/site-dashboard/services/{service.slug}/',
            {'name': 'تغییر نام'}, format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


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
