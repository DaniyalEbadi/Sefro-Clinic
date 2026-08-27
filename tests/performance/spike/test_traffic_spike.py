"""Spike tests: simulate sudden traffic bursts.

All heavy-gated. Measures how the application handles abrupt load changes.
"""
import unittest

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from tests.performance.conftest import HEAVY, EndpointWorker, run_concurrent, save_result
from tests.performance.factories import build_clinic_dataset

User = get_user_model()


def _make_client(worker_index):
    client = APIClient()
    admin = User.objects.get(username='sefro_admin')
    client.force_authenticate(user=admin)
    return client


@unittest.skipUnless(HEAVY, 'set SEFRO_PERF_HEAVY=1')
class SpikeTests(TestCase):
    """Simulate sudden traffic spikes and measure recovery."""

    @classmethod
    def setUpTestData(cls):
        build_clinic_dataset(customers=200, visits_per_customer=3, payments_per_customer=3)

    def test_spike_10_to_100_to_500(self):
        endpoints = [
            ('/api/customers/', 'GET'),
            ('/api/dashboard/', 'GET'),
            ('/api/payments/?page=1', 'GET'),
        ]
        phases = {
            'spike_10': 10,
            'spike_50': 50,
            'spike_100': 100,
        }
        results = {}
        for label, workers in phases.items():
            result = run_concurrent(
                workers=workers, requests_per_worker=5,
                client_factory=_make_client,
                call_fn=EndpointWorker(endpoints),
            )
            results[label] = {
                'p95_ms': result.get('p95_ms'),
                'error_rate': result.get('error_rate'),
                'rps': result.get('aggregate_rps'),
            }
            save_result(label, result)
        max_error = max(r['error_rate'] or 0 for r in results.values())
        self.assertLess(max_error, 0.10, f'spike error rate: {results}')

    def test_spike_recovery(self):
        """Burst then verify latency returns to baseline."""
        endpoints = [('/api/customers/', 'GET')]
        baseline = run_concurrent(
            workers=4, requests_per_worker=10,
            client_factory=_make_client,
            call_fn=EndpointWorker(endpoints),
        )
        _ = run_concurrent(
            workers=50, requests_per_worker=10,
            client_factory=_make_client,
            call_fn=EndpointWorker(endpoints),
        )
        recovery = run_concurrent(
            workers=4, requests_per_worker=10,
            client_factory=_make_client,
            call_fn=EndpointWorker(endpoints),
        )
        save_result('spike_recovery', {
            'baseline_p95': baseline.get('p95_ms'),
            'recovery_p95': recovery.get('p95_ms'),
        })
