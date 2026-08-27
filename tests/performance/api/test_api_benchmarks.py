"""API endpoint performance benchmarks.

Measures latency percentiles, throughput, and response sizes for every
critical endpoint. Uses Django unittest + DRF APIClient (zero extra deps).
Results persist as JSON under reports/data/<phase>/ for the report.
"""
import time

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from tests.performance.conftest import (
    BUDGETS,
    EndpointMeter,
    save_result,
    summarize_latencies,
)
from tests.performance.factories import build_clinic_dataset, create_products

User = get_user_model()


def _auth_client():
    client = APIClient()
    admin = User.objects.get(username='sefro_admin')
    client.force_authenticate(user=admin)
    return client


class AuthBenchmarkTests(TestCase):
    """Login / token-refresh / me endpoint latency benchmarks."""

    @classmethod
    def setUpTestData(cls):
        from tests.performance.factories import make_admin
        make_admin()

    def test_login_latency(self):
        from tests.helpers import ADMIN_PASSWORD, ADMIN_USERNAME
        latencies = []
        for _ in range(20):
            client = __import__('django.test', fromlist=['Client']).Client()
            start = time.perf_counter()
            client.post('/api/auth/token/', {
                'username': ADMIN_USERNAME,
                'password': ADMIN_PASSWORD,
            }, content_type='application/json')
            latencies.append((time.perf_counter() - start) * 1000)
        stats = summarize_latencies(latencies)
        save_result('auth_login', stats)
        self.assertLess(stats['max_ms'], BUDGETS['login_p95_ms_fast_mode'])

    def test_token_refresh_latency(self):
        from rest_framework_simplejwt.tokens import RefreshToken

        from tests.helpers import ADMIN_USERNAME
        user = User.objects.get(username=ADMIN_USERNAME)
        refresh = RefreshToken.for_user(user)
        client = __import__('django.test', fromlist=['Client']).Client()
        latencies = []
        for _ in range(20):
            start = time.perf_counter()
            client.post('/api/auth/token/refresh/', {
                'refresh': str(refresh),
            }, content_type='application/json')
            latencies.append((time.perf_counter() - start) * 1000)
        stats = summarize_latencies(latencies)
        save_result('auth_refresh', stats)
        self.assertLess(stats['max_ms'], BUDGETS['token_refresh_max_ms_fast_mode'])

    def test_me_endpoint_latency(self):
        client = _auth_client()
        meter = EndpointMeter(client)
        result = meter.run('get', '/api/auth/me/', iterations=30)
        save_result('auth_me', result)
        self.assertLess(result['p95_ms'], 500)


class CRUDBenchmarkTests(TestCase):
    """List / detail / search benchmarks for every major resource."""

    @classmethod
    def setUpTestData(cls):
        cls.summary = build_clinic_dataset(
            customers=200, visits_per_customer=3, payments_per_customer=3, services=20,
        )
        cls.products = create_products(500)

    def setUp(self):
        self.client = _auth_client()
        self.meter = EndpointMeter(self.client)

    def test_customer_list(self):
        result = self.meter.run('get', '/api/customers/', iterations=30)
        save_result('crud_customer_list', result)
        self.assertLess(result['p95_ms'], BUDGETS['crud_list_p95_ms_fast_mode'])

    def test_customer_search(self):
        result = self.meter.run('get', '/api/customers/?search=مشتری', iterations=20)
        save_result('crud_customer_search', result)
        self.assertLess(result['p95_ms'], BUDGETS['search_p95_ms_fast_mode'])

    def test_customer_detail(self):
        from customers.models import Customer
        cid = Customer.objects.order_by('pk').values_list('pk', flat=True).first()
        result = self.meter.run('get', f'/api/customers/{cid}/', iterations=30)
        save_result('crud_customer_detail', result)
        self.assertLess(result['p95_ms'], BUDGETS['detail_p95_ms_fast_mode'])

    def test_visit_list(self):
        result = self.meter.run('get', '/api/visits/', iterations=30)
        save_result('crud_visit_list', result)
        self.assertLess(result['p95_ms'], BUDGETS['crud_list_p95_ms_fast_mode'])

    def test_payment_list(self):
        result = self.meter.run('get', '/api/payments/', iterations=30)
        save_result('crud_payment_list', result)
        self.assertLess(result['p95_ms'], BUDGETS['crud_list_p95_ms_fast_mode'])

    def test_payment_by_service(self):
        result = self.meter.run('get', '/api/payments/by_service/', iterations=20)
        save_result('crud_payment_by_service', result)
        self.assertLess(result['p95_ms'], BUDGETS['crud_list_p95_ms_fast_mode'])

    def test_service_list(self):
        result = self.meter.run('get', '/api/services/', iterations=30)
        save_result('crud_service_list', result)
        self.assertLess(result['p95_ms'], BUDGETS['crud_list_p95_ms_fast_mode'])


class InventoryBenchmarkTests(TestCase):
    """Product catalog (inventory) performance tests."""

    @classmethod
    def setUpTestData(cls):
        cls.products = create_products(500)

    def setUp(self):
        self.client = _auth_client()
        self.meter = EndpointMeter(self.client)

    def test_product_list(self):
        result = self.meter.run('get', '/api/inventory/products/', iterations=30)
        save_result('inventory_product_list', result)
        self.assertLess(result['p95_ms'], BUDGETS['crud_list_p95_ms_fast_mode'])

    def test_product_search(self):
        result = self.meter.run('get', '/api/inventory/products/?search=محصول', iterations=20)
        save_result('inventory_product_search', result)
        self.assertLess(result['p95_ms'], BUDGETS['search_p95_ms_fast_mode'])

    def test_product_detail(self):
        from inventory.models import Product
        pid = Product.objects.order_by('pk').values_list('pk', flat=True).first()
        result = self.meter.run('get', f'/api/inventory/products/{pid}/', iterations=30)
        save_result('inventory_product_detail', result)
        self.assertLess(result['p95_ms'], BUDGETS['detail_p95_ms_fast_mode'])

    def test_product_list_response_size(self):
        response = self.client.get('/api/inventory/products/')
        self.assertEqual(response.status_code, 200)
        body = getattr(response, 'content', b'')
        save_result('inventory_product_list_size', {'bytes': len(body)})

    def test_product_create_latency(self):
        latencies = []
        for i in range(15):
            start = time.perf_counter()
            self.client.post('/api/inventory/products/', {
                'name': f'Performance Test Product {i}',
                'sku': f'PERF-{i:05d}',
                'unit_price': '150000.00',
                'count': 100,
                'status': 'available',
                'unit': 'عدد',
            }, format='json')
            latencies.append((time.perf_counter() - start) * 1000)
        stats = summarize_latencies(latencies)
        save_result('inventory_product_create', stats)
        self.assertLess(stats['p95_ms'], 1000)


class DashboardAndReportsBenchmarkTests(TestCase):
    """Dashboard and reporting endpoint latency benchmarks."""

    @classmethod
    def setUpTestData(cls):
        cls.summary = build_clinic_dataset(
            customers=200, visits_per_customer=3, payments_per_customer=3, services=20,
        )

    def setUp(self):
        self.client = _auth_client()
        self.meter = EndpointMeter(self.client)

    def test_dashboard(self):
        result = self.meter.run('get', '/api/dashboard/', iterations=20)
        save_result('dashboard', result)
        self.assertLess(result['p95_ms'], BUDGETS['dashboard_p95_ms_fast_mode'])

    def test_reports_summary(self):
        result = self.meter.run('get', '/api/reports/', iterations=15)
        save_result('reports_summary', result)
        self.assertLess(result['p95_ms'], BUDGETS['reports_heavy_p95_ms_fast_mode'])

    def test_all_reports(self):
        result = self.meter.run('get', '/api/reports/all/', iterations=10)
        save_result('reports_all', result)
        self.assertLess(result['p95_ms'], BUDGETS['reports_heavy_p95_ms_fast_mode'])

    def test_daily_report(self):
        result = self.meter.run('get', '/api/reports/daily/', iterations=15)
        save_result('reports_daily', result)

    def test_weekly_report(self):
        result = self.meter.run('get', '/api/reports/weekly/', iterations=15)
        save_result('reports_weekly', result)

    def test_monthly_report(self):
        result = self.meter.run('get', '/api/reports/monthly/', iterations=15)
        save_result('reports_monthly', result)

    def test_customer_report(self):
        result = self.meter.run('get', '/api/reports/customers/', iterations=15)
        save_result('reports_customers', result)

    def test_referral_report(self):
        result = self.meter.run('get', '/api/reports/referral/', iterations=15)
        save_result('reports_referral', result)


class PaginationBenchmarkTests(TestCase):
    """Pagination performance at various page depths."""

    @classmethod
    def setUpTestData(cls):
        from tests.performance.factories import create_customers
        create_customers(300)

    def setUp(self):
        self.client = _auth_client()

    def test_pagination_latency_by_page(self):
        results = {}
        for page in (1, 3, 5, 10, 15):
            start = time.perf_counter()
            response = self.client.get(f'/api/customers/?page={page}')
            elapsed_ms = (time.perf_counter() - start) * 1000
            results[f'page_{page}_ms'] = round(elapsed_ms, 2)
            self.assertEqual(response.status_code, 200)
        save_result('pagination_latency_by_page', results)
        self.assertLess(max(results.values()), 1000)


class ResponseSizeTests(TestCase):
    """Measure response payload sizes for every critical endpoint."""

    @classmethod
    def setUpTestData(cls):
        build_clinic_dataset(customers=100, visits_per_customer=2, payments_per_customer=2, services=15)
        create_products(100)

    def setUp(self):
        self.client = _auth_client()

    def _measure_size(self, url):
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        return len(getattr(response, 'content', b''))

    def test_all_endpoint_response_sizes(self):
        endpoints = [
            '/api/customers/',
            '/api/visits/',
            '/api/payments/',
            '/api/services/',
            '/api/inventory/products/',
            '/api/dashboard/',
            '/api/reports/',
        ]
        sizes = {url: self._measure_size(url) for url in endpoints}
        save_result('response_sizes', sizes)
        for url, size in sizes.items():
            self.assertLess(size, 500_000, f'{url} response too large: {size} bytes')
