"""Threaded concurrency load tests.

Simulates multiple simultaneous users hitting critical endpoints. Uses
Django's test client in-process (no network layer). Gated behind
SEFRO_PERF_HEAVY=1 except for a lightweight concurrency smoke test.
"""
import unittest

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from tests.performance.conftest import (
    HEAVY,
    EndpointWorker,
    run_concurrent,
    save_result,
)
from tests.performance.factories import build_clinic_dataset

User = get_user_model()


def _make_client(worker_index):
    client = APIClient()
    admin = User.objects.get(username='sefro_admin')
    client.force_authenticate(user=admin)
    return client


class ConcurrencySmokeTests(TestCase):
    """Lightweight concurrency check that runs in every CI build."""

    @classmethod
    def setUpTestData(cls):
        build_clinic_dataset(customers=50, visits_per_customer=2, payments_per_customer=2, services=10)

    def test_4_concurrent_readers_no_errors(self):
        endpoints = [
            ('/api/customers/', 'GET'),
            ('/api/visits/', 'GET'),
            ('/api/payments/', 'GET'),
            ('/api/dashboard/', 'GET'),
        ]
        result = run_concurrent(
            workers=4, requests_per_worker=5,
            client_factory=_make_client,
            call_fn=EndpointWorker(endpoints),
        )
        save_result('concurrency_smoke_4w', result)
        self.assertLess(result['error_rate'], 0.05, f'concurrent reads error rate: {result}')


@unittest.skipUnless(HEAVY, 'set SEFRO_PERF_HEAVY=1 to run heavy concurrency tests')
class HeavyConcurrencyTests(TestCase):
    """Higher-concurrency scenarios for the scheduled workflow."""

    @classmethod
    def setUpTestData(cls):
        build_clinic_dataset(customers=200, visits_per_customer=3, payments_per_customer=3, services=20)

    def test_16_concurrent_readers(self):
        endpoints = [
            ('/api/customers/', 'GET'),
            ('/api/visits/?page=1', 'GET'),
            ('/api/payments/?page=1', 'GET'),
            ('/api/dashboard/', 'GET'),
            ('/api/services/', 'GET'),
            ('/api/inventory/products/', 'GET'),
        ]
        result = run_concurrent(
            workers=16, requests_per_worker=10,
            client_factory=_make_client,
            call_fn=EndpointWorker(endpoints),
        )
        save_result('concurrency_heavy_16w', result)
        self.assertLess(result['error_rate'], 0.02)

    def test_32_concurrent_writers(self):
        """Create resources concurrently to surface lock contention."""
        def create_fn(client, worker_idx, call_idx):
            response = client.post('/api/inventory/products/', {
                'name': f'Concurrent Product {worker_idx}-{call_idx}',
                'sku': f'CONC-{worker_idx:02d}-{call_idx:04d}',
                'unit_price': '100000.00',
                'count': 10,
                'status': 'available',
                'unit': 'عدد',
            }, format='json')
            return response.status_code

        result = run_concurrent(
            workers=8, requests_per_worker=20,
            client_factory=_make_client,
            call_fn=create_fn,
        )
        save_result('concurrency_heavy_writers_8w', result)
        self.assertLess(result['error_rate'], 0.05)
