"""Integration tests for OperatingExpense API endpoints.

Covers cross-cutting concerns: category linkage, filtering, search, ordering,
idempotency, receipt upload, and isolation from Expense/Wallet/Sale domains.
"""
from datetime import date
from decimal import Decimal

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
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
from finance.services.exchange_rates import set_rate
from tests.helpers import admin_client, employee_client, make_employee

RATE = Decimal('100000')


def make_opex_category(name='Test Category', slug='test-category', **overrides):
    base = {'name': name, 'slug': slug}
    base.update(overrides)
    return OperatingExpenseCategory.objects.create(**base)


class OperatingExpenseCategoryIntegrationTests(TestCase):
    """Category CRUD + linkage to expenses."""

    def setUp(self):
        self.client = admin_client()
        set_rate('USD', 'TOMAN', RATE)

    def test_admin_full_crud(self):
        created = self.client.post('/api/finance/operating-expense-categories/', {
            'name': 'Integration Test Supplies', 'slug': 'int-test-supplies', 'description': 'Pens, paper',
        }, format='json')
        self.assertEqual(created.status_code, 201, created.data)
        cat_id = created.data['id']

        # Seeded categories already exist, so count will be 11 (10 seeded + 1 new)
        listed = self.client.get('/api/finance/operating-expense-categories/')
        self.assertEqual(listed.data['count'], 11)

        updated = self.client.patch(f'/api/finance/operating-expense-categories/{cat_id}/', {'is_active': False}, format='json')
        self.assertEqual(updated.status_code, 200)
        self.assertFalse(updated.data['is_active'])

        deleted = self.client.delete(f'/api/finance/operating-expense-categories/{cat_id}/')
        self.assertEqual(deleted.status_code, 204)
        self.assertFalse(OperatingExpenseCategory.objects.filter(pk=cat_id).exists())

    def test_employee_can_create_category(self):
        emp = employee_client()
        resp = emp.post('/api/finance/operating-expense-categories/', {
            'name': 'Emp Category', 'slug': 'emp-category',
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)

    def test_employee_can_read_categories(self):
        make_opex_category()
        emp = employee_client()
        self.assertEqual(emp.get('/api/finance/operating-expense-categories/').status_code, 200)

    def test_delete_category_blocked_when_expenses_exist(self):
        cat = make_opex_category()
        emp = employee_client()
        emp.post('/api/finance/operating-expenses/', {
            'category': cat.id, 'title': 'Coffee', 'amount_usd': '10.00',
            'expense_date': date.today().isoformat(),
        }, format='json')
        resp = emp.delete(f'/api/finance/operating-expense-categories/{cat.id}/')
        self.assertEqual(resp.status_code, 400)
        self.assertTrue(OperatingExpenseCategory.objects.filter(pk=cat.id).exists())


class OperatingExpenseIntegrationTests(TestCase):
    """Expense CRUD + filters/search/ordering + idempotency + receipt."""

    def setUp(self):
        self.client = employee_client()
        set_rate('USD', 'TOMAN', RATE)
        self.category = make_opex_category()

    def _payload(self, **overrides):
        base = {
            'category': self.category.id,
            'title': 'Coffee and tea',
            'amount_usd': '25.00',
            'expense_date': date.today().isoformat(),
            'payment_method': 'cash',
        }
        base.update(overrides)
        return base

    def test_employee_full_crud(self):
        created = self.client.post('/api/finance/operating-expenses/', self._payload(), format='json')
        self.assertEqual(created.status_code, 201, created.data)
        opex_id = created.data['id']
        self.assertEqual(created.data['category_name'], self.category.name)
        self.assertEqual(Decimal(created.data['amount_toman']), Decimal('2500000.00'))

        detail = self.client.get(f'/api/finance/operating-expenses/{opex_id}/')
        self.assertEqual(detail.status_code, 200)

        updated = self.client.patch(f'/api/finance/operating-expenses/{opex_id}/', {'title': 'Tea only'}, format='json')
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.data['title'], 'Tea only')

        put = self.client.put(f'/api/finance/operating-expenses/{opex_id}/', self._payload(title='Full update'), format='json')
        self.assertEqual(put.status_code, 200)
        self.assertEqual(put.data['title'], 'Full update')

        deleted = self.client.delete(f'/api/finance/operating-expenses/{opex_id}/')
        self.assertEqual(deleted.status_code, 204)
        self.assertFalse(OperatingExpense.objects.filter(pk=opex_id).exists())

    def test_admin_full_crud(self):
        admin = admin_client()
        created = admin.post('/api/finance/operating-expenses/', self._payload(title='Rent'), format='json')
        self.assertEqual(created.status_code, 201, created.data)
        opex_id = created.data['id']
        self.assertEqual(admin.get(f'/api/finance/operating-expenses/{opex_id}/').status_code, 200)
        self.assertEqual(admin.patch(f'/api/finance/operating-expenses/{opex_id}/', {'vendor': 'Landlord'}, format='json').status_code, 200)
        self.assertEqual(admin.delete(f'/api/finance/operating-expenses/{opex_id}/').status_code, 204)

    def test_anonymous_rejected(self):
        anon = APIClient()
        self.assertEqual(anon.get('/api/finance/operating-expenses/').status_code, 401)
        self.assertEqual(anon.post('/api/finance/operating-expenses/', self._payload(), format='json').status_code, 401)

    def test_not_exposed_on_public_v2(self):
        anon = APIClient()
        self.assertEqual(anon.get('/api/v2/operating-expenses/').status_code, 404)

    def test_created_by_not_spoofable(self):
        admin_user = make_employee(username='other_admin')
        resp = self.client.post('/api/finance/operating-expenses/', self._payload(created_by=admin_user.id), format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        expense = OperatingExpense.objects.get(pk=resp.data['id'])
        self.assertEqual(expense.created_by.username, 'emp_user')

    def test_server_owned_fields_ignored(self):
        resp = self.client.post('/api/finance/operating-expenses/', self._payload(exchange_rate='1', amount_toman='1'), format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        expense = OperatingExpense.objects.get(pk=resp.data['id'])
        self.assertEqual(expense.exchange_rate, RATE)
        self.assertEqual(expense.amount_toman, Decimal('2500000.00'))

    def test_inactive_category_rejected(self):
        inactive = make_opex_category(name='Old', slug='old', is_active=False)
        resp = self.client.post('/api/finance/operating-expenses/', self._payload(category=inactive.id), format='json')
        self.assertEqual(resp.status_code, 400)

    def test_negative_amount_rejected(self):
        resp = self.client.post('/api/finance/operating-expenses/', self._payload(amount_usd='-5'), format='json')
        self.assertEqual(resp.status_code, 400)

    def test_invalid_payment_method_rejected(self):
        resp = self.client.post('/api/finance/operating-expenses/', self._payload(payment_method='wallet'), format='json')
        self.assertEqual(resp.status_code, 400)

    def test_idempotent_create(self):
        key = 'idem-opex-1'
        r1 = self.client.post('/api/finance/operating-expenses/', self._payload(idempotency_key=key), format='json')
        r2 = self.client.post('/api/finance/operating-expenses/', self._payload(idempotency_key=key), format='json')
        self.assertEqual(r1.status_code, 201)
        self.assertEqual(r2.status_code, 201)
        self.assertEqual(r1.data['id'], r2.data['id'])
        self.assertEqual(OperatingExpense.objects.count(), 1)

    def test_filters_and_search(self):
        other_cat = make_opex_category(name='Int Test Utilities', slug='int-test-utilities')
        self.client.post('/api/finance/operating-expenses/', self._payload(
            title='Coffee and tea', vendor='Corner Store', payment_method='cash',
        ), format='json')
        self.client.post('/api/finance/operating-expenses/', self._payload(
            category=other_cat.id, title='Electricity bill', vendor='Power Co',
            payment_method='bank_transfer',
        ), format='json')

        by_cat = self.client.get(f'/api/finance/operating-expenses/?category={other_cat.id}')
        self.assertEqual(by_cat.data['count'], 1)
        self.assertEqual(by_cat.data['results'][0]['title'], 'Electricity bill')

        by_method = self.client.get('/api/finance/operating-expenses/?payment_method=cash')
        self.assertEqual(by_method.data['count'], 1)

        other_emp = make_employee(username='other_emp')
        by_creator = self.client.get(f'/api/finance/operating-expenses/?created_by={other_emp.id}')
        self.assertEqual(by_creator.data['count'], 0)

        search = self.client.get('/api/finance/operating-expenses/?search=coffee')
        self.assertEqual(search.data['count'], 1)

        vendor_search = self.client.get('/api/finance/operating-expenses/?search=Power')
        self.assertEqual(vendor_search.data['count'], 1)

        today = date.today().isoformat()
        in_range = self.client.get(f'/api/finance/operating-expenses/?date_from={today}&date_to={today}')
        self.assertEqual(in_range.data['count'], 2)

        out_of_range = self.client.get('/api/finance/operating-expenses/?date_from=2000-01-01&date_to=2000-01-02')
        self.assertEqual(out_of_range.data['count'], 0)

    def test_ordering(self):
        self.client.post('/api/finance/operating-expenses/', self._payload(title='Small', amount_usd='5'), format='json')
        self.client.post('/api/finance/operating-expenses/', self._payload(title='Large', amount_usd='500'), format='json')
        resp = self.client.get('/api/finance/operating-expenses/?ordering=-amount_usd')
        self.assertEqual(resp.data['results'][0]['title'], 'Large')

    def test_summary_endpoint(self):
        self.client.post('/api/finance/operating-expenses/', self._payload(amount_usd='25'), format='json')
        self.client.post('/api/finance/operating-expenses/', self._payload(
            title='Electricity', amount_usd='75', payment_method='bank_transfer',
        ), format='json')
        resp = self.client.get('/api/finance/operating-expenses/summary/')
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(Decimal(resp.data['total_usd']), Decimal('100'))
        self.assertEqual(Decimal(resp.data['total_toman']), Decimal('10000000'))
        self.assertEqual(resp.data['count'], 2)
        methods = {row['payment_method']: Decimal(row['total_usd']) for row in resp.data['by_payment_method']}
        self.assertEqual(methods['cash'], Decimal('25'))
        self.assertEqual(methods['bank_transfer'], Decimal('75'))


class OperatingExpenseReceiptIntegrationTests(TestCase):
    """Receipt upload validation and storage path."""

    def setUp(self):
        self.client = employee_client()
        set_rate('USD', 'TOMAN', RATE)
        self.category = make_opex_category()

    @override_settings(MEDIA_ROOT='/tmp/test_media')
    def test_receipt_upload_saved_under_correct_path(self):
        upload = SimpleUploadedFile('receipt.txt', b'sample receipt', content_type='text/plain')
        resp = self.client.post('/api/finance/operating-expenses/', {
            'category': self.category.id,
            'title': 'Paper towels',
            'amount_usd': '12.50',
            'expense_date': date.today().isoformat(),
            'receipt': upload,
        }, format='multipart')
        self.assertEqual(resp.status_code, 201, resp.data)
        expense = OperatingExpense.objects.get(pk=resp.data['id'])
        self.assertTrue(expense.receipt.name.startswith('operating_expenses/'))
        self.assertTrue(resp.data['receipt'])


class OperatingExpenseIsolationTests(TestCase):
    """Verify OperatingExpense does not touch Wallet/Sale/PaymentComponent."""

    def setUp(self):
        self.client = employee_client()
        set_rate('USD', 'TOMAN', RATE)
        self.category = make_opex_category()

    def test_wallet_sale_payment_untouched(self):
        self.client.post('/api/finance/operating-expenses/', {
            'category': self.category.id, 'title': 'Coffee',
            'amount_usd': '25.00', 'expense_date': date.today().isoformat(),
        }, format='json')
        self.client.post('/api/finance/operating-expenses/', {
            'category': self.category.id, 'title': 'Rent',
            'amount_usd': '1000.00', 'expense_date': date.today().isoformat(),
        }, format='json')

        self.assertEqual(Wallet.objects.count(), 0)
        self.assertEqual(WalletTransaction.objects.count(), 0)
        self.assertEqual(Sale.objects.count(), 0)
        self.assertEqual(PaymentComponent.objects.count(), 0)

    def test_expense_domain_unchanged(self):
        exp_cat = ExpenseCategory.objects.create(name='Travel')
        self.client.post('/api/finance/expenses/', {
            'category': exp_cat.id, 'amount_usd': '50.00',
            'expense_date': date.today().isoformat(), 'vendor': 'Taxi',
        }, format='json')
        self.client.post('/api/finance/operating-expenses/', {
            'category': self.category.id, 'title': 'Office Supplies',
            'amount_usd': '30.00', 'expense_date': date.today().isoformat(),
        }, format='json')

        self.assertEqual(Expense.objects.count(), 1)
        self.assertEqual(OperatingExpense.objects.count(), 1)
        expense = Expense.objects.first()
        self.assertEqual(expense.status, 'draft')
        self.assertNotEqual(expense.created_by, None)

    def test_expense_listing_still_works(self):
        self.assertEqual(self.client.get('/api/finance/expenses/').status_code, 200)
        self.assertEqual(self.client.get('/api/finance/expense-categories/').status_code, 200)


class OperatingExpenseAuditIntegrationTests(TestCase):
    """Audit logging for create/update/delete."""

    def setUp(self):
        self.client = employee_client()
        set_rate('USD', 'TOMAN', RATE)
        self.category = make_opex_category()

    def test_audit_records_create_update_delete(self):
        from logs.models import AuditLog
        created = self.client.post('/api/finance/operating-expenses/', {
            'category': self.category.id, 'title': 'Printer toner',
            'amount_usd': '40.00', 'expense_date': date.today().isoformat(),
        }, format='json')
        opex_id = created.data['id']
        self.assertTrue(AuditLog.objects.filter(
            action='CREATE', model_name='finance.operatingexpense', object_id=opex_id,
        ).exists())

        self.client.patch(f'/api/finance/operating-expenses/{opex_id}/', {'title': 'Toner XL'}, format='json')
        self.assertTrue(AuditLog.objects.filter(
            action='UPDATE', model_name='finance.operatingexpense', object_id=opex_id,
        ).exists())

        self.client.delete(f'/api/finance/operating-expenses/{opex_id}/')
        self.assertTrue(AuditLog.objects.filter(
            action='DELETE', model_name='finance.operatingexpense', object_id=opex_id,
        ).exists())

    def test_audit_never_leaks_credentials(self):
        from logs.models import AuditLog
        self.client.post('/api/finance/operating-expenses/', {
            'category': self.category.id, 'title': 'Printer toner',
            'amount_usd': '40.00', 'expense_date': date.today().isoformat(),
        }, format='json')
        for row in AuditLog.objects.filter(model_name='finance.operatingexpense'):
            self.assertNotIn('password', row.changes)


class OperatingExpenseRateSnapshotTests(TestCase):
    """Exchange rate snapshot behavior — historical values never repriced."""

    def setUp(self):
        self.client = employee_client()
        self.category = make_opex_category()

    def test_rate_snapshot_on_create(self):
        set_rate('USD', 'TOMAN', Decimal('95000'))
        created = self.client.post('/api/finance/operating-expenses/', {
            'category': self.category.id, 'title': 'Test',
            'amount_usd': '10.00', 'expense_date': date.today().isoformat(),
        }, format='json')
        self.assertEqual(Decimal(created.data['exchange_rate']), Decimal('95000'))
        self.assertEqual(Decimal(created.data['amount_toman']), Decimal('950000.00'))

    def test_rate_change_does_not_reprice_history(self):
        set_rate('USD', 'TOMAN', Decimal('95000'))
        created = self.client.post('/api/finance/operating-expenses/', {
            'category': self.category.id, 'title': 'Test',
            'amount_usd': '10.00', 'expense_date': date.today().isoformat(),
        }, format='json')
        opex_id = created.data['id']
        Decimal(created.data['amount_toman'])
        original_rate = Decimal(created.data['exchange_rate'])

        set_rate('USD', 'TOMAN', Decimal('200000'))
        # Update amount — should use ORIGINAL rate
        updated = self.client.patch(f'/api/finance/operating-expenses/{opex_id}/', {'amount_usd': '20.00'}, format='json')
        self.assertEqual(updated.status_code, 200)
        # 20 USD * original 95000, NOT new 200000
        self.assertEqual(Decimal(updated.data['amount_toman']), Decimal('1900000.00'))
        self.assertEqual(Decimal(updated.data['exchange_rate']), original_rate)
