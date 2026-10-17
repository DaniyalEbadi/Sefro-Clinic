"""Monthly closing: freezing a past Shamsi month, and everything that must stop afterwards.

Closing is an explicit POST -- the GET report never closes anything -- and it
has to hold its promises from four sides at once:

* only a PAST Shamsi month can close (current/future rejected), closing twice
  is idempotent, and the unique constraint keeps one row per month even if two
  closers race;
* the stored snapshot is byte-for-byte the live ``_render_month`` row the
  report shows, plus an informational ``outstanding`` block -- unpaid payouts
  and approved claims are reported, never a blocker;
* once closed, every mutation touching that month answers 409 through the API
  (central exception handler) or raises ``PeriodClosedError`` inside services:
  refunds, the expense workflow, operating-expense CRUD, payout cancellation
  and re-pricing, backdated purchases (direct and via purchase order), and the
  Django admin -- where it surfaces as a form ValidationError, not a 500;
* every refusal is audited (``changes.event`` starting with ``BLOCKED:``) even
  though no row changed, and close/reopen are audited with the acting user,
  the close note, and the mandatory reopen reason.

Reopen keeps the row (``status='reopened'``): the month becomes live again in
the report, with its closing history still attached; re-closing refreshes the
same row.
"""
from datetime import timedelta
from decimal import Decimal

import jdatetime
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import RequestFactory, TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from finance.admin_guards import ClosedPeriodGuardAdminMixin
from finance.models import (
    Expense,
    ExpenseCategory,
    MonthlyClose,
    OperatingExpense,
    OperatingExpenseCategory,
    PaymentComponent,
    ProductPurchase,
    ProductUsage,
    PurchaseOrder,
    Sale,
    StaffPayout,
)
from finance.services import accounting, closing, payments, staff_compensation
from finance.services import expenses as expense_svc
from finance.services import operating_expenses as opex_svc
from finance.services import purchases as purchase_svc
from finance.services.inventory import record_product_purchase
from finance.services.periods_guard import PeriodClosedError
from logs.models import AuditLog
from Sefro_Clinic.periods import shamsi_months_of_year
from tests.finance.test_operating_expenses import ensure_seed_categories
from tests.finance.test_staff_compensation import CompensationFixtureMixin, make_rule
from tests.helpers import admin_client, employee_client, make_admin

URL_REPORT = '/api/finance/reports/monthly-close/'
URL_CLOSE = f'{URL_REPORT}close/'
URL_REOPEN = f'{URL_REPORT}reopen/'
URL_SALES = '/api/finance/sales/'
URL_EXPENSES = '/api/finance/expenses/'
URL_OPEX = '/api/finance/operating-expenses/'
URL_PURCHASES = '/api/finance/product-purchases/'
RATE = Decimal('100000')


def shamsi_today():
    return jdatetime.datetime.fromgregorian(
        datetime=timezone.localtime(timezone.now()),
    ).date()


def shamsi_str(greg_dt):
    """Convert a Gregorian date/datetime to Shamsi 'YYYY-MM-DD' string."""
    if hasattr(greg_dt, 'date'):
        greg_dt = greg_dt.date()
    return jdatetime.date.fromgregorian(date=greg_dt).strftime('%Y-%m-%d')


def a_past_period():
    """A (year, month) strictly before the current Shamsi month."""
    today = shamsi_today()
    if today.month > 1:
        return today.year, today.month - 1
    return today.year - 1, 12


def money(value):
    return Decimal(str(value))


class _AdminBase:
    """Minimal stand-in for ModelAdmin's save/delete hooks.

    ``django.contrib.admin`` is not installed in this project (finance/admin.py
    is dormant), so the guard mixin is exercised against plain hooks -- the
    contract it will have with ModelAdmin if the admin is ever enabled.
    """

    def save_model(self, request, obj, form, change):
        self.saved = obj

    def delete_model(self, request, obj):
        self.deleted = obj

    def delete_queryset(self, request, queryset):
        self.deleted_pks = [obj.pk for obj in queryset]


class _AdminUnderTest(ClosedPeriodGuardAdminMixin, _AdminBase):
    pass


class ClosingFixture(CompensationFixtureMixin, TestCase):
    """One collected visit, its consumption, pay and stock -- all booked into a PAST month."""

    def setUp(self):
        super().setUp()
        ensure_seed_categories()
        self.client = admin_client()
        self.admin_user = make_admin()
        make_rule()  # doctor: 50% of the collected revenue
        accounting.record_visit_consumption(self.visit, rate=RATE)
        payments.checkout(
            customer=self.customer, amount_usd=Decimal('200'),
            visit=self.visit, rate=RATE,
            components=[{'method': 'cash_toman', 'amount_usd': Decimal('200') * RATE}],
        )

        self.year, self.month = a_past_period()
        self.bounds = next(
            b for b in shamsi_months_of_year(self.year) if b['month'] == self.month
        )
        self.past_dt = self.bounds['start'] + (self.bounds['end'] - self.bounds['start']) / 2
        self.past_date = self.past_dt.date()

        # Everything above was created "now"; move the whole booking into the
        # past month so there is a real month to freeze.
        self.visit.start_at = self.past_dt - timedelta(hours=1)
        self.visit.end_at = self.past_dt
        self.visit.save(update_fields=['start_at', 'end_at'])
        Sale.objects.filter(visit=self.visit).update(created_at=self.past_dt)
        PaymentComponent.objects.filter(sale__visit=self.visit).update(created_at=self.past_dt)
        ProductUsage.objects.filter(visit=self.visit).update(created_at=self.past_dt)
        StaffPayout.objects.filter(visit=self.visit).update(created_at=self.past_dt)
        record_product_purchase(
            product=self.product, quantity=Decimal('4'), unit_cost_usd=Decimal('10'),
            supplier='Close Supplier', rate=RATE, purchase_date=self.past_date,
        )

        self.sale = Sale.objects.get(visit=self.visit)
        self.payout = StaffPayout.objects.get(visit=self.visit)

    def _close(self, *, year=None, month=None, note='', client=None):
        client = client or self.client
        return client.post(URL_CLOSE, {
            'year': self.year if year is None else year,
            'month': self.month if month is None else month,
            'note': note,
        }, format='json')

    def _reopen(self, *, year=None, month=None, reason='correction needed', client=None):
        client = client or self.client
        return client.post(URL_REOPEN, {
            'year': self.year if year is None else year,
            'month': self.month if month is None else month,
            'reason': reason,
        }, format='json')

    def _report(self, **query):
        query.setdefault('year', self.year)
        response = self.client.get(URL_REPORT, query)
        self.assertEqual(response.status_code, 200, response.data)
        return response.data

    def _month_row(self, payload=None, month=None):
        payload = self._report() if payload is None else payload
        month = self.month if month is None else month
        return next(row for row in payload['months'] if row['month'] == month)

    def _closing_events(self, prefix=''):
        """Audit events recorded against the closing ledger (closes, reopens, blocks)."""
        rows = AuditLog.objects.filter(model_name='finance.monthlyclose')
        events = [row.changes.get('event', '') for row in rows]
        if prefix:
            events = [e for e in events if e.startswith(prefix)]
        return events

    def _row(self):
        return closing.get_close_row(self.year, self.month)


class CloseFreezesTheMonthTests(ClosingFixture):
    def test_closing_a_past_month_freezes_it_and_writes_the_audit(self):
        response = self._close(note='oct books')
        self.assertEqual(response.status_code, 200, response.data)
        data = response.data

        self.assertEqual(data['period'], f'{self.year}-{self.month:02d}')
        self.assertEqual(data['status'], 'closed')
        self.assertFalse(data['already_closed'])
        self.assertEqual(data['closed_by'], 'sefro_admin')
        self.assertEqual(data['close_note'], 'oct books')
        self.assertIsNone(data['reopened_at'])

        row = self._row()
        self.assertEqual(row.status, MonthlyClose.Status.CLOSED)
        self.assertEqual(row.closed_by_id, self.admin_user.id)
        self.assertEqual(row.revenue_usd, Decimal('200.00'))
        self.assertEqual(row.net_profit_usd, Decimal('50.00'))
        self.assertEqual(row.purchases_usd, Decimal('40.00'))
        self.assertEqual(row.rate_used, RATE)

        payload = row.payload
        self.assertEqual(payload['revenue']['usd'], '200.00')
        self.assertEqual(payload['revenue']['toman'], '20000000.00')
        self.assertEqual(payload['net_profit']['usd'], '50.00')
        self.assertEqual(payload['purchases']['usd'], '40.00')
        self.assertIn('outstanding', payload)

        close_logs = AuditLog.objects.filter(
            model_name='finance.monthlyclose',
        )
        close_events = [row.changes.get('event') for row in close_logs]
        self.assertEqual(close_events.count('MONTHLY_CLOSE'), 1)
        log = next(row for row in close_logs if row.changes.get('event') == 'MONTHLY_CLOSE')
        self.assertEqual(log.user_id, self.admin_user.id)
        self.assertEqual(log.changes.get('note'), 'oct books')
        self.assertEqual(log.changes.get('period'), f'{self.year}-{self.month:02d}')

    def test_only_past_months_can_be_closed(self):
        today = shamsi_today()

        current = self._close(year=today.year, month=today.month)
        self.assertEqual(current.status_code, 400, current.data)
        self.assertIn('past months', str(current.data['error']))

        future = self._close(year=self.year + 1, month=1)
        self.assertEqual(future.status_code, 400, future.data)

        out_of_range = self.client.post(
            URL_CLOSE, {'year': self.year, 'month': 13}, format='json',
        )
        self.assertEqual(out_of_range.status_code, 400, out_of_range.data)

        self.assertEqual(MonthlyClose.objects.count(), 0)
        self.assertEqual(self._closing_events('MONTHLY_CLOSE'), [])

    def test_closing_twice_is_idempotent_and_keeps_the_first_snapshot(self):
        first = self._close(note='first close')
        self.assertEqual(first.status_code, 200, first.data)
        self.assertFalse(first.data['already_closed'])

        row = self._row()
        payload_before = dict(row.payload)
        closed_at = row.closed_at

        second = self._close(note='second attempt')
        self.assertEqual(second.status_code, 200, second.data)
        self.assertTrue(second.data['already_closed'])

        row.refresh_from_db()
        self.assertEqual(MonthlyClose.objects.count(), 1)
        self.assertEqual(row.payload, payload_before)
        self.assertEqual(row.closed_at, closed_at)
        self.assertEqual(row.close_note, 'first close')
        self.assertEqual(len(self._closing_events('MONTHLY_CLOSE')), 1)

    def test_close_reports_outstanding_obligations_but_never_blocks(self):
        expense = expense_svc.create_expense(
            created_by=self.staff,
            category=ExpenseCategory.objects.get(name='Transport'),
            amount_usd=Decimal('50.00'),
            expense_date=self.past_date,
        )
        expense_svc.submit_expense(expense)
        expense_svc.approve_expense(expense, self.admin_user)

        response = self._close()
        self.assertEqual(response.status_code, 200, response.data)

        outstanding = self._row().payload['outstanding']
        self.assertEqual(outstanding['unpaid_payouts']['count'], 1)
        self.assertEqual(outstanding['unpaid_payouts']['usd'], '100.00')
        self.assertEqual(outstanding['unpaid_claims']['count'], 1)
        self.assertEqual(outstanding['unpaid_claims']['usd'], '50.00')
        self.assertEqual(outstanding['unpaid_claims']['toman'], '5000000.00')

    def test_the_live_report_and_the_stored_snapshot_agree_at_close_time(self):
        before = self._month_row()

        self._close()
        after = self._month_row()
        row = self._row()

        for key in (
            'revenue', 'product_cost', 'gross_profit', 'staff_compensation_total',
            'operating_expenses', 'staff_expense_claims', 'net_profit', 'purchases',
            'net_profit_after_purchases', 'payout_total',
        ):
            with self.subTest(key=key):
                self.assertEqual(money(after[key]['usd']), money(before[key]['usd']))
        self.assertTrue(after['is_closed'])
        self.assertEqual(row.revenue_usd, money(before['revenue']['usd']))
        self.assertEqual(row.net_profit_usd, money(before['net_profit']['usd']))
        self.assertEqual(
            row.net_profit_after_purchases_usd,
            money(before['net_profit_after_purchases']['usd']),
        )


class ClosedMonthIsFrozenTests(ClosingFixture):
    def test_a_refund_of_a_closed_month_sale_is_blocked_until_reopened(self):
        self._close()

        blocked = self.client.post(
            f'{URL_SALES}{self.sale.id}/refund/',
            {'reason': 'not happy', 'refund_amount_usd': '200.00'},
            format='json',
        )
        self.assertEqual(blocked.status_code, 409, blocked.data)
        self.assertIn('closed', str(blocked.data['error']))

        self.sale.refresh_from_db()
        self.assertEqual(self.sale.status, Sale.Status.PAID)
        self.assertTrue(self._closing_events('BLOCKED:refund'))
        sale_events = [
            row.changes.get('event')
            for row in AuditLog.objects.filter(model_name='finance.sale')
        ]
        self.assertNotIn('SALE_REFUND', sale_events)

        reopened = self._reopen(reason='refund approved late')
        self.assertEqual(reopened.status_code, 200, reopened.data)

        allowed = self.client.post(
            f'{URL_SALES}{self.sale.id}/refund/',
            {'reason': 'not happy', 'refund_amount_usd': '200.00'},
            format='json',
        )
        self.assertEqual(allowed.status_code, 201, allowed.data)
        self.sale.refresh_from_db()
        self.assertEqual(self.sale.status, Sale.Status.REFUNDED)

    def test_every_expense_path_into_a_closed_month_is_refused(self):
        claim = expense_svc.create_expense(
            created_by=self.staff,
            category=ExpenseCategory.objects.get(name='Transport'),
            amount_usd=Decimal('10.00'),
            expense_date=self.past_date,
        )
        self._close()

        created = self.client.post(URL_EXPENSES, {
            'category': ExpenseCategory.objects.get(name='Transport').id,
            'amount_usd': '25.00',
            'expense_date': shamsi_str(self.past_date),
            'vendor': 'Late claim',
        }, format='json')
        self.assertEqual(created.status_code, 409, created.data)
        self.assertFalse(Expense.objects.filter(vendor='Late claim').exists())

        submitted = self.client.post(f'{URL_EXPENSES}{claim.id}/submit/', {}, format='json')
        self.assertEqual(submitted.status_code, 409, submitted.data)
        claim.refresh_from_db()
        self.assertEqual(claim.status, Expense.Status.DRAFT)

        patched = self.client.patch(
            f'{URL_EXPENSES}{claim.id}/', {'amount_usd': '99.00'}, format='json',
        )
        self.assertEqual(patched.status_code, 409, patched.data)
        claim.refresh_from_db()
        self.assertEqual(claim.amount_usd, Decimal('10.00'))

        deleted = self.client.delete(f'{URL_EXPENSES}{claim.id}/')
        self.assertEqual(deleted.status_code, 409, deleted.data)
        self.assertTrue(Expense.objects.filter(pk=claim.pk).exists())

        blocked = self._closing_events('BLOCKED:')
        self.assertTrue(any('expense' in event for event in blocked), blocked)

    def test_every_operating_expense_path_into_a_closed_month_is_refused(self):
        category = OperatingExpenseCategory.objects.first()
        expense = opex_svc.create_operating_expense(
            created_by=self.admin_user, category=category, title='Rent',
            amount_usd=Decimal('120.00'), expense_date=self.past_date,
        )
        self._close()

        created = self.client.post(URL_OPEX, {
            'category': category.id,
            'title': 'Late rent',
            'amount_usd': '50.00',
            'expense_date': shamsi_str(self.past_date),
        }, format='json')
        self.assertEqual(created.status_code, 409, created.data)
        self.assertFalse(OperatingExpense.objects.filter(title='Late rent').exists())

        patched = self.client.patch(
            f'{URL_OPEX}{expense.id}/', {'amount_usd': '150.00'}, format='json',
        )
        self.assertEqual(patched.status_code, 409, patched.data)
        expense.refresh_from_db()
        self.assertEqual(expense.amount_usd, Decimal('120.00'))

        deleted = self.client.delete(f'{URL_OPEX}{expense.id}/')
        self.assertEqual(deleted.status_code, 409, deleted.data)
        self.assertTrue(OperatingExpense.objects.filter(pk=expense.pk).exists())

        blocked = self._closing_events('BLOCKED:')
        self.assertTrue(any('operating expense' in event for event in blocked), blocked)

    def test_the_django_admin_cannot_rewrite_a_closed_month(self):
        claim = expense_svc.create_expense(
            created_by=self.staff,
            category=ExpenseCategory.objects.get(name='Transport'),
            amount_usd=Decimal('10.00'),
            expense_date=self.past_date,
        )
        self._close()

        request = RequestFactory().post('/admin/finance/sale/1/change/')
        request.user = self.admin_user
        admin_obj = _AdminUnderTest()

        with self.assertRaises(ValidationError):
            admin_obj.save_model(request, self.sale, form=None, change=True)
        self.assertFalse(hasattr(admin_obj, 'saved'))

        # Claims are anchored on expense_date, exactly as ExpenseAdmin
        # configures the guard (the default anchor is created_at).
        claim_admin = _AdminUnderTest()
        claim_admin.closed_anchor_field = 'expense_date'
        with self.assertRaises(ValidationError):
            claim_admin.delete_model(request, claim)
        self.assertTrue(Expense.objects.filter(pk=claim.pk).exists())

        with self.assertRaises(ValidationError):
            claim_admin.delete_queryset(request, Expense.objects.filter(pk=claim.pk))
        self.assertFalse(hasattr(claim_admin, 'deleted_pks'))

        # A refused attempt is a business event even though nothing changed.
        blocked = self._closing_events('BLOCKED:')
        self.assertTrue(any('sale' in event for event in blocked), blocked)
        self.assertTrue(any('expense' in event for event in blocked), blocked)

    def test_payout_cancellation_and_repricing_are_refused_in_a_closed_month(self):
        self._close()

        with self.assertRaises(PeriodClosedError):
            staff_compensation.cancel_payouts_for_visit(self.visit, reason='changed mind')
        self.payout.refresh_from_db()
        self.assertNotEqual(self.payout.status, StaffPayout.Status.CANCELLED)
        self.assertTrue(self._closing_events('BLOCKED:cancel a staff payout'))

        # A cheaper rule would silently re-price the unsettled payout booked
        # into the closed month; regeneration must refuse instead.
        make_rule(percent_revenue=Decimal('10.00'))
        with self.assertRaises(PeriodClosedError):
            staff_compensation.generate_visit_payouts(self.visit)
        self.payout.refresh_from_db()
        self.assertEqual(self.payout.payout_cash_usd, Decimal('100.00'))

    def test_backdated_purchases_cannot_enter_a_closed_month(self):
        self._close()

        created = self.client.post(URL_PURCHASES, {
            'product': self.product.id,
            'quantity': '2',
            'unit_cost_usd': '10.00',
            'purchase_date': shamsi_str(self.past_date),
            'supplier': 'Backdated Supplier',
        }, format='json')
        self.assertEqual(created.status_code, 409, created.data)
        self.assertFalse(ProductPurchase.objects.filter(supplier='Backdated Supplier').exists())
        self.assertTrue(self._closing_events('BLOCKED:record a product purchase'))

        order, _ = purchase_svc.create_purchase_order(
            items_data=[{
                'product': self.product.id, 'quantity': '3', 'unit_cost_usd': '8.00',
            }],
            supplier='PO Supplier',
        )
        with self.assertRaises(PeriodClosedError):
            purchase_svc.receive_purchase_order(order, received_date=self.past_date)
        order.refresh_from_db()
        self.assertNotEqual(order.status, PurchaseOrder.Status.RECEIVED)
        self.assertIsNone(order.received_date)

        # Receiving into an OPEN month still works while the past one is closed.
        purchase_svc.receive_purchase_order(order)
        order.refresh_from_db()
        self.assertEqual(order.status, PurchaseOrder.Status.RECEIVED)
        self.assertTrue(self._closing_events('BLOCKED:receive a purchase order'))


class ReopenTests(ClosingFixture):
    def test_reopening_requires_a_written_reason(self):
        self._close()

        with self.assertRaises(closing.ClosingError):
            closing.reopen_month(self.year, self.month, reason='   ')

        missing = self.client.post(
            URL_REOPEN, {'year': self.year, 'month': self.month}, format='json',
        )
        self.assertEqual(missing.status_code, 400, missing.data)
        self.assertIn('reason', missing.data)
        self.assertEqual(self._row().status, MonthlyClose.Status.CLOSED)

    def test_reopening_a_month_that_was_never_closed_is_refused(self):
        response = self._reopen(reason='no such month', year=1399, month=5)
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn('never been closed', str(response.data['error']))

    def test_reopen_keeps_the_row_and_audits_the_reason(self):
        self._close(note='first close')

        response = self._reopen(reason='late refund approved')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['status'], 'reopened')
        self.assertEqual(response.data['reopen_reason'], 'late refund approved')

        row = self._row()
        self.assertEqual(row.status, MonthlyClose.Status.REOPENED)
        self.assertEqual(row.reopen_reason, 'late refund approved')
        self.assertEqual(row.reopened_by_id, self.admin_user.id)
        self.assertEqual(row.close_note, 'first close')
        self.assertIn('revenue', row.payload)  # the snapshot survives reopening

        reopen_logs = AuditLog.objects.filter(model_name='finance.monthlyclose')
        self.assertEqual(
            [row.changes.get('event') for row in reopen_logs].count('MONTHLY_REOPEN'), 1,
        )
        log = next(row for row in reopen_logs if row.changes.get('event') == 'MONTHLY_REOPEN')
        self.assertEqual(log.user_id, self.admin_user.id)
        self.assertEqual(log.changes.get('reason'), 'late refund approved')

    def test_after_reopening_the_month_is_mutable_again_and_reported_live(self):
        self._close()

        while_closed = self.client.post(URL_EXPENSES, {
            'category': ExpenseCategory.objects.get(name='Transport').id,
            'amount_usd': '25.00',
            'expense_date': shamsi_str(self.past_date),
            'vendor': 'Blocked vendor',
        }, format='json')
        self.assertEqual(while_closed.status_code, 409, while_closed.data)

        self._reopen(reason='corrections')

        allowed = self.client.post(URL_EXPENSES, {
            'category': ExpenseCategory.objects.get(name='Transport').id,
            'amount_usd': '25.00',
            'expense_date': shamsi_str(self.past_date),
            'vendor': 'After reopen',
        }, format='json')
        self.assertEqual(allowed.status_code, 201, allowed.data)
        # Only approved claims count against profit, so take it through the
        # workflow now that the month is open again.
        claim = Expense.objects.get(vendor='After reopen')
        expense_svc.submit_expense(claim)
        expense_svc.approve_expense(claim, self.staff)  # not the creator

        self.assertEqual(self._row().payload['staff_expense_claims']['usd'], '0.00')
        live = self._month_row()
        self.assertFalse(live['is_closed'])
        self.assertTrue(live['was_reopened'])
        self.assertEqual(live['reopen_reason'], 'corrections')
        self.assertEqual(money(live['staff_expense_claims']['usd']), Decimal('25.00'))
        self.assertEqual(money(live['revenue']['usd']), Decimal('200.00'))

    def test_a_closed_month_stays_frozen_even_when_ledger_rows_change(self):
        self._close()

        # A raw ORM write (the one path services cannot intercept) must not
        # leak into the report: the month is served from its snapshot.
        Sale.objects.filter(pk=self.sale.pk).update(amount_usd=Decimal('999.00'))
        frozen = self._month_row()
        self.assertTrue(frozen['is_closed'])
        self.assertEqual(money(frozen['revenue']['usd']), Decimal('200.00'))
        self.assertEqual(self._row().revenue_usd, Decimal('200.00'))

        self._reopen(reason='legit edit')
        live = self._month_row()
        self.assertFalse(live['is_closed'])
        self.assertTrue(live['was_reopened'])
        self.assertEqual(money(live['revenue']['usd']), Decimal('999.00'))


class ReportConsistencyTests(ClosingFixture):
    def test_the_year_view_mixes_frozen_closed_and_live_rows(self):
        self._close()

        data = self._report()
        frozen = self._month_row(data)
        self.assertTrue(frozen['is_closed'])
        self.assertEqual(frozen['closed_by_name'], 'sefro_admin')
        self.assertIsNotNone(frozen['closed_at'])
        self.assertEqual(frozen['close_note'], '')

        current = next(row for row in data['months'] if row['is_current'])
        self.assertFalse(current['is_closed'])
        self.assertEqual(data['closed_month_count'], 1)

        # Frozen strings and live Decimals must add up in the same total.
        total = sum((money(row['revenue']['usd']) for row in data['months']), Decimal('0'))
        self.assertEqual(total, money(data['year_total']['revenue']['usd']))
        self.assertEqual(
            data['year_total']['payout_count'],
            sum(row['payout_total']['payout_count'] for row in data['months']),
        )

    def test_closing_one_month_leaves_every_other_month_mutable(self):
        self._close()

        in_open_month = self.client.post(URL_EXPENSES, {
            'category': ExpenseCategory.objects.get(name='Transport').id,
            'amount_usd': '15.00',
            'expense_date': shamsi_str(timezone.now()),
            'vendor': 'Still open',
        }, format='json')
        self.assertEqual(in_open_month.status_code, 201, in_open_month.data)

        data = self._report()
        others = [row for row in data['months'] if row['month'] != self.month]
        self.assertTrue(all(not row['is_closed'] for row in others))

    def test_paid_payouts_are_still_counted_exactly_once_in_the_snapshot(self):
        StaffPayout.objects.filter(pk=self.payout.pk).update(
            status=StaffPayout.Status.PAID,
        )
        self._close()

        payload = self._row().payload
        # Counted as owed while unpaid AND once it is paid: never twice, never zero.
        self.assertEqual(payload['staff_compensation_total']['usd'], '100.00')
        self.assertEqual(payload['payout_total']['usd'], '100.00')
        self.assertEqual(payload['payout_total']['payout_count'], 1)

    def test_the_unique_constraint_keeps_one_row_per_month(self):
        self._close()

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                MonthlyClose.objects.create(
                    shamsi_year=self.year, shamsi_month=self.month,
                )


class ClosingAccessTests(ClosingFixture):
    def test_anonymous_cannot_close_or_reopen(self):
        anonymous = APIClient()

        close = anonymous.post(
            URL_CLOSE, {'year': self.year, 'month': self.month}, format='json',
        )
        reopen = anonymous.post(URL_REOPEN, {
            'year': self.year, 'month': self.month, 'reason': 'x',
        }, format='json')

        self.assertEqual(close.status_code, 401)
        self.assertEqual(reopen.status_code, 401)
        self.assertEqual(MonthlyClose.objects.count(), 0)

    def test_a_non_admin_employee_can_close_and_reopen(self):
        employee = employee_client()

        closed = self._close(client=employee)
        self.assertEqual(closed.status_code, 200, closed.data)
        self.assertEqual(closed.data['closed_by'], 'emp_user')

        reopened = self._reopen(reason='employee correction', client=employee)
        self.assertEqual(reopened.status_code, 200, reopened.data)
        self.assertEqual(reopened.data['reopened_by'], 'emp_user')
        self.assertEqual(self._row().status, MonthlyClose.Status.REOPENED)
