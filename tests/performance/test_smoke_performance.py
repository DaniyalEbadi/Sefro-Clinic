import os
import time
import unittest

from django.test import TestCase
from django.utils import timezone

from customers.models import Customer, Payment, Service, Visit
from tests.helpers import admin_client


@unittest.skipUnless(
    os.environ.get('SEFRO_PERF') == '1',
    'opt-in: set SEFRO_PERF=1 to run performance smoke checks',
)
class ReportPerformanceSmokeTests(TestCase):
    THRESHOLD_SECONDS = 2.0

    @classmethod
    def setUpTestData(cls):
        # Dataset only; client is per-test to avoid TestCase client shadowing
        customer = Customer.objects.create(
            first_name='Bulk', last_name='Buyer',
            mobile_number='09130000000', national_id='100-0000100',
        )
        service = Service.objects.create(name='Bulk Service')
        visit = Visit.objects.create(customer=customer, start_at=timezone.now(), end_at=timezone.now())
        visit.services.add(service)
        Payment.objects.bulk_create([
            Payment(
                customer=customer,
                amount=str(1000 + index),
                paid_at=timezone.now(),
            )
            for index in range(500)
        ])

    def setUp(self):
        # Per-test authenticated client (avoids class-level client shadowing by TestCase)
        self.client = admin_client()

    def _timed_get(self, url):
        started = time.perf_counter()
        response = self.client.get(url)
        elapsed = time.perf_counter() - started
        self.assertEqual(response.status_code, 200, url)
        return elapsed

    def test_dashboard_under_threshold(self):
        self.assertLess(self._timed_get('/api/dashboard/'), self.THRESHOLD_SECONDS)

    def test_reports_under_threshold(self):
        self.assertLess(self._timed_get('/api/reports/'), self.THRESHOLD_SECONDS)

    def test_all_reports_under_threshold(self):
        self.assertLess(self._timed_get('/api/reports/all/'), self.THRESHOLD_SECONDS)
