"""Filter scoping and package-attribution regression tests.

Three bugs live here:

1. ``build_report`` filters used to apply only where a column happened to
   exist: ``?service=`` narrowed costs but not revenue, ``?package=`` narrowed
   revenue but not costs, ``?personnel=`` used clinic-wide product cost,
   compensation and operating expenses. Every active filter must now scope
   each component through an established attribution, or zero it.
2. ``welcome_pack_totals(product_id=...)`` ignored the product id, so the
   product-scoped path summed every pack's consumption rows.
3. ``profit_by_package`` copied each visit's payout and welcome-pack cost
   onto EVERY package sold on that visit, double-charging multi-package
   visits. Attribution now goes through ``financials.package_attribution``:
   session payouts only, unambiguous service membership, single package sale
   for packs -- exclusion over a guess.
"""
from decimal import Decimal

from django.utils import timezone

from finance.models import (
    Expense,
    ExpenseCategory,
    OperatingExpense,
    OperatingExpenseCategory,
    Package,
    PackageService,
    StaffPayout,
    WelcomePack,
    WelcomePackItem,
    WelcomePackUsage,
)
from finance.services import financials, payments, reporting
from finance.services.welcome_pack import issue_welcome_pack
from tests.finance.test_clinic_financial_logic import (
    RATE,
    FinancialTestBase,
    window,
)
from tests.helpers import make_employee

PACK_COST_USD = Decimal('2.00')


class ReportFilterScopingTests(FinancialTestBase):
    """Every filter scopes every attributable component, or zeros it."""

    def setUp(self):
        super().setUp()
        self.other_staff = make_employee(username='other_clinic_staff')

        self.visit_a = self.make_visit(self.doctor_service)  # cost 100
        self.pay(self.visit_a, Decimal('500'))
        self.complete(self.visit_a)

        self.visit_b = self.make_visit(
            self.facial_service, staff=self.other_staff,
        )  # cost 50
        self.pay(self.visit_b, Decimal('300'))
        self.complete(self.visit_b)

        OperatingExpense.objects.create(
            category=OperatingExpenseCategory.objects.first(), title='Rent',
            amount_usd=Decimal('40'), amount_toman=Decimal('4000000'),
            exchange_rate=RATE,
            expense_date=timezone.localtime(timezone.now()).date(),
        )
        Expense.objects.create(
            created_by=self.staff, category=ExpenseCategory.objects.first(),
            amount_usd=Decimal('10'), amount_toman=Decimal('1000000'),
            exchange_rate_snapshot=RATE,
            expense_date=timezone.localtime(timezone.now()).date(),
            status=Expense.Status.APPROVED,
        )

    def test_unfiltered_report_sees_the_whole_period(self):
        report = financials.build_report(*window())
        self.assertEqual(report['revenue']['usd'], Decimal('800.00'))
        self.assertEqual(report['product_cost']['usd'], Decimal('150.00'))
        self.assertEqual(report['operating_expenses']['usd'], Decimal('40.00'))
        self.assertEqual(report['staff_expense_claims']['usd'], Decimal('10.00'))
        # doctor 250 + facial 90
        self.assertEqual(report['staff_compensation']['total']['usd'], Decimal('340.00'))

    def test_personnel_filter_scopes_revenue_cost_compensation_and_claims(self):
        report = financials.build_report(*window(), personnel_id=self.staff.id)

        self.assertEqual(report['revenue']['usd'], Decimal('500.00'))
        self.assertEqual(report['product_cost']['usd'], Decimal('100.00'))
        self.assertEqual(report['staff_compensation']['total']['usd'], Decimal('250.00'))
        self.assertEqual(report['staff_expense_claims']['usd'], Decimal('10.00'))
        # Operating expenses carry no person attribution: never clinic-wide.
        self.assertEqual(report['operating_expenses']['usd'], Decimal('0.00'))
        self.assertEqual(report['counts']['appointments'], 1)

    def test_service_filter_allocates_revenue_and_scopes_costs(self):
        visit = self.make_visit(self.doctor_service, self.facial_service)
        self.pay(visit, Decimal('800'))
        self.complete(visit)

        report = financials.build_report(*window(), service_id=self.facial_service.id)

        # setUp's visit_b (facial alone, sale 300) plus this visit's list-price
        # share: 300 / (500 + 300) of the 800 sale = 300.
        self.assertEqual(report['revenue']['usd'], Decimal('600.00'))
        self.assertEqual(report['product_cost']['usd'], Decimal('100.00'))
        self.assertEqual(report['staff_compensation']['total']['usd'], Decimal('180.00'))
        self.assertEqual(report['operating_expenses']['usd'], Decimal('0.00'))
        self.assertEqual(report['staff_expense_claims']['usd'], Decimal('0.00'))
        self.assertEqual(report['counts']['appointments'], 2)

    def test_product_filter_scopes_cost_to_that_product(self):
        report = financials.build_report(*window(), product_id=self.material.id)

        # Only the doctor material, not the facial material bought in setUp.
        self.assertEqual(report['product_cost']['usd'], Decimal('100.00'))
        # Revenue follows the visits that consumed the product.
        self.assertEqual(report['revenue']['usd'], Decimal('500.00'))
        # No product attribution for compensation, claims or overhead.
        self.assertEqual(report['staff_compensation']['total']['usd'], Decimal('0.00'))
        self.assertEqual(report['operating_expenses']['usd'], Decimal('0.00'))
        self.assertEqual(report['staff_expense_claims']['usd'], Decimal('0.00'))

    def test_product_filter_scopes_purchases_to_that_product(self):
        from finance.services.inventory import record_product_purchase

        record_product_purchase(
            product=self.material, quantity=Decimal('2'), unit_cost_usd=Decimal('10'),
            supplier='Filter Supplier', rate=RATE,
        )
        record_product_purchase(
            product=self.facial_material, quantity=Decimal('3'), unit_cost_usd=Decimal('10'),
            supplier='Filter Supplier', rate=RATE,
        )

        report = financials.build_report(*window(), product_id=self.material.id)
        self.assertEqual(report['purchases']['usd'], Decimal('20.00'))

    def test_package_filter_scopes_revenue_compensation_and_zeros_overhead(self):
        package = Package.objects.create(name='Filter pack', price_usd=Decimal('500'))
        PackageService.objects.create(package=package, service=self.doctor_service)
        visit = self.make_visit(self.doctor_service)
        payments.checkout(
            customer=self.customer, amount_usd=Decimal('500'), visit=visit,
            package=package, rate=RATE,
            components=[{'method': 'cash', 'amount_usd': Decimal('500')}],
        )
        self.complete(visit)

        report = financials.build_report(*window(), package_id=package.id)

        self.assertEqual(report['revenue']['usd'], Decimal('500.00'))
        # Session payout for the doctor service, attributed via visit linkage.
        self.assertEqual(report['staff_compensation']['total']['usd'], Decimal('250.00'))
        self.assertEqual(report['operating_expenses']['usd'], Decimal('0.00'))
        self.assertEqual(report['staff_expense_claims']['usd'], Decimal('0.00'))
        self.assertEqual(report['purchases']['usd'], Decimal('0.00'))
        # Revenue outside the package (visit_b's facial sale) is gone.
        self.assertEqual(report['counts']['revenue_sales'], 1)

    def test_welcome_pack_totals_product_path_filters_by_product(self):
        pack = WelcomePack.objects.create(name='Filter welcome pack')
        WelcomePackItem.objects.create(
            welcome_pack=pack, product=self.pack_item, quantity=Decimal('2'),
        )
        issue_welcome_pack(welcome_pack=pack, customer=self.customer, quantity='1', rate=RATE)

        in_period = window()
        pack_cost = financials.welcome_pack_totals(*in_period, product_id=self.pack_item.id)
        other = financials.welcome_pack_totals(*in_period, product_id=self.material.id)

        self.assertEqual(pack_cost['usd'], PACK_COST_USD)
        self.assertEqual(pack_cost['source'], 'product_usage')
        self.assertEqual(other['usd'], Decimal('0.00'))

    def test_personnel_filter_scopes_welcome_pack_cost(self):
        pack = WelcomePack.objects.create(name='Staff welcome pack')
        WelcomePackItem.objects.create(
            welcome_pack=pack, product=self.pack_item, quantity=Decimal('2'),
        )
        issue_welcome_pack(
            welcome_pack=pack, customer=self.customer, quantity='1', rate=RATE,
            visit=self.visit_b,  # staffed by other_staff
        )

        mine = financials.build_report(*window(), personnel_id=self.staff.id)
        theirs = financials.build_report(*window(), personnel_id=self.other_staff.id)

        self.assertEqual(mine['welcome_pack_cost']['usd'], Decimal('0.00'))
        self.assertEqual(theirs['welcome_pack_cost']['usd'], PACK_COST_USD)


class PackageAttributionTests(FinancialTestBase):
    """Visit-level costs never land on every package sold on the visit."""

    def setUp(self):
        super().setUp()
        self.pack = WelcomePack.objects.create(name='Attribution pack')
        WelcomePackItem.objects.create(
            welcome_pack=self.pack, product=self.pack_item, quantity=Decimal('2'),
        )

    def _sell_package(self, package, visit, amount):
        payments.checkout(
            customer=self.customer, amount_usd=amount, visit=visit,
            package=package, rate=RATE,
            components=[{'method': 'cash', 'amount_usd': amount}],
        )

    def test_two_package_sales_on_one_visit_do_not_duplicate_costs(self):
        package_a = Package.objects.create(name='Doctor day', price_usd=Decimal('500'))
        PackageService.objects.create(package=package_a, service=self.doctor_service)
        package_b = Package.objects.create(name='Facial day', price_usd=Decimal('300'))
        PackageService.objects.create(package=package_b, service=self.facial_service)

        visit = self.make_visit(self.doctor_service, self.facial_service)
        self._sell_package(package_a, visit, Decimal('500'))
        self._sell_package(package_b, visit, Decimal('300'))
        self.complete(visit)
        WelcomePackUsage.objects.create(
            welcome_pack=self.pack, customer=self.customer, visit=visit,
            quantity=Decimal('1'),
            total_cost_usd_snapshot=PACK_COST_USD,
            exchange_rate_snapshot=RATE,
            total_cost_toman_snapshot=PACK_COST_USD * RATE,
            issued_at=timezone.now(),
        )

        rows = {row['package_id']: row for row in reporting.profit_by_package(*window())}

        # Doctor payout (250) belongs to A only; facial (90) to B only.
        self.assertEqual(rows[package_a.id]['operator_compensation_usd'], Decimal('250.00'))
        self.assertEqual(rows[package_b.id]['operator_compensation_usd'], Decimal('90.00'))
        # Pack cost has two package sales on the visit: excluded from both,
        # never copied onto each.
        self.assertEqual(rows[package_a.id]['welcome_pack_cost_usd'], Decimal('0.00'))
        self.assertEqual(rows[package_b.id]['welcome_pack_cost_usd'], Decimal('0.00'))

    def test_service_shared_by_two_packages_is_excluded_not_split(self):
        package_a = Package.objects.create(name='Shared A', price_usd=Decimal('500'))
        package_b = Package.objects.create(name='Shared B', price_usd=Decimal('500'))
        PackageService.objects.create(package=package_a, service=self.doctor_service)
        PackageService.objects.create(package=package_b, service=self.doctor_service)

        visit = self.make_visit(self.doctor_service)
        self._sell_package(package_a, visit, Decimal('500'))
        self._sell_package(package_b, visit, Decimal('500'))
        self.complete(visit)

        rows = {row['package_id']: row for row in reporting.profit_by_package(*window())}

        self.assertEqual(rows[package_a.id]['operator_compensation_usd'], Decimal('0.00'))
        self.assertEqual(rows[package_b.id]['operator_compensation_usd'], Decimal('0.00'))

    def test_monthly_salary_payout_is_never_attributed_to_a_package(self):
        package = Package.objects.create(name='Salary visit pack', price_usd=Decimal('500'))
        PackageService.objects.create(package=package, service=self.laser_service)
        visit = self.make_visit(self.laser_service, consume=False)
        self._sell_package(package, visit, Decimal('500'))
        StaffPayout.objects.create(
            staff=self.staff, visit=visit, service=self.laser_service,
            role='laser', payout_kind=StaffPayout.PayoutKind.MONTHLY_SALARY,
            salary_period=timezone.localtime(timezone.now()).date().replace(day=1),
            status=StaffPayout.Status.PENDING,
            exchange_rate=RATE,
        )

        attr = financials.package_attribution(*window())

        # Salary rows are not session candidates at all: nothing is charged
        # to the package and nothing is ambiguous.
        self.assertEqual(attr['payout_usd_by_package'], {})
        self.assertEqual(attr['excluded_payout_count'], 0)

    def test_single_package_visit_keeps_full_attribution(self):
        package = Package.objects.create(name='Solo pack', price_usd=Decimal('500'))
        PackageService.objects.create(package=package, service=self.doctor_service)
        visit = self.make_visit(self.doctor_service)
        self._sell_package(package, visit, Decimal('500'))
        self.complete(visit)
        WelcomePackUsage.objects.create(
            welcome_pack=self.pack, customer=self.customer, visit=visit,
            quantity=Decimal('1'),
            total_cost_usd_snapshot=PACK_COST_USD,
            exchange_rate_snapshot=RATE,
            total_cost_toman_snapshot=PACK_COST_USD * RATE,
            issued_at=timezone.now(),
        )

        rows = reporting.profit_by_package(*window())
        row = next(r for r in rows if r['package_id'] == package.id)

        self.assertEqual(row['operator_compensation_usd'], Decimal('250.00'))
        self.assertEqual(row['welcome_pack_cost_usd'], PACK_COST_USD)
        self.assertEqual(row['welcome_pack_cost_basis'], 'allocated_by_visit_linkage')
        self.assertEqual(
            row['operator_compensation_basis'],
            'session_payout_unambiguous_visit_linkage',
        )
