"""Money correctness in the finance reports (P0 #2/#3/#4, P1 #5/#6).

Covers: cash variants folded into one cash tile, pending/cancelled sales
excluded from revenue, missing product cost made observable, per-service
revenue de-duplicated per visit and labelled as list price, and per-staff
visit counts de-duplicated.
"""
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from customers.models import Customer, Service, Visit
from finance.models import (
    Expense,
    ExpenseCategory,
    PaymentComponent,
    ProductUsage,
    Sale,
    WelcomePack,
    WelcomePackItem,
    WelcomePackUsage,
)
from finance.services import reporting
from finance.services.exchange_rates import set_rate
from inventory.models import Product
from tests.helpers import admin_client, make_customer, make_employee

RATE = Decimal('100000')
SUMMARY_URL = '/api/finance/reports/financial-summary/'
DASHBOARD_URL = '/api/finance/reports/dashboard/'
PROFIT_BY_SERVICE_URL = '/api/finance/reports/profit-by-service/'
PROFIT_BY_STAFF_URL = '/api/finance/reports/profit-by-staff/'


def window():
    return timezone.now() - timedelta(days=1), timezone.now() + timedelta(days=1)


class PaymentMethodBreakdownTests(TestCase):
    """P0 #2: `cash_toman`/`cash_usd` are real cash and must be counted."""

    def setUp(self):
        set_rate('USD', 'TOMAN', RATE, effective_at=timezone.now(), source='method-test')
        self.client = admin_client()
        self.customer = make_customer()

    def _sale_with_components(self, method, amount, status=Sale.Status.PAID):
        sale = Sale.objects.create(
            customer=self.customer, amount_usd=amount, amount_toman=amount * RATE,
            status=status, exchange_rate=RATE,
        )
        PaymentComponent.objects.create(sale=sale, method=method, amount_usd=amount)
        return sale

    def test_all_cash_variants_are_folded_into_the_cash_tile(self):
        self._sale_with_components(PaymentComponent.Method.CASH, Decimal('4.28'))
        self._sale_with_components(PaymentComponent.Method.CASH_TOMAN, Decimal('111.51'))
        self._sale_with_components(PaymentComponent.Method.CASH_USD, Decimal('10.00'))
        self._sale_with_components(PaymentComponent.Method.CARD, Decimal('2.00'))

        start, end = window()
        summary = reporting.financial_summary(start, end)

        self.assertEqual(summary['payment_methods']['cash'], Decimal('125.79'))
        self.assertEqual(summary['payment_methods']['card'], Decimal('2.00'))
        self.assertEqual(summary['payment_methods']['wallet'], Decimal('0'))
        # The UI still gets its three tiles, and the split stays available.
        self.assertEqual(
            set(summary['payment_methods']),
            {'cash', 'card', 'wallet'},
        )
        self.assertEqual(summary['payment_methods_by_method']['cash_toman'], Decimal('111.51'))
        self.assertEqual(summary['payment_methods_by_method']['cash_usd'], Decimal('10.00'))

    def test_dashboard_uses_the_same_folded_breakdown(self):
        self._sale_with_components(PaymentComponent.Method.CASH_TOMAN, Decimal('111.51'))
        self._sale_with_components(PaymentComponent.Method.CASH, Decimal('4.28'))

        response = self.client.get(DASHBOARD_URL)
        self.assertEqual(response.status_code, 200)
        methods = response.data['sales_summary']['payment_methods']
        self.assertEqual(Decimal(methods['cash']), Decimal('115.79'))
        self.assertEqual(
            Decimal(response.data['sales_summary']['payment_methods_by_method']['cash_toman']),
            Decimal('111.51'),
        )

    def test_dashboard_and_summary_report_the_same_cash_total(self):
        self._sale_with_components(PaymentComponent.Method.CASH_TOMAN, Decimal('111.51'))
        start, end = window()
        summary = reporting.financial_summary(start, end)
        dashboard = self.client.get(DASHBOARD_URL).data['sales_summary']
        self.assertEqual(
            Decimal(dashboard['payment_methods']['cash']),
            summary['payment_methods']['cash'],
        )


class RevenueStatusTests(TestCase):
    """P0 #3: only revenue-bearing sales count, consistently everywhere."""

    def setUp(self):
        set_rate('USD', 'TOMAN', RATE, effective_at=timezone.now(), source='revenue-test')
        self.client = admin_client()
        self.customer = make_customer()

    def _sale(self, amount, status, method=PaymentComponent.Method.CASH_TOMAN):
        sale = Sale.objects.create(
            customer=self.customer, amount_usd=amount, amount_toman=amount * RATE,
            status=status, exchange_rate=RATE,
        )
        PaymentComponent.objects.create(sale=sale, method=method, amount_usd=amount)
        return sale

    def test_pending_and_cancelled_sales_are_excluded_from_revenue(self):
        self._sale(Decimal('100'), Sale.Status.PAID)
        self._sale(Decimal('500'), Sale.Status.PENDING)
        self._sale(Decimal('700'), Sale.Status.CANCELLED)

        start, end = window()
        summary = reporting.financial_summary(start, end)

        self.assertEqual(summary['revenue']['usd'], Decimal('100.00'))
        self.assertEqual(summary['payment_methods']['cash'], Decimal('100.00'))
        self.assertEqual(summary['counts']['paid_sales'], 1)

    def test_refunded_sales_keep_their_negative_effect(self):
        self._sale(Decimal('100'), Sale.Status.PAID)
        self._sale(Decimal('-40'), Sale.Status.REFUNDED)

        start, end = window()
        summary = reporting.financial_summary(start, end)

        self.assertEqual(summary['revenue']['usd'], Decimal('60.00'))
        self.assertEqual(summary['wallet']['refunds'], Decimal('40.00'))

    def test_average_ticket_uses_the_same_revenue_bearing_set(self):
        self._sale(Decimal('100'), Sale.Status.PAID)
        self._sale(Decimal('300'), Sale.Status.PAID)
        self._sale(Decimal('9000'), Sale.Status.PENDING)

        start, end = window()
        summary = reporting.financial_summary(start, end)

        # (100 + 300) / 2 revenue-bearing sales, not 12400 / 2.
        self.assertEqual(summary['counts']['average_transaction_value'], Decimal('200.00'))
        self.assertEqual(summary['revenue_basis'], 'sale_ledger')

    def test_dashboard_excludes_pending_sales_too(self):
        self._sale(Decimal('100'), Sale.Status.PAID)
        self._sale(Decimal('900'), Sale.Status.PENDING)

        summary = self.client.get(DASHBOARD_URL).data['sales_summary']
        self.assertEqual(Decimal(summary['revenue_usd']), Decimal('100.00'))
        self.assertEqual(Decimal(summary['avg_ticket_usd']), Decimal('100.00'))


class CostCoverageTests(TestCase):
    """P0 #4: a product with no cost must be visible, not silently priced 0."""

    def setUp(self):
        set_rate('USD', 'TOMAN', RATE, effective_at=timezone.now(), source='cost-test')
        self.customer = make_customer()
        self.free_product = Product.objects.create(
            name='Never purchased', sku='NO-COST', unit_price=Decimal('50'),
            cost_usd=Decimal('0'), count=Decimal('5'),
        )

    def test_zero_cost_consumption_is_reported(self):
        ProductUsage.objects.create(
            product=self.free_product, quantity=Decimal('1'),
            unit_cost_usd_snapshot=Decimal('0'), total_cost_usd_snapshot=Decimal('0'),
        )
        start, end = window()
        coverage = reporting.financial_summary(start, end)['cost_coverage']
        self.assertEqual(coverage['usage_rows'], 1)
        self.assertEqual(coverage['zero_cost_rows'], 1)
        self.assertEqual(coverage['products_missing_cost'], [self.free_product.id])
        self.assertIn('overstated', coverage['warning'])

    def test_priced_consumption_reports_full_coverage(self):
        priced = Product.objects.create(
            name='Priced', sku='PRICED', unit_price=Decimal('50'),
            cost_usd=Decimal('7.25'), count=Decimal('5'),
        )
        ProductUsage.objects.create(
            product=priced, quantity=Decimal('1'),
            unit_cost_usd_snapshot=Decimal('7.25'), total_cost_usd_snapshot=Decimal('7.25'),
        )
        start, end = window()
        coverage = reporting.financial_summary(start, end)['cost_coverage']
        self.assertEqual(coverage['zero_cost_rows'], 0)
        self.assertEqual(coverage['products_missing_cost'], [])
        self.assertNotIn('warning', coverage)


class ProfitByServiceRevenueTests(TestCase):
    """P1 #5: revenue is de-duplicated per visit, and labelled as list price."""

    def setUp(self):
        set_rate('USD', 'TOMAN', RATE, effective_at=timezone.now(), source='pbs-test')
        self.client = admin_client()
        self.customer = make_customer()
        self.staff = make_employee()
        self.service = Service.objects.create(name='Two line recipe', price_usd=Decimal('100'))
        self.second = Service.objects.create(name='Second', price_usd=Decimal('50'))
        for line in range(2):
            product = Product.objects.create(
                name=f'Consumable {line}', sku=f'CONS-{line}', unit_price=Decimal('5'),
                cost_usd=Decimal('4.00'), count=Decimal('10'),
            )
            ProductUsage.objects.create(
                service=self.service, product=product, quantity=Decimal('1'),
                unit_cost_usd_snapshot=Decimal('4.00'), total_cost_usd_snapshot=Decimal('4.00'),
            )

    def _visit(self, *services, status=Visit.Status.COMPLETED):
        visit = Visit.objects.create(
            customer=self.customer, staff=self.staff, start_at=timezone.now(),
            end_at=timezone.now() + timedelta(hours=1), status=status,
        )
        for service in services:
            visit.services.add(service)
        return visit

    def test_service_price_is_counted_once_per_visit_not_once_per_consumable(self):
        self._visit(self.service)
        start, end = window()
        rows = reporting.profit_by_service(start, end)
        row = next(r for r in rows if r['service_id'] == self.service.id)
        # Two consumable lines used to book 2 x 100.
        self.assertEqual(row['revenue_usd'], Decimal('100.00'))
        self.assertEqual(row['count'], 1)
        self.assertEqual(row['product_cost_usd'], Decimal('8.00'))
        self.assertEqual(row['profit_usd'], Decimal('92.00'))

    def test_each_visit_adds_one_more_service_price(self):
        self._visit(self.service)
        self._visit(self.service)
        start, end = window()
        row = next(
            r for r in reporting.profit_by_service(start, end) if r['service_id'] == self.service.id
        )
        self.assertEqual(row['revenue_usd'], Decimal('200.00'))
        self.assertEqual(row['count'], 2)

    def test_service_without_any_consumable_recipe_still_appears(self):
        self._visit(self.second)
        start, end = window()
        row = next(
            r for r in reporting.profit_by_service(start, end) if r['service_id'] == self.second.id
        )
        self.assertEqual(row['revenue_usd'], Decimal('50.00'))
        self.assertEqual(row['product_cost_usd'], Decimal('0.00'))
        self.assertEqual(row['count'], 1)

    def test_multiple_services_in_one_visit_are_each_reported(self):
        self._visit(self.service, self.second)
        start, end = window()
        rows = {r['service_id']: r for r in reporting.profit_by_service(start, end)}
        self.assertEqual(rows[self.service.id]['revenue_usd'], Decimal('100.00'))
        self.assertEqual(rows[self.second.id]['revenue_usd'], Decimal('50.00'))

    def test_not_completed_visits_are_not_counted(self):
        self._visit(self.service, status=Visit.Status.CANCELED)
        start, end = window()
        self.assertEqual(reporting.profit_by_service(start, end), [])

    def test_response_labels_revenue_as_list_price(self):
        self._visit(self.service)
        response = self.client.get(PROFIT_BY_SERVICE_URL)
        self.assertEqual(response.status_code, 200)
        row = next(r for r in response.data if r['service_id'] == self.service.id)
        self.assertEqual(row['revenue_basis'], 'list_price')
        self.assertEqual(row['welcome_pack_cost_basis'], 'excluded')
        # Backward compatible keys are all still present.
        for key in ('service_id', 'service_name', 'revenue_usd', 'product_cost_usd', 'count', 'profit_usd'):
            self.assertIn(key, row)


class ProfitByStaffTests(TestCase):
    """P1 #6: visit_count counts visits; list-price revenue is labelled."""

    def setUp(self):
        set_rate('USD', 'TOMAN', RATE, effective_at=timezone.now(), source='pbs-test')
        self.client = admin_client()
        self.staff = make_employee()
        self.customer = make_customer()
        self.service = Service.objects.create(name='Multi', price_usd=Decimal('100'))
        self.other = Service.objects.create(name='Other', price_usd=Decimal('25'))

    def _visit(self, staff, *services, status=Visit.Status.COMPLETED):
        visit = Visit.objects.create(
            customer=self.customer, staff=staff, start_at=timezone.now(),
            end_at=timezone.now() + timedelta(hours=1), status=status,
        )
        for service in services:
            visit.services.add(service)
        return visit

    def test_visit_with_three_services_counts_as_one_visit(self):
        third = Service.objects.create(name='Third', price_usd=Decimal('10'))
        self._visit(self.staff, self.service, self.other, third)

        response = self.client.get(PROFIT_BY_STAFF_URL)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 1)
        row = response.data[0]
        self.assertEqual(row['visit_count'], 1)
        # Revenue is still the sum over the three services.
        self.assertEqual(row['revenue_usd'], '135.00')

    def test_repeated_visits_accumulate(self):
        self._visit(self.staff, self.service, self.other)
        self._visit(self.staff, self.service, self.other)
        row = self.client.get(PROFIT_BY_STAFF_URL).data[0]
        self.assertEqual(row['visit_count'], 2)
        self.assertEqual(row['revenue_usd'], '250.00')

    def test_row_is_labelled_as_list_price(self):
        self._visit(self.staff, self.service)
        row = self.client.get(PROFIT_BY_STAFF_URL).data[0]
        self.assertEqual(row['revenue_basis'], 'list_price')
        self.assertEqual(row['welcome_pack_cost_basis'], 'excluded')

    def test_response_is_still_a_bare_list(self):
        self._visit(self.staff, self.service)
        response = self.client.get(PROFIT_BY_STAFF_URL)
        self.assertIsInstance(response.data, list)
        self.assertEqual(response.data[0]['staff_name'], 'emp_user')

    def test_unassigned_visits_are_reported_by_the_coverage_action(self):
        self._visit(self.staff, self.service)
        self._visit(None, self.service)

        # The list endpoint still only returns attributed staff.
        self.assertEqual(len(self.client.get(PROFIT_BY_STAFF_URL).data), 1)

        coverage = self.client.get(f'{PROFIT_BY_STAFF_URL}coverage/')
        self.assertEqual(coverage.status_code, 200)
        self.assertEqual(coverage.data['total_visits'], 2)
        self.assertEqual(coverage.data['visits_with_staff'], 1)
        self.assertEqual(coverage.data['unassigned_visits'], 1)

    def test_all_unassigned_visits_degrade_to_an_empty_list_without_error(self):
        self._visit(None, self.service)
        response = self.client.get(PROFIT_BY_STAFF_URL)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, [])
        self.assertEqual(
            self.client.get(f'{PROFIT_BY_STAFF_URL}coverage/').data['unassigned_visits'], 1,
        )


class WelcomePackCostVisibilityTests(TestCase):
    """P1 #7: per-service/package reports state that pack cost is excluded."""

    def setUp(self):
        set_rate('USD', 'TOMAN', RATE, effective_at=timezone.now(), source='pack-vis-test')
        self.client = admin_client()
        self.customer = make_customer()
        self.product = Product.objects.create(
            name='Pack item', sku='PACK-VIS', unit_price=Decimal('10'),
            cost_usd=Decimal('3.00'), count=Decimal('10'),
        )
        self.pack = WelcomePack.objects.create(name='Visibility pack')
        WelcomePackItem.objects.create(welcome_pack=self.pack, product=self.product, quantity=Decimal('1'))
        WelcomePackUsage.objects.create(
            welcome_pack=self.pack, customer=self.customer, quantity=Decimal('1'),
            total_cost_usd_snapshot=Decimal('3.00'), exchange_rate_snapshot=RATE,
            total_cost_toman_snapshot=Decimal('300000.00'),
        )

    def test_profit_by_package_states_pack_cost_is_excluded(self):
        response = self.client.get('/api/finance/reports/profit-by-package/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, [])

    def test_summary_still_carries_the_pack_cost(self):
        start, end = timezone.now() - timedelta(days=1), timezone.now() + timedelta(days=1)
        self.assertEqual(
            reporting.financial_summary(start, end)['welcome_pack_cost']['usd'], Decimal('3.00'),
        )

    def test_unrelated_models_are_untouched(self):
        self.assertEqual(ExpenseCategory.objects.count(), 5)
        self.assertEqual(Customer.objects.count(), 1)
        self.assertEqual(Expense.Status.DRAFT, 'draft')
