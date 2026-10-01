"""Tests for the staff compensation module.

Covers the pure calculation helpers, the payout generator, the payout
reports, and the compensation API endpoints. This feature previously had no
tests at any level.
"""
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from customers.models import Service, Visit
from finance.models import ProductUsage, ServiceItem, StaffCompensationRule, StaffCompensationRuleProduct, StaffPayout
from finance.services import staff_compensation
from finance.services.exchange_rates import set_rate
from inventory.models import Product
from tests.helpers import admin_client, employee_client, make_customer, make_employee

RATE = Decimal('100000')


def make_rule(role=StaffCompensationRule.Role.DOCTOR, **overrides):
    base = {
        'role': role,
        'payout_type': StaffCompensationRule.PayoutType.CASH,
        'calculation_type': StaffCompensationRule.CalculationType.PERCENT_PROFIT,
        'percent_profit': Decimal('50.00'),
    }
    base.update(overrides)
    # get_or_create: the clinic rules ship in a data migration, so the default
    # role already exists and each test sets the attributes it cares about.
    rule, _ = StaffCompensationRule.objects.get_or_create(role=role)
    for field, value in base.items():
        if field != 'role':
            setattr(rule, field, value)
    rule.save()
    return rule


class CompensationFixtureMixin:
    def setUp(self):
        set_rate('USD', 'TOMAN', RATE)
        self.staff = make_employee()
        self.customer = make_customer()
        self.product = Product.objects.create(
            name='Filler', sku='FIL-1', unit_price=Decimal('100'),
            cost_usd=Decimal('25.00'), count=10,
        )
        self.service = Service.objects.create(
            name='Botox', price_usd=Decimal('200'),
            compensation_role=Service.CompensationRole.DOCTOR,
        )
        ServiceItem.objects.create(service=self.service, product=self.product, quantity=Decimal('2'))
        self.visit = Visit.objects.create(
            customer=self.customer, staff=self.staff,
            start_at=timezone.now(), end_at=timezone.now() + timedelta(hours=1),
            status=Visit.Status.COMPLETED,
        )
        self.visit.services.add(self.service)


class CalculateVisitProfitTests(CompensationFixtureMixin, TestCase):
    def test_revenue_cost_and_profit(self):
        data = staff_compensation.calculate_visit_profit(self.visit)
        self.assertEqual(data['revenue_usd'], Decimal('200.00'))
        self.assertEqual(data['product_cost_usd'], Decimal('50.00'))
        self.assertEqual(data['profit_usd'], Decimal('150.00'))
        self.assertEqual(data['revenue_toman'], Decimal('20000000.00'))
        self.assertEqual(data['product_cost_toman'], Decimal('5000000.00'))
        self.assertEqual(data['profit_toman'], Decimal('15000000.00'))
        self.assertEqual(data['rate'], RATE)

    def test_visit_without_services_is_all_zero(self):
        visit = Visit.objects.create(
            customer=self.customer, staff=self.staff,
            start_at=timezone.now(), end_at=timezone.now() + timedelta(hours=1),
            status=Visit.Status.COMPLETED,
        )
        data = staff_compensation.calculate_visit_profit(visit)
        self.assertEqual(data['revenue_usd'], Decimal('0'))
        self.assertEqual(data['profit_usd'], Decimal('0'))
        self.assertEqual(data['profit_toman'], Decimal('0'))


class CalculateServicePayoutTests(CompensationFixtureMixin, TestCase):
    PROFIT_USD = Decimal('150.00')
    PROFIT_TOMAN = Decimal('15000000.00')

    def _calc(self, rule):
        return staff_compensation.calculate_service_payout(
            self.visit, self.service, rule, self.PROFIT_USD, self.PROFIT_TOMAN, RATE,
        )

    def test_percent_of_profit(self):
        result = self._calc(make_rule(percent_profit=Decimal('50.00')))
        self.assertEqual(result['payout_cash_usd'], Decimal('75.00'))
        self.assertEqual(result['payout_cash_toman'], Decimal('7500000.00'))
        self.assertEqual(result['payout_product_value_usd'], Decimal('0'))

    def test_percent_with_transport_usd(self):
        result = self._calc(make_rule(transport_usd=Decimal('5.00')))
        self.assertEqual(result['payout_cash_usd'], Decimal('80.00'))
        self.assertEqual(result['payout_cash_toman'], Decimal('8000000.00'))

    def test_percent_with_transport_toman_converts_to_usd(self):
        result = self._calc(make_rule(transport_toman=Decimal('300000.00')))
        self.assertEqual(result['payout_cash_toman'], Decimal('7800000.00'))
        self.assertEqual(result['payout_cash_usd'], Decimal('78.00'))

    def test_percent_missing_yields_zero_cash(self):
        result = self._calc(make_rule(percent_profit=None))
        self.assertEqual(result['payout_cash_usd'], Decimal('0'))
        self.assertEqual(result['payout_cash_toman'], Decimal('0'))

    def test_fixed_per_session_usd(self):
        result = self._calc(make_rule(
            calculation_type=StaffCompensationRule.CalculationType.FIXED_PER_SESSION,
            fixed_amount_usd=Decimal('40.00'),
        ))
        self.assertEqual(result['payout_cash_usd'], Decimal('40.00'))
        self.assertEqual(result['payout_cash_toman'], Decimal('4000000.00'))

    def test_fixed_per_session_toman_converts_to_usd(self):
        result = self._calc(make_rule(
            calculation_type=StaffCompensationRule.CalculationType.FIXED_PER_SESSION,
            fixed_amount_toman=Decimal('2500000.00'),
        ))
        self.assertEqual(result['payout_cash_toman'], Decimal('2500000.00'))
        self.assertEqual(result['payout_cash_usd'], Decimal('25.00'))

    def test_product_payout_values_from_cost(self):
        rule = make_rule(
            calculation_type=StaffCompensationRule.CalculationType.FIXED_PER_SESSION,
            payout_type=StaffCompensationRule.PayoutType.PRODUCT,
            product=self.product, product_qty=Decimal('2'),
        )
        result = self._calc(rule)
        self.assertEqual(result['payout_cash_usd'], Decimal('0'))
        self.assertEqual(result['payout_product'], self.product)
        self.assertEqual(result['payout_product_qty'], Decimal('2'))
        self.assertEqual(result['payout_product_value_usd'], Decimal('50.00'))
        self.assertEqual(result['payout_product_value_toman'], Decimal('5000000.00'))

    def test_hybrid_payout_combines_cash_and_product(self):
        rule = make_rule(
            payout_type=StaffCompensationRule.PayoutType.HYBRID,
            product=self.product, product_qty=Decimal('1'),
        )
        result = self._calc(rule)
        self.assertEqual(result['payout_cash_usd'], Decimal('75.00'))
        self.assertEqual(result['payout_product_value_usd'], Decimal('25.00'))

    def test_cash_payout_ignores_product(self):
        rule = make_rule(product=self.product, product_qty=Decimal('2'))
        result = self._calc(rule)
        self.assertIsNone(result['payout_product'])
        self.assertEqual(result['payout_product_value_usd'], Decimal('0'))


class GenerateVisitPayoutsTests(CompensationFixtureMixin, TestCase):
    def test_incomplete_visit_generates_nothing(self):
        Visit.objects.filter(pk=self.visit.pk).update(status=Visit.Status.PENDING)
        self.visit.refresh_from_db()
        make_rule()
        self.assertEqual(staff_compensation.generate_visit_payouts(self.visit), [])
        self.assertEqual(StaffPayout.objects.count(), 0)

    def test_visit_without_staff_is_rejected_for_a_compensable_service(self):
        # A compensable visit must not complete with no staff: that would
        # silently produce zero compensation.
        Visit.objects.filter(pk=self.visit.pk).update(staff=None)
        self.visit.refresh_from_db()
        make_rule()
        with self.assertRaises(staff_compensation.CompensationError):
            staff_compensation.generate_visit_payouts(self.visit)
        self.assertEqual(StaffPayout.objects.count(), 0)

    def test_visit_without_staff_is_skipped_when_no_service_is_compensable(self):
        Visit.objects.filter(pk=self.visit.pk).update(staff=None)
        Service.objects.filter(pk=self.service.pk).update(compensation_role=Service.CompensationRole.NONE)
        self.visit.refresh_from_db()
        make_rule()
        self.assertEqual(staff_compensation.generate_visit_payouts(self.visit), [])
        self.assertEqual(StaffPayout.objects.count(), 0)

    def test_service_without_compensation_role_is_skipped(self):
        Service.objects.filter(pk=self.service.pk).update(compensation_role=Service.CompensationRole.NONE)
        make_rule()
        self.assertEqual(staff_compensation.generate_visit_payouts(self.visit), [])
        self.assertEqual(StaffPayout.objects.count(), 0)

    def test_missing_rule_is_skipped(self):
        # The clinic rules ship in a data migration, so remove them to exercise
        # the "no applicable rule" path this test is about.
        StaffCompensationRule.objects.all().delete()
        self.assertEqual(staff_compensation.generate_visit_payouts(self.visit), [])
        self.assertEqual(StaffPayout.objects.count(), 0)

    def test_inactive_rule_is_skipped(self):
        make_rule(is_active=False)
        self.assertEqual(staff_compensation.generate_visit_payouts(self.visit), [])
        self.assertEqual(StaffPayout.objects.count(), 0)

    def test_creates_pending_cash_payout(self):
        make_rule()
        payouts = staff_compensation.generate_visit_payouts(self.visit)
        self.assertEqual(len(payouts), 1)
        payout = StaffPayout.objects.get()
        self.assertEqual(payout.staff, self.staff)
        self.assertEqual(payout.visit, self.visit)
        self.assertEqual(payout.service, self.service)
        self.assertEqual(payout.role, StaffCompensationRule.Role.DOCTOR)
        self.assertEqual(payout.status, StaffPayout.Status.PENDING)
        self.assertEqual(payout.payout_mode, StaffPayout.PayoutMode.CASH)
        self.assertEqual(payout.exchange_rate, RATE)
        self.assertEqual(payout.revenue_usd, Decimal('200.00'))
        self.assertEqual(payout.product_cost_usd, Decimal('50.00'))
        self.assertEqual(payout.profit_usd, Decimal('150.00'))
        self.assertEqual(payout.payout_cash_usd, Decimal('75.00'))
        self.assertEqual(payout.payout_cash_toman, Decimal('7500000.00'))

    def test_regenerating_updates_instead_of_duplicating(self):
        make_rule()
        staff_compensation.generate_visit_payouts(self.visit)
        StaffCompensationRule.objects.filter(role=StaffCompensationRule.Role.DOCTOR).update(
            percent_profit=Decimal('40.00'),
        )
        staff_compensation.generate_visit_payouts(self.visit)
        self.assertEqual(StaffPayout.objects.count(), 1)
        self.assertEqual(StaffPayout.objects.get().payout_cash_usd, Decimal('60.00'))

    def test_product_payout_records_commission_usage_and_stock(self):
        make_rule(
            calculation_type=StaffCompensationRule.CalculationType.FIXED_PER_SESSION,
            payout_type=StaffCompensationRule.PayoutType.PRODUCT,
            product=self.product, product_qty=Decimal('2'),
        )
        staff_compensation.generate_visit_payouts(self.visit)

        payout = StaffPayout.objects.get()
        self.assertEqual(payout.payout_mode, StaffPayout.PayoutMode.PRODUCT)
        self.assertEqual(payout.payout_product, self.product)
        self.assertEqual(payout.payout_product_qty, Decimal('2'))
        self.assertEqual(payout.payout_product_value_usd, Decimal('50.00'))

        usage = ProductUsage.objects.get()
        self.assertEqual(usage.product, self.product)
        self.assertEqual(usage.quantity, Decimal('2'))
        self.assertEqual(usage.total_cost_usd_snapshot, Decimal('50.00'))

        self.product.refresh_from_db()
        self.assertEqual(self.product.count, 8)

    def test_regenerating_does_not_duplicate_commission_usage(self):
        make_rule(
            calculation_type=StaffCompensationRule.CalculationType.FIXED_PER_SESSION,
            payout_type=StaffCompensationRule.PayoutType.PRODUCT,
            product=self.product, product_qty=Decimal('2'),
        )
        staff_compensation.generate_visit_payouts(self.visit)
        staff_compensation.generate_visit_payouts(self.visit)
        self.assertEqual(ProductUsage.objects.count(), 1)


class StaffPayoutReportTests(CompensationFixtureMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.second_service = Service.objects.create(
            name='Laser', price_usd=Decimal('100'),
            compensation_role=Service.CompensationRole.FACIAL,
        )
        self.second_visit = Visit.objects.create(
            customer=self.customer, staff=self.staff,
            start_at=timezone.now(), end_at=timezone.now() + timedelta(hours=1),
            status=Visit.Status.COMPLETED,
        )
        self.second_visit.services.add(self.second_service)
        self.cash_payout = StaffPayout.objects.create(
            staff=self.staff, visit=self.visit, service=self.service,
            role=StaffCompensationRule.Role.DOCTOR,
            payout_cash_usd=Decimal('75.00'), payout_cash_toman=Decimal('7500000.00'),
            exchange_rate=RATE,
        )
        self.product_payout = StaffPayout.objects.create(
            staff=self.staff, visit=self.second_visit, service=self.second_service,
            role=StaffCompensationRule.Role.FACIAL,
            payout_product=self.product, payout_product_qty=Decimal('1'),
            payout_product_value_usd=Decimal('25.00'),
            payout_product_value_toman=Decimal('2500000.00'),
            exchange_rate=RATE,
        )

    def test_summary_totals(self):
        result = staff_compensation.staff_payout_summary()
        self.assertEqual(result['total_cash_usd'], Decimal('75.00'))
        self.assertEqual(result['total_cash_toman'], Decimal('7500000.00'))
        self.assertEqual(result['total_product_value_usd'], Decimal('25.00'))
        self.assertEqual(result['total_payout_usd'], Decimal('100.00'))
        self.assertEqual(result['total_payout_toman'], Decimal('10000000.00'))
        self.assertEqual(result['payout_count'], 2)

    def test_summary_defaults_to_today(self):
        result = staff_compensation.staff_payout_summary()
        self.assertEqual(result['period']['start'].date(), timezone.localtime(timezone.now()).date())
        self.assertEqual(result['period']['end'].date(), timezone.localtime(timezone.now()).date())

    def test_summary_excludes_out_of_range_period(self):
        yesterday = timezone.now() - timedelta(days=1)
        result = staff_compensation.staff_payout_summary(
            timezone.make_aware(timezone.datetime.combine(yesterday.date(), timezone.datetime.min.time())),
            timezone.make_aware(timezone.datetime.combine(yesterday.date(), timezone.datetime.max.time())),
        )
        self.assertEqual(result['payout_count'], 0)
        self.assertEqual(result['total_payout_usd'], Decimal('0'))

    def test_summary_filters_by_role(self):
        result = staff_compensation.staff_payout_summary(role=StaffCompensationRule.Role.FACIAL)
        self.assertEqual(result['payout_count'], 1)
        self.assertEqual(result['total_payout_usd'], Decimal('25.00'))

    def test_summary_filters_by_staff(self):
        other = make_employee(username='emp_other')
        result = staff_compensation.staff_payout_summary(staff_id=str(other.id))
        self.assertEqual(result['payout_count'], 0)

        mine = staff_compensation.staff_payout_summary(staff_id=str(self.staff.id))
        self.assertEqual(mine['payout_count'], 2)

    def test_detail_returns_row_per_payout(self):
        rows = staff_compensation.staff_payout_detail()
        self.assertEqual(len(rows), 2)
        by_role = {row['role']: row for row in rows}
        doctor = by_role[StaffCompensationRule.Role.DOCTOR]
        self.assertEqual(doctor['payout_cash_usd'], Decimal('75.00'))
        self.assertEqual(doctor['service__name'], 'Botox')
        facial = by_role[StaffCompensationRule.Role.FACIAL]
        self.assertEqual(facial['payout_product__name'], 'Filler')
        self.assertEqual(facial['staff__username'], 'emp_user')

    def test_detail_filters_by_staff(self):
        other = make_employee(username='emp_other')
        self.assertEqual(staff_compensation.staff_payout_detail(staff_id=str(other.id)), [])
        self.assertEqual(len(staff_compensation.staff_payout_detail(staff_id=str(self.staff.id))), 2)


class StaffCompensationRuleAPITests(TestCase):
    URL = '/api/finance/staff-compensation-rules/'

    def setUp(self):
        self.admin = admin_client()
        self.employee = employee_client()

    def test_admin_can_create_and_list_rules(self):
        # Rules ship in a data migration and role is unique, so clear them to
        # exercise the create endpoint itself.
        StaffCompensationRule.objects.all().delete()
        payload = {
            'role': StaffCompensationRule.Role.DOCTOR,
            'payout_type': StaffCompensationRule.PayoutType.CASH,
            'calculation_type': StaffCompensationRule.CalculationType.PERCENT_PROFIT,
            'percent_profit': '50.00',
        }
        created = self.admin.post(self.URL, payload, format='json')
        self.assertEqual(created.status_code, 201, created.data)
        self.assertEqual(created.data['role'], StaffCompensationRule.Role.DOCTOR)

        listing = self.admin.get(self.URL)
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(listing.data['count'], 1)

    def test_admin_can_update_rule(self):
        rule = make_rule()
        response = self.admin.patch(f'{self.URL}{rule.id}/', {'percent_profit': '60.00'}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        rule.refresh_from_db()
        self.assertEqual(rule.percent_profit, Decimal('60.00'))

    def test_duplicate_role_is_rejected(self):
        make_rule()
        response = self.admin.post(self.URL, {
            'role': StaffCompensationRule.Role.DOCTOR,
            'calculation_type': StaffCompensationRule.CalculationType.PERCENT_PROFIT,
            'percent_profit': '10.00',
        }, format='json')
        self.assertEqual(response.status_code, 400)

    def test_employee_cannot_mutate_rules(self):
        response = self.employee.post(self.URL, {
            'role': StaffCompensationRule.Role.LASER,
            'calculation_type': StaffCompensationRule.CalculationType.PERCENT_PROFIT,
            'percent_profit': '10.00',
        }, format='json')
        self.assertEqual(response.status_code, 403)

    def test_anonymous_is_rejected(self):
        from rest_framework.test import APIClient
        self.assertEqual(APIClient().get(self.URL).status_code, 401)


class StaffPayoutAPITests(CompensationFixtureMixin, TestCase):
    LIST_URL = '/api/finance/staff-payouts/'

    def setUp(self):
        super().setUp()
        make_rule()
        staff_compensation.generate_visit_payouts(self.visit)
        self.client = admin_client()

    def test_list_is_paginated_and_filterable(self):
        response = self.client.get(self.LIST_URL)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 1)

        by_role = self.client.get(f'{self.LIST_URL}?role={StaffCompensationRule.Role.DOCTOR}')
        self.assertEqual(by_role.data['count'], 1)
        by_role_none = self.client.get(f'{self.LIST_URL}?role={StaffCompensationRule.Role.LASER}')
        self.assertEqual(by_role_none.data['count'], 0)

        by_staff = self.client.get(f'{self.LIST_URL}?staff={self.staff.id}')
        self.assertEqual(by_staff.data['count'], 1)
        by_visit = self.client.get(f'{self.LIST_URL}?visit={self.visit.id}')
        self.assertEqual(by_visit.data['count'], 1)
        by_status = self.client.get(f'{self.LIST_URL}?status={StaffPayout.Status.PENDING}')
        self.assertEqual(by_status.data['count'], 1)

    def test_detail_exposes_calculated_totals(self):
        payout_id = StaffPayout.objects.get().id
        response = self.client.get(f'{self.LIST_URL}{payout_id}/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['staff_name'], 'emp_user')
        self.assertEqual(response.data['service_name'], 'Botox')
        self.assertEqual(response.data['total_payout_usd'], '75.00')

    def test_summary_action(self):
        response = self.client.get(f'{self.LIST_URL}summary/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['total_payout_usd'], '75.00')
        self.assertEqual(response.data['payout_count'], 1)

    def test_summary_action_accepts_explicit_range(self):
        today = timezone.localtime(timezone.now()).date().isoformat()
        response = self.client.get(f'{self.LIST_URL}summary/?start_date={today}&end_date={today}')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['payout_count'], 1)

    def test_summary_action_out_of_range_is_empty(self):
        yesterday = (timezone.localtime(timezone.now()).date() - timedelta(days=1)).isoformat()
        response = self.client.get(f'{self.LIST_URL}summary/?start_date={yesterday}&end_date={yesterday}')
        self.assertEqual(response.data['payout_count'], 0)

    def test_detail_report_action(self):
        response = self.client.get(f'{self.LIST_URL}detail_report/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['service__name'], 'Botox')

    def test_reports_staff_payout_summary_endpoint(self):
        response = self.client.get('/api/finance/reports/staff-payout-summary/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['total_payout_usd'], '75.00')

    def test_employee_can_read_but_not_see_other_data(self):
        employee = employee_client()
        self.assertEqual(employee.get(self.LIST_URL).status_code, 200)

    def test_anonymous_is_rejected(self):
        from rest_framework.test import APIClient
        self.assertEqual(APIClient().get(self.LIST_URL).status_code, 401)


class VisitCompletionGeneratesPayoutsTests(CompensationFixtureMixin, TestCase):
    """Regression: the payout generator was never reachable from any code path.

    Completing a visit through the API must create the pending payouts for the
    services that carry a compensation role.
    """

    def setUp(self):
        super().setUp()
        self.client = admin_client()
        Visit.objects.filter(pk=self.visit.pk).update(status=Visit.Status.CONFIRMED)

    def test_completing_visit_creates_payout(self):
        make_rule()
        response = self.client.post(f'/api/visits/{self.visit.id}/complete/')
        self.assertEqual(response.status_code, 200, response.data)
        payout = StaffPayout.objects.get()
        self.assertEqual(payout.visit_id, self.visit.id)
        self.assertEqual(payout.staff, self.staff)
        self.assertEqual(payout.payout_cash_usd, Decimal('75.00'))

    def test_completing_visit_without_rule_creates_nothing(self):
        StaffCompensationRule.objects.all().delete()
        response = self.client.post(f'/api/visits/{self.visit.id}/complete/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(StaffPayout.objects.count(), 0)

    def test_completing_compensable_visit_without_staff_is_rejected(self):
        make_rule()
        Visit.objects.filter(pk=self.visit.pk).update(staff=None)
        response = self.client.post(f'/api/visits/{self.visit.id}/complete/')
        self.assertEqual(response.status_code, 400)
        self.assertIn('staff', response.data['error'])
        self.assertEqual(StaffPayout.objects.count(), 0)

    def test_recompleting_visit_does_not_duplicate_payout(self):
        make_rule()
        self.client.post(f'/api/visits/{self.visit.id}/complete/')
        self.client.post(f'/api/visits/{self.visit.id}/complete/')
        self.assertEqual(StaffPayout.objects.count(), 1)

    def test_employee_can_complete_and_get_payout(self):
        make_rule()
        Visit.objects.filter(pk=self.visit.pk).update(staff=self.staff)
        employee = employee_client(username='emp_user')
        response = employee.post(f'/api/visits/{self.visit.id}/complete/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(StaffPayout.objects.count(), 1)

    def test_completing_visit_with_monthly_salary_rule_creates_salary_payout(self):
        make_rule(
            calculation_type=StaffCompensationRule.CalculationType.MONTHLY_SALARY,
            fixed_amount_usd=Decimal('500.00'),
        )
        response = self.client.post(f'/api/visits/{self.visit.id}/complete/')
        self.assertEqual(response.status_code, 200, response.data)
        payout = StaffPayout.objects.get()
        self.assertEqual(payout.payout_kind, StaffPayout.PayoutKind.MONTHLY_SALARY)
        self.assertEqual(payout.payout_cash_usd, Decimal('500.00'))


class MonthlySalaryPayoutTests(CompensationFixtureMixin, TestCase):
    SALARY_USD = Decimal('500.00')

    def _make_salary_rule(self, **overrides):
        overrides.setdefault('calculation_type', StaffCompensationRule.CalculationType.MONTHLY_SALARY)
        overrides.setdefault('fixed_amount_usd', self.SALARY_USD)
        return make_rule(**overrides)

    def _make_visit(self, at=None):
        start = at or timezone.now()
        visit = Visit.objects.create(
            customer=self.customer, staff=self.staff,
            start_at=start, end_at=start + timedelta(hours=1),
            status=Visit.Status.COMPLETED,
        )
        visit.services.add(self.service)
        return visit

    def test_salary_amount_is_paid(self):
        self._make_salary_rule()
        payouts = staff_compensation.generate_visit_payouts(self.visit)
        self.assertEqual(len(payouts), 1)
        payout = StaffPayout.objects.get()
        self.assertEqual(payout.payout_cash_usd, Decimal('500.00'))
        self.assertEqual(payout.payout_cash_toman, Decimal('50000000.00'))
        self.assertEqual(payout.payout_kind, StaffPayout.PayoutKind.MONTHLY_SALARY)
        self.assertEqual(payout.salary_period, timezone.localtime(self.visit.start_at).date().replace(day=1))
        self.assertEqual(payout.revenue_usd, Decimal('0'))
        self.assertEqual(payout.profit_usd, Decimal('0'))
        self.assertEqual(payout.status, StaffPayout.Status.PENDING)

    def test_only_one_salary_row_per_month(self):
        self._make_salary_rule()
        first = staff_compensation.generate_visit_payouts(self.visit)
        second = self._make_visit()
        repeated = staff_compensation.generate_visit_payouts(second)
        self.assertEqual(StaffPayout.objects.count(), 1)
        self.assertEqual(repeated[0].pk, first[0].pk)

    def test_recompleting_same_visit_does_not_duplicate_salary_row(self):
        self._make_salary_rule()
        staff_compensation.generate_visit_payouts(self.visit)
        staff_compensation.generate_visit_payouts(self.visit)
        self.assertEqual(StaffPayout.objects.count(), 1)

    def test_next_month_creates_a_new_salary_row(self):
        self._make_salary_rule()
        staff_compensation.generate_visit_payouts(self.visit)
        next_month_visit = self._make_visit(at=timezone.now() + timedelta(days=40))
        payouts = staff_compensation.generate_visit_payouts(next_month_visit)
        self.assertEqual(len(payouts), 1)
        self.assertEqual(StaffPayout.objects.count(), 2)
        periods = set(StaffPayout.objects.values_list('salary_period', flat=True))
        self.assertEqual(len(periods), 2)

    def test_toman_amount_converts_to_usd(self):
        self._make_salary_rule(fixed_amount_usd=None, fixed_amount_toman=Decimal('2500000.00'))
        staff_compensation.generate_visit_payouts(self.visit)
        payout = StaffPayout.objects.get()
        self.assertEqual(payout.payout_cash_toman, Decimal('2500000.00'))
        self.assertEqual(payout.payout_cash_usd, Decimal('25.00'))

    def test_pending_row_tracks_rule_amount_change(self):
        self._make_salary_rule()
        staff_compensation.generate_visit_payouts(self.visit)
        StaffCompensationRule.objects.filter(role=StaffCompensationRule.Role.DOCTOR).update(
            fixed_amount_usd=Decimal('600.00'),
        )
        staff_compensation.generate_visit_payouts(self._make_visit())
        payout = StaffPayout.objects.get()
        self.assertEqual(payout.payout_cash_usd, Decimal('600.00'))
        self.assertEqual(payout.status, StaffPayout.Status.PENDING)

    def test_approved_row_is_not_reprice(self):
        self._make_salary_rule()
        staff_compensation.generate_visit_payouts(self.visit)
        StaffPayout.objects.update(status=StaffPayout.Status.PAID, payout_cash_usd=Decimal('500.00'))
        StaffCompensationRule.objects.filter(role=StaffCompensationRule.Role.DOCTOR).update(
            fixed_amount_usd=Decimal('600.00'),
        )
        staff_compensation.generate_visit_payouts(self._make_visit())
        payout = StaffPayout.objects.get()
        self.assertEqual(payout.payout_cash_usd, Decimal('500.00'))
        self.assertEqual(payout.status, StaffPayout.Status.PAID)
        self.assertEqual(StaffPayout.objects.count(), 1)

    def test_salary_with_product_pays_products_once_per_month(self):
        self._make_salary_rule(
            payout_type=StaffCompensationRule.PayoutType.PRODUCT,
            product=self.product, product_qty=Decimal('2'),
        )
        staff_compensation.generate_visit_payouts(self.visit)
        staff_compensation.generate_visit_payouts(self._make_visit())

        payout = StaffPayout.objects.get()
        self.assertEqual(payout.payout_cash_usd, Decimal('500.00'))
        self.assertEqual(payout.payout_product_value_usd, Decimal('50.00'))
        self.assertEqual(ProductUsage.objects.filter(is_commission=True).count(), 1)
        self.product.refresh_from_db()
        self.assertEqual(self.product.count, 8)


class MultiProductPayoutTests(CompensationFixtureMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.other_product = Product.objects.create(
            name='Botox', sku='BTX-1', unit_price=Decimal('50'),
            cost_usd=Decimal('10.00'), count=5,
        )

    def _multi_product_rule(self, **overrides):
        rule = make_rule(
            payout_type=StaffCompensationRule.PayoutType.HYBRID,
            **overrides,
        )
        StaffCompensationRuleProduct.objects.create(rule=rule, product=self.product, quantity=Decimal('2'))
        StaffCompensationRuleProduct.objects.create(rule=rule, product=self.other_product, quantity=Decimal('3'))
        return rule

    def test_payout_covers_every_product_line(self):
        self._multi_product_rule()
        staff_compensation.generate_visit_payouts(self.visit)

        payout = StaffPayout.objects.get()
        self.assertEqual(payout.payout_cash_usd, Decimal('75.00'))
        self.assertEqual(payout.payout_product_value_usd, Decimal('80.00'))
        self.assertEqual(payout.payout_product_value_toman, Decimal('8000000.00'))
        lines = list(payout.product_lines.all())
        self.assertEqual(len(lines), 2)
        self.assertEqual(
            {(line.product_id, line.quantity) for line in lines},
            {(self.product.pk, Decimal('2')), (self.other_product.pk, Decimal('3'))},
        )

    def test_stock_is_decremented_per_line(self):
        self._multi_product_rule()
        staff_compensation.generate_visit_payouts(self.visit)

        usages = ProductUsage.objects.filter(is_commission=True)
        self.assertEqual(usages.count(), 2)
        self.product.refresh_from_db()
        self.other_product.refresh_from_db()
        self.assertEqual(self.product.count, 8)
        self.assertEqual(self.other_product.count, 2)

    def test_regenerating_does_not_duplicate_lines_or_usage(self):
        self._multi_product_rule()
        staff_compensation.generate_visit_payouts(self.visit)
        staff_compensation.generate_visit_payouts(self.visit)

        payout = StaffPayout.objects.get()
        self.assertEqual(payout.product_lines.count(), 2)
        self.assertEqual(ProductUsage.objects.filter(is_commission=True).count(), 2)

    def test_detail_report_includes_product_lines(self):
        self._multi_product_rule()
        staff_compensation.generate_visit_payouts(self.visit)
        rows = staff_compensation.staff_payout_detail()
        self.assertEqual(len(rows), 1)
        lines = rows[0]['payout_products']
        self.assertEqual(len(lines), 2)
        self.assertEqual({line['product_name'] for line in lines}, {'Filler', 'Botox'})


class StaffCompensationRuleProductsAPITests(CompensationFixtureMixin, TestCase):
    URL = '/api/finance/staff-compensation-rules/'

    def setUp(self):
        super().setUp()
        # role is unique and the clinic rules ship in a data migration; clear
        # them so the create endpoint is exercised on a clean table.
        StaffCompensationRule.objects.all().delete()
        self.admin = admin_client()
        self.product_a = Product.objects.create(
            name='Filler', sku='FIL-2', unit_price=Decimal('100'),
            cost_usd=Decimal('25.00'), count=10,
        )
        self.product_b = Product.objects.create(
            name='Botox', sku='BTX-2', unit_price=Decimal('50'),
            cost_usd=Decimal('10.00'), count=10,
        )

    def _payload(self, **extra):
        payload = {
            'role': StaffCompensationRule.Role.DOCTOR,
            'payout_type': StaffCompensationRule.PayoutType.HYBRID,
            'calculation_type': StaffCompensationRule.CalculationType.FIXED_PER_SESSION,
            'fixed_amount_usd': '40.00',
        }
        payload.update(extra)
        return payload

    def test_create_with_product_objects(self):
        response = self.admin.post(self.URL, self._payload(products=[
            {'product': self.product_a.id, 'quantity': '2'},
            {'product': self.product_b.id, 'quantity': '3'},
        ]), format='json')
        self.assertEqual(response.status_code, 201, response.data)
        rule = StaffCompensationRule.objects.get()
        self.assertEqual(rule.product_lines.count(), 2)
        self.assertEqual(rule.product_id, self.product_a.id)
        self.assertEqual(rule.product_qty, Decimal('2'))
        self.assertEqual(len(response.data['products']), 2)
        self.assertEqual(response.data['products'][0]['product_name'], 'Filler')

    def test_create_with_bare_product_ids(self):
        response = self.admin.post(self.URL, self._payload(products=[
            self.product_a.id, self.product_b.id,
        ]), format='json')
        self.assertEqual(response.status_code, 201, response.data)
        rule = StaffCompensationRule.objects.get()
        self.assertEqual(rule.product_lines.count(), 2)
        self.assertEqual(
            list(rule.product_lines.values_list('quantity', flat=True)),
            [Decimal('1'), Decimal('1')],
        )

    def test_create_with_legacy_product_fields(self):
        response = self.admin.post(self.URL, self._payload(
            product=self.product_a.id, product_qty='3',
        ), format='json')
        self.assertEqual(response.status_code, 201, response.data)
        rule = StaffCompensationRule.objects.get()
        self.assertEqual(rule.product_lines.count(), 1)
        self.assertEqual(rule.product_lines.get().quantity, Decimal('3'))
        self.assertEqual(len(response.data['products']), 1)

    def test_update_replaces_product_lines(self):
        created = self.admin.post(self.URL, self._payload(products=[
            {'product': self.product_a.id, 'quantity': '2'},
            {'product': self.product_b.id, 'quantity': '3'},
        ]), format='json')
        rule_id = created.data['id']

        response = self.admin.patch(
            f'{self.URL}{rule_id}/',
            {'products': [{'product': self.product_b.id, 'quantity': '5'}]},
            format='json',
        )
        self.assertEqual(response.status_code, 200, response.data)
        rule = StaffCompensationRule.objects.get(pk=rule_id)
        self.assertEqual(rule.product_lines.count(), 1)
        self.assertEqual(rule.product_lines.get().product_id, self.product_b.id)
        self.assertEqual(rule.product_lines.get().quantity, Decimal('5'))
        self.assertEqual(rule.product_id, self.product_b.id)

    def test_duplicate_products_are_rejected(self):
        response = self.admin.post(self.URL, self._payload(products=[
            {'product': self.product_a.id, 'quantity': '1'},
            self.product_a.id,
        ]), format='json')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(StaffCompensationRule.objects.count(), 0)

    def test_zero_quantity_is_rejected(self):
        response = self.admin.post(self.URL, self._payload(products=[
            {'product': self.product_a.id, 'quantity': '0'},
        ]), format='json')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(StaffCompensationRule.objects.count(), 0)

    def test_payout_list_exposes_product_lines(self):
        StaffCompensationRuleProduct.objects.create(
            rule=make_rule(payout_type=StaffCompensationRule.PayoutType.HYBRID),
            product=self.product_a, quantity=Decimal('2'),
        )
        staff_compensation.generate_visit_payouts(self.visit)

        response = self.admin.get('/api/finance/staff-payouts/')
        self.assertEqual(response.status_code, 200)
        row = response.data['results'][0]
        self.assertEqual(len(row['payout_products']), 1)
        self.assertEqual(row['payout_products'][0]['product_name'], 'Filler')
        self.assertEqual(row['payout_kind'], StaffPayout.PayoutKind.SESSION)
