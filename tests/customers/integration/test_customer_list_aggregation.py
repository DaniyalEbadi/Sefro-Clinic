"""Regression tests for the Customer aggregation multi-join bug.

Production symptom: a customer with 4 visits and 4 payments reported
``visit_number`` 16 and ``total_payments`` 57,036,333 instead of 4 and
14,259,083.33 — both aggregates multiplied by the row count of the join,
because ``CustomerViewSet.get_queryset`` annotated ``Count('visits')`` and
``Sum('payments__amount')`` in the *same* ``.annotate()`` call, putting both
relations in one FROM clause (4 x 4 = 16 joined rows).

The fix computes each aggregate in its own correlated subquery, so neither
relation can multiply the other and the page still costs one SQL statement.
"""
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from customers.models import Customer, Payment, Visit
from Sefro_Clinic.fields import greg_to_shamsi_date
from tests.helpers import admin_client
from tests.performance.conftest import BUDGETS, QueryProbe

# 4 payments: 1,000,000 + 2,500,000.50 + 3,000,000 + 4,500,000 = 11,000,000.50
CASE_A_AMOUNTS = [
    Decimal('1000000.00'),
    Decimal('2500000.50'),
    Decimal('3000000.00'),
    Decimal('4500000.00'),
]
CASE_A_TOTAL = sum(CASE_A_AMOUNTS)


def _customer(tag, seq):
    return Customer.objects.create(
        first_name='Aggregation',
        last_name=tag,
        mobile_number=f'091290000{seq:03d}',
        national_id=f'9000000{seq:07d}',
    )


def _visit(customer, days_ago, minutes=60):
    start = (timezone.now() - timedelta(days=days_ago)).replace(second=0, microsecond=0)
    return Visit.objects.create(
        customer=customer,
        start_at=start,
        end_at=start + timedelta(minutes=minutes),
        status=Visit.Status.COMPLETED,
    )


def _payment(customer, amount, days_ago):
    return Payment.objects.create(
        customer=customer,
        amount=amount,
        payment_method=Payment.Method.CARD,
        paid_at=timezone.now() - timedelta(days=days_ago),
    )


class CustomerAggregationRegressionTests(TestCase):
    """Cases A-D from the aggregation bug report."""

    def setUp(self):
        self.client = admin_client()

    def _row(self, customer):
        resp = self.client.get(f'/api/customers/?search={customer.mobile_number}')
        self.assertEqual(resp.status_code, 200)
        results = resp.data['results']
        self.assertEqual(len(results), 1, f'expected exactly one row for {customer.mobile_number}')
        return results[0]

    # --- Case A -----------------------------------------------------------

    def test_multiple_visits_and_payments_are_not_multiplied(self):
        customer = _customer('Multi', 1)
        for idx, amount in enumerate(CASE_A_AMOUNTS):
            _visit(customer, days_ago=40 - idx * 10)
            _payment(customer, amount, days_ago=40 - idx * 10)

        row = self._row(customer)

        self.assertEqual(row['visit_number'], 4, 'visits were multiplied by the payment join')
        self.assertEqual(Decimal(str(row['total_payments'])), CASE_A_TOTAL)
        # The historical bug produced exactly these inflated values.
        self.assertNotEqual(row['visit_number'], 16)
        self.assertNotEqual(
            Decimal(str(row['total_payments'])), CASE_A_TOTAL * 4,
            'payment sum was multiplied by the number of visits',
        )
        self.assertFalse(row['is_loyal_customer'], '4 visits must not be reported as loyal (>=5)')

    def test_customer_detail_reports_unmultiplied_aggregates(self):
        customer = _customer('Detail', 2)
        for idx, amount in enumerate(CASE_A_AMOUNTS):
            _visit(customer, days_ago=30 - idx * 5)
            _payment(customer, amount, days_ago=30 - idx * 5)

        resp = self.client.get(f'/api/customers/{customer.id}/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['visit_number'], 4)
        self.assertEqual(Decimal(str(resp.data['total_payments'])), CASE_A_TOTAL)
        self.assertFalse(resp.data['is_loyal_customer'])

    # --- Case B -----------------------------------------------------------

    def test_customer_without_payments_totals_zero(self):
        customer = _customer('Unpaid', 3)
        _visit(customer, days_ago=12)
        _visit(customer, days_ago=5)

        row = self._row(customer)

        self.assertEqual(row['visit_number'], 2)
        self.assertIsNotNone(row['total_payments'], 'null total must serialise as 0, never None')
        self.assertEqual(float(row['total_payments']), 0.0)
        self.assertFalse(row['is_new_customer'])

    def test_brand_new_customer_reports_zero_and_new_flag(self):
        customer = _customer('Fresh', 4)

        row = self._row(customer)

        self.assertEqual(row['visit_number'], 0)
        self.assertEqual(float(row['total_payments']), 0.0)
        self.assertTrue(row['is_new_customer'])
        self.assertIsNone(row['last_visit_date'])

    # --- Case C -----------------------------------------------------------

    def test_single_payment_is_counted_once(self):
        customer = _customer('Single', 5)
        for days_ago in (21, 14, 7):
            _visit(customer, days_ago=days_ago)
        _payment(customer, Decimal('800000.00'), days_ago=14)

        row = self._row(customer)

        self.assertEqual(row['visit_number'], 3)
        self.assertEqual(Decimal(str(row['total_payments'])), Decimal('800000.00'))

    def test_payment_unlinked_to_a_visit_is_still_summed_once(self):
        customer = _customer('OrphanPay', 6)
        _visit(customer, days_ago=9)
        _payment(customer, Decimal('125000.75'), days_ago=3)

        row = self._row(customer)

        self.assertEqual(row['visit_number'], 1)
        self.assertEqual(Decimal(str(row['total_payments'])), Decimal('125000.75'))

    # --- Case D -----------------------------------------------------------

    def test_referral_report_counts_returning_customers_once(self):
        counts = {'zero': 0, 'one': 1, 'two': 2, 'four': 4}
        for seq, (tag, n_visits) in enumerate(counts.items(), start=10):
            customer = _customer(tag, seq)
            for i in range(n_visits):
                _visit(customer, days_ago=60 - i)

        resp = self.client.get('/api/reports/referral/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['total_customers'], 4)
        self.assertEqual(resp.data['returning_customers'], 2, 'customers with >=2 visits miscounted')
        self.assertEqual(resp.data['referral_rate'], 50.0)

    # --- correctness of the derived fields --------------------------------

    def test_last_visit_date_is_the_most_recent_visit(self):
        customer = _customer('Recent', 7)
        for days_ago in (40, 30, 20, 10):
            _visit(customer, days_ago=days_ago)

        row = self._row(customer)

        self.assertEqual(row['visit_number'], 4)
        expected = greg_to_shamsi_date((timezone.now() - timedelta(days=10)).date())
        self.assertEqual(row['last_visit_date'], expected)

    # --- query-shape regression ------------------------------------------

    def test_customer_list_stays_within_query_budget(self):
        for seq in range(20, 30):
            customer = _customer(f'Budget{seq}', seq)
            for i in range(3):
                _visit(customer, days_ago=50 - i)
                _payment(customer, Decimal('100000.00'), days_ago=50 - i)

        with QueryProbe() as probe:
            resp = self.client.get('/api/customers/?ordering=num_visits')

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data['results']), 10)
        self.assertLessEqual(
            probe.count, BUDGETS['max_queries_customer_list'],
            f'customer list issued {probe.count} queries:\n' + '\n'.join(probe.sql_statements),
        )
        per_row_lookups = [
            sql for sql in probe.sql_statements
            if 'customers_customer' in sql and 'WHERE' in sql and 'id =' in sql
        ]
        self.assertEqual(per_row_lookups, [], 'per-row customer lookup leaked into customer list')
        # Repeated statements only matter for the tables under test; the auth
        # user lookup legitimately runs twice (JWT auth + permission check).
        dup_statements = [
            sql for sql in probe.duplicates()
            if 'customers_customer' in sql or 'customers_visit' in sql or 'customers_payment' in sql
        ]
        self.assertEqual(dup_statements, [], f'duplicate statements detected: {dup_statements[:2]}')

    def test_customer_list_orders_by_num_visits(self):
        small = _customer('SortedSmall', 30)
        big = _customer('SortedBig', 31)
        for i in range(1):
            _visit(small, days_ago=10)
        for i in range(5):
            _visit(big, days_ago=30 - i)

        resp = self.client.get('/api/customers/?ordering=-num_visits')
        self.assertEqual(resp.status_code, 200)
        ordered = [r['id'] for r in resp.data['results']]
        self.assertEqual(ordered.index(big.id), 0)
        self.assertLess(ordered.index(big.id), ordered.index(small.id))

        resp_asc = self.client.get('/api/customers/?ordering=num_visits')
        self.assertEqual(resp_asc.status_code, 200)
        ordered_asc = [r['id'] for r in resp_asc.data['results']]
        self.assertLess(ordered_asc.index(small.id), ordered_asc.index(big.id))
