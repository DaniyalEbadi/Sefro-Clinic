"""Welcome-pack cost must appear in every profit report, exactly once.

Issuing a pack writes the cost in two places -- the ``WelcomePackUsage``
snapshot and one ``ProductUsage`` row per item -- so the report layer has to
charge it once and must never drop it. These tests walk the whole chain:

    welcome-pack report <-> financial summary <-> net profit
    profit-by-service, profit-by-package, profit-by-staff
"""
from decimal import Decimal

from django.utils import timezone

from customers.models import Service
from finance.models import (
    Expense,
    ExpenseCategory,
    OperatingExpense,
    OperatingExpenseCategory,
    Package,
    PackageService,
    WelcomePack,
    WelcomePackItem,
)
from finance.services import financials, payments, reporting
from finance.services.welcome_pack import issue_welcome_pack
from tests.finance.test_clinic_financial_logic import RATE, FinancialTestBase, window

PACK_COST_USD = Decimal('2.00')  # pack item cost 1.00 x quantity 2


class WelcomePackInProfitReportsTests(FinancialTestBase):
    def setUp(self):
        super().setUp()
        self.pack = WelcomePack.objects.create(name='Report pack')
        WelcomePackItem.objects.create(
            welcome_pack=self.pack, product=self.pack_item, quantity=Decimal('2'),
        )

    def _issue(self, **kwargs):
        return issue_welcome_pack(
            welcome_pack=self.pack, customer=self.customer, quantity='1', rate=RATE, **kwargs,
        )

    def _seed_below_the_line(self):
        """One operating expense and one approved staff claim."""
        OperatingExpense.objects.create(
            category=OperatingExpenseCategory.objects.first(), title='Rent',
            amount_usd=Decimal('40'), amount_toman=Decimal('4000000'), exchange_rate=RATE,
            expense_date=timezone.localtime(timezone.now()).date(),
        )
        Expense.objects.create(
            created_by=self.staff, category=ExpenseCategory.objects.first(),
            amount_usd=Decimal('10'), amount_toman=Decimal('1000000'),
            exchange_rate_snapshot=RATE,
            expense_date=timezone.localtime(timezone.now()).date(),
            status=Expense.Status.APPROVED,
        )

    # --- the welcome-pack endpoint and the summary agree -----------------

    def test_welcome_pack_report_totals_match_the_summary_pack_cost(self):
        self._issue()
        start, end = window()

        pack_report = self.client.get('/api/finance/reports/welcome-packs/').data
        summary = reporting.financial_summary(start, end)

        self.assertGreater(summary['welcome_pack_cost']['usd'], Decimal('0'))
        self.assertEqual(pack_report['total_usage_count'], 1)
        self.assertEqual(Decimal(pack_report['total_cost_usd']), summary['welcome_pack_cost']['usd'])
        self.assertEqual(Decimal(pack_report['total_cost_toman']), summary['welcome_pack_cost']['toman'])

    def test_pack_consumption_is_charged_once_and_never_as_product_cost(self):
        self._issue()
        start, end = window()
        report = financials.build_report(start, end)

        self.assertEqual(report['product_cost']['usd'], Decimal('0.00'))
        self.assertEqual(report['welcome_pack_cost']['usd'], PACK_COST_USD)

        dashboard = self.client.get('/api/finance/reports/dashboard/').data['sales_summary']
        self.assertEqual(Decimal(dashboard['product_cost_usd']), Decimal('0'))
        self.assertEqual(Decimal(dashboard['welcome_pack_cost_usd']), PACK_COST_USD)
        self.assertEqual(Decimal(dashboard['net_profit_usd']), report['net_profit']['usd'])

    # --- gross and net profit --------------------------------------------

    def test_pack_cost_is_deducted_inside_net_profit(self):
        visit = self.make_visit(self.doctor_service)
        self.pay(visit, Decimal('500'))
        self.complete(visit)
        self._issue()
        self._seed_below_the_line()

        report = financials.build_report(*window())
        self.assertEqual(report['welcome_pack_cost']['usd'], PACK_COST_USD)

        expected_gross = (
            report['revenue']['usd'] - report['product_cost']['usd']
            - report['welcome_pack_cost']['usd']
        )
        self.assertEqual(report['gross_profit']['usd'], expected_gross)

        below_line = (
            report['staff_compensation']['total']['usd']
            + report['operating_expenses']['usd']
            + report['staff_expense_claims']['usd']
        )
        self.assertEqual(report['below_the_line_total']['usd'], below_line)
        self.assertEqual(report['net_profit']['usd'], expected_gross - below_line)

        # The pack is the only thing making net lower than the same period
        # would be without it: prove the deduction is really its cost.
        self.assertEqual(expected_gross, Decimal('398.00'))
        self.assertLess(report['net_profit']['usd'], report['gross_profit']['usd'])

    def test_issuing_two_packs_charges_both_to_net_profit(self):
        visit = self.make_visit(self.doctor_service)
        self.pay(visit, Decimal('500'))
        self.complete(visit)
        self._issue()
        issue_welcome_pack(
            welcome_pack=self.pack, customer=self.customer, quantity='1', rate=RATE,
        )

        report = financials.build_report(*window())
        self.assertEqual(report['welcome_pack_cost']['usd'], PACK_COST_USD * 2)
        self.assertEqual(report['gross_profit']['usd'], Decimal('396.00'))

    # --- profit-by-service ------------------------------------------------

    def test_profit_by_service_carries_the_pack_cost(self):
        visit = self.make_visit(self.doctor_service)
        self.pay(visit, Decimal('500'))
        self.complete(visit)
        self._issue(visit=visit)

        rows = reporting.profit_by_service(*window())
        row = next(r for r in rows if r['service_id'] == self.doctor_service.id)

        self.assertEqual(row['welcome_pack_cost_usd'], PACK_COST_USD)
        self.assertEqual(
            sum(r['welcome_pack_cost_usd'] for r in rows), PACK_COST_USD,
            'the per-service rows must add back to the visit total',
        )
        self.assertEqual(
            row['clinic_share_usd'],
            (row['revenue_usd'] - row['product_cost_usd']
             - row['operator_compensation_usd'] - row['welcome_pack_cost_usd']),
        )

    def test_profit_by_service_keeps_the_pack_cost_when_the_visit_billed_nothing(self):
        # A free service still triggers a pack issuance, and that cost is real.
        free = Service.objects.create(
            name='Free consult', price_usd=Decimal('0'), compensation_role='none',
        )
        visit = self.make_visit(free, consume=False)
        self.complete(visit)
        self._issue(visit=visit)

        report = financials.build_report(*window())
        self.assertEqual(report['welcome_pack_cost']['usd'], PACK_COST_USD)

        rows = reporting.profit_by_service(*window())
        row = next(r for r in rows if r['service_id'] == free.id)
        self.assertEqual(
            row['welcome_pack_cost_usd'], PACK_COST_USD,
            'pack cost must not vanish when the visit carries no revenue',
        )
        self.assertEqual(sum(r['welcome_pack_cost_usd'] for r in rows), PACK_COST_USD)

    # --- profit-by-package ------------------------------------------------

    def test_profit_by_package_carries_the_pack_cost(self):
        package = Package.objects.create(name='Spa day', price_usd=Decimal('500'))
        PackageService.objects.create(package=package, service=self.doctor_service)
        visit = self.make_visit(self.doctor_service, consume=False)
        self.complete(visit)
        payments.checkout(
            customer=self.customer, amount_usd=Decimal('500'), visit=visit, package=package,
            rate=RATE, components=[{'method': 'cash', 'amount_usd': Decimal('500')}],
        )
        self._issue(visit=visit)

        rows = reporting.profit_by_package(*window())
        row = next(r for r in rows if r['package_id'] == package.id)

        self.assertEqual(row['welcome_pack_cost_usd'], PACK_COST_USD)
        self.assertEqual(
            row['clinic_share_usd'],
            (row['revenue_usd'] - row['product_cost_usd']
             - row['operator_compensation_usd'] - row['welcome_pack_cost_usd']),
        )

    # --- profit-by-staff --------------------------------------------------

    def test_profit_by_staff_carries_the_pack_cost(self):
        visit = self.make_visit(self.doctor_service)
        self.pay(visit, Decimal('500'))
        self.complete(visit)
        self._issue(visit=visit)

        rows = self.client.get('/api/finance/reports/profit-by-staff/').data
        row = next(r for r in rows if r['staff_id'] == self.staff.id)

        self.assertEqual(Decimal(row['welcome_pack_cost_usd']), PACK_COST_USD)
        self.assertEqual(
            Decimal(row['welcome_pack_cost_toman']), PACK_COST_USD * RATE,
        )
