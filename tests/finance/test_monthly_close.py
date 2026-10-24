"""Monthly close: a Shamsi year of P&L rows, each next to its operators.

The "close this month, move to the next one" report. It has to hold four
promises at once:

* twelve months of the requested Shamsi year -- or exactly one, when a month
  is asked for -- each one an ordinary ``build_report`` over that month's own
  range, so a month here can never disagree with
  ``/reports/financial-summary/`` for the same dates;
* the cash view: ``purchases`` (both buying ledgers) and
  ``net_profit_after_purchases``, while ``net_profit`` stays untouched,
  because inventory is charged once, at consumption;
* one row per operator (doctor / facial / laser) carrying both halves of the
  month -- what they produced and what they are owed -- whose obligations add
  back up to that month's ``staff_compensation.total``;
* ``year_total`` that is simply the sum of the twelve months above it.
"""
from decimal import Decimal

import jdatetime
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from finance.models import StaffPayout
from finance.services import payments, reporting
from finance.services.inventory import record_product_purchase
from Sefro_Clinic.periods import SHAMSI_MONTH_NAMES, shamsi_months_of_year
from tests.finance.test_staff_compensation import CompensationFixtureMixin, make_rule
from tests.helpers import admin_client, make_employee

URL = '/api/finance/reports/monthly-close/'
RATE = Decimal('100000')
ZERO = Decimal('0.00')


def shamsi_today():
    return jdatetime.datetime.fromgregorian(
        datetime=timezone.localtime(timezone.now()),
    ).date()


def money(value):
    return Decimal(value)


class MonthlyCloseTests(CompensationFixtureMixin, TestCase):
    """One real month: a collected visit, its consumption, its pay, its stock."""

    def setUp(self):
        super().setUp()
        self.client = admin_client()
        make_rule()  # doctor: 50% of the service's collected revenue
        payments.checkout(
            customer=self.customer, amount_usd=Decimal('200'),
            visit=self.visit, rate=RATE,
            components=[{'method': 'cash_toman', 'amount_usd': Decimal('200') * RATE}],
        )
        # Stock bought this month: the cash half of the report.
        record_product_purchase(
            product=self.product, quantity=Decimal('4'), unit_cost_usd=Decimal('10'),
            supplier='Close Supplier', rate=RATE,
        )
        self.today = shamsi_today()
        self.year = self.today.year
        self.month = self.today.month

    def _close(self, **query):
        query.setdefault('year', self.year)
        params = '&'.join(f'{k}={v}' for k, v in query.items())
        response = self.client.get(f'{URL}?{params}')
        self.assertEqual(response.status_code, 200, response.data)
        return response.data

    def _month(self, payload=None, month=None):
        payload = payload if payload is not None else self._close()
        return next(row for row in payload['months'] if row['month'] == (month or self.month))

    def _bounds(self, month=None):
        month = month or self.month
        return next(b for b in shamsi_months_of_year(self.year) if b['month'] == month)

    # --- the shape of the year --------------------------------------------

    def test_default_returns_the_whole_current_shamsi_year(self):
        data = self._close()

        self.assertEqual(data['calendar'], 'shamsi')
        self.assertEqual(data['year'], self.year)
        self.assertIsNone(data['month'])
        self.assertEqual(len(data['months']), 12)
        self.assertEqual([row['month'] for row in data['months']], list(range(1, 13)))
        self.assertEqual(
            [row['month_name'] for row in data['months']], SHAMSI_MONTH_NAMES[1:],
        )
        self.assertEqual(
            [row['key'] for row in data['months']],
            [b['key'] for b in shamsi_months_of_year(self.year)],
        )
        self.assertEqual(
            [row['month'] for row in data['months'] if row['is_current']], [self.month],
        )

    def test_a_single_month_can_be_requested_by_number_or_by_key(self):
        by_number = self._close(month=self.month)
        self.assertEqual(by_number['month'], self.month)
        self.assertEqual(len(by_number['months']), 1)
        self.assertEqual(by_number['months'][0]['month'], self.month)

        by_key = self._close(month=f'{self.year}-{self.month:02d}')
        self.assertEqual(by_key['months'], by_number['months'])
        self.assertEqual(by_key['month'], self.month)

    def test_an_unusable_month_falls_back_to_the_whole_year(self):
        for month in ('99', 'zero', '1405-99'):
            with self.subTest(month=month):
                data = self._close(month=month)
                self.assertEqual(len(data['months']), 12)
                self.assertIsNone(data['month'])

    def test_a_year_without_activity_is_zero_filled(self):
        data = self._close(year=1399)

        self.assertEqual(len(data['months']), 12)
        self.assertFalse(any(row['is_current'] for row in data['months']))
        for row in data['months']:
            with self.subTest(month=row['month']):
                self.assertEqual(row['revenue']['usd'], '0.00')
                self.assertEqual(row['purchases']['usd'], '0.00')
                self.assertEqual(row['net_profit']['usd'], '0.00')
                self.assertEqual(row['operators'], [])
                self.assertEqual(row['role_totals'], [])
        self.assertEqual(data['year_total']['revenue']['usd'], '0.00')
        self.assertEqual(data['year_total']['payout_count'], 0)

    # --- a month agrees with the report it is built from -------------------

    def test_a_month_agrees_with_financial_summary_for_the_same_dates(self):
        month = self._month()
        bounds = self._bounds()
        summary = reporting.financial_summary(bounds['start'], bounds['end'])

        for key in (
            'revenue', 'product_cost', 'welcome_pack_cost', 'gross_profit',
            'clinic_share', 'operating_expenses', 'staff_expense_claims',
            'net_profit', 'purchases', 'net_profit_after_purchases',
        ):
            with self.subTest(key=key):
                self.assertEqual(money(month[key]['usd']), summary[key]['usd'])
        self.assertEqual(
            money(month['staff_compensation_total']['usd']),
            summary['staff_compensation']['total']['usd'],
        )
        self.assertEqual(month['shamsi_start'], bounds['key'] + '-01')
        self.assertNotIn('gregorian_start', month)
        self.assertNotIn('gregorian_end', month)

    def test_year_total_is_the_sum_of_its_months(self):
        data = self._close()

        for key in ('revenue', 'product_cost', 'gross_profit', 'net_profit',
                    'purchases', 'net_profit_after_purchases'):
            with self.subTest(key=key):
                total = sum((money(row[key]['usd']) for row in data['months']), Decimal('0'))
                self.assertEqual(total, money(data['year_total'][key]['usd']))
        self.assertEqual(
            data['year_total']['payout_count'],
            sum(row['payout_total']['payout_count'] for row in data['months']),
        )

    # --- purchases: the cash view, kept out of net profit ------------------

    def test_purchases_are_reported_from_both_buying_ledgers(self):
        month = self._month()

        self.assertEqual(month['purchases']['usd'], '40.00')
        self.assertEqual(month['purchases']['count'], 1)
        self.assertEqual(month['purchases']['by_source']['direct']['usd'], '40.00')
        self.assertEqual(month['purchases']['by_source']['purchase_order']['count'], 0)
        for row in self._close()['months']:
            if row['month'] != self.month:
                with self.subTest(month=row['month']):
                    self.assertEqual(row['purchases']['usd'], '0.00')

    def test_net_profit_never_subtracts_purchases_and_the_cash_view_does(self):
        month = self._month()

        # Revenue 200 - product cost 50 = gross 150; minus the 100 owed to the
        # doctor (50% of that collected 200) = net 50. Purchases sit outside
        # that arithmetic on purpose.
        self.assertEqual(month['revenue']['usd'], '200.00')
        self.assertEqual(month['product_cost']['usd'], '50.00')
        self.assertEqual(month['gross_profit']['usd'], '150.00')
        self.assertEqual(month['net_profit']['usd'], '50.00')
        self.assertEqual(month['net_profit_after_purchases']['usd'], '10.00')

        for row in self._close()['months']:
            with self.subTest(month=row['month']):
                self.assertEqual(
                    money(row['net_profit_after_purchases']['usd']),
                    (money(row['net_profit']['usd']) - money(row['purchases']['usd'])).quantize(
                        Decimal('0.01'),
                    ),
                )

    # --- operators: produced next to owed ----------------------------------

    def test_operator_row_carries_both_production_and_obligation(self):
        month = self._month()

        self.assertEqual(len(month['operators']), 1)
        row = month['operators'][0]
        self.assertEqual(row['staff_id'], self.staff.id)
        self.assertEqual(row['staff_name'], 'emp_user')
        self.assertEqual(row['roles'], ['doctor'])
        self.assertEqual(row['revenue_usd'], '200.00')
        self.assertEqual(row['product_cost_usd'], '50.00')
        self.assertEqual(row['material_profit_usd'], '150.00')
        # 50% of the collected 200 booked against this doctor's service.
        self.assertEqual(row['owed_usd'], '100.00')
        self.assertEqual(row['session_payout_usd'], '100.00')
        self.assertEqual(row['salary_payout_usd'], '0.00')
        self.assertEqual(row['by_role']['doctor']['owed_usd'], '100.00')
        self.assertEqual(row['calculation']['doctor']['calculation_type'], 'percent_revenue')

        self.assertEqual(len(month['role_totals']), 1)
        self.assertEqual(month['role_totals'][0]['role'], 'doctor')
        self.assertEqual(month['role_totals'][0]['owed_usd'], '100.00')
        self.assertEqual(month['role_totals'][0]['operator_count'], 1)

    def test_operator_obligations_add_back_up_to_staff_compensation(self):
        for month in self._close()['months']:
            with self.subTest(month=month['key']):
                owed = sum((money(row['owed_usd']) for row in month['operators']), Decimal('0'))
                self.assertEqual(owed, money(month['staff_compensation_total']['usd']))
                self.assertEqual(
                    month['payout_total']['usd'], month['staff_compensation_total']['usd'],
                )

    def test_operator_revenue_adds_back_up_to_the_month_revenue(self):
        for month in self._close()['months']:
            with self.subTest(month=month['key']):
                produced = sum(
                    (money(row['revenue_usd']) for row in month['operators']), Decimal('0'),
                )
                produced += money(month['unattributed']['revenue_usd'])
                self.assertEqual(produced, money(month['revenue']['usd']))

    def test_cancelling_a_payout_moves_the_debt_not_the_production(self):
        StaffPayout.objects.filter(visit=self.visit).update(
            status=StaffPayout.Status.CANCELLED,
        )
        month = self._month()

        self.assertEqual(month['operators'][0]['owed_usd'], '0.00')
        self.assertEqual(month['payout_total']['usd'], '0.00')
        self.assertEqual(month['staff_compensation_total']['usd'], '0.00')
        # Revenue is a fact about the month; voiding a debt erases none of it.
        self.assertEqual(month['operators'][0]['revenue_usd'], '200.00')
        self.assertEqual(month['net_profit']['usd'], '150.00')

        everything = self._close(status='all')
        self.assertEqual(self._month(everything)['operators'][0]['owed_usd'], '100.00')
        self.assertEqual(self._month(everything)['payout_total']['usd'], '100.00')

    def test_staff_filter_narrows_the_operator_rows_not_just_their_pay(self):
        other = make_employee(username='other_close_staff')

        only_mine = self._close(month=self.month, staff=self.staff.id)
        self.assertEqual(
            [row['staff_id'] for row in only_mine['months'][0]['operators']],
            [self.staff.id],
        )
        self.assertEqual(only_mine['months'][0]['operators'][0]['owed_usd'], '100.00')

        someone_else = self._close(month=self.month, staff=other.id)
        self.assertEqual(someone_else['months'][0]['operators'], [])
        self.assertEqual(someone_else['months'][0]['role_totals'], [])
        # Narrowed to one person, the report stops claiming to explain the
        # whole month's revenue.
        self.assertEqual(someone_else['months'][0]['unattributed']['revenue_usd'], '0.00')

    def test_role_filter_narrows_the_operator_rows_to_that_role(self):
        doctor = self._close(month=self.month, role='doctor')
        self.assertEqual(
            [row['staff_id'] for row in self._month(doctor)['operators']],
            [self.staff.id],
        )
        self.assertEqual(self._month(doctor)['operators'][0]['owed_usd'], '100.00')
        self.assertEqual(self._month(doctor)['role_totals'][0]['role'], 'doctor')

        laser = self._close(month=self.month, role='laser')
        # Nobody here has a laser obligation, so no operator row claims one.
        self.assertEqual(self._month(laser)['operators'], [])
        self.assertEqual(self._month(laser)['role_totals'], [])
        self.assertEqual(self._month(laser)['payout_total']['usd'], '0.00')
        # The month's P&L is not a per-role view: revenue stays whole.
        self.assertEqual(self._month(laser)['revenue']['usd'], '200.00')
        self.assertEqual(self._month(laser)['unattributed']['revenue_usd'], '0.00')

    # --- access ------------------------------------------------------------

    def test_anonymous_cannot_read_the_close(self):
        self.assertEqual(APIClient().get(URL).status_code, 401)
        self.assertEqual(
            APIClient().get(f'{URL}?year={self.year}').status_code, 401,
        )
