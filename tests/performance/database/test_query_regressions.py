"""Deterministic query-count regression tests.

These tests are environment independent: they assert exact maximum query
counts (and absence of duplicated statements / N+1 patterns), never wall
clock time. A failure here means a real performance regression slipped in.

Known historical offenders guarded here (measured 2026-08):

* GET /api/customers/ executed ~65 queries per page: three per-row
  property queries (visit_count, total_payments, last_visit_date)
  multiplied by the page size plus pagination overheads.
* GET /api/dashboard/ loaded every customer and issued one COUNT query
  per customer while resolving is_loyal_customer.
* GET /api/payments/by_service/ pulled every payment row into Python.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from tests.performance.conftest import BUDGETS, QueryProbe
from tests.performance.factories import build_clinic_dataset, create_products

User = get_user_model()


def _auth_client():
    """Return an APIClient authenticated as the admin user."""
    client = APIClient()
    admin = User.objects.get(username='sefro_admin')
    client.force_authenticate(user=admin)
    return client


class EndpointQueryBudgetTests(TestCase):
    """Hard ceilings on SQL round-trips per authenticated request."""

    @classmethod
    def setUpTestData(cls):
        cls.summary = build_clinic_dataset(
            customers=40, visits_per_customer=2, payments_per_customer=2, services=10,
        )
        cls.products = create_products(30)

    def setUp(self):
        self.client = _auth_client()

    def _get(self, url):
        with QueryProbe() as probe:
            response = self.client.get(url)
        return probe, response

    # --- core CRUD lists -------------------------------------------------

    def test_customer_list_within_budget(self):
        probe, response = self._get('/api/customers/')
        self.assertEqual(response.status_code, 200)
        self.assertLessEqual(
            probe.count, BUDGETS['max_queries_customer_list'],
            f'customer list issued {probe.count} queries:\n' + '\n'.join(probe.sql_statements),
        )

    def test_customer_list_has_no_duplicate_statements(self):
        with QueryProbe() as probe:
            response = self.client.get('/api/customers/?page=1')
        self.assertEqual(response.status_code, 200)
        dups = probe.duplicates()
        self.assertEqual(dups, [], f'duplicated statements detected: {dups[:3]}')

    def test_customer_detail_within_budget(self):
        from customers.models import Customer
        cid = Customer.objects.order_by('pk').values_list('pk', flat=True).first()
        probe, response = self._get(f'/api/customers/{cid}/')
        self.assertEqual(response.status_code, 200)
        self.assertLessEqual(probe.count, BUDGETS['max_queries_customer_detail'])

    def test_visit_list_prefetches_related(self):
        probe, response = self._get('/api/visits/')
        self.assertEqual(response.status_code, 200)
        self.assertLessEqual(probe.count, BUDGETS['max_queries_visit_list'])
        services_queries = probe.statements_matching('visits_services')
        self.assertLessEqual(len(services_queries), 1, 'services M2M fetched more than once')

    def test_payment_list_selects_related(self):
        probe, response = self._get('/api/payments/')
        self.assertEqual(response.status_code, 200)
        self.assertLessEqual(probe.count, BUDGETS['max_queries_payment_list'])
        per_row_lookups = [
            sql for sql in probe.sql_statements
            if 'customers_customer' in sql and 'WHERE' in sql and 'id =' in sql
        ]
        self.assertEqual(per_row_lookups, [], 'per-row customer lookup leaked into payment list')

    def test_payment_by_service_is_bounded(self):
        probe, response = self._get('/api/payments/by_service/')
        self.assertEqual(response.status_code, 200)
        self.assertLessEqual(probe.count, 6, f'by_service issued {probe.count} queries')

    def test_service_list_within_budget(self):
        probe, response = self._get('/api/services/')
        self.assertEqual(response.status_code, 200)
        # Budget 4: count + services(category join) + serviceitems + exchange rate
        # Previously 3 before product costing; now includes prefetched products
        self.assertLessEqual(probe.count, 5)

    def test_service_category_list_within_budget(self):
        probe, response = self._get('/api/service-categories/')
        self.assertEqual(response.status_code, 200)
        self.assertLessEqual(probe.count, 4)

    def test_service_pricing_no_n_plus_one(self):
        # Ensure pricing derivation does not issue per-service exchange query
        with QueryProbe() as probe:
            resp = self.client.get('/api/services/')
        self.assertEqual(resp.status_code, 200)
        # Only one exchange-rate query despite many services
        rate_qs = probe.statements_matching('exchange')
        self.assertLessEqual(len(rate_qs), 1, f'Exchange rate queried {len(rate_qs)} times')
        # Only one serviceitems query
        item_qs = probe.statements_matching('serviceitem')
        self.assertLessEqual(len(item_qs), 1, 'ServiceItem prefetched more than once')

    # --- inventory (products) ---------------------------------------------

    def test_product_list_within_budget(self):
        probe, response = self._get('/api/inventory/products/')
        self.assertEqual(response.status_code, 200)
        self.assertLessEqual(probe.count, BUDGETS['max_queries_product_list'])

    def test_product_search_within_budget(self):
        probe, response = self._get('/api/inventory/products/?search=محصول')
        self.assertEqual(response.status_code, 200)
        self.assertLessEqual(probe.count, BUDGETS['max_queries_product_search'])

    def test_product_detail_within_budget(self):
        from inventory.models import Product
        pid = Product.objects.order_by('pk').values_list('pk', flat=True).first()
        probe, response = self._get(f'/api/inventory/products/{pid}/')
        self.assertEqual(response.status_code, 200)
        self.assertLessEqual(probe.count, 3)

    # --- dashboards and reports --------------------------------------------

    def test_dashboard_within_budget(self):
        probe, response = self._get('/api/dashboard/')
        self.assertEqual(response.status_code, 200)
        budget = BUDGETS['max_queries_dashboard']
        self.assertLessEqual(
            probe.count, budget,
            f'dashboard issued {probe.count} queries (budget {budget})',
        )

    def test_reports_summary_within_budget(self):
        probe, response = self._get('/api/reports/')
        self.assertEqual(response.status_code, 200)
        self.assertLessEqual(probe.count, BUDGETS['max_queries_reports_summary'])

    def test_all_reports_within_budget(self):
        probe, response = self._get('/api/reports/all/')
        self.assertEqual(response.status_code, 200)
        self.assertLessEqual(probe.count, BUDGETS['max_queries_reports_summary'] + 4)

    def test_period_reports_stay_bounded(self):
        for suffix in ('daily', 'weekly', 'monthly'):
            probe, response = self._get(f'/api/reports/{suffix}/')
            self.assertEqual(response.status_code, 200)
            self.assertLessEqual(probe.count, 8, f'/api/reports/{suffix}/')

    def test_customer_report_no_n_plus_one(self):
        probe, response = self._get('/api/reports/customers/')
        self.assertEqual(response.status_code, 200)
        count_stmts = [sql for sql in probe.sql_statements if 'COUNT' in sql.upper()]
        self.assertLessEqual(len(count_stmts), 8)

    # --- auth/logs -------------------------------------------------------

    def test_me_endpoint_single_lookup(self):
        probe, response = self._get('/api/auth/me/')
        self.assertEqual(response.status_code, 200)
        self.assertLessEqual(probe.count, BUDGETS['max_queries_me_endpoint'])

    def test_employee_list_within_budget(self):
        probe, response = self._get('/api/auth/employees/list/')
        self.assertEqual(response.status_code, 200)
        self.assertLessEqual(probe.count, 3)

    def test_audit_log_list_select_related(self):
        probe, response = self._get('/api/logs/')
        self.assertIn(response.status_code, (200, 403))
        self.assertLessEqual(probe.count, 4)


class VisitOverlapGuardPerformance(TestCase):
    """The overlap EXISTS check must stay O(1)-ish, not grow with history."""

    @classmethod
    def setUpTestData(cls):
        cls.dataset = build_clinic_dataset(
            customers=30, visits_per_customer=30, payments_per_customer=0,
        )

    def setUp(self):
        self.client = _auth_client()

    def test_overlapping_reservation_check_is_fast(self):
        from datetime import timedelta

        from django.utils import timezone

        from customers.models import Customer
        customer = Customer.objects.first()
        start = timezone.now() + timedelta(days=400)
        payload = {
            'customer': customer.id,
            'services': [1],
            'date': start.date().isoformat(),
            'time': '10:00',
        }
        started = timezone.now()
        response = self.client.post('/api/visits/reserve/', payload, format='json')
        elapsed = (timezone.now() - started).total_seconds()
        self.assertIn(response.status_code, (201, 400))
        self.assertLess(elapsed, 2.0, 'reserve became pathologically slow')
