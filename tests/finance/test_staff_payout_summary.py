"""Payout reports: one number, two doors, and the line between owing and earning.

Regression cover for the audit of the Reports vs Staff Compensation endpoints:

* ``/reports/staff-payout-summary/`` and ``/staff-payouts/summary/`` must stay
  byte-identical -- they are two documented doors onto the same figure.
* Both, plus ``/staff-payouts/detail_report/``, share one date-range and one
  status convention: a bare call means today, and only payouts still owed are
  totalled (``?status=all`` shows the raw ledger, cancelled rows included).
* ``/reports/profit-by-staff/`` answers a different question -- what the
  clinic earned -- so it stays a separate ledger. It is *comparable* with the
  payout summary for the same window, not forced to equal it.
"""
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from customers.models import Service, Visit
from finance.models import StaffCompensationRule, StaffPayout
from finance.services import staff_compensation
from tests.finance.test_staff_compensation import CompensationFixtureMixin, make_rule
from tests.helpers import admin_client

SUMMARY_URL = '/api/finance/staff-payouts/summary/'
REPORT_SUMMARY_URL = '/api/finance/reports/staff-payout-summary/'
DETAIL_URL = '/api/finance/staff-payouts/detail_report/'
PROFIT_BY_STAFF_URL = '/api/finance/reports/profit-by-staff/'
SUMMARY_ROUTES = (SUMMARY_URL, REPORT_SUMMARY_URL)

#: The doctor rule pays 50% of a 200.00 visit -> 100.00 owed.
PAYOUT_USD = Decimal('100.00')


def _day(offset=0):
    """A query-date string: the Shamsi day `offset` Gregorian days from now."""
    import jdatetime

    day = timezone.localtime(timezone.now()).date() + timedelta(days=offset)
    return jdatetime.date.fromgregorian(date=day).strftime('%Y-%m-%d')


def _total(payload):
    return Decimal(payload['total_payout_usd'])


class PayoutSummaryTests(CompensationFixtureMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.client = admin_client()
        make_rule()
        staff_compensation.generate_visit_payouts(self.visit)

    def _set_payout_status(self, status):
        updated = StaffPayout.objects.filter(visit=self.visit).update(status=status)
        self.assertEqual(updated, 1, 'fixture should own exactly one payout')

    # --- the two summary routes are one endpoint, not two -----------------

    def test_both_summary_routes_return_identical_payloads(self):
        by_route = self.client.get(SUMMARY_URL)
        by_report = self.client.get(REPORT_SUMMARY_URL)

        self.assertEqual(by_route.status_code, 200, by_route.data)
        self.assertEqual(by_report.status_code, 200, by_report.data)
        self.assertEqual(by_route.data, by_report.data)
        self.assertEqual(_total(by_route.data), PAYOUT_USD)

    def test_both_summary_routes_honour_the_same_query_parameters(self):
        role = StaffCompensationRule.Role.DOCTOR
        for query, expected_total in (
            ('?period=today', PAYOUT_USD),
            (f'?start_date={_day()}&end_date={_day()}', PAYOUT_USD),
            (f'?staff={self.staff.id}', PAYOUT_USD),
            (f'?role={role}', PAYOUT_USD),
            (f'?role={StaffCompensationRule.Role.LASER}', Decimal('0.00')),
        ):
            with self.subTest(query=query):
                by_route = self.client.get(f'{SUMMARY_URL}{query}')
                by_report = self.client.get(f'{REPORT_SUMMARY_URL}{query}')
                self.assertEqual(by_route.status_code, 200, by_route.data)
                self.assertEqual(by_report.status_code, 200, by_report.data)
                self.assertEqual(by_report.data, by_route.data, query)
                self.assertEqual(_total(by_route.data), expected_total, query)

    # --- date filters -----------------------------------------------------

    def test_default_window_is_today_on_every_payout_route(self):
        StaffPayout.objects.filter(visit=self.visit).update(
            created_at=timezone.now() - timedelta(days=1),
        )

        for url in SUMMARY_ROUTES:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.data['payout_count'], 0)
                self.assertEqual(_total(response.data), Decimal('0.00'))
        self.assertEqual(self.client.get(DETAIL_URL).data, [])

    def test_explicit_range_and_period_select_the_same_rows(self):
        by_dates = self.client.get(f'{SUMMARY_URL}?start_date={_day()}&end_date={_day()}')
        by_period = self.client.get(f'{SUMMARY_URL}?period=today')

        self.assertEqual(_total(by_dates.data), PAYOUT_USD)
        self.assertEqual(by_period.data, by_dates.data)

    def test_yesterday_is_empty_on_both_routes(self):
        for url in SUMMARY_ROUTES:
            with self.subTest(url=url):
                response = self.client.get(f'{url}?start_date={_day(-1)}&end_date={_day(-1)}')
                self.assertEqual(response.data['payout_count'], 0)
                self.assertEqual(_total(response.data), Decimal('0.00'))
        self.assertEqual(
            self.client.get(f'{DETAIL_URL}?start_date={_day(-1)}&end_date={_day(-1)}').data, [],
            'detail_report must use the same window as the summaries',
        )

    # --- statuses and cancelled payouts -----------------------------------

    def test_cancelled_payouts_are_excluded_from_both_summaries(self):
        self._set_payout_status(StaffPayout.Status.CANCELLED)

        for url in SUMMARY_ROUTES:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.data['payout_count'], 0)
                self.assertEqual(_total(response.data), Decimal('0.00'))
        self.assertEqual(
            self.client.get(DETAIL_URL).data, [],
            'detail_report must not show lines the summary refuses to total',
        )

    def test_status_all_returns_the_cancelled_ledger(self):
        self._set_payout_status(StaffPayout.Status.CANCELLED)

        for url in SUMMARY_ROUTES:
            with self.subTest(url=url):
                response = self.client.get(f'{url}?status=all')
                self.assertEqual(response.data['payout_count'], 1)
                self.assertEqual(_total(response.data), PAYOUT_USD)
        self.assertEqual(len(self.client.get(f'{DETAIL_URL}?status=all').data), 1)

    def test_a_single_status_can_be_selected(self):
        self._set_payout_status(StaffPayout.Status.PAID)

        paid = self.client.get(f'{SUMMARY_URL}?status=paid')
        pending = self.client.get(f'{SUMMARY_URL}?status=pending')
        cancelled = self.client.get(f'{SUMMARY_URL}?status=cancelled')

        self.assertEqual(paid.data['payout_count'], 1)
        self.assertEqual(pending.data['payout_count'], 0)
        self.assertEqual(cancelled.data['payout_count'], 0)
        # 'paid' is still owed, so the default (no status) keeps it.
        self.assertEqual(self.client.get(REPORT_SUMMARY_URL).data['payout_count'], 1)

    def test_detail_report_understands_the_status_filter(self):
        self._set_payout_status(StaffPayout.Status.CANCELLED)

        owed = self.client.get(DETAIL_URL)
        all_rows = self.client.get(f'{DETAIL_URL}?status=all')
        cancelled_only = self.client.get(f'{DETAIL_URL}?status=cancelled')

        self.assertEqual(owed.data, [])
        self.assertEqual(len(all_rows.data), 1)
        self.assertEqual(len(cancelled_only.data), 1)
        self.assertEqual(all_rows.data, cancelled_only.data)

    # --- detail and summary agree -----------------------------------------

    def test_detail_lines_add_up_to_the_summary_totals(self):
        top_up = Service.objects.create(
            name='Botox top-up', price_usd=Decimal('100'),
            compensation_role=Service.CompensationRole.DOCTOR,
        )
        second_visit = Visit.objects.create(
            customer=self.customer, staff=self.staff,
            start_at=timezone.now() + timedelta(hours=2),
            end_at=timezone.now() + timedelta(hours=3),
            status=Visit.Status.COMPLETED,
        )
        second_visit.services.add(top_up)
        staff_compensation.generate_visit_payouts(second_visit)
        self.assertEqual(StaffPayout.objects.filter(visit=second_visit).count(), 1)
        # One of the two obligations is voided; neither report should show it.
        StaffPayout.objects.filter(visit=second_visit).update(
            status=StaffPayout.Status.CANCELLED,
        )

        summary = self.client.get(SUMMARY_URL).data
        rows = self.client.get(DETAIL_URL).data

        self.assertEqual(summary['payout_count'], len(rows))
        line_total = sum(
            (Decimal(row['payout_cash_usd']) + Decimal(row['payout_product_value_usd']))
            for row in rows
        )
        self.assertEqual(line_total, _total(summary))
        self.assertEqual(_total(summary), PAYOUT_USD)
        # ...and the Reports door shows exactly the same numbers.
        self.assertEqual(self.client.get(REPORT_SUMMARY_URL).data, summary)

    # --- the two ledgers stay separate, and comparable ---------------------

    def test_profit_by_staff_compensation_ties_to_the_summary(self):
        summary = self.client.get(SUMMARY_URL).data
        rows = self.client.get(f'{PROFIT_BY_STAFF_URL}?period=today').data

        self.assertEqual(len(rows), 1)
        self.assertEqual(Decimal(rows[0]['operator_compensation_usd']), _total(summary))
        self.assertEqual(_total(summary), PAYOUT_USD)

    def test_the_two_reports_answer_different_questions(self):
        summary = self.client.get(SUMMARY_URL).data
        row = self.client.get(PROFIT_BY_STAFF_URL).data[0]

        # Profitability: what the clinic earned. Absent from the payout view.
        self.assertEqual(Decimal(row['revenue_usd']), Decimal('200.00'))
        self.assertEqual(Decimal(row['profit_usd']), Decimal('150.00'))
        for key in ('revenue_usd', 'profit_usd', 'clinic_share_usd'):
            self.assertNotIn(key, summary)

        # Obligation: what the clinic owes. Absent from the profitability view.
        for key in ('total_payout_usd', 'payout_count'):
            self.assertNotIn(key, row)

    def test_voiding_an_obligation_does_not_change_profitability(self):
        before = self.client.get(PROFIT_BY_STAFF_URL).data[0]

        self._set_payout_status(StaffPayout.Status.CANCELLED)

        after = self.client.get(PROFIT_BY_STAFF_URL).data[0]
        summary = self.client.get(SUMMARY_URL).data

        # The debt is gone...
        self.assertEqual(summary['payout_count'], 0)
        self.assertEqual(_total(summary), Decimal('0.00'))
        self.assertEqual(Decimal(after['operator_compensation_usd']), Decimal('0.00'))
        # ...but the visit still earned what it earned.
        self.assertEqual(after['revenue_usd'], before['revenue_usd'])
        self.assertEqual(after['profit_usd'], before['profit_usd'])
        # Only the clinic's share moves, because one of its costs disappeared.
        self.assertGreater(Decimal(after['clinic_share_usd']), Decimal(before['clinic_share_usd']))

    def test_the_reports_are_comparable_but_not_forced_to_match(self):
        # Work delivered yesterday, obligation booked today: the summary counts
        # the payout today (its `created_at`), profit-by-staff does not (its
        # visit `start_at`). Both are right; they are simply keyed differently.
        Visit.objects.filter(pk=self.visit.pk).update(
            start_at=timezone.now() - timedelta(days=1),
            end_at=timezone.now() - timedelta(days=1) + timedelta(hours=1),
        )

        rows = self.client.get(f'{PROFIT_BY_STAFF_URL}?period=today').data
        summary = self.client.get(f'{SUMMARY_URL}?period=today').data

        self.assertEqual(rows, [])
        self.assertEqual(summary['payout_count'], 1)
        self.assertEqual(_total(summary), PAYOUT_USD)

    def test_anonymous_is_rejected_on_every_payout_report(self):
        anon = APIClient()
        for url in (*SUMMARY_ROUTES, DETAIL_URL, PROFIT_BY_STAFF_URL):
            with self.subTest(url=url):
                self.assertEqual(anon.get(url).status_code, 401, url)
