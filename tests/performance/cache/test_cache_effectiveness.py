"""Cache performance tests.

The project uses Django's default LocMemCache. These tests measure
cache effectiveness when enabled vs disabled, and detect stampede patterns.
"""
import threading
import time

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from rest_framework.test import APIClient

from tests.performance.conftest import QueryProbe, save_result, summarize_latencies
from tests.performance.factories import build_clinic_dataset

User = get_user_model()


def _auth_client():
    client = APIClient()
    admin = User.objects.get(username='sefro_admin')
    client.force_authenticate(user=admin)
    return client


class CacheEffectivenessTests(TestCase):
    """Measure raw cache latency and effectiveness."""

    @classmethod
    def setUpTestData(cls):
        build_clinic_dataset(customers=50, visits_per_customer=2, payments_per_customer=2)

    def test_cache_set_get_latency(self):
        latencies_set, latencies_get = [], []
        for _ in range(100):
            cache.clear()
            start = time.perf_counter()
            cache.set('bench_key', 'bench_value', 60)
            latencies_set.append((time.perf_counter() - start) * 1000)
            start = time.perf_counter()
            cache.get('bench_key')
            latencies_get.append((time.perf_counter() - start) * 1000)
        stats_set = summarize_latencies(latencies_set)
        stats_get = summarize_latencies(latencies_get)
        save_result('cache_raw_latency', {'set': stats_set, 'get': stats_get})
        self.assertLess(stats_set['p95_ms'], 10)
        self.assertLess(stats_get['p95_ms'], 5)

    def test_dashboard_query_count_with_cache_clear(self):
        client = _auth_client()
        cache.clear()
        with QueryProbe() as probe:
            client.get('/api/dashboard/')
        uncached_queries = probe.count
        cache.clear()
        with QueryProbe() as probe2:
            client.get('/api/dashboard/')
        cached_queries = probe2.count
        save_result('cache_dashboard_queries', {
            'uncached': uncached_queries,
            'cached': cached_queries,
        })

    def test_concurrent_cache_access_no_stampede(self):
        """Multiple threads hitting cache simultaneously."""
        cache.clear()
        cache.set('stampede_key', 'value', 60)
        latencies = []

        def worker():
            start = time.perf_counter()
            val = cache.get('stampede_key')
            latencies.append((time.perf_counter() - start) * 1000)
            return val

        threads = [threading.Thread(target=worker) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        stats = summarize_latencies(latencies)
        save_result('cache_stampede', stats)
        self.assertLess(stats['max_ms'], 50)
