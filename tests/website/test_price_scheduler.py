from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.test import TestCase

from tests.website.test_models import make_package, make_service
from website.models import SitePackagePriceOption, WebsitePriceSyncRun
from website.services.sync import sync_website_prices_if_due

TEHRAN = ZoneInfo('Asia/Tehran')


class WebsitePriceSchedulerTests(TestCase):
    @patch('website.services.sync.fetch_website_rate')
    def test_usd_base_reprices_once_in_each_tehran_six_hour_window(self, fetch_rate):
        service = make_service(price_usd=Decimal('1'))
        option = SitePackagePriceOption.objects.create(
            package=make_package(price_usd=Decimal('1')), label='Inactive option',
            price=Decimal('0'), price_usd=Decimal('1'), is_active=False,
        )
        slots = [datetime(2026, 10, 31, hour, 5, tzinfo=TEHRAN) for hour in (0, 6, 12, 18)]
        rates = [Decimal('100000'), Decimal('200000'), Decimal('150000'), Decimal('250000')]
        fetch_rate.side_effect = [(rate, 'priceto_day') for rate in rates]
        for slot, rate in zip(slots, rates):
            with patch('website.services.sync.timezone.now', return_value=slot):
                self.assertEqual(sync_website_prices_if_due(now=slot).status, 'succeeded')
                self.assertIsNone(sync_website_prices_if_due(now=slot))
            service.refresh_from_db()
            option.refresh_from_db()
            self.assertEqual(service.price, rate)
            self.assertEqual(option.price, rate)
        self.assertEqual(service.price_usd, Decimal('1'))
        self.assertEqual(WebsitePriceSyncRun.objects.count(), 4)
        self.assertEqual(fetch_rate.call_count, 4)

    @patch('website.services.sync.fetch_website_rate')
    def test_failed_provider_retries_after_fifteen_minutes(self, fetch_rate):
        make_service(price_usd=Decimal('1'))
        start = datetime(2026, 10, 31, 12, 5, tzinfo=TEHRAN)
        fetch_rate.side_effect = [(None, ''), (Decimal('100000'), 'nerkhsanj')]
        with patch('website.services.sync.timezone.now', return_value=start):
            self.assertEqual(sync_website_prices_if_due(now=start).status, 'failed')
        self.assertIsNone(sync_website_prices_if_due(now=start + timedelta(minutes=5)))
        later = start + timedelta(minutes=16)
        with patch('website.services.sync.timezone.now', return_value=later):
            self.assertEqual(sync_website_prices_if_due(now=later).status, 'succeeded')
        self.assertEqual(fetch_rate.call_count, 2)
