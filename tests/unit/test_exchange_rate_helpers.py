"""Unit tests for the exchange-rate helpers and providers.

The conversion helpers and both HTTP providers (Tindex primary, BrsApi backup)
previously had only partial coverage; the provider parsing paths were untested.
"""
from decimal import Decimal
from unittest import mock

from django.test import TestCase, override_settings

from finance.services import exchange_rates as xr


class ValidateRateTests(TestCase):
    def test_positive_values_are_accepted(self):
        self.assertEqual(xr._validate_rate(Decimal('100000')), Decimal('100000'))
        self.assertEqual(xr._validate_rate('92570.5'), Decimal('92570.5'))
        self.assertEqual(xr._validate_rate(92570), Decimal('92570'))

    def test_invalid_values_are_rejected(self):
        for bad in (None, '0', 0, '-1', -1, 'abc', Decimal('-0.01'), '', []):
            self.assertIsNone(xr._validate_rate(bad), repr(bad))


class ConversionHelperTests(TestCase):
    def test_to_toman_with_explicit_rate(self):
        self.assertEqual(xr.to_toman(Decimal('100'), Decimal('50000')), Decimal('5000000.00'))

    def test_to_toman_with_invalid_rate_raises(self):
        with self.assertRaises(ValueError):
            xr.to_toman(Decimal('100'), Decimal('-1'))

    def test_to_toman_without_rate_uses_database_rate(self):
        xr.set_rate('USD', 'TOMAN', Decimal('60000'))
        self.assertEqual(xr.to_toman(Decimal('2')), Decimal('120000.00'))

    def test_to_usd_round_trips(self):
        rate = Decimal('50000')
        toman = xr.to_toman(Decimal('100'), rate)
        self.assertEqual(xr.to_usd(toman, rate), Decimal('100.00'))

    def test_to_usd_with_invalid_rate_returns_zero(self):
        self.assertEqual(xr.to_usd(Decimal('100'), Decimal('0')), Decimal('0'))
        self.assertEqual(xr.to_usd(Decimal('100'), None), Decimal('0'))

    def test_convert_rejects_bad_inputs(self):
        with self.assertRaises(ValueError):
            xr.convert_usd_to_toman('not-a-number', Decimal('1'))
        with self.assertRaises(ValueError):
            xr.convert_usd_to_toman(Decimal('1'), Decimal('0'))

    def test_usd_to_toman_returns_none_without_rate(self):
        with mock.patch.object(xr, 'get_current_usd_to_toman_rate', return_value=None):
            self.assertIsNone(xr.usd_to_toman(Decimal('10')))

    def test_usd_to_toman_converts_when_rate_available(self):
        with mock.patch.object(xr, 'get_current_usd_to_toman_rate', return_value=Decimal('100000')):
            self.assertEqual(xr.usd_to_toman(Decimal('10')), Decimal('1000000.00'))


class ExternalProviderParsingTests(TestCase):
    """The Tindex/primary provider must tolerate several upstream shapes."""

    def setUp(self):
        self.provider = xr.ExternalExchangeRateProvider()

    def _fetch(self, body, status=200):
        response = mock.MagicMock()
        response.status = status
        response.read.return_value = body if isinstance(body, bytes) else body.encode()
        response.__enter__.return_value = response
        with mock.patch.object(xr.urllib.request, 'urlopen', return_value=response):
            return self.provider.get_usd_to_toman_rate()

    def test_list_payload_with_slug_key(self):
        body = '{"data":[{"key":"EUR","rate":1},{"slug":"usd-exchange-rate","rate":"92570"}]}'
        self.assertEqual(self._fetch(body), Decimal('92570'))

    def test_single_indicator_payload(self):
        self.assertEqual(self._fetch('{"success":true,"data":{"price":"92570"}}'), Decimal('92570'))

    def test_nested_current_price(self):
        self.assertEqual(self._fetch('{"data":{"current":{"price": 92570}}}'), Decimal('92570'))

    def test_generic_rate_key_fallback(self):
        self.assertEqual(self._fetch('{"rate": 92570}'), Decimal('92570'))

    def test_non_200_response_returns_none(self):
        self.assertIsNone(self._fetch('{}', status=500))

    def test_malformed_json_returns_none(self):
        self.assertIsNone(self._fetch('not-json'))

    def test_payload_without_rate_returns_none(self):
        self.assertIsNone(self._fetch('{"data":[]}'))


class BrsApiBackupProviderTests(TestCase):
    def setUp(self):
        self.provider = xr.BrsApiExchangeRateProvider()

    def _fetch(self, body, status=200):
        response = mock.MagicMock()
        response.status = status
        response.read.return_value = body if isinstance(body, bytes) else body.encode()
        response.__enter__.return_value = response
        with mock.patch.object(xr.urllib.request, 'urlopen', return_value=response):
            return self.provider.get_usd_to_toman_rate()

    @override_settings(EXCHANGE_RATE_BACKUP_API_URL='https://backup.example/api',
                       EXCHANGE_RATE_BACKUP_API_KEY='key-123')
    def test_parses_currency_list(self):
        body = '{"currency":[{"name_en":"US Dollar","symbol":"USD","price":"220300"}]}'
        self.assertEqual(self._fetch(body), Decimal('220300'))

    @override_settings(EXCHANGE_RATE_BACKUP_API_URL='https://backup.example/api',
                       EXCHANGE_RATE_BACKUP_API_KEY='key-123')
    def test_no_usd_row_returns_none(self):
        body = '{"currency":[{"name_en":"Euro","symbol":"EUR","price":"240000"}]}'
        self.assertIsNone(self._fetch(body))

    @override_settings(EXCHANGE_RATE_BACKUP_API_KEY='')
    def test_missing_api_key_returns_none(self):
        self.assertIsNone(self.provider.get_usd_to_toman_rate())

    @override_settings(EXCHANGE_RATE_BACKUP_API_URL='ftp://not-http',
                       EXCHANGE_RATE_BACKUP_API_KEY='key')
    def test_invalid_url_scheme_returns_none(self):
        self.assertIsNone(self.provider.get_usd_to_toman_rate())

    @override_settings(EXCHANGE_RATE_BACKUP_API_URL='https://backup.example/api',
                       EXCHANGE_RATE_BACKUP_API_KEY='key')
    def test_http_error_returns_none(self):
        error = xr.urllib.error.HTTPError('u', 500, 'x', None, None)
        with mock.patch.object(xr.urllib.request, 'urlopen', side_effect=error):
            self.assertIsNone(self.provider.get_usd_to_toman_rate())

    @override_settings(EXCHANGE_RATE_BACKUP_API_URL='https://backup.example/api',
                       EXCHANGE_RATE_BACKUP_API_KEY='key')
    def test_url_error_returns_none(self):
        with mock.patch.object(xr.urllib.request, 'urlopen', side_effect=xr.urllib.error.URLError('down')):
            self.assertIsNone(self.provider.get_usd_to_toman_rate())


class PricingHelperTests(TestCase):
    """finance/services/pricing.py was only 41% covered."""

    def setUp(self):
        xr.set_rate('USD', 'TOMAN', Decimal('50000'))
        from customers.models import Service
        from finance.models import Package
        self.service = Service.objects.create(name='Priced', price_usd=Decimal('40'))
        self.package = Package.objects.create(name='Priced Pack', price_usd=Decimal('200'))
        # Refresh so Decimals carry the DB's two-place quantization.
        self.service.refresh_from_db()
        self.package.refresh_from_db()

    def test_service_price_toman(self):
        from finance.services.pricing import service_price_toman
        self.assertEqual(service_price_toman(self.service), Decimal('2000000.00'))
        self.assertEqual(service_price_toman(self.service, rate=Decimal('100000')), Decimal('4000000.00'))

    def test_package_price_toman(self):
        from finance.services.pricing import package_price_toman
        self.assertEqual(package_price_toman(self.package), Decimal('10000000.00'))

    def test_payloads_are_serialisable(self):
        from finance.services.pricing import package_pricing_payload, service_pricing_payload
        svc = service_pricing_payload(self.service)
        self.assertEqual(svc['price_usd'], '40.00')
        self.assertEqual(svc['exchange_rate'], '50000.000000')
        pack = package_pricing_payload(self.package)
        self.assertEqual(pack['price_toman'], '10000000.00')
