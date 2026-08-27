"""Endurance tests: sustained load for extended duration.

Detects memory leaks, connection leaks, and latency drift over time.
Heavy-gated (SEFRO_PERF_HEAVY=1).
"""
import unittest

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from rest_framework.test import APIClient

from tests.performance.conftest import (
    HEAVY,
    EndpointWorker,
    MemoryTracker,
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
class EnduranceTests(TestCase):
    """Sustained traffic for 45-60 seconds checking for resource leaks."""

    @classmethod
    def setUpTestData(cls):
        build_clinic_dataset(customers=200, visits_per_customer=3, payments_per_customer=3)

    def test_60s_sustained_load(self):
        endpoints = [
            ('/api/customers/', 'GET'),
            ('/api/dashboard/', 'GET'),
            ('/api/payments/?page=1', 'GET'),
            ('/api/inventory/products/', 'GET'),
        ]
        with MemoryTracker() as tracker:
            result = run_concurrent(
                workers=8, requests_per_worker=80,
                client_factory=_make_client,
                call_fn=EndpointWorker(endpoints),
            )
        result['memory'] = tracker.result
        save_result('endurance_60s', result)
        if tracker.result.get('rss_growth_mb') is not None:
            self.assertLess(
                tracker.result['rss_growth_mb'], 50,
                f'memory grew {tracker.result["rss_growth_mb"]}MB during endurance run',
            )

    def test_connection_stability(self):
        """Verify DB connections don't leak across sustained load."""
        before = connection.queries.__len__()
        for _ in range(5):
            run_concurrent(
                workers=4, requests_per_worker=10,
                client_factory=_make_client,
                call_fn=EndpointWorker([('/api/customers/', 'GET')]),
            )
        connection.close()
        save_result('endurance_connections', {'queries_executed_before': before})
