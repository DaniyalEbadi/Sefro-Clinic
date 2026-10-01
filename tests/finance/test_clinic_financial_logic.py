"""Clinic financial logic: the authoritative chain end to end.

    Revenue -> Product cost -> Welcome pack cost -> Gross Profit
            -> Staff compensation -> Operating expenses / claims -> Net Profit

Covers the clinic's stated terms:
  doctor 50% of her own service profit, facial operator 30% of hers,
  laser operator 26,000,000 Toman/month (18M base + 8M transport, never per visit).
"""
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from customers.models import Service, Visit
from finance.models import (
    Expense,
    ExpenseCategory,
    OperatingExpense,
    OperatingExpenseCategory,
    ProductUsage,
    StaffCompensationRule,
    StaffPayout,
    WelcomePack,
    WelcomePackItem,
)
from finance.services import accounting, financials, payments, staff_compensation
from finance.services.exchange_rates import set_rate
from inventory.models import Product
from tests.helpers import admin_client, make_customer, make_employee

RATE = Decimal('100000')
LASER_BASE_TOMAN = Decimal('18000000')
LASER_TRANSPORT_TOMAN = Decimal('8000000')


def window():
    return timezone.now() - timedelta(days=2), timezone.now() + timedelta(days=2)


def make_pack_usage(*, welcome_pack, customer, cost_usd=Decimal('2.00')):
    from finance.models import WelcomePackUsage

    return WelcomePackUsage.objects.create(
        welcome_pack=welcome_pack,
        customer=customer,
        quantity=Decimal('1'),
        total_cost_usd_snapshot=cost_usd,
        exchange_rate_snapshot=RATE,
        total_cost_toman_snapshot=cost_usd * RATE,
        issued_at=timezone.now(),
    )


class FinancialTestBase(TestCase):
    def setUp(self):
        set_rate('USD', 'TOMAN', RATE, effective_at=timezone.now(), source='clinic-financial-test')
        self.client = admin_client()
        self.customer = make_customer()

        self.material = Product.objects.create(
            name='Doctor material', sku='CLIN-DOC-1', unit_price=Decimal('300'),
            cost_usd=Decimal('100'), count=Decimal('500'),
        )
        self.facial_material = Product.objects.create(
            name='Facial material', sku='CLIN-FAC-1', unit_price=Decimal('150'),
            cost_usd=Decimal('50'), count=Decimal('500'),
        )
        self.pack_item = Product.objects.create(
            name='Welcome pack coffee', sku='CLIN-PACK-1', unit_price=Decimal('5'),
            cost_usd=Decimal('1'), count=Decimal('500'),
        )

        # Doctor service: revenue 500, material cost 100 -> profit 400
        self.doctor_service = Service.objects.create(
            name='Doctor laser', price_usd=Decimal('500'), compensation_role='doctor',
        )
        from finance.models import ServiceItem
        ServiceItem.objects.create(service=self.doctor_service, product=self.material, quantity=Decimal('1'))
        # Facial service: revenue 300, material cost 50 -> profit 250
        self.facial_service = Service.objects.create(
            name='Facial treatment', price_usd=Decimal('300'), compensation_role='facial',
        )
        ServiceItem.objects.create(
            service=self.facial_service, product=self.facial_material, quantity=Decimal('1'),
        )
        self.laser_service = Service.objects.create(
            name='Laser session', price_usd=Decimal('80'), compensation_role='laser',
        )

        self.staff = make_employee(username='clinic_staff')

        for role, pct in (('doctor', '50.00'), ('facial', '30.00')):
            StaffCompensationRule.objects.update_or_create(role=role, defaults={
                'calculation_type': StaffCompensationRule.CalculationType.PERCENT_PROFIT,
                'percent_profit': Decimal(pct),
                'payout_type': StaffCompensationRule.PayoutType.CASH,
                'is_active': True,
            })
        StaffCompensationRule.objects.update_or_create(role='laser', defaults={
            'calculation_type': StaffCompensationRule.CalculationType.MONTHLY_SALARY,
            'fixed_amount_toman': LASER_BASE_TOMAN,
            'transport_toman': LASER_TRANSPORT_TOMAN,
            'payout_type': StaffCompensationRule.PayoutType.CASH,
            'is_active': True,
        })

    def make_visit(self, *services, staff=None, status=Visit.Status.CONFIRMED, consume=True):
        visit = Visit.objects.create(
            customer=self.customer, staff=staff if staff is not None else self.staff,
            start_at=timezone.now(), end_at=timezone.now() + timedelta(hours=1), status=status,
        )
        for service in services:
            visit.services.add(service)
        if consume:
            accounting.record_visit_consumption(visit, rate=RATE)
        return visit

    def complete(self, visit):
        visit.status = Visit.Status.COMPLETED
        visit.save(update_fields=['status'])
        return staff_compensation.generate_visit_payouts(visit)

    def pay(self, visit, amount_usd):
        """Checkout a visit. ``cash_toman`` components carry a Toman amount."""
        return payments.checkout(
            customer=self.customer, amount_usd=Decimal(amount_usd), visit=visit, rate=RATE,
            components=[{'method': 'cash_toman', 'amount_usd': Decimal(amount_usd) * RATE}],
        )


class DoctorAndFacialPayoutTests(FinancialTestBase):
    """Each role is paid a percentage of ITS OWN service profit."""

    def test_doctor_service_alone_pays_50_percent_of_its_profit(self):
        visit = self.make_visit(self.doctor_service)
        self.complete(visit)

        payout = StaffPayout.objects.get(visit=visit, service=self.doctor_service)
        self.assertEqual(payout.revenue_usd, Decimal('500.00'))
        self.assertEqual(payout.product_cost_usd, Decimal('100.00'))
        self.assertEqual(payout.profit_usd, Decimal('400.00'))
        self.assertEqual(payout.payout_cash_usd, Decimal('200.00'))

    def test_facial_service_alone_pays_30_percent_of_its_profit(self):
        visit = self.make_visit(self.facial_service)
        self.complete(visit)

        payout = StaffPayout.objects.get(visit=visit, service=self.facial_service)
        self.assertEqual(payout.revenue_usd, Decimal('300.00'))
        self.assertEqual(payout.product_cost_usd, Decimal('50.00'))
        self.assertEqual(payout.profit_usd, Decimal('250.00'))
        self.assertEqual(payout.payout_cash_usd, Decimal('75.00'))

    def test_doctor_and_facial_each_paid_on_their_own_service_profit(self):
        # One visit, both services, collected 800 (the sum of the two prices).
        visit = self.make_visit(self.doctor_service, self.facial_service)
        self.pay(visit, Decimal('800'))
        self.complete(visit)

        doctor = StaffPayout.objects.get(visit=visit, service=self.doctor_service)
        facial = StaffPayout.objects.get(visit=visit, service=self.facial_service)

        self.assertEqual(doctor.profit_usd, Decimal('400.00'))
        self.assertEqual(doctor.payout_cash_usd, Decimal('200.00'))
        self.assertEqual(facial.profit_usd, Decimal('250.00'))
        self.assertEqual(facial.payout_cash_usd, Decimal('75.00'))
        # Total 275, NOT doctor 325 / facial 195 (the whole-visit-profit bug).
        total = sum(
            (p.payout_cash_usd for p in StaffPayout.objects.filter(visit=visit)), Decimal('0'),
        )
        self.assertEqual(total, Decimal('275.00'))

    def test_two_doctor_services_are_not_paid_twice_on_the_visit_total(self):
        second = Service.objects.create(
            name='Doctor peel', price_usd=Decimal('200'), compensation_role='doctor',
        )
        visit = self.make_visit(self.doctor_service, second)
        self.complete(visit)

        payouts = list(StaffPayout.objects.filter(visit=visit).order_by('service_id'))
        self.assertEqual(len(payouts), 2)
        visit_profit = Decimal('700') - Decimal('100')
        total = sum((p.payout_cash_usd for p in payouts), Decimal('0'))
        # 50% of each service's own profit, which sums to exactly 50% of the visit.
        self.assertEqual(total, (visit_profit * Decimal('0.5')).quantize(Decimal('0.01')))
        for payout in payouts:
            expected = (payout.profit_usd * Decimal('0.5')).quantize(Decimal('0.01'))
            self.assertEqual(payout.payout_cash_usd, expected)

    def test_payouts_are_not_duplicated_when_completion_runs_again(self):
        visit = self.make_visit(self.doctor_service)
        self.complete(visit)
        self.complete(visit)
        self.assertEqual(StaffPayout.objects.filter(visit=visit).count(), 1)

    def test_approved_payout_keeps_its_settled_amount_when_recalculated(self):
        visit = self.make_visit(self.doctor_service)
        self.complete(visit)
        payout = StaffPayout.objects.get(visit=visit)
        payout.status = StaffPayout.Status.APPROVED
        payout.payout_cash_usd = Decimal('123.00')
        payout.save(update_fields=['status', 'payout_cash_usd'])

        self.complete(visit)

        payout.refresh_from_db()
        self.assertEqual(payout.status, StaffPayout.Status.APPROVED)
        self.assertEqual(payout.payout_cash_usd, Decimal('123.00'))

    def test_cost_uses_the_recorded_snapshot_not_live_product_cost(self):
        visit = self.make_visit(self.doctor_service)
        # Price the product far higher after consumption; the payout base must
        # not move because it uses the recorded snapshot.
        self.material.cost_usd = Decimal('999')
        self.material.save(update_fields=['cost_usd'])

        self.complete(visit)
        payout = StaffPayout.objects.get(visit=visit, service=self.doctor_service)
        self.assertEqual(payout.product_cost_usd, Decimal('100.00'))
        self.assertEqual(payout.profit_usd, Decimal('400.00'))


class LaserSalaryTests(FinancialTestBase):
    def test_twenty_laser_visits_in_one_month_produce_one_salary(self):
        month_start = timezone.now().replace(day=1, hour=9, minute=0, second=0, microsecond=0)
        for index in range(20):
            visit = Visit.objects.create(
                customer=self.customer, staff=self.staff, start_at=month_start + timedelta(hours=index),
                end_at=month_start + timedelta(hours=index, minutes=30), status=Visit.Status.CONFIRMED,
            )
            visit.services.add(self.laser_service)
            visit.status = Visit.Status.COMPLETED
            visit.save(update_fields=['status'])
            staff_compensation.generate_visit_payouts(visit)

        payouts = list(StaffPayout.objects.filter(role='laser'))
        self.assertEqual(len(payouts), 1, '20 visits must not create 20 salaries')
        payout = payouts[0]
        self.assertEqual(payout.payout_cash_toman, LASER_BASE_TOMAN + LASER_TRANSPORT_TOMAN)
        self.assertEqual(payout.payout_cash_toman, Decimal('26000000.00'))
        self.assertEqual(payout.salary_period, timezone.localtime(month_start).date().replace(day=1))

    def test_a_second_month_produces_one_more_salary(self):
        now = timezone.now()
        for month_offset in (0, 1):
            start = (now - timedelta(days=30 * month_offset)).replace(day=1, hour=9, minute=0, second=0, microsecond=0)
            visit = Visit.objects.create(
                customer=self.customer, staff=self.staff, start_at=start,
                end_at=start + timedelta(hours=1), status=Visit.Status.CONFIRMED,
            )
            visit.services.add(self.laser_service)
            visit.status = Visit.Status.COMPLETED
            visit.save(update_fields=['status'])
            staff_compensation.generate_visit_payouts(visit)

        payouts = list(StaffPayout.objects.filter(role='laser'))
        self.assertEqual(len(payouts), 2)
        self.assertEqual({p.salary_period for p in payouts}.__len__(), 2)
        for payout in payouts:
            self.assertEqual(payout.payout_cash_toman, Decimal('26000000.00'))

    def test_seeded_rules_match_the_clinic_terms(self):
        doctor = StaffCompensationRule.objects.get(role='doctor')
        facial = StaffCompensationRule.objects.get(role='facial')
        laser = StaffCompensationRule.objects.get(role='laser')
        self.assertEqual(doctor.calculation_type, 'percent_profit')
        self.assertEqual(doctor.percent_profit, Decimal('50.00'))
        self.assertEqual(facial.percent_profit, Decimal('30.00'))
        self.assertEqual(laser.calculation_type, 'monthly_salary')
        self.assertEqual(laser.fixed_amount_toman, LASER_BASE_TOMAN)
        self.assertEqual(laser.transport_toman, LASER_TRANSPORT_TOMAN)


class StaffAssignmentTests(FinancialTestBase):
    def test_completing_a_compensable_visit_without_staff_is_rejected(self):
        visit = self.make_visit(self.doctor_service, staff=None, consume=False)
        visit.staff = None
        visit.save(update_fields=['staff'])

        response = self.client.post(f'/api/visits/{visit.id}/complete/')
        self.assertEqual(response.status_code, 400)
        self.assertIn('staff', response.data['error'])
        self.assertEqual(StaffPayout.objects.count(), 0)

    def test_non_compensable_visit_can_complete_without_staff(self):
        plain = Service.objects.create(name='Plain service', price_usd=Decimal('10'))
        visit = self.make_visit(plain, staff=None, consume=False)
        visit.staff = None
        visit.save(update_fields=['staff'])
        response = self.client.post(f'/api/visits/{visit.id}/complete/')
        self.assertEqual(response.status_code, 200)

    def test_patch_to_completed_also_creates_payouts(self):
        visit = self.make_visit(self.doctor_service, status=Visit.Status.CONFIRMED)
        response = self.client.patch(
            f'/api/visits/{visit.id}/', {'status': 'completed'}, format='json',
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(StaffPayout.objects.filter(visit=visit).count(), 1)

    def test_patch_to_completed_without_staff_is_rejected(self):
        visit = self.make_visit(self.doctor_service, staff=None, consume=False)
        visit.staff = None
        visit.save(update_fields=['staff'])
        response = self.client.patch(
            f'/api/visits/{visit.id}/', {'status': 'completed'}, format='json',
        )
        self.assertEqual(response.status_code, 400)
        visit.refresh_from_db()
        self.assertNotEqual(visit.status, Visit.Status.COMPLETED)
        self.assertEqual(StaffPayout.objects.count(), 0)


class RefundAndCancellationTests(FinancialTestBase):
    def test_refunding_a_sale_voids_the_staff_payout(self):
        visit = self.make_visit(self.doctor_service)
        sale = self.pay(visit, Decimal('500'))
        self.complete(visit)
        self.assertEqual(StaffPayout.objects.filter(visit=visit, status=StaffPayout.Status.PENDING).count(), 1)

        payments.refund_sale(sale, reason='customer cancelled')

        payout = StaffPayout.objects.get(visit=visit)
        self.assertEqual(payout.status, StaffPayout.Status.CANCELLED)
        start, end = window()
        report = financials.build_report(start, end)
        self.assertEqual(report['staff_compensation']['total']['usd'], Decimal('0.00'))

    def test_cancelling_a_visit_voids_the_staff_payout(self):
        visit = self.make_visit(self.doctor_service)
        self.complete(visit)
        response = self.client.post(f'/api/visits/{visit.id}/cancel/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            StaffPayout.objects.get(visit=visit).status, StaffPayout.Status.CANCELLED,
        )

    def test_cancelling_twice_does_not_create_duplicate_reversals(self):
        visit = self.make_visit(self.doctor_service)
        self.complete(visit)
        self.client.post(f'/api/visits/{visit.id}/cancel/')
        self.client.post(f'/api/visits/{visit.id}/cancel/')
        # Voiding is idempotent: one row, still cancelled, no second reversal.
        payouts = StaffPayout.objects.filter(visit=visit)
        self.assertEqual(payouts.count(), 1)
        self.assertEqual(payouts.get().status, StaffPayout.Status.CANCELLED)

    def test_refund_nets_the_payment_method_breakdown(self):
        visit = self.make_visit(self.doctor_service)
        sale = self.pay(visit, Decimal('500'))
        payments.refund_sale(sale, reason='full refund')
        start, end = window()
        report = financials.build_report(start, end)
        self.assertEqual(report['revenue']['usd'], Decimal('0.00'))
        # Cash tile must net down with revenue instead of still showing the sale.
        self.assertEqual(report['payment_methods']['cash'], Decimal('0.00'))


class WelcomePackFinancialTests(FinancialTestBase):
    def setUp(self):
        super().setUp()
        self.pack = WelcomePack.objects.create(name='Clinic welcome pack')
        WelcomePackItem.objects.create(welcome_pack=self.pack, product=self.pack_item, quantity=Decimal('2'))

    def test_pack_is_free_to_the_patient_but_costs_the_clinic(self):
        before = ProductUsage.objects.count()
        usage = make_pack_usage(welcome_pack=self.pack, customer=self.customer)
        self.assertEqual(usage.total_cost_usd_snapshot, Decimal('2.00'))
        self.assertEqual(ProductUsage.objects.count(), before)

    def test_stock_decreases_by_item_quantity_times_pack_quantity(self):
        WelcomePackItem.objects.filter(welcome_pack=self.pack).update(quantity=Decimal('2'))
        from finance.services.welcome_pack import issue_welcome_pack
        issue_welcome_pack(welcome_pack=self.pack, customer=self.customer, quantity='3', rate=RATE)
        self.pack_item.refresh_from_db()
        self.assertEqual(self.pack_item.count, Decimal('494'))

    def test_insufficient_stock_blocks_the_issuance(self):
        from finance.services.welcome_pack import WelcomePackError, issue_welcome_pack
        Product.objects.filter(pk=self.pack_item.pk).update(count=Decimal('1'))
        with self.assertRaises(WelcomePackError):
            issue_welcome_pack(welcome_pack=self.pack, customer=self.customer, quantity='1', rate=RATE)
        self.pack_item.refresh_from_db()
        self.assertEqual(self.pack_item.count, Decimal('1'))

    def test_duplicate_issuance_with_same_key_is_idempotent(self):
        from finance.models import WelcomePackUsage
        from finance.services.welcome_pack import issue_welcome_pack
        first = issue_welcome_pack(
            welcome_pack=self.pack, customer=self.customer, quantity='1', rate=RATE,
            idempotency_key='pack-key-1',
        )
        self.pack_item.refresh_from_db()
        after_first = self.pack_item.count
        again = issue_welcome_pack(
            welcome_pack=self.pack, customer=self.customer, quantity='1', rate=RATE,
            idempotency_key='pack-key-1',
        )
        self.pack_item.refresh_from_db()
        self.assertEqual(again.pk, first.pk, 'the same key must return the original issuance')
        self.assertEqual(self.pack_item.count, after_first, 'stock must not be deducted twice')
        self.assertEqual(WelcomePackUsage.objects.count(), 1)

    def test_pack_cost_is_charged_once_in_gross_profit(self):
        from finance.services.welcome_pack import issue_welcome_pack
        visit = self.make_visit(self.doctor_service)
        self.pay(visit, Decimal('500'))
        issue_welcome_pack(welcome_pack=self.pack, customer=self.customer, quantity='1', rate=RATE)
        start, end = window()
        report = financials.build_report(start, end)
        # revenue 500, product 100, pack 2 -> gross 398
        self.assertEqual(report['welcome_pack_cost']['usd'], Decimal('2.00'))
        self.assertEqual(report['gross_profit']['usd'], Decimal('398.00'))


class GrossAndNetProfitTests(FinancialTestBase):
    def _seed_full_period(self):
        """One doctor visit: revenue 500, product 100, pack 2, laser salary, opex, claim."""
        visit = self.make_visit(self.doctor_service)
        self.pay(visit, Decimal('500'))
        self.complete(visit)

        pack = WelcomePack.objects.create(name='Net profit pack')
        WelcomePackItem.objects.create(welcome_pack=pack, product=self.pack_item, quantity=Decimal('2'))
        make_pack_usage(welcome_pack=pack, customer=self.customer, cost_usd=Decimal('2.00'))

        month_start = timezone.now().replace(day=1, hour=9, minute=0, second=0, microsecond=0)
        laser_visit = Visit.objects.create(
            customer=self.customer, staff=self.staff, start_at=month_start,
            end_at=month_start + timedelta(hours=1), status=Visit.Status.CONFIRMED,
        )
        laser_visit.services.add(self.laser_service)
        laser_visit.status = Visit.Status.COMPLETED
        laser_visit.save(update_fields=['status'])
        staff_compensation.generate_visit_payouts(laser_visit)

        category = ExpenseCategory.objects.first()
        expense = Expense.objects.create(
            created_by=self.staff, category=category, amount_usd=Decimal('30'),
            amount_toman=Decimal('3000000'), exchange_rate_snapshot=RATE,
            expense_date=timezone.localtime(timezone.now()).date(), status=Expense.Status.APPROVED,
        )
        opex_cat = OperatingExpenseCategory.objects.first()
        OperatingExpense.objects.create(
            category=opex_cat, title='Rent', amount_usd=Decimal('200'),
            amount_toman=Decimal('20000000'), exchange_rate=RATE,
            expense_date=timezone.localtime(timezone.now()).date(),
        )
        return expense

    def test_gross_profit_excludes_staff_and_overhead(self):
        self._seed_full_period()
        start, end = window()
        report = financials.build_report(start, end)
        self.assertEqual(report['revenue']['usd'], Decimal('500.00'))
        self.assertEqual(report['product_cost']['usd'], Decimal('100.00'))
        self.assertEqual(report['welcome_pack_cost']['usd'], Decimal('2.00'))
        self.assertEqual(report['gross_profit']['usd'], Decimal('398.00'))
        # Gross is not reduced by compensation/opex/claims.
        self.assertEqual(
            report['gross_profit']['usd'],
            report['revenue']['usd'] - report['product_cost']['usd'] - report['welcome_pack_cost']['usd'],
        )

    def test_net_profit_subtracts_staff_operating_and_claims(self):
        self._seed_full_period()
        start, end = window()
        report = financials.build_report(start, end)

        gross = Decimal('398.00')
        # Doctor 50% of 400 = 200, plus the laser operator's 26,000,000 Toman
        # monthly salary (260.00 USD at this test rate).
        laser_usd = ((LASER_BASE_TOMAN + LASER_TRANSPORT_TOMAN) / RATE).quantize(Decimal('0.01'))
        staff = report['staff_compensation']['total']['usd']
        opex = report['operating_expenses']['usd']
        claims = report['staff_expense_claims']['usd']

        self.assertEqual(report['staff_compensation']['by_role']['doctor']['total_usd'], Decimal('200.00'))
        self.assertEqual(report['staff_compensation']['by_role']['laser']['total_usd'], laser_usd)
        self.assertEqual(staff, Decimal('200.00') + laser_usd)
        self.assertEqual(report['operating_expenses']['usd'], Decimal('200.00'))
        self.assertEqual(report['staff_expense_claims']['usd'], Decimal('30.00'))
        self.assertEqual(report['net_profit']['usd'], gross - staff - opex - claims)

    def test_staff_cost_is_below_gross_and_inside_net(self):
        self._seed_full_period()
        start, end = window()
        report = financials.build_report(start, end)
        # Staff cost must not have been deducted from gross profit...
        self.assertEqual(report['gross_profit']['usd'], Decimal('398.00'))
        # ...but must be deducted before net profit.
        self.assertLess(
            report['net_profit']['usd'],
            report['gross_profit']['usd'] - report['operating_expenses']['usd'],
        )

    def test_dashboard_and_summary_agree_on_gross_and_net(self):
        self._seed_full_period()
        start, end = window()
        report = financials.build_report(start, end)

        summary = self.client.get('/api/finance/reports/financial-summary/').data
        dashboard = self.client.get('/api/finance/reports/dashboard/').data['sales_summary']

        self.assertEqual(Decimal(summary['gross_profit']['usd']), report['gross_profit']['usd'])
        self.assertEqual(Decimal(summary['net_profit']['usd']), report['net_profit']['usd'])
        self.assertEqual(Decimal(dashboard['gross_profit_usd']), report['gross_profit']['usd'])
        self.assertEqual(Decimal(dashboard['net_profit_usd']), report['net_profit']['usd'])

    def test_staff_compensation_and_operating_expenses_are_exposed_to_the_dashboard(self):
        self._seed_full_period()
        dashboard = self.client.get('/api/finance/reports/dashboard/').data
        self.assertIn('staff_compensation', dashboard)
        self.assertIn('operating_expenses', dashboard)
        self.assertEqual(
            Decimal(dashboard['sales_summary']['operating_expenses_usd']), Decimal('200.00'),
        )

    def test_cancelled_payout_is_excluded_from_staff_compensation_totals(self):
        self._seed_full_period()
        start, end = window()
        before = financials.build_report(start, end)
        self.assertEqual(before['staff_compensation']['by_role']['doctor']['total_usd'], Decimal('200.00'))

        StaffPayout.objects.filter(role='doctor').update(status=StaffPayout.Status.CANCELLED)

        after = financials.build_report(start, end)
        # The cancelled doctor payout drops out entirely; the laser salary stays.
        self.assertNotIn('doctor', after['staff_compensation']['by_role'])
        self.assertIn('laser', after['staff_compensation']['by_role'])
