"""Unit tests for the exchange-rate helpers and providers.

The conversion helpers and the PriceToDay HTTP provider.
"""
from decimal import Decimal
from unittest import mock

from django.test import TestCase

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
    """PriceToDay returns rial per USD, with an explicit success flag."""

    def setUp(self):
        self.provider = xr.ExternalExchangeRateProvider()

    def _fetch(self, body, status=200):
        response = mock.MagicMock()
        response.status = status
        response.read.return_value = body if isinstance(body, bytes) else body.encode()
        response.__enter__.return_value = response
        with mock.patch.object(xr.urllib.request, 'urlopen', return_value=response):
            return self.provider.get_usd_to_toman_rate()

    def test_rial_quote_is_converted_to_toman(self):
        self.assertEqual(self._fetch('{"success":true,"price":2705000}'), Decimal('270500'))

    def test_fractional_toman_quote_is_preserved(self):
        self.assertEqual(self._fetch('{"success":true,"price":2705001}'), Decimal('270500.1'))

    def test_unsuccessful_response_is_rejected(self):
        self.assertIsNone(self._fetch('{"success":false,"price":2705000}'))

    def test_legacy_provider_shape_is_rejected(self):
        self.assertIsNone(self._fetch('{"rate":2705000}'))

    def test_non_200_response_returns_none(self):
        self.assertIsNone(self._fetch('{}', status=500))

    def test_malformed_json_returns_none(self):
        self.assertIsNone(self._fetch('not-json'))

    def test_payload_without_rate_returns_none(self):
        self.assertIsNone(self._fetch('{"data":[]}'))

class NerkhsanjProviderTests(TestCase):
    def setUp(self):
        self.provider = xr.NerkhsanjExchangeRateProvider()

    def _fetch(self, body, status=200):
        response = mock.MagicMock()
        response.status = status
        response.read.return_value = body if isinstance(body, bytes) else body.encode()
        response.__enter__.return_value = response
        with mock.patch.object(xr.urllib.request, 'urlopen', return_value=response) as opener:
            rate = self.provider.get_usd_to_toman_rate()
        self.assertNotIn('Authorization', opener.call_args.args[0].headers)
        return rate

    def test_toman_quote_is_used_without_rial_conversion(self):
        self.assertEqual(self._fetch('{"rates":{"dollar":270010}}'), Decimal('270010'))

    def test_missing_or_bad_dollar_is_rejected(self):
        for body in ('{}', '{"rates":{"dollar":0}}', '{"rates":{"dollar":"NaN"}}'):
            self.assertIsNone(self._fetch(body))

    def test_http_and_json_failures_are_rejected(self):
        self.assertIsNone(self._fetch('{}', status=500))
        self.assertIsNone(self._fetch('not-json'))

    def test_transport_failure_is_rejected(self):
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
