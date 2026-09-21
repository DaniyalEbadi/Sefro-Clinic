"""Tests for the OperatingExpense / OperatingExpenseCategory domain.

Covers the service layer, model/DB constraints, API CRUD for both roles,
filtering/searching, idempotency, audit logging, and regression checks that
the existing Expense/Wallet/Sale domains are untouched.
"""
from decimal import Decimal

from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from finance.models import (
    Expense,
    ExpenseCategory,
    OperatingExpense,
    OperatingExpenseCategory,
    PaymentComponent,
    Sale,
    Wallet,
    WalletTransaction,
)
from finance.services import operating_expenses as opex_svc
from finance.services.exchange_rates import set_rate
from logs.models import AuditLog
from tests.helpers import admin_client, employee_client, make_admin, make_employee

DEFAULT_RATE = Decimal('100000')


def make_category(name='Test Refreshments', slug='test-refreshments', **overrides):
    """Test category using non-seeded names/slugs.

    The data migration seeds 10 production categories (customer-refreshments,
    utilities, ...), so tests must avoid those exact name/slug values.
    """
    base = {'name': name, 'slug': slug}
    base.update(overrides)
    return OperatingExpenseCategory.objects.create(**base)


class OpexBase(TestCase):
    def setUp(self):
        set_rate('USD', 'TOMAN', DEFAULT_RATE, effective_at=timezone.now(), source='test')
        self.category = make_category()
        self.admin = make_admin()
        self.employee = make_employee()


class OperatingExpenseServiceTests(OpexBase):
    def _create(self, **overrides):
        payload = {
            'created_by': self.employee,
            'category': self.category,
            'title': 'Coffee and tea',
            'amount_usd': Decimal('25.00'),
            'expense_date': timezone.localdate(),
        }
        payload.update(overrides)
        return opex_svc.create_operating_expense(**payload)

    def test_create_snapshots_rate_and_toman(self):
        expense = self._create()
        self.assertEqual(expense.amount_usd, Decimal('25.00'))
        self.assertEqual(expense.exchange_rate, DEFAULT_RATE)
        self.assertEqual(expense.amount_toman, Decimal('2500000.00'))
        self.assertEqual(expense.created_by, self.employee)
        self.assertEqual(expense.payment_method, OperatingExpense.PaymentMethod.CASH)

    def test_history_not_repriced_after_rate_change(self):
        expense = self._create()
        set_rate('USD', 'TOMAN', Decimal('200000'), effective_at=timezone.now(), source='new')
        expense.refresh_from_db()
        self.assertEqual(expense.exchange_rate, DEFAULT_RATE)
        self.assertEqual(expense.amount_toman, Decimal('2500000.00'))

    def test_amount_update_uses_original_rate(self):
        expense = self._create()
        set_rate('USD', 'TOMAN', Decimal('200000'), effective_at=timezone.now(), source='new')
        opex_svc.update_operating_expense(expense, amount_usd=Decimal('50.00'))
        expense.refresh_from_db()
        # 50 USD * the ORIGINAL 100000 snapshot, never today's 200000.
        self.assertEqual(expense.amount_toman, Decimal('5000000.00'))
        self.assertEqual(expense.exchange_rate, DEFAULT_RATE)

    def test_inactive_category_rejected_on_create(self):
        inactive = make_category(name='Old', slug='old', is_active=False)
        with self.assertRaises(opex_svc.OperatingExpenseError):
            self._create(category=inactive)

    def test_inactive_category_rejected_on_move(self):
        expense = self._create()
        inactive = make_category(name='Old', slug='old', is_active=False)
        with self.assertRaises(opex_svc.OperatingExpenseError):
            opex_svc.update_operating_expense(expense, category=inactive)

    def test_negative_amount_rejected(self):
        with self.assertRaises(opex_svc.OperatingExpenseError):
            self._create(amount_usd=Decimal('-1.00'))

    def test_zero_amount_allowed_matching_expense_convention(self):
        expense = self._create(amount_usd=Decimal('0'))
        self.assertEqual(expense.amount_usd, Decimal('0'))
        self.assertEqual(expense.amount_toman, Decimal('0'))

    def test_idempotency_key_returns_existing(self):
        first = self._create(idempotency_key='opex-test-1')
        second = self._create(title='Duplicate attempt', idempotency_key='opex-test-1')
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(OperatingExpense.objects.count(), 1)

    def test_delete_service_removes_row(self):
        expense = self._create()
        opex_svc.delete_operating_expense(expense)
        self.assertEqual(OperatingExpense.objects.count(), 0)



class OperatingExpenseConstraintTests(OpexBase):
    def test_category_name_unique(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            OperatingExpenseCategory.objects.create(name='Test Refreshments', slug='another-slug')

    def test_category_slug_unique(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            OperatingExpenseCategory.objects.create(name='Another Name', slug='test-refreshments')

    def test_negative_amount_blocked_by_db_constraint(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            OperatingExpense.objects.create(
                category=self.category,
                title='Bad row',
                amount_usd=Decimal('-0.01'),
                amount_toman=Decimal('0'),
                expense_date=timezone.localdate(),
            )

    def test_category_delete_blocked_by_protect(self):
        opex_svc.create_operating_expense(
            created_by=self.admin, category=self.category, title='Coffee',
            amount_usd=Decimal('10'), expense_date=timezone.localdate(),
        )
        with self.assertRaises(ProtectedError):
            self.category.delete()



class OperatingExpenseApiTests(OpexBase):
    def _payload(self, **overrides):
        payload = {
            'category': self.category.id,
            'title': 'Coffee and tea',
            'amount_usd': '25.00',
            'expense_date': timezone.localdate().isoformat(),
            'payment_method': OperatingExpense.PaymentMethod.CASH,
        }
        payload.update(overrides)
        return payload

    def test_requires_authentication(self):
        anon = APIClient()
        self.assertEqual(anon.get('/api/finance/operating-expenses/').status_code, 401)
        self.assertEqual(anon.post('/api/finance/operating-expenses/', self._payload(), format='json').status_code, 401)
        self.assertEqual(anon.get('/api/finance/operating-expense-categories/').status_code, 401)

    def test_not_exposed_on_public_v2_api(self):
        anon = APIClient()
        self.assertEqual(anon.get('/api/v2/operating-expenses/').status_code, 404)

    def test_employee_create_read_update_delete_expense(self):
        client = employee_client()
        created = client.post('/api/finance/operating-expenses/', self._payload(), format='json')
        self.assertEqual(created.status_code, 201, created.data)
        self.assertEqual(created.data['category_name'], self.category.name)
        self.assertEqual(Decimal(created.data['exchange_rate']), DEFAULT_RATE)
        self.assertEqual(Decimal(created.data['amount_toman']), Decimal('2500000.00'))

        opex_id = created.data['id']
        detail = client.get(f'/api/finance/operating-expenses/{opex_id}/')
        self.assertEqual(detail.status_code, 200)

        updated = client.patch(
            f'/api/finance/operating-expenses/{opex_id}/', {'title': 'Tea only'}, format='json',
        )
        self.assertEqual(updated.status_code, 200, updated.data)
        self.assertEqual(updated.data['title'], 'Tea only')

        put = client.put(
            f'/api/finance/operating-expenses/{opex_id}/', self._payload(title='Full update'), format='json',
        )
        self.assertEqual(put.status_code, 200, put.data)
        self.assertEqual(put.data['title'], 'Full update')

        deleted = client.delete(f'/api/finance/operating-expenses/{opex_id}/')
        self.assertEqual(deleted.status_code, 204)
        self.assertFalse(OperatingExpense.objects.filter(pk=opex_id).exists())

    def test_admin_create_read_update_delete_expense(self):
        client = admin_client()
        created = client.post('/api/finance/operating-expenses/', self._payload(title='Rent'), format='json')
        self.assertEqual(created.status_code, 201, created.data)
        opex_id = created.data['id']
        self.assertEqual(client.get(f'/api/finance/operating-expenses/{opex_id}/').status_code, 200)
        patch = client.patch(
            f'/api/finance/operating-expenses/{opex_id}/', {'vendor': 'Landlord'}, format='json',
        )
        self.assertEqual(patch.status_code, 200, patch.data)
        self.assertEqual(client.delete(f'/api/finance/operating-expenses/{opex_id}/').status_code, 204)

    def test_employee_full_crud_categories(self):
        client = employee_client()
        created = client.post(
            '/api/finance/operating-expense-categories/',
            {'name': 'Delivery Supplies', 'slug': 'delivery-supplies'},
            format='json',
        )
        self.assertEqual(created.status_code, 201, created.data)
        cat_id = created.data['id']
        self.assertEqual(client.get(f'/api/finance/operating-expense-categories/{cat_id}/').status_code, 200)
        patched = client.patch(
            f'/api/finance/operating-expense-categories/{cat_id}/', {'is_active': False}, format='json',
        )
        self.assertEqual(patched.status_code, 200, patched.data)
        self.assertFalse(patched.data['is_active'])
        self.assertEqual(client.delete(f'/api/finance/operating-expense-categories/{cat_id}/').status_code, 204)

    def test_created_by_cannot_be_spoofed(self):
        client = employee_client()
        spoof = self._payload(created_by=self.admin.id)
        resp = client.post('/api/finance/operating-expenses/', spoof, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        expense = OperatingExpense.objects.get(pk=resp.data['id'])
        self.assertEqual(expense.created_by.username, 'emp_user')

    def test_server_owned_fields_ignored_from_client(self):
        client = employee_client()
        payload = self._payload(exchange_rate='1', amount_toman='1')
        resp = client.post('/api/finance/operating-expenses/', payload, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        expense = OperatingExpense.objects.get(pk=resp.data['id'])
        self.assertEqual(expense.exchange_rate, DEFAULT_RATE)
        self.assertEqual(expense.amount_toman, Decimal('2500000.00'))

    def test_invalid_category_rejected(self):
        client = employee_client()
        resp = client.post('/api/finance/operating-expenses/', self._payload(category=999999), format='json')
        self.assertEqual(resp.status_code, 400)

    def test_inactive_category_rejected(self):
        inactive = make_category(name='Old', slug='old', is_active=False)
        client = employee_client()
        resp = client.post('/api/finance/operating-expenses/', self._payload(category=inactive.id), format='json')
        self.assertEqual(resp.status_code, 400)

    def test_negative_amount_rejected(self):
        client = employee_client()
        resp = client.post('/api/finance/operating-expenses/', self._payload(amount_usd='-5'), format='json')
        self.assertEqual(resp.status_code, 400)

    def test_invalid_payment_method_rejected(self):
        client = employee_client()
        resp = client.post('/api/finance/operating-expenses/', self._payload(payment_method='wallet'), format='json')
        self.assertEqual(resp.status_code, 400)

    def test_idempotent_create_via_api(self):
        client = employee_client()
        first = client.post('/api/finance/operating-expenses/', self._payload(idempotency_key='retry-1'), format='json')
        second = client.post('/api/finance/operating-expenses/', self._payload(idempotency_key='retry-1'), format='json')
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 201)
        self.assertEqual(first.data['id'], second.data['id'])
        self.assertEqual(OperatingExpense.objects.count(), 1)

    def test_category_delete_blocked_when_used(self):
        client = employee_client()
        client.post('/api/finance/operating-expenses/', self._payload(), format='json')
        resp = client.delete(f'/api/finance/operating-expense-categories/{self.category.id}/')
        self.assertEqual(resp.status_code, 400)
        self.assertTrue(OperatingExpenseCategory.objects.filter(pk=self.category.id).exists())

    def test_filters_and_search(self):
        client = employee_client()
        other_category = make_category(name='Test Utilities', slug='test-utilities')
        client.post('/api/finance/operating-expenses/', self._payload(
            title='Coffee and tea', vendor='Corner Store', payment_method='cash',
        ), format='json')
        client.post('/api/finance/operating-expenses/', self._payload(
            category=other_category.id, title='Electricity bill', vendor='Power Co',
            payment_method='bank_transfer',
        ), format='json')

        by_category = client.get(f'/api/finance/operating-expenses/?category={other_category.id}')
        self.assertEqual(by_category.data['count'], 1)
        self.assertEqual(by_category.data['results'][0]['title'], 'Electricity bill')

        by_method = client.get('/api/finance/operating-expenses/?payment_method=cash')
        self.assertEqual(by_method.data['count'], 1)

        creator = make_employee(username='other_emp')
        by_creator = client.get(f'/api/finance/operating-expenses/?created_by={creator.id}')
        self.assertEqual(by_creator.data['count'], 0)

        by_search = client.get('/api/finance/operating-expenses/?search=coffee')
        self.assertEqual(by_search.data['count'], 1)

        by_vendor = client.get('/api/finance/operating-expenses/?search=Power')
        self.assertEqual(by_vendor.data['count'], 1)

        today = timezone.localdate().isoformat()
        in_range = client.get(f'/api/finance/operating-expenses/?date_from={today}&date_to={today}')
        self.assertEqual(in_range.data['count'], 2)

        out_of_range = client.get('/api/finance/operating-expenses/?date_from=2000-01-01&date_to=2000-01-02')
        self.assertEqual(out_of_range.data['count'], 0)

    def test_ordering(self):
        client = employee_client()
        client.post('/api/finance/operating-expenses/', self._payload(title='Small', amount_usd='5'), format='json')
        client.post('/api/finance/operating-expenses/', self._payload(title='Large', amount_usd='500'), format='json')
        resp = client.get('/api/finance/operating-expenses/?ordering=-amount_usd')
        self.assertEqual(resp.data['results'][0]['title'], 'Large')

    def test_summary_endpoint(self):
        client = employee_client()
        client.post('/api/finance/operating-expenses/', self._payload(amount_usd='25'), format='json')
        client.post('/api/finance/operating-expenses/', self._payload(
            title='Electricity', amount_usd='75', payment_method='bank_transfer',
        ), format='json')
        resp = client.get('/api/finance/operating-expenses/summary/')
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(Decimal(resp.data['total_usd']), Decimal('100'))
        self.assertEqual(Decimal(resp.data['total_toman']), Decimal('10000000'))
        self.assertEqual(resp.data['count'], 2)
        methods = {row['payment_method']: Decimal(row['total_usd']) for row in resp.data['by_payment_method']}
        self.assertEqual(methods['cash'], Decimal('25'))
        self.assertEqual(methods['bank_transfer'], Decimal('75'))


    def test_search_with_sql_metacharacters_is_safe(self):
        client = employee_client()
        client.post('/api/finance/operating-expenses/', self._payload(), format='json')
        resp = client.get("/api/finance/operating-expenses/?search=' OR 1=1--")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['count'], 0)


class OperatingExpenseAuditAndIsolationTests(OpexBase):
    def _payload(self, **overrides):
        payload = {
            'category': self.category.id,
            'title': 'Printer toner',
            'amount_usd': '40.00',
            'expense_date': timezone.localdate().isoformat(),
        }
        payload.update(overrides)
        return payload

    def test_audit_log_records_create_update_delete(self):
        client = employee_client()
        created = client.post('/api/finance/operating-expenses/', self._payload(), format='json')
        opex_id = created.data['id']
        self.assertTrue(AuditLog.objects.filter(
            action='CREATE', model_name='finance.operatingexpense', object_id=opex_id,
        ).exists())

        client.patch(f'/api/finance/operating-expenses/{opex_id}/', {'title': 'Toner XL'}, format='json')
        self.assertTrue(AuditLog.objects.filter(
            action='UPDATE', model_name='finance.operatingexpense', object_id=opex_id,
        ).exists())

        client.delete(f'/api/finance/operating-expenses/{opex_id}/')
        self.assertTrue(AuditLog.objects.filter(
            action='DELETE', model_name='finance.operatingexpense', object_id=opex_id,
        ).exists())

    def test_audit_log_never_leaks_credentials(self):
        # Existing global rule: password column is never captured. Sanity-check
        # that creating an operating expense writing audit rows does not store
        # credential-like data.
        client = employee_client()
        client.post('/api/finance/operating-expenses/', self._payload(), format='json')
        for row in AuditLog.objects.filter(model_name='finance.operatingexpense'):
            self.assertNotIn('password', row.changes)

    def test_wallet_sale_and_payments_untouched(self):
        client = employee_client()
        client.post('/api/finance/operating-expenses/', self._payload(), format='json')
        client.post('/api/finance/operating-expenses/', self._payload(title='Rent', amount_usd='1000'), format='json')
        self.assertEqual(Wallet.objects.count(), 0)
        self.assertEqual(WalletTransaction.objects.count(), 0)
        self.assertEqual(Sale.objects.count(), 0)
        self.assertEqual(PaymentComponent.objects.count(), 0)

    def test_existing_expense_workflow_regression(self):
        """The employee expense-claim domain must behave exactly as before."""
        category = ExpenseCategory.objects.create(name='Supplies')
        client = employee_client()
        created = client.post('/api/finance/expenses/', {
            'category': category.id,
            'amount_usd': '15.00',
            'expense_date': timezone.localdate().isoformat(),
            'vendor': 'Stationery Shop',
        }, format='json')
        self.assertEqual(created.status_code, 201, created.data)
        self.assertEqual(created.data['status'], 'draft')
        expense = Expense.objects.get(pk=created.data['id'])
        self.assertEqual(expense.status, Expense.Status.DRAFT)
        # Expense and OperatingExpense must not share data.
        self.assertEqual(OperatingExpense.objects.count(), 0)
        self.assertEqual(Expense.objects.count(), 1)

    def test_existing_expense_listing_still_works(self):
        client = employee_client()
        resp = client.get('/api/finance/expenses/')
        self.assertEqual(resp.status_code, 200)
        resp = client.get('/api/finance/expense-categories/')
        self.assertEqual(resp.status_code, 200)


class OperatingExpenseReceiptTests(OpexBase):
    def test_receipt_upload_saved_under_operating_expenses_path(self):
        import tempfile
        with tempfile.TemporaryDirectory() as media_root:
            with override_settings(MEDIA_ROOT=media_root):
                client = employee_client()
                upload = SimpleUploadedFile('receipt.txt', b'sample receipt', content_type='text/plain')
                resp = client.post('/api/finance/operating-expenses/', {
                    'category': self.category.id,
                    'title': 'Paper towels',
                    'amount_usd': '12.50',
                    'expense_date': timezone.localdate().isoformat(),
                    'receipt': upload,
                }, format='multipart')
                self.assertEqual(resp.status_code, 201, resp.data)
                expense = OperatingExpense.objects.get(pk=resp.data['id'])
                self.assertTrue(expense.receipt.name.startswith('operating_expenses/'))
                self.assertTrue(resp.data['receipt'])



class OperatingExpenseSeedMigrationTests(TestCase):
    """The data migration seeds deterministic production categories."""

    EXPECTED = {
        'office-supplies', 'cleaning-hygiene', 'customer-refreshments',
        'utilities', 'rent', 'maintenance-repairs', 'marketing',
        'equipment', 'internet-telephone', 'other',
    }

    def test_seeded_categories_present_and_active(self):
        slugs = set(OperatingExpenseCategory.objects.values_list('slug', flat=True))
        self.assertTrue(self.EXPECTED.issubset(slugs), self.EXPECTED - slugs)
        self.assertFalse(
            OperatingExpenseCategory.objects.filter(slug__in=self.EXPECTED, is_active=False).exists()
        )

    def test_seeded_categories_ordered_deterministically(self):
        first = OperatingExpenseCategory.objects.filter(slug__in=self.EXPECTED).first()
        self.assertEqual(first.slug, 'office-supplies')

