"""Regression tests for the finance reporting endpoints.

``/api/finance/reports/dashboard/`` and ``/api/finance/reports/profit-by-staff/``
used to answer 500 to *every* request, because:

* ``_resolve_range()`` returned ``(None, None)`` when neither
  ``start_date``/``end_date`` nor ``period`` was supplied, while these two views
  filter inline -> ``ValueError: Cannot use None as a query value``;
* ``Sum``, ``get_rate`` and ``PaymentComponent`` were never imported in
  ``finance/views.py`` -> ``NameError`` as soon as the range bug was past.

The default range must follow the existing service-layer convention
(``services/reporting.py::_range``, ``services/staff_compensation.py``): fall
back to *today*.
"""
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from customers.models import Service, Visit
from finance.models import PaymentComponent, ProductUsage, Sale, StaffCompensationRule, StaffPayout
from finance.services.exchange_rates import set_rate
from inventory.models import Product
from tests.helpers import admin_client, employee_client, make_customer, make_employee

RATE = Decimal('60000')
DASHBOARD_URL = '/api/finance/reports/dashboard/'
PROFIT_BY_STAFF_URL = '/api/finance/reports/profit-by-staff/'


def local_today():
    return timezone.localtime(timezone.now()).date()


def day_range(day):
    return f'?start_date={day.isoformat()}&end_date={day.isoformat()}'


class FinanceReportDefaultRangeTests(TestCase):
    """A request without date parameters must not 500; it defaults to today."""

    def setUp(self):
        self.client = admin_client()

    def test_dashboard_without_parameters_returns_200(self):
        self.assertEqual(self.client.get(DASHBOARD_URL).status_code, 200)

    def test_profit_by_staff_without_parameters_returns_200(self):
        self.assertEqual(self.client.get(PROFIT_BY_STAFF_URL).status_code, 200)

    def test_dashboard_accepts_explicit_range(self):
        response = self.client.get(DASHBOARD_URL + day_range(local_today()))
        self.assertEqual(response.status_code, 200)

    def test_dashboard_accepts_period_parameter(self):
        for period in ('today', 'this_week', 'this_month', 'prev_month', 'this_year'):
            response = self.client.get(f'{DASHBOARD_URL}?period={period}')
            self.assertEqual(response.status_code, 200, period)

    def test_dashboard_tolerates_malformed_dates(self):
        response = self.client.get(f'{DASHBOARD_URL}?start_date=not-a-date&end_date=also-bad')
        self.assertEqual(response.status_code, 200)

    def test_default_range_covers_today_only(self):
        customer = make_customer()
        staff = make_employee()
        yesterday = timezone.now() - timedelta(days=1)
        Visit.objects.create(
            customer=customer, staff=staff,
            start_at=yesterday, end_at=yesterday + timedelta(hours=1),
            status=Visit.Status.COMPLETED,
        )
        Visit.objects.create(
            customer=customer, staff=staff,
            start_at=timezone.now(), end_at=timezone.now() + timedelta(hours=1),
            status=Visit.Status.COMPLETED,
        )

        default = self.client.get(DASHBOARD_URL)
        self.assertEqual(default.data['operational']['visits_completed'], 1)

        explicit = self.client.get(DASHBOARD_URL + day_range(yesterday.date()))
        self.assertEqual(explicit.data['operational']['visits_completed'], 1)

    def test_default_range_excludes_yesterday_sales(self):
        customer = make_customer()
        Sale.objects.create(
            customer=customer,
            amount_usd=Decimal('50'), amount_toman=Decimal('3000000'),
            exchange_rate=RATE, status=Sale.Status.PAID,
            created_at=timezone.now() - timedelta(days=1),
        )

        default = self.client.get(DASHBOARD_URL)
        self.assertEqual(default.data['sales_summary']['revenue_usd'], '0')

        explicit = self.client.get(DASHBOARD_URL + day_range(local_today() - timedelta(days=1)))
        self.assertEqual(explicit.data['sales_summary']['revenue_usd'], '50.00')


class FinanceDashboardReportTests(TestCase):
    """Numbers returned by /api/finance/reports/dashboard/."""

    def setUp(self):
        self.client = admin_client()
        set_rate('USD', 'TOMAN', RATE)
        self.staff = make_employee()
        self.customer = make_customer()
        self.service = Service.objects.create(name='Hydrafacial', price_usd=Decimal('120'))
        self.visit = Visit.objects.create(
            customer=self.customer, staff=self.staff,
            start_at=timezone.now(), end_at=timezone.now() + timedelta(hours=1),
            status=Visit.Status.COMPLETED,
        )
        self.visit.services.add(self.service)

        self.product = Product.objects.create(
            name='Serum', sku='SER-1', unit_price=Decimal('10'), cost_usd=Decimal('5'),
        )
        ProductUsage.objects.create(
            product=self.product, visit=self.visit, service=self.service,
            quantity=Decimal('2'),
            unit_cost_usd_snapshot=Decimal('5'), total_cost_usd_snapshot=Decimal('10'),
            exchange_rate_snapshot=RATE,
        )

        self.sale = Sale.objects.create(
            customer=self.customer, visit=self.visit,
            amount_usd=Decimal('120'), amount_toman=Decimal('7200000'),
            exchange_rate=RATE, status=Sale.Status.PAID,
        )
        PaymentComponent.objects.create(
            sale=self.sale, method=PaymentComponent.Method.CASH, amount_usd=Decimal('70'),
        )
        PaymentComponent.objects.create(
            sale=self.sale, method=PaymentComponent.Method.CARD, amount_usd=Decimal('50'),
        )

        StaffPayout.objects.create(
            staff=self.staff, visit=self.visit, service=self.service,
            role=StaffCompensationRule.Role.DOCTOR,
            revenue_usd=Decimal('120'), revenue_toman=Decimal('7200000'),
            profit_usd=Decimal('120'), profit_toman=Decimal('7200000'),
            payout_cash_usd=Decimal('30'), payout_cash_toman=Decimal('1800000'),
            exchange_rate=RATE,
        )

    def test_totals_reflect_seeded_data(self):
        summary = self.client.get(DASHBOARD_URL).data['sales_summary']
        self.assertEqual(summary['revenue_usd'], '120.00')
        self.assertEqual(summary['revenue_toman'], '7200000.00')
        self.assertEqual(summary['gross_profit_usd'], '110.00')
        self.assertEqual(summary['gross_profit_toman'], '6600000.00')
        self.assertEqual(summary['expenses_usd'], '0')
        self.assertEqual(summary['net_profit_usd'], '110.00')
        self.assertEqual(summary['sale_count'], 1)
        self.assertEqual(summary['avg_ticket_usd'], '120.00')
        self.assertEqual(summary['total_payout_usd'], '30.00')
        self.assertEqual(summary['total_payout_toman'], '1800000.00')

    def test_operational_counters(self):
        operational = self.client.get(DASHBOARD_URL).data['operational']
        self.assertEqual(operational['visits_completed'], 1)
        self.assertEqual(operational['new_customers'], 1)
        self.assertEqual(operational['staff_payout_count'], 1)

    def test_payment_method_breakdown(self):
        methods = self.client.get(DASHBOARD_URL).data['sales_summary']['payment_methods']
        self.assertEqual(methods['cash'], '70.00')
        self.assertEqual(methods['card'], '50.00')
        self.assertEqual(methods['wallet'], '0')

    def test_product_cost_falls_back_to_current_rate(self):
        ProductUsage.objects.all().update(exchange_rate_snapshot=None)
        summary = self.client.get(DASHBOARD_URL).data['sales_summary']
        self.assertEqual(summary['gross_profit_toman'], '6600000.00')

    def test_activity_outside_range_is_excluded(self):
        Sale.objects.create(
            customer=self.customer,
            amount_usd=Decimal('999'), amount_toman=Decimal('59940000'),
            exchange_rate=RATE, status=Sale.Status.PAID,
            created_at=timezone.now() + timedelta(days=2),
        )
        summary = self.client.get(DASHBOARD_URL).data['sales_summary']
        self.assertEqual(summary['revenue_usd'], '120.00')

    def test_period_today_matches_explicit_today_range(self):
        today = local_today().isoformat()
        by_period = self.client.get(f'{DASHBOARD_URL}?period=today').data['sales_summary']
        explicit = self.client.get(f'{DASHBOARD_URL}?start_date={today}&end_date={today}').data
        self.assertEqual(by_period['revenue_usd'], explicit['sales_summary']['revenue_usd'])
        self.assertEqual(by_period['revenue_usd'], '120.00')


class ProfitByStaffReportTests(TestCase):
    """Numbers returned by /api/finance/reports/profit-by-staff/."""

    def setUp(self):
        self.client = admin_client()
        set_rate('USD', 'TOMAN', RATE)
        self.staff = make_employee()
        self.customer = make_customer()
        self.service = Service.objects.create(name='Laser', price_usd=Decimal('120'))
        self.visit = Visit.objects.create(
            customer=self.customer, staff=self.staff,
            start_at=timezone.now(), end_at=timezone.now() + timedelta(hours=1),
            status=Visit.Status.COMPLETED,
        )
        self.visit.services.add(self.service)

    def test_aggregates_completed_visits(self):
        response = self.client.get(PROFIT_BY_STAFF_URL)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 1)
        row = response.data[0]
        self.assertEqual(row['staff_name'], 'emp_user')
        self.assertEqual(row['visit_count'], 1)
        self.assertEqual(row['revenue_usd'], '120.00')
        self.assertEqual(row['revenue_toman'], '7200000.00')
        self.assertEqual(row['product_cost_usd'], '0.00')
        self.assertEqual(row['profit_usd'], '120.00')
        self.assertEqual(row['profit_toman'], '7200000.00')

    def test_non_completed_visits_are_ignored(self):
        Visit.objects.filter(pk=self.visit.pk).update(status=Visit.Status.PENDING)
        self.assertEqual(self.client.get(PROFIT_BY_STAFF_URL).data, [])

    def test_staff_without_completed_visits_are_skipped(self):
        make_employee(username='emp_idle')
        response = self.client.get(PROFIT_BY_STAFF_URL)
        self.assertEqual([row['staff_name'] for row in response.data], ['emp_user'])

    def test_groups_by_staff_member(self):
        other = make_employee(username='emp_two')
        other_visit = Visit.objects.create(
            customer=make_customer(mobile_number='09120000001', national_id='000-0000001'),
            staff=other, start_at=timezone.now(), end_at=timezone.now() + timedelta(hours=1),
            status=Visit.Status.COMPLETED,
        )
        other_visit.services.add(self.service)

        response = self.client.get(PROFIT_BY_STAFF_URL)
        self.assertEqual(len(response.data), 2)
        self.assertEqual(sorted(row['staff_name'] for row in response.data), ['emp_two', 'emp_user'])
        for row in response.data:
            self.assertEqual(row['visit_count'], 1)


class FinanceReportsAccessTests(TestCase):
    def test_anonymous_is_rejected_on_both_reports(self):
        anon = APIClient()
        for url in (DASHBOARD_URL, PROFIT_BY_STAFF_URL):
            self.assertEqual(anon.get(url).status_code, 401, url)

    def test_employee_can_read_both_reports(self):
        client = employee_client()
        for url in (DASHBOARD_URL, PROFIT_BY_STAFF_URL):
            self.assertEqual(client.get(url).status_code, 200, url)
