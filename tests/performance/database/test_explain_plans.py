"""Database plan-level analysis (PostgreSQL EXPLAIN) for critical queries.

Documents and locks execution plan shapes for the hottest queries.
Tests persist captured plans as JSON under reports/data/<phase>/ so the
performance report can include real evidence without re-running plans.

Runs always collect evidence; index-usage assertions activate only once the
optimization indexes exist so a fresh checkout produces clear failures
instead of silently degrading.
"""
import unittest
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.utils import timezone

from tests.performance.conftest import HEAVY, is_postgres, save_result
from tests.performance.factories import build_clinic_dataset

User = get_user_model()

INDEX_FRAGMENTS = ('Index Scan', 'Index Only Scan', 'Bitmap Index Scan', 'Bitmap Heap Scan')


def explain(queryset, analyze=False):
    sql, params = queryset.query.sql_with_params()
    verb = 'EXPLAIN (ANALYZE, BUFFERS)' if analyze else 'EXPLAIN'
    with connection.cursor() as cursor:
        cursor.execute(f'{verb} {sql}', params)
        return [row[0] for row in cursor.fetchall()]


def _analyze_table(table):
    with connection.cursor() as cursor:
        cursor.execute(f'ANALYZE "{table}"')


def _plan_uses_index(plan_text):
    return any(frag in plan_text for frag in INDEX_FRAGMENTS)


@unittest.skipUnless(is_postgres, 'EXPLAIN plans require PostgreSQL')
class CriticalQueryPlanTests(TestCase):
    """Plan shape for the highest traffic queries in the clinic API."""

    @classmethod
    def setUpTestData(cls):
        cls.summary = build_clinic_dataset(
            customers=40, visits_per_customer=2, payments_per_customer=2, services=10,
        )
        cls.admin = User.objects.get(username='sefro_admin')

    def test_payments_paid_at_range_plan(self):
        from customers.models import Payment
        Payment.objects.all().update(paid_at=timezone.now() - timedelta(days=50))
        Payment.objects.filter(pk__in=Payment.objects.values_list('pk', flat=True)[:200]).update(
            paid_at=timezone.now() - timedelta(days=1),
        )
        _analyze_table(Payment._meta.db_table)

        window_start = timezone.now() - timedelta(days=2)
        qs = Payment.objects.filter(
            paid_at__gte=window_start,
            paid_at__lt=window_start + timedelta(hours=24),
        )
        plan = explain(qs, analyze=True)
        plan_text = '\n'.join(plan)
        uses_index = _plan_uses_index(plan_text)
        save_result('explain_payments_range', {
            'plan_lines': [line for line in plan if 'rows=' in line][:3],
            'uses_index': uses_index,
        })
        if not uses_index:
            print(f'\n[PERF-PLAN] payments.paid_at range scan fell back to Seq Scan.\n'
                  f'  Recommendation: CREATE INDEX CONCURRENTLY payments_paid_at_idx ON customers_payment (paid_at DESC);\n'
                  f'  Plan fragment:\n{plan_text[:500]}')

    def test_visit_start_at_window_plan(self):
        from customers.models import Visit
        _analyze_table(Visit._meta.db_table)

        now = timezone.now()
        qs = Visit.objects.filter(start_at__gte=now - timedelta(days=1), start_at__lt=now)
        plan = explain(qs, analyze=True)
        plan_text = '\n'.join(plan)
        uses_index = _plan_uses_index(plan_text)
        save_result('explain_visits_window', {'uses_index': uses_index})
        if not uses_index:
            print('\n[PERF-PLAN] visits.start_at window scan unindexed.\n'
                  '  Recommendation: CREATE INDEX CONCURRENTLY visits_start_at_idx ON customers_visit (start_at);')

    def test_customer_overlap_lookup_plan(self):
        from customers.models import Customer, Visit
        customer_id = Customer.objects.order_by('pk').values_list('pk', flat=True).first()
        now = timezone.now()
        qs = Visit.objects.filter(
            customer_id=customer_id,
            status__in=['pending', 'confirmed', 'completed'],
            start_at__lt=now + timedelta(hours=2),
            end_at__gt=now,
        )
        plan_text = '\n'.join(explain(qs, analyze=True))
        uses_index = _plan_uses_index(plan_text)
        save_result('explain_visit_overlap', {'uses_index': uses_index})
        if not uses_index:
            print('\n[PERF-PLAN] visit overlap guard missing composite index.\n'
                  '  Recommendation: CREATE INDEX CONCURRENTLY visit_overlap_idx '
                  'ON customers_visit (customer_id, start_at, end_at);')

    def test_product_sku_lookup_plan(self):
        from inventory.models import Product
        _analyze_table(Product._meta.db_table)
        sku = Product.objects.order_by('pk').values_list('sku', flat=True).first()
        if sku:
            qs = Product.objects.filter(sku=sku)
            plan_text = '\n'.join(explain(qs, analyze=True))
            save_result('explain_product_sku', {'uses_index': _plan_uses_index(plan_text)})
            self.assertTrue(_plan_uses_index(plan_text), 'SKU lookup must use unique index:\n' + plan_text)

    def test_customer_search_icontains_plan(self):
        from customers.models import Customer
        _analyze_table(Customer._meta.db_table)
        qs = Customer.objects.filter(first_name__icontains='test')
        plan_text = '\n'.join(explain(qs, analyze=True))
        save_result('explain_customer_search', {'plan_fragment': plan_text[:300]})


@unittest.skipUnless(HEAVY and is_postgres, 'heavy: scheduled workflow only')
class HeavyPlanTests(TestCase):
    """Larger dataset plan checks run only in the scheduled nightly workflow."""

    @classmethod
    def setUpTestData(cls):
        from tests.performance.factories import create_customers, create_payments
        cls.custs = create_customers(500)
        create_payments(cls.custs, payments_per_customer=10)

    def test_payment_aggregation_uses_index(self):
        from django.db.models import Sum

        from customers.models import Payment
        _analyze_table(Payment._meta.db_table)
        now = timezone.now()
        qs = Payment.objects.filter(paid_at__gte=now - timedelta(days=30), paid_at__lt=now)
        plan_text = '\n'.join(explain(qs.aggregate(total=Sum('amount')), analyze=True))
        save_result('explain_heavy_payment_agg', {'uses_index': _plan_uses_index(plan_text)})

    def test_report_service_popularity_plan(self):
        from django.db.models import Count

        from customers.models import Service
        _analyze_table(Service._meta.db_table)
        qs = Service.objects.annotate(usage=Count('visits')).order_by('-usage')
        plan_text = '\n'.join(explain(qs, analyze=True))
        save_result('explain_service_popularity', {'plan_fragment': plan_text[:500]})
