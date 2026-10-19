"""End-to-end money chain, driven through the real API endpoints.

The whole customer journey in one file:

    book visit -> confirm -> record consumption -> issue welcome pack
    -> checkout -> complete (payouts) -> every report must agree

Two things are proven here:

1. Role-based access on the Staff Compensation endpoints (who may read the
   payout ledger, who may set the compensation rules, who may write nothing).
2. The authoritative formula, checked with exact numbers in both currencies:

       net_profit = revenue - product cost - welcome pack cost
                    - staff compensation - operating expenses - claims

   plus cross-consistency: financial-summary, dashboard, both payout-summary
   routes, profit-by-staff, profit-by-service, coverage, the welcome-pack
   report and the Activity reports (daily / all) all tell the same story,
   and stock actually decrements when the products are consumed.
"""
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import ClinicUser
from customers.models import VisitService
from finance.models import (
    Expense,
    ExpenseCategory,
    OperatingExpense,
    OperatingExpenseCategory,
    StaffCompensationRule,
    StaffPayout,
    WelcomePack,
    WelcomePackItem,
)
from Sefro_Clinic.fields import greg_to_shamsi_dt
from tests.finance.test_clinic_financial_logic import RATE, FinancialTestBase
from tests.helpers import admin_client, employee_client, make_employee

D = Decimal

RULE_DEFAULTS = {
    'calculation_type': StaffCompensationRule.CalculationType.PERCENT_REVENUE,
    'percent_revenue': D('50.00'),
    'payout_type': StaffCompensationRule.PayoutType.CASH,
    'is_active': True,
}


def _results(response):
    """DRF page or bare list, whichever the endpoint returns."""
    data = response.data
    if isinstance(data, dict) and 'results' in data:
        return data['results']
    return data


class StaffCompensationAccessTests(TestCase):
    """Role matrix for the Staff Compensation endpoints.

    Anonymous: 401 everywhere. Employees: may read the payout ledger and both
    payout summaries, may never touch the rules or write the ledger.
    Admins: full rule management plus the same reads.
    """

    rules_url = '/api/finance/staff-compensation-rules/'
    payouts_url = '/api/finance/staff-payouts/'
    payout_summary_url = '/api/finance/staff-payouts/summary/'
    report_summary_url = '/api/finance/reports/staff-payout-summary/'

    def setUp(self):
        self.admin = admin_client()
        self.employee = employee_client()
        StaffCompensationRule.objects.update_or_create(
            role='doctor', defaults=dict(RULE_DEFAULTS),
        )
        self.rule = StaffCompensationRule.objects.get(role='doctor')

    def test_anonymous_is_rejected_on_every_compensation_endpoint(self):
        anon = APIClient()
        for method, url in (
            ('get', self.rules_url),
            ('post', self.rules_url),
            ('get', self.payouts_url),
            ('post', self.payouts_url),
            ('get', self.payout_summary_url),
            ('get', self.report_summary_url),
        ):
            response = getattr(anon, method)(url, {}, format='json')
            self.assertEqual(
                response.status_code, 401, f'{method} {url} -> {response.status_code}',
            )

    def test_employee_cannot_read_or_write_the_rules(self):
        for method, url, payload in (
            ('get', self.rules_url, None),
            ('post', self.rules_url, {'role': 'laser'}),
            ('patch', f'{self.rules_url}{self.rule.id}/', {'percent_revenue': '10.00'}),
            ('delete', f'{self.rules_url}{self.rule.id}/', None),
        ):
            if payload is None:
                response = getattr(self.employee, method)(url)
            else:
                response = getattr(self.employee, method)(url, payload, format='json')
            self.assertEqual(
                response.status_code, 403, f'employee {method} {url} -> {response.status_code}',
            )
        self.rule.refresh_from_db()
        self.assertEqual(self.rule.percent_revenue, D('50.00'), 'rule must be untouched')

    def test_employee_can_read_payouts_and_both_summaries_but_never_write(self):
        self.assertEqual(self.employee.get(self.payouts_url).status_code, 200)
        self.assertEqual(self.employee.get(self.payout_summary_url).status_code, 200)
        self.assertEqual(self.employee.get(self.report_summary_url).status_code, 200)
        # The ledger is read-only for every role.
        self.assertEqual(
            self.employee.post(self.payouts_url, {}, format='json').status_code, 405,
        )
        self.assertEqual(
            self.employee.patch(
                f'{self.payouts_url}999/', {'status': 'approved'}, format='json',
            ).status_code,
            405,
        )
        self.assertEqual(self.employee.delete(f'{self.payouts_url}999/').status_code, 405)

    def test_admin_can_read_and_set_the_rules(self):
        response = self.admin.get(self.rules_url)
        self.assertEqual(response.status_code, 200)
        roles = {
            row['role'] for row in _results(response)
        }
        self.assertIn('doctor', roles)

        patched = self.admin.patch(
            f'{self.rules_url}{self.rule.id}/', {'percent_revenue': '45.00'}, format='json',
        )
        self.assertEqual(patched.status_code, 200, patched.data)
        self.rule.refresh_from_db()
        self.assertEqual(self.rule.percent_revenue, D('45.00'))

        self.assertEqual(self.admin.get(self.payouts_url).status_code, 200)
        self.assertEqual(self.admin.get(self.payout_summary_url).status_code, 200)
        self.assertEqual(self.admin.get(self.report_summary_url).status_code, 200)


class VisitMoneyFlowTests(FinancialTestBase):
    """One real visit, then every number the system reports about it.

    Fixture (from ``FinancialTestBase``): doctor service $500 (recipe material
    $100), facial service $300 (recipe material $50), doctor rule 50%,
    facial rule 30%, laser monthly salary rule (unused here).

    This test's own rows: welcome pack with 2x $1 pack item, operating
    expense $200, approved claim $30. The bill collected is $800.

    Expected everywhere:
        revenue 800 | product 150 | pack 2 | gross 648
        staff   340 (doctor 250 + facial 90) | opex 200 | claims 30
        below the line 570 | net profit 78 | clinic share 308
        stock: material 500->499, facial material 500->499, pack item 500->498
        products sold quantity: 1 + 1 + 2 = 4
    """

    def setUp(self):
        super().setUp()

        self.doctor_op = make_employee(username='e2e_doctor')
        self.doctor_op.compensation_role = ClinicUser.CompensationRole.DOCTOR
        self.doctor_op.save(update_fields=['compensation_role'])
        self.facial_op = make_employee(username='e2e_facial')
        self.facial_op.compensation_role = ClinicUser.CompensationRole.FACIAL
        self.facial_op.save(update_fields=['compensation_role'])

        self.pack = WelcomePack.objects.create(name='E2E welcome pack')
        WelcomePackItem.objects.create(
            welcome_pack=self.pack, product=self.pack_item, quantity=D('2'),
        )

        self.opex_category = OperatingExpenseCategory.objects.first()
        self.assertIsNotNone(
            self.opex_category,
            'OperatingExpenseCategory seeds must exist; ensure_seed_categories() should have restored them.',
        )
        OperatingExpense.objects.create(
            category=self.opex_category, title='E2E rent', amount_usd=D('200'),
            amount_toman=D('20000000'), exchange_rate=RATE,
            expense_date=timezone.localtime(timezone.now()).date(),
        )
        self.claim_category = ExpenseCategory.objects.first()
        self.assertIsNotNone(
            self.claim_category,
            'ExpenseCategory seeds must exist; ensure_seed_categories() should have restored them.',
        )
        Expense.objects.create(
            created_by=self.staff, category=self.claim_category, amount_usd=D('30'),
            amount_toman=D('3000000'), exchange_rate_snapshot=RATE,
            expense_date=timezone.localtime(timezone.now()).date(),
            status=Expense.Status.APPROVED,
        )

        self.visit_id = self._run_flow()

    def _run_flow(self):
        """Book, confirm, consume, issue, pay and complete -- all via the API."""
        create = self.client.post('/api/visits/', {
            'customer': self.customer.id,
            'staff': self.doctor_op.id,
            'services': [self.doctor_service.id, self.facial_service.id],
            'start_at': greg_to_shamsi_dt(timezone.now()),
            'end_at': greg_to_shamsi_dt(timezone.now() + timedelta(hours=1)),
        }, format='json')
        self.assertEqual(create.status_code, 201, create.data)
        visit_id = create.data['id']

        confirm = self.client.post(f'/api/visits/{visit_id}/confirm/')
        self.assertEqual(confirm.status_code, 200, confirm.data)

        consume = self.client.post(
            f'/api/finance/visits/{visit_id}/record-consumption/', {
                'selected_products': {
                    str(self.doctor_service.id): [[self.material.id, '1']],
                    str(self.facial_service.id): [[self.facial_material.id, '1']],
                },
            }, format='json',
        )
        self.assertEqual(consume.status_code, 201, consume.data)

        issue = self.client.post(f'/api/finance/welcome-packs/{self.pack.id}/issue/', {
            'customer': self.customer.id, 'visit': visit_id, 'quantity': '1',
        }, format='json')
        self.assertIn(issue.status_code, (200, 201), issue.data)

        checkout = self.client.post('/api/finance/checkout/', {
            'customer': self.customer.id,
            'amount_usd': '800.00',
            'visit': visit_id,
            'components': [{'method': 'cash_toman', 'amount_usd': str(D('800') * RATE)}],
        }, format='json')
        self.assertEqual(checkout.status_code, 201, checkout.data)

        complete = self.client.post(f'/api/visits/{visit_id}/complete/')
        self.assertEqual(complete.status_code, 200, complete.data)
        return visit_id

    def test_consumption_and_pack_issuance_decrement_stock(self):
        self.material.refresh_from_db()
        self.facial_material.refresh_from_db()
        self.pack_item.refresh_from_db()
        self.assertEqual(self.material.count, D('499'))
        self.assertEqual(self.facial_material.count, D('499'))
        self.assertEqual(self.pack_item.count, D('498'))

        summary = self.client.get('/api/finance/reports/financial-summary/').data
        self.assertEqual(D(summary['counts']['products_sold_quantity']), D('4'))
        self.assertEqual(int(summary['counts']['paid_sales']), 1)

    def test_each_service_operator_is_paid_for_their_own_service(self):
        links = {
            (link.service_id, link.staff_id)
            for link in VisitService.objects.filter(visit_id=self.visit_id)
        }
        self.assertIn((self.doctor_service.id, self.doctor_op.id), links)
        self.assertIn((self.facial_service.id, self.facial_op.id), links)

        payouts = StaffPayout.objects.filter(visit_id=self.visit_id)
        by_staff = {payout.staff_id: payout for payout in payouts}
        self.assertEqual(set(by_staff), {self.doctor_op.id, self.facial_op.id})

        doctor_payout = by_staff[self.doctor_op.id]
        self.assertEqual(doctor_payout.role, 'doctor')
        self.assertEqual(doctor_payout.payout_cash_usd, D('250.00'))

        facial_payout = by_staff[self.facial_op.id]
        self.assertEqual(facial_payout.role, 'facial')
        self.assertEqual(facial_payout.payout_cash_usd, D('90.00'))

    def test_financial_summary_matches_the_net_profit_formula_exactly(self):
        s = self.client.get('/api/finance/reports/financial-summary/').data

        self.assertEqual(D(s['revenue']['usd']), D('800.00'))
        self.assertEqual(D(s['product_cost']['usd']), D('150.00'))
        self.assertEqual(D(s['welcome_pack_cost']['usd']), D('2.00'))
        self.assertEqual(D(s['gross_profit']['usd']), D('648.00'))
        self.assertEqual(D(s['staff_compensation']['total']['usd']), D('340.00'))
        self.assertEqual(D(s['staff_compensation']['by_role']['doctor']['total_usd']), D('250.00'))
        self.assertEqual(D(s['staff_compensation']['by_role']['facial']['total_usd']), D('90.00'))
        self.assertEqual(D(s['operating_expenses']['usd']), D('200.00'))
        self.assertEqual(D(s['staff_expense_claims']['usd']), D('30.00'))
        self.assertEqual(D(s['below_the_line_total']['usd']), D('570.00'))
        self.assertEqual(D(s['net_profit']['usd']), D('78.00'))
        self.assertEqual(D(s['clinic_share']['usd']), D('308.00'))

        self.assertEqual(D(s['revenue']['toman']), D('80000000.00'))
        self.assertEqual(D(s['product_cost']['toman']), D('15000000.00'))
        self.assertEqual(D(s['welcome_pack_cost']['toman']), D('200000.00'))
        self.assertEqual(D(s['staff_compensation']['total']['toman']), D('34000000.00'))
        self.assertEqual(D(s['operating_expenses']['toman']), D('20000000.00'))
        self.assertEqual(D(s['staff_expense_claims']['toman']), D('3000000.00'))
        self.assertEqual(D(s['net_profit']['toman']), D('7800000.00'))

        # The formula itself, in both currencies, out of the response's own numbers.
        for currency in ('usd', 'toman'):
            self.assertEqual(
                D(s['gross_profit'][currency]),
                D(s['revenue'][currency])
                - D(s['product_cost'][currency])
                - D(s['welcome_pack_cost'][currency]),
            )
            self.assertEqual(
                D(s['net_profit'][currency]),
                D(s['revenue'][currency])
                - D(s['product_cost'][currency])
                - D(s['welcome_pack_cost'][currency])
                - D(s['staff_compensation']['total'][currency])
                - D(s['operating_expenses'][currency])
                - D(s['staff_expense_claims'][currency]),
            )

    def test_dashboard_and_both_payout_summaries_agree_with_the_summary(self):
        summary = self.client.get('/api/finance/reports/financial-summary/').data
        dashboard = self.client.get('/api/finance/reports/dashboard/').data['sales_summary']

        for dashboard_key, summary_path in (
            ('revenue_usd', ('revenue', 'usd')),
            ('product_cost_usd', ('product_cost', 'usd')),
            ('welcome_pack_cost_usd', ('welcome_pack_cost', 'usd')),
            ('gross_profit_usd', ('gross_profit', 'usd')),
            ('total_payout_usd', ('staff_compensation', 'total', 'usd')),
            ('staff_compensation_usd', ('staff_compensation', 'total', 'usd')),
            ('operating_expenses_usd', ('operating_expenses', 'usd')),
            ('expenses_usd', ('staff_expense_claims', 'usd')),
            ('net_profit_usd', ('net_profit', 'usd')),
            ('clinic_share_usd', ('clinic_share', 'usd')),
            ('below_the_line_total_usd', ('below_the_line_total', 'usd')),
        ):
            value = summary
            for key in summary_path:
                value = value[key]
            self.assertEqual(
                D(dashboard[dashboard_key]), D(value),
                f'dashboard {dashboard_key} disagrees with summary {".".join(summary_path)}',
            )

        payout_from_compensation = self.client.get('/api/finance/staff-payouts/summary/').data
        payout_from_reports = self.client.get('/api/finance/reports/staff-payout-summary/').data
        self.assertEqual(payout_from_compensation, payout_from_reports)
        self.assertEqual(D(payout_from_reports['total_payout_usd']), D('340.00'))
        self.assertEqual(D(payout_from_reports['total_cash_toman']), D('34000000.00'))
        self.assertEqual(int(payout_from_reports['payout_count']), 2)

        ledger = _results(self.client.get('/api/finance/staff-payouts/'))
        self.assertEqual(len(ledger), 2)

    def test_profit_by_staff_and_profit_by_service_tie_back_to_the_summary(self):
        summary = self.client.get('/api/finance/reports/financial-summary/').data

        staff_rows = self.client.get('/api/finance/reports/profit-by-staff/').data
        by_staff = {row['staff_id']: row for row in staff_rows}
        doctor_row = by_staff[self.doctor_op.id]
        facial_row = by_staff[self.facial_op.id]

        self.assertEqual(D(doctor_row['revenue_usd']), D('500.00'))
        self.assertEqual(D(doctor_row['operator_compensation_usd']), D('250.00'))
        self.assertEqual(D(facial_row['revenue_usd']), D('300.00'))
        self.assertEqual(D(facial_row['operator_compensation_usd']), D('90.00'))

        self.assertEqual(sum(D(row['revenue_usd']) for row in staff_rows), D('800.00'))
        self.assertEqual(
            sum(D(row['operator_compensation_usd']) for row in staff_rows), D('340.00'),
        )
        self.assertEqual(sum(D(row['welcome_pack_cost_usd']) for row in staff_rows), D('2.00'))
        self.assertEqual(
            sum(D(row['revenue_usd']) for row in staff_rows),
            D(summary['revenue']['usd']),
        )
        self.assertEqual(
            sum(D(row['operator_compensation_usd']) for row in staff_rows),
            D(summary['staff_compensation']['total']['usd']),
        )

        service_rows = self.client.get('/api/finance/reports/profit-by-service/').data
        by_service = {row['service_id']: row for row in service_rows}
        doctor_service_row = by_service[self.doctor_service.id]
        facial_service_row = by_service[self.facial_service.id]

        self.assertEqual(D(doctor_service_row['revenue_usd']), D('500.00'))
        self.assertEqual(D(doctor_service_row['product_cost_usd']), D('100.00'))
        self.assertEqual(D(doctor_service_row['operator_compensation_usd']), D('250.00'))
        self.assertEqual(D(facial_service_row['revenue_usd']), D('300.00'))
        self.assertEqual(D(facial_service_row['product_cost_usd']), D('50.00'))
        self.assertEqual(D(facial_service_row['operator_compensation_usd']), D('90.00'))

        self.assertEqual(sum(D(row['revenue_usd']) for row in service_rows), D('800.00'))
        self.assertEqual(sum(D(row['product_cost_usd']) for row in service_rows), D('150.00'))
        self.assertEqual(
            sum(D(row['operator_compensation_usd']) for row in service_rows), D('340.00'),
        )
        self.assertEqual(sum(D(row['welcome_pack_cost_usd']) for row in service_rows), D('2.00'))
        self.assertEqual(
            sum(D(row['product_cost_usd']) for row in service_rows),
            D(summary['product_cost']['usd']),
        )

        coverage = self.client.get('/api/finance/reports/profit-by-staff/coverage/').data
        self.assertEqual(int(coverage['total_visits']), 1)
        self.assertEqual(int(coverage['visits_with_staff']), 1)
        self.assertEqual(int(coverage['unassigned_visits']), 0)

    def test_welcome_pack_report_matches_the_pack_cost_in_the_summary(self):
        report = self.client.get('/api/finance/reports/welcome-packs/').data
        self.assertEqual(D(report['total_cost_usd']), D('2.00'))
        self.assertEqual(D(report['total_packs_issued']), D('1'))
        self.assertEqual(int(report['total_usage_count']), 1)

        summary = self.client.get('/api/finance/reports/financial-summary/').data
        self.assertEqual(D(report['total_cost_usd']), D(summary['welcome_pack_cost']['usd']))

    def test_activity_reports_tie_to_the_ledger(self):
        daily = self.client.get('/api/reports/daily/').data
        self.assertEqual(D(str(daily['total'])), D('80000000.00'))
        self.assertEqual(int(daily['visits']), 1)

        everything = self.client.get('/api/reports/all/').data
        self.assertEqual(D(str(everything['total_sales'])), D('80000000.00'))
        self.assertEqual(int(everything['total_visits']), 1)
        self.assertEqual(int(everything['customer_status']['completed']), 1)

        # Activity toman equals the finance report's revenue toman.
        summary = self.client.get('/api/finance/reports/financial-summary/').data
        self.assertEqual(D(str(daily['total'])), D(summary['revenue']['toman']))

    def test_visits_report_counts_the_visit(self):
        visits_report = self.client.get('/api/reports/visits/').data
        self.assertEqual(int(visits_report['current_count']), 1)
