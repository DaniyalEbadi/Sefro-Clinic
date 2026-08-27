"""Scalability tests: measure how performance changes as data volume grows.

Tests list/search/pagination latency across dataset sizes (2k, 10k, 50k rows)
to determine where performance begins to degrade.
"""
import unittest

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from tests.performance.conftest import HEAVY, EndpointMeter, QueryProbe, save_result
from tests.performance.factories import build_clinic_dataset, create_products

User = get_user_model()


def _auth_client():
    client = APIClient()
    admin = User.objects.get(username='sefro_admin')
    client.force_authenticate(user=admin)
    return client


class DatasetScalingTests(TestCase):
    """Measure latency as customer count increases."""

    def _run_at_scale(self, n_customers):
        build_clinic_dataset(customers=n_customers, visits_per_customer=1, payments_per_customer=1, services=10)
        client = _auth_client()
        meter = EndpointMeter(client)
        list_result = meter.run('get', '/api/customers/', iterations=15)
        search_result = meter.run('get', '/api/customers/?search=مشتری', iterations=10)
        return {'list': list_result, 'search': search_result}

    def test_scaling_100_vs_1000(self):
        small = self._run_at_scale(100)
        save_result('scale_100_customers', small['list'])
        large = self._run_at_scale(1000)
        save_result('scale_1000_customers', large['list'])
        self.assertLess(large['list']['p95_ms'], 2000)

    def test_scaling_query_count_stable(self):
        build_clinic_dataset(customers=500, visits_per_customer=2, payments_per_customer=2, services=10)
        client = _auth_client()
        with QueryProbe() as probe:
            client.get('/api/customers/')
        save_result('scale_500_query_count', {'count': probe.count})
        self.assertLessEqual(probe.count, 10, f'query count at 500 customers: {probe.count}')


@unittest.skipUnless(HEAVY, 'set SEFRO_PERF_HEAVY=1')
class HeavyScalingTests(TestCase):
    """Larger dataset scaling for nightly runs."""

    def test_5000_customer_list(self):
        build_clinic_dataset(customers=5000, visits_per_customer=1, payments_per_customer=1, services=15)
        client = _auth_client()
        meter = EndpointMeter(client)
        result = meter.run('get', '/api/customers/', iterations=10)
        save_result('scale_5000_customers', result)
        self.assertLess(result['p95_ms'], 5000)

    def test_5000_search_performance(self):
        build_clinic_dataset(customers=5000, visits_per_customer=1, payments_per_customer=1, services=15)
        client = _auth_client()
        meter = EndpointMeter(client)
        result = meter.run('get', '/api/customers/?search=مشتری', iterations=10)
        save_result('scale_5000_search', result)
        self.assertLess(result['p95_ms'], 5000)


class ProductScalingTests(TestCase):
    """Inventory scaling as product count grows."""

    def test_product_list_at_1000(self):
        create_products(1000)
        client = _auth_client()
        meter = EndpointMeter(client)
        result = meter.run('get', '/api/inventory/products/', iterations=15)
        save_result('scale_1000_products', result)
        self.assertLess(result['p95_ms'], 1500)

    def test_product_search_at_1000(self):
        create_products(1000)
        client = _auth_client()
        meter = EndpointMeter(client)
        result = meter.run('get', '/api/inventory/products/?search=محصول', iterations=10)
        save_result('scale_1000_product_search', result)
        self.assertLess(result['p95_ms'], 1500)
