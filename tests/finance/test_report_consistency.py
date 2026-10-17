"""The finance reports must tell one story, not several.

Every figure on a finance screen is supposed to come from
``financials.build_report``. These tests guard that promise from the outside:

* ``/reports/dashboard/`` and ``/reports/financial-summary/`` render the same
  period report, so their shared numbers cannot drift apart;
* ``net_profit_after_purchases`` is exactly ``net_profit - purchases`` for
  every period, and buying stock never moves ``net_profit`` (inventory is
  charged once, at consumption);
* the dashboard's wallet rewards and payments are read from that same report,
  not from a second query with its own definition of them;
* the per-service and per-package rows name the several "profit" figures they
  carry instead of leaving one ambiguous ``profit_usd``.
"""
from decimal import Decimal

from finance.models import Package, PackageService, Wallet, WalletTransaction
from finance.services import payments
from finance.services.inventory import record_product_purchase
from tests.finance.test_clinic_financial_logic import RATE, FinancialTestBase

DASHBOARD = '/api/finance/reports/dashboard/'
SUMMARY = '/api/finance/reports/financial-summary/'
BY_SERVICE = '/api/finance/reports/profit-by-service/'
BY_PACKAGE = '/api/finance/reports/profit-by-package/'

PACK_REWARD_USD = Decimal('10.00')
WALLET_PAID_USD = Decimal('100.00')


def usd(value):
    """API payloads are stringified and service payloads are Decimals."""
    return Decimal(str(value)).quantize(Decimal('0.01'))


class OneStoryAcrossEndpointsTests(FinancialTestBase):
    """One day of trading, read back from every endpoint that shows it."""

    def setUp(self):
        super().setUp()
        # A wallet exists and has been rewarded, so the wallet figures under
        # test are real numbers rather than two agreeing zeroes.
        self.wallet = Wallet.objects.create(customer=self.customer, balance=Decimal('300.00'))
        WalletTransaction.objects.create(
            wallet=self.wallet, transaction_type=WalletTransaction.Type.REWARD,
            amount=PACK_REWARD_USD, balance_after=Decimal('310.00'),
        )

        visit = self.make_visit(self.doctor_service)
        self.complete(visit)
        # 500 collected: 400 cash, 100 from the customer's wallet.
        payments.checkout(
            customer=self.customer, amount_usd=Decimal('500'), visit=visit, rate=RATE,
            components=[
                {'method': 'cash_toman', 'amount_usd': Decimal('400') * RATE},
                {'method': 'wallet', 'amount_usd': WALLET_PAID_USD},
            ],
        )
        # Stock bought in the same period: the cash half of the report.
        record_product_purchase(
            product=self.material, quantity=Decimal('2'), unit_cost_usd=Decimal('10'),
            supplier='Consistency Co', rate=RATE,
        )

    def _both(self, query='period=today'):
        return (
            self.client.get(f'{DASHBOARD}?{query}').data,
            self.client.get(f'{SUMMARY}?{query}').data,
        )

    def test_the_dashboard_renders_the_same_report_as_the_summary(self):
        dashboard, summary = self._both()
        tile = dashboard['sales_summary']

        for tile_key, summary_value in (
            ('revenue_usd', summary['revenue']['usd']),
            ('revenue_toman', summary['revenue']['toman']),
            ('product_cost_usd', summary['product_cost']['usd']),
            ('product_cost_toman', summary['product_cost']['toman']),
            ('welcome_pack_cost_usd', summary['welcome_pack_cost']['usd']),
            ('gross_profit_usd', summary['gross_profit']['usd']),
            ('net_profit_usd', summary['net_profit']['usd']),
            ('total_payout_usd', summary['staff_compensation']['total']['usd']),
            ('staff_compensation_usd', summary['staff_compensation']['total']['usd']),
            ('operating_expenses_usd', summary['operating_expenses']['usd']),
            ('expenses_usd', summary['staff_expense_claims']['usd']),
            ('clinic_share_usd', summary['clinic_share']['usd']),
            ('below_the_line_total_usd', summary['below_the_line_total']['usd']),
            ('avg_ticket_usd', summary['counts']['average_transaction_value']),
            ('sale_count', summary['counts']['paid_sales']),
        ):
            with self.subTest(tile_key=tile_key):
                self.assertEqual(usd(tile[tile_key]), usd(summary_value))

        self.assertEqual(
            {k: usd(v) for k, v in tile['payment_methods'].items()},
            {k: usd(v) for k, v in summary['payment_methods'].items()},
        )
        # The day really happened: this is not two endpoints agreeing on zero.
        self.assertEqual(usd(summary['revenue']['usd']), Decimal('500.00'))

    def test_the_dashboard_breakdown_adds_back_up_to_net_profit(self):
        dashboard, summary = self._both()
        breakdown = dashboard['sales_summary']['net_profit_breakdown']

        arithmetic = (
            usd(breakdown['gross_profit_usd'])
            - usd(breakdown['minus_staff_compensation_usd'])
            - usd(breakdown['minus_operating_expenses_usd'])
            - usd(breakdown['minus_staff_claims_usd'])
        )
        self.assertEqual(usd(arithmetic), usd(breakdown['net_profit_usd']))
        self.assertEqual(usd(breakdown['net_profit_usd']), usd(summary['net_profit']['usd']))

    def test_both_endpoints_show_the_same_cash_view(self):
        dashboard, summary = self._both()

        self.assertEqual(usd(summary['purchases']['usd']), Decimal('20.00'))
        self.assertEqual(usd(dashboard['purchases']['usd']), usd(summary['purchases']['usd']))
        self.assertEqual(dashboard['purchases']['count'], summary['purchases']['count'])
        self.assertEqual(
            usd(dashboard['net_profit_after_purchases']['usd']),
            usd(summary['net_profit_after_purchases']['usd']),
        )

    def test_wallet_figures_are_read_from_the_period_report(self):
        dashboard, summary = self._both()
        wallet = dashboard['wallet_summary']

        self.assertEqual(
            usd(wallet['rewards_issued_usd']), usd(summary['wallet']['rewards_issued']),
        )
        self.assertEqual(usd(wallet['rewards_issued_usd']), PACK_REWARD_USD)
        self.assertEqual(
            usd(wallet['wallet_payments_usd']), abs(usd(summary['wallet']['wallet_payments'])),
        )
        self.assertEqual(usd(wallet['wallet_payments_usd']), WALLET_PAID_USD)

    def test_net_profit_after_purchases_is_net_minus_purchases_for_every_period(self):
        for period in ('today', 'this_week', 'this_month', 'prev_month', 'this_year'):
            with self.subTest(period=period):
                summary = self.client.get(f'{SUMMARY}?period={period}').data
                self.assertEqual(
                    usd(summary['net_profit_after_purchases']['usd']),
                    usd(usd(summary['net_profit']['usd']) - usd(summary['purchases']['usd'])),
                )

    def test_buying_stock_changes_only_the_cash_view(self):
        before = self.client.get(f'{SUMMARY}?period=today').data

        record_product_purchase(
            product=self.facial_material, quantity=Decimal('1'),
            unit_cost_usd=Decimal('5'), supplier='Later Co', rate=RATE,
        )

        after = self.client.get(f'{SUMMARY}?period=today').data
        self.assertEqual(after['net_profit']['usd'], before['net_profit']['usd'])
        self.assertEqual(after['product_cost']['usd'], before['product_cost']['usd'])
        self.assertEqual(
            usd(after['purchases']['usd']), usd(before['purchases']['usd']) + Decimal('5.00'),
        )
        self.assertEqual(
            usd(after['net_profit_after_purchases']['usd']),
            usd(before['net_profit_after_purchases']['usd']) - Decimal('5.00'),
        )


class ProfitBasisLabelTests(FinancialTestBase):
    """Four numbers can be called "profit"; the reports must say which is which."""

    def test_profit_by_service_names_every_profit_it_carries(self):
        visit = self.make_visit(self.doctor_service)
        self.complete(visit)
        self.pay(visit, '500')

        row = next(
            r for r in self.client.get(BY_SERVICE).data
            if r['service_id'] == self.doctor_service.id
        )

        self.assertEqual(row['profit_basis'], 'revenue_minus_product_cost')
        # The historical key survives, meaning exactly what it always meant.
        self.assertEqual(usd(row['profit_usd']), Decimal('400.00'))  # 500 - 100
        self.assertEqual(usd(row['material_profit_usd']), usd(row['profit_usd']))
        self.assertEqual(
            usd(row['after_welcome_pack_profit_usd']),
            usd(
                usd(row['revenue_usd']) - usd(row['product_cost_usd'])
                - usd(row['welcome_pack_cost_usd'])
            ),
        )
        # The clinic keeps 150 of 500 once the doctor is paid 50%.
        self.assertEqual(usd(row['clinic_share_margin_percent']), Decimal('30.00'))

    def test_profit_by_package_carries_the_same_labels(self):
        package = Package.objects.create(name='Consistency pack', price_usd=Decimal('500'))
        PackageService.objects.create(package=package, service=self.doctor_service)
        visit = self.make_visit(self.doctor_service, consume=False)
        self.complete(visit)
        payments.checkout(
            customer=self.customer, amount_usd=Decimal('500'), visit=visit, package=package,
            rate=RATE, components=[{'method': 'cash', 'amount_usd': Decimal('500')}],
        )

        row = next(
            r for r in self.client.get(BY_PACKAGE).data if r['package_id'] == package.id
        )

        self.assertEqual(row['profit_basis'], 'revenue_minus_product_cost')
        self.assertEqual(usd(row['material_profit_usd']), usd(row['profit_usd']))
        self.assertEqual(
            usd(row['after_welcome_pack_profit_usd']),
            usd(
                usd(row['revenue_usd']) - usd(row['product_cost_usd'])
                - usd(row['welcome_pack_cost_usd'])
            ),
        )
