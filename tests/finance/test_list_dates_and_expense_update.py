"""List endpoints honour their date parameters (P1 #8) and expense edits are
re-priced (P2 #9).

`date_from`/`date_to` are Jalali `YYYY-MM-DD` strings, matching the reports the
PWA already calls. The unfiltered list calls the PWA makes today must keep
working unchanged.
"""
from datetime import timedelta
from decimal import Decimal

import jdatetime
from django.test import TestCase
from django.utils import timezone

from customers.models import Service, Visit
from finance.models import Expense, ExpenseCategory, ProductUsage, StaffPayout
from finance.services.exchange_rates import set_rate
from inventory.models import Product
from tests.helpers import admin_client, make_customer, make_employee

RATE = Decimal('100000')
USAGES_URL = '/api/finance/product-usages/'
PAYOUTS_URL = '/api/finance/staff-payouts/'
EXPENSES_URL = '/api/finance/expenses/'


def shamsi_of(dt):
    return jdatetime.datetime.fromgregorian(datetime=dt).strftime('%Y-%m-%d')


class ListDateFilterTests(TestCase):
    def setUp(self):
        set_rate('USD', 'TOMAN', RATE, effective_at=timezone.now(), source='date-filter-test')
        self.client = admin_client()
        self.customer = make_customer()
        self.staff = make_employee()
        self.product = Product.objects.create(
            name='Filter item', sku='FILTER-1', unit_price=Decimal('5'),
            cost_usd=Decimal('2.00'), count=Decimal('10'),
        )
        self.service = Service.objects.create(name='Filter service', price_usd=Decimal('20'))
        now = timezone.now()
        # created_at is auto_now_add, so historical timestamps are set with an
        # explicit UPDATE (the ORM would ignore a value passed to create()).
        self.old_usage = ProductUsage.objects.create(
            product=self.product, quantity=Decimal('1'),
            unit_cost_usd_snapshot=Decimal('2.00'), total_cost_usd_snapshot=Decimal('2.00'),
        )
        self.new_usage = ProductUsage.objects.create(
            product=self.product, quantity=Decimal('1'),
            unit_cost_usd_snapshot=Decimal('2.00'), total_cost_usd_snapshot=Decimal('2.00'),
        )
        ProductUsage.objects.filter(pk=self.old_usage.pk).update(created_at=now - timedelta(days=40))
        ProductUsage.objects.filter(pk=self.new_usage.pk).update(created_at=now - timedelta(days=2))

        self.old_visit = Visit.objects.create(
            customer=self.customer, staff=self.staff, start_at=now - timedelta(days=40),
            end_at=now - timedelta(days=40) + timedelta(hours=1), status=Visit.Status.COMPLETED,
        )
        self.new_visit = Visit.objects.create(
            customer=self.customer, staff=self.staff, start_at=now - timedelta(days=2),
            end_at=now - timedelta(days=2) + timedelta(hours=1), status=Visit.Status.COMPLETED,
        )
        self.old_payout = StaffPayout.objects.create(
            staff=self.staff, visit=self.old_visit, service=self.service, role='doctor',
            revenue_usd=Decimal('20'), exchange_rate=RATE,
        )
        self.new_payout = StaffPayout.objects.create(
            staff=self.staff, visit=self.new_visit, service=self.service, role='doctor',
            revenue_usd=Decimal('20'), exchange_rate=RATE,
        )
        StaffPayout.objects.filter(pk=self.old_payout.pk).update(created_at=now - timedelta(days=40))
        StaffPayout.objects.filter(pk=self.new_payout.pk).update(created_at=now - timedelta(days=2))

    def _ids(self, url, response):
        self.assertEqual(response.status_code, 200, response.data)
        return {row['id'] for row in response.data['results']}

    # --- product usages ---------------------------------------------------

    def test_unfiltered_product_usage_list_is_unchanged(self):
        response = self.client.get(USAGES_URL)
        self.assertEqual(
            self._ids(USAGES_URL, response), {self.old_usage.id, self.new_usage.id},
        )

    def test_product_usages_respect_jalali_date_from(self):
        from_date = shamsi_of(timezone.now() - timedelta(days=10))
        response = self.client.get(USAGES_URL, {'date_from': from_date})
        self.assertEqual(self._ids(USAGES_URL, response), {self.new_usage.id})

    def test_product_usages_respect_jalali_date_to(self):
        to_date = shamsi_of(timezone.now() - timedelta(days=10))
        response = self.client.get(USAGES_URL, {'date_to': to_date})
        self.assertEqual(self._ids(USAGES_URL, response), {self.old_usage.id})

    def test_product_usages_respect_a_date_window(self):
        response = self.client.get(USAGES_URL, {
            'date_from': shamsi_of(timezone.now() - timedelta(days=50)),
            'date_to': shamsi_of(timezone.now()),
        })
        self.assertEqual(
            self._ids(USAGES_URL, response), {self.old_usage.id, self.new_usage.id},
        )

    def test_product_usage_date_filter_combines_with_existing_filters(self):
        from_date = shamsi_of(timezone.now() - timedelta(days=10))
        response = self.client.get(USAGES_URL, {'date_from': from_date, 'product': self.product.id})
        self.assertEqual(self._ids(USAGES_URL, response), {self.new_usage.id})

    # --- staff payouts ----------------------------------------------------

    def test_unfiltered_staff_payout_list_is_unchanged(self):
        response = self.client.get(PAYOUTS_URL)
        self.assertEqual(
            self._ids(PAYOUTS_URL, response), {self.old_payout.id, self.new_payout.id},
        )

    def test_staff_payouts_support_date_filtering(self):
        from_date = shamsi_of(timezone.now() - timedelta(days=10))
        response = self.client.get(PAYOUTS_URL, {'date_from': from_date})
        self.assertEqual(self._ids(PAYOUTS_URL, response), {self.new_payout.id})

        to_date = shamsi_of(timezone.now() - timedelta(days=10))
        response = self.client.get(PAYOUTS_URL, {'date_to': to_date})
        self.assertEqual(self._ids(PAYOUTS_URL, response), {self.old_payout.id})

    def test_staff_payout_date_filter_combines_with_existing_filters(self):
        from_date = shamsi_of(timezone.now() - timedelta(days=10))
        response = self.client.get(PAYOUTS_URL, {'date_from': from_date, 'staff': self.staff.id})
        self.assertEqual(self._ids(PAYOUTS_URL, response), {self.new_payout.id})

    def test_gregorian_start_date_alias_still_works(self):
        # start_date/end_date stay Gregorian, matching the report endpoints.
        three_days_ago = (timezone.localtime(timezone.now()) - timedelta(days=3)).date().isoformat()
        response = self.client.get(PAYOUTS_URL, {'start_date': three_days_ago})
        self.assertEqual(self._ids(PAYOUTS_URL, response), {self.new_payout.id})

    def test_gregorian_date_sent_as_jalali_is_rejected(self):
        # A Gregorian value must never be silently reinterpreted as a Jalali
        # year the way it was before the date contract was enforced.
        today = timezone.localtime(timezone.now()).date().isoformat()
        response = self.client.get(PAYOUTS_URL, {'date_from': today})
        self.assertEqual(response.status_code, 400)
        self.assertIn('Gregorian', str(response.data))


class ExpenseUpdateRepricingTests(TestCase):
    """P2 #9: changing amount_usd must re-derive amount_toman."""

    def setUp(self):
        set_rate('USD', 'TOMAN', RATE, effective_at=timezone.now(), source='expense-update-test')
        self.client = admin_client()
        self.category = ExpenseCategory.objects.get_or_create(name='Supplies')[0]

    def _create(self, amount='10.00'):
        return self.client.post(EXPENSES_URL, {
            'category': self.category.id, 'amount_usd': amount,
            'expense_date': timezone.localtime(timezone.now()).date().isoformat(),
            'vendor': 'Test vendor',
        }, format='json')

    def test_patch_recomputes_toman_from_the_new_usd_amount(self):
        created = self._create('10.00')
        self.assertEqual(created.status_code, 201, created.data)
        self.assertEqual(Decimal(created.data['amount_toman']), Decimal('1000000.00'))

        patched = self.client.patch(f'{EXPENSES_URL}{created.data["id"]}/', {
            'amount_usd': '25.50',
        }, format='json')

        self.assertEqual(patched.status_code, 200, patched.data)
        self.assertEqual(Decimal(patched.data['amount_usd']), Decimal('25.50'))
        self.assertEqual(Decimal(patched.data['amount_toman']), Decimal('2550000.00'))
        self.assertEqual(Decimal(patched.data['exchange_rate_snapshot']), RATE)

    def test_persisted_row_matches_the_response(self):
        created = self._create('10.00')
        self.client.patch(f'{EXPENSES_URL}{created.data["id"]}/', {'amount_usd': '7.00'}, format='json')
        expense = Expense.objects.get(pk=created.data['id'])
        self.assertEqual(expense.amount_usd, Decimal('7.00'))
        self.assertEqual(expense.amount_toman, Decimal('700000.00'))

    def test_put_recomputes_toman(self):
        created = self._create('10.00')
        payload = {
            'category': self.category.id, 'amount_usd': '12.00',
            'expense_date': timezone.localtime(timezone.now()).date().isoformat(),
            'vendor': 'Test vendor', 'status': created.data['status'],
        }
        response = self.client.put(f'{EXPENSES_URL}{created.data["id"]}/', payload, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(Decimal(response.data['amount_toman']), Decimal('1200000.00'))

    def test_unrelated_edit_does_not_reprice(self):
        created = self._create('10.00')
        patched = self.client.patch(
            f'{EXPENSES_URL}{created.data["id"]}/', {'vendor': 'New vendor'}, format='json',
        )
        self.assertEqual(patched.status_code, 200, patched.data)
        self.assertEqual(Decimal(patched.data['amount_toman']), Decimal('1000000.00'))

    def test_claiming_the_toman_amount_directly_is_still_ignored(self):
        created = self._create('10.00')
        patched = self.client.patch(
            f'{EXPENSES_URL}{created.data["id"]}/',
            {'amount_usd': '10.00', 'amount_toman': '9999999.00'},
            format='json',
        )
        self.assertEqual(patched.status_code, 200, patched.data)
        self.assertEqual(Decimal(patched.data['amount_toman']), Decimal('1000000.00'))

    def test_updated_amount_shows_up_in_the_reports(self):
        from finance.services import reporting

        created = self._create('10.00')
        expense = Expense.objects.get(pk=created.data['id'])
        expense.status = Expense.Status.APPROVED
        expense.save(update_fields=['status'])
        self.client.patch(f'{EXPENSES_URL}{created.data["id"]}/', {'amount_usd': '40.00'}, format='json')

        start, end = timezone.now() - timedelta(days=1), timezone.now() + timedelta(days=1)
        self.assertEqual(
            reporting.financial_summary(start, end)['expenses']['usd'], Decimal('40.00'),
        )
