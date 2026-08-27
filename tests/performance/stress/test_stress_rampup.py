"""Stress tests: ramp up concurrency until degradation is observed.

All heavy-gated (SEFRO_PERF_HEAVY=1). Tests systematically increase
worker count and measure error rate + latency growth.
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


@unittest.skipUnless(HEAVY, 'set SEFRO_PERF_HEAVY=1')
class StressRampupTests(TestCase):
    """Progressively increase load to find the degradation point."""

    @classmethod
    def setUpTestData(cls):
        build_clinic_dataset(customers=200, visits_per_customer=3, payments_per_customer=3)

    def _run_ramp(self, workers, requests_per_worker=10):
        endpoints = [
            ('/api/customers/', 'GET'),
            ('/api/dashboard/', 'GET'),
            ('/api/payments/?page=1', 'GET'),
        ]
        result = run_concurrent(
            workers=workers, requests_per_worker=requests_per_worker,
            client_factory=_make_client,
            call_fn=EndpointWorker(endpoints),
        )
        return result

    def test_ramp_8_to_32_workers(self):
        results = {}
        for w in (8, 16, 24, 32):
            result = self._run_ramp(w, requests_per_worker=10)
            results[f'w{w}'] = {
                'p95_ms': result.get('p95_ms'),
                'error_rate': result.get('error_rate'),
                'rps': result.get('aggregate_rps'),
            }
            save_result(f'stress_ramp_{w}w', result)
        self.assertLess(
            results['w32']['error_rate'] or 0, 0.10,
            f'error rate at 32 workers: {results["w32"]["error_rate"]}',
        )

    def test_sustained_16_workers_30_seconds(self):
        result = run_concurrent(
            workers=16, requests_per_worker=40,
            client_factory=_make_client,
            call_fn=EndpointWorker([
                ('/api/customers/', 'GET'),
                ('/api/dashboard/', 'GET'),
                ('/api/visits/?page=1', 'GET'),
                ('/api/inventory/products/', 'GET'),
            ]),
        )
        save_result('stress_sustained_16w', result)
        self.assertLess(result.get('error_rate', 1), 0.05)
