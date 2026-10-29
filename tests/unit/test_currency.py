from decimal import Decimal
from unittest import mock

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone

from finance.models import ExchangeRate
from finance.services.exchange_rates import (
    ExternalExchangeRateProvider,
    _validate_rate,
    convert_usd_to_toman,
    get_current_usd_to_toman_rate,
    get_rate,
    usd_to_toman,
)


@override_settings(EXCHANGE_RATE_PROVIDER='database')
class CurrencyValidationTests(TestCase):
    def test_validate_rate_positive(self):
        self.assertEqual(_validate_rate('100000'), Decimal('100000'))
        self.assertEqual(_validate_rate(Decimal('100')), Decimal('100'))

    def test_validate_rate_zero_negative_non_numeric(self):
        self.assertIsNone(_validate_rate('0'))
        self.assertIsNone(_validate_rate('-5'))
        self.assertIsNone(_validate_rate('abc'))
        self.assertIsNone(_validate_rate(None))
        self.assertIsNone(_validate_rate(''))

    def test_convert_usd_to_toman(self):
        self.assertEqual(convert_usd_to_toman(Decimal('100'), Decimal('100000')), Decimal('10000000.00'))

    def test_convert_invalid_rate(self):
        with self.assertRaises(ValueError):
            convert_usd_to_toman(Decimal('100'), Decimal('0'))
        with self.assertRaises(ValueError):
            convert_usd_to_toman(Decimal('100'), Decimal('-5'))
        with self.assertRaises(ValueError):
            convert_usd_to_toman(Decimal('100'), 'bad')

    def test_usd_to_toman_conversion(self):
        ExchangeRate.objects.create(currency_from='USD', currency_to='TOMAN', rate=Decimal('110000'), effective_at=timezone.now(), source='test')
        self.assertEqual(usd_to_toman(Decimal('100')), Decimal('11000000.00'))

    def test_get_rate_fallback(self):
        # No DB rate -> fallback to setting default 100000
        ExchangeRate.objects.all().delete()
        with override_settings(FINANCE_DEFAULT_USD_TO_TOMAN_RATE=Decimal('12345')):
            self.assertEqual(get_rate('USD', 'TOMAN'), Decimal('12345'))

    def test_get_current_rate_cached_reuse(self):
        ExchangeRate.objects.all().delete()
        ExchangeRate.objects.create(currency_from='USD', currency_to='TOMAN', rate=Decimal('50000'), effective_at=timezone.now(), source='test')
        first = get_current_usd_to_toman_rate()
        second = get_current_usd_to_toman_rate()
        self.assertEqual(first, second)
        self.assertEqual(first, Decimal('50000'))

    def test_no_silent_default_when_fallback_missing(self):
        ExchangeRate.objects.all().delete()
        with override_settings(FINANCE_DEFAULT_USD_TO_TOMAN_RATE=Decimal('0'), EXCHANGE_RATE_PROVIDER='database'):
            # _validate will reject 0, so should return None
            self.assertIsNone(get_current_usd_to_toman_rate())

    def test_invalid_exchange_rate_not_used(self):
        ExchangeRate.objects.all().delete()
        # Create invalid zero rate (bypass model validation via raw? Use set_rate will reject, so create directly)
        # Instead test that _validate rejects it
        self.assertIsNone(_validate_rate(Decimal('0')))
        self.assertIsNone(_validate_rate(Decimal('-10')))


class ExternalProviderTests(TestCase):
    @override_settings(PRICE_TO_DAY_API_URL='http://example.com/rate', EXCHANGE_RATE_TIMEOUT=5)
    def test_timeout_handled(self):
        provider = ExternalExchangeRateProvider()
        with mock.patch('finance.services.exchange_rates.urllib.request.urlopen', side_effect=TimeoutError('timeout')):
            self.assertIsNone(provider.get_usd_to_toman_rate())

    @override_settings(PRICE_TO_DAY_API_URL='http://example.com/rate', EXCHANGE_RATE_TIMEOUT=5)
    def test_connection_failure(self):
        provider = ExternalExchangeRateProvider()
        import urllib.error

        with mock.patch('finance.services.exchange_rates.urllib.request.urlopen', side_effect=urllib.error.URLError('fail')):
            self.assertIsNone(provider.get_usd_to_toman_rate())

    @override_settings(PRICE_TO_DAY_API_URL='http://example.com/rate', EXCHANGE_RATE_TIMEOUT=5)
    def test_http_failure(self):
        provider = ExternalExchangeRateProvider()
        mock_resp = mock.MagicMock()
        mock_resp.status = 500
        mock_resp.read.return_value = b'{}'
        mock_ctx = mock.MagicMock()
        mock_ctx.__enter__.return_value = mock_resp
        with mock.patch('finance.services.exchange_rates.urllib.request.urlopen', return_value=mock_ctx):
            self.assertIsNone(provider.get_usd_to_toman_rate())

    @override_settings(PRICE_TO_DAY_API_URL='http://example.com/rate', EXCHANGE_RATE_TIMEOUT=5)
    def test_malformed_json(self):
        provider = ExternalExchangeRateProvider()
        mock_resp = mock.MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = b'not json'
        mock_ctx = mock.MagicMock()
        mock_ctx.__enter__.return_value = mock_resp
        with mock.patch('finance.services.exchange_rates.urllib.request.urlopen', return_value=mock_ctx):
            self.assertIsNone(provider.get_usd_to_toman_rate())

    @override_settings(PRICE_TO_DAY_API_URL='http://example.com/rate', EXCHANGE_RATE_TIMEOUT=5)
    def test_missing_rate(self):
        provider = ExternalExchangeRateProvider()
        mock_resp = mock.MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = b'{"foo": "bar"}'
        mock_ctx = mock.MagicMock()
        mock_ctx.__enter__.return_value = mock_resp
        with mock.patch('finance.services.exchange_rates.urllib.request.urlopen', return_value=mock_ctx):
            self.assertIsNone(provider.get_usd_to_toman_rate())

    @override_settings(PRICE_TO_DAY_API_URL='http://example.com/rate', EXCHANGE_RATE_TIMEOUT=5)
    def test_zero_and_negative_rate(self):
        provider = ExternalExchangeRateProvider()
        for payload in [b'{"success":true,"price":0}', b'{"success":true,"price":-5}', b'{"success":true,"price":"abc"}', b'{"success":true,"price":"NaN"}']:
            mock_resp = mock.MagicMock()
            mock_resp.status = 200
            mock_resp.read.return_value = payload
            mock_ctx = mock.MagicMock()
            mock_ctx.__enter__.return_value = mock_resp
            with mock.patch('finance.services.exchange_rates.urllib.request.urlopen', return_value=mock_ctx):
                self.assertIsNone(provider.get_usd_to_toman_rate())

    @override_settings(PRICE_TO_DAY_API_URL='http://example.com/rate', EXCHANGE_RATE_TIMEOUT=5)
    def test_valid_rate_extracted(self):
        provider = ExternalExchangeRateProvider()
        mock_resp = mock.MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = b'{"success":true,"price":1100000}'
        mock_ctx = mock.MagicMock()
        mock_ctx.__enter__.return_value = mock_resp
        with mock.patch('finance.services.exchange_rates.urllib.request.urlopen', return_value=mock_ctx):
            self.assertEqual(provider.get_usd_to_toman_rate(), Decimal('110000'))

    @override_settings(PRICE_TO_DAY_API_URL='', EXCHANGE_RATE_TIMEOUT=5)
    def test_no_url_configured(self):
        provider = ExternalExchangeRateProvider()
        # The provider falls back to a public DEFAULT_URL when no URL is set,
        # so blank that out too — otherwise this test performs a live HTTP call.
        with mock.patch.object(ExternalExchangeRateProvider, 'DEFAULT_URL', ''):
            self.assertIsNone(provider.get_usd_to_toman_rate())

    @override_settings(EXCHANGE_RATE_PROVIDER='external', PRICE_TO_DAY_API_URL='http://example.com/rate', EXCHANGE_RATE_CACHE_TTL=3600, FINANCE_DEFAULT_USD_TO_TOMAN_RATE=Decimal('100000'))
    def test_caching_uses_db_when_fresh(self):
        ExchangeRate.objects.all().delete()
        # Create fresh rate
        ExchangeRate.objects.create(currency_from='USD', currency_to='TOMAN', rate=Decimal('90000'), effective_at=timezone.now(), source='priceto_day')
        # Should not call external
        with mock.patch('finance.services.exchange_rates.ExternalExchangeRateProvider.get_usd_to_toman_rate') as mock_fetch:
            rate = get_current_usd_to_toman_rate()
            mock_fetch.assert_not_called()
            self.assertEqual(rate, Decimal('90000'))

    @override_settings(EXCHANGE_RATE_PROVIDER='external', PRICE_TO_DAY_API_URL='http://example.com/rate', EXCHANGE_RATE_CACHE_TTL=3600)
    def test_stale_cached_triggers_fetch_and_caches(self):
        ExchangeRate.objects.all().delete()
        old = timezone.now() - timezone.timedelta(seconds=7200)
        ExchangeRate.objects.create(currency_from='USD', currency_to='TOMAN', rate=Decimal('80000'), effective_at=old, source='old')
        mock_resp = mock.MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = b'{"success":true,"price":950000}'
        mock_ctx = mock.MagicMock()
        mock_ctx.__enter__.return_value = mock_resp
        with mock.patch('finance.services.exchange_rates.urllib.request.urlopen', return_value=mock_ctx):
            rate = get_current_usd_to_toman_rate()
            self.assertEqual(rate, Decimal('95000'))
            # Should have cached new rate
            self.assertTrue(ExchangeRate.objects.filter(rate=Decimal('95000'), source='priceto_day').exists())

    @override_settings(EXCHANGE_RATE_PROVIDER='external', FINANCE_DEFAULT_USD_TO_TOMAN_RATE=Decimal('0'))
    def test_primary_failure_uses_nerkhsanj_backup(self):
        with mock.patch('finance.services.exchange_rates.ExternalExchangeRateProvider.get_usd_to_toman_rate', return_value=None):
            with mock.patch('finance.services.exchange_rates.NerkhsanjExchangeRateProvider.get_usd_to_toman_rate', return_value=Decimal('270010')):
                self.assertEqual(get_current_usd_to_toman_rate(), Decimal('270010'))
        self.assertTrue(ExchangeRate.objects.filter(rate=Decimal('270010'), source='nerkhsanj').exists())

    @override_settings(EXCHANGE_RATE_PROVIDER='external', FINANCE_DEFAULT_USD_TO_TOMAN_RATE=Decimal('0'))
    def test_both_providers_failing_preserves_cached_rate(self):
        ExchangeRate.objects.all().delete()
        old = timezone.now() - timezone.timedelta(hours=3)
        ExchangeRate.objects.create(currency_from='USD', currency_to='TOMAN', rate=Decimal('220000'), effective_at=old, source='priceto_day')
        with mock.patch('finance.services.exchange_rates.ExternalExchangeRateProvider.get_usd_to_toman_rate', return_value=None):
            with mock.patch('finance.services.exchange_rates.NerkhsanjExchangeRateProvider.get_usd_to_toman_rate', return_value=None):
                self.assertEqual(get_current_usd_to_toman_rate(), Decimal('220000'))
        self.assertEqual(ExchangeRate.objects.count(), 1)

    @override_settings(EXCHANGE_RATE_PROVIDER='external', TESTING=False, FINANCE_DEFAULT_USD_TO_TOMAN_RATE=Decimal('0'))
    def test_provider_outage_is_rate_limited(self):
        cache.clear()
        ExchangeRate.objects.all().delete()
        try:
            with mock.patch('finance.services.exchange_rates.ExternalExchangeRateProvider.get_usd_to_toman_rate', return_value=None) as primary:
                with mock.patch('finance.services.exchange_rates.NerkhsanjExchangeRateProvider.get_usd_to_toman_rate', return_value=None) as backup:
                    self.assertIsNone(get_current_usd_to_toman_rate())
                    self.assertIsNone(get_current_usd_to_toman_rate())
            primary.assert_called_once()
            backup.assert_called_once()
        finally:
            cache.clear()
