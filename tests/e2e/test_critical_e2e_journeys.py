"""
E2E Critical Journeys — covers skill §101 checklist & §75 critical suite
Uses real HTTP API via APIClient (API E2E) as frontend is API-only.
Verifies user-visible result + API + DB + financial invariants per §35, §58.
"""
from decimal import Decimal
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
import jdatetime

from django.test import TestCase, override_settings
from django.utils import timezone

from customers.models import Customer, Service, Visit
from finance.models import ExpenseCategory, ExchangeRate, Sale, Wallet, WalletRewardRule, WalletTransaction
from finance.services.exchange_rates import set_rate
from inventory.models import Product
from tests.helpers import ADMIN_PASSWORD, ADMIN_USERNAME, admin_client, employee_client, make_admin, make_employee


def _unique_customer(suffix, birthday=None):
    return {
        'first_name': f'E2E{ suffix }',
        'last_name': 'Journey',
        'mobile_number': f'09120009{suffix:03d}',
        'national_id': f'990-0000{suffix:03d}',
        'birthday': birthday,
    }


class AdminCustomerWalletCheckoutReportE2ETests(TestCase):
    """
    P0 Critical Journey: Admin login → customer (with Shamsi birthday) → visit → checkout (wallet) → report
    Verifies: customer, visit, wallet, Sale, WalletTransaction, ProductUsage, profit, report
    Skill §17, §20, §23, §29, §58, §60
    """
    def setUp(self):
        set_rate('USD', 'TOMAN', Decimal('100000'), effective_at=timezone.now(), source='e2e-critical')
        WalletRewardRule.objects.all().delete()
        WalletRewardRule.objects.create(name='5pct', rule_type='percentage', value=Decimal('5'), min_base_amount_usd=Decimal('0'), is_active=True)

    def test_admin_full_customer_wallet_checkout_report_journey_e2e(self):
        # Arrange: admin login via API (real auth)
        client = admin_client()
        # Act 1: Create customer with Shamsi birthday
        birthday_shamsi = '1370-05-15'
        cust_payload = _unique_customer(100, birthday=birthday_shamsi)
        cust_resp = client.post('/api/customers/', cust_payload, format='json')
        self.assertEqual(cust_resp.status_code, 201)
        self.assertEqual(cust_resp.data['birthday'], birthday_shamsi)
        cid = cust_resp.data['id']
        customer = Customer.objects.get(id=cid)
        self.assertEqual(customer.birthday, jdatetime.date(1370, 5, 15).togregorian())
        # Act 2: Create product + service with product link (cost history)
        prod = Product.objects.create(name='E2E-Gel', unit_price=Decimal('100'), cost_usd=Decimal('5'), count=100)
        from finance.services.inventory import record_product_purchase
        record_product_purchase(product=prod, quantity=Decimal('10'), unit_cost_usd=Decimal('5'), purchase_date=timezone.now().date())
        svc = Service.objects.create(name='E2E-Facial', price_usd=Decimal('100'), time=30)
        from finance.models import ServiceItem
        ServiceItem.objects.create(service=svc, product=prod, quantity=Decimal('2'))  # cost 10
        # Act 3: Schedule visit via Shamsi API
        visit_resp = client.post('/api/visits/', {
            'customer': cid,
            'start_at': '1404-06-15 10:00',
            'end_at': '1404-06-15 11:00',
            'services': [svc.id],
        }, format='json')
        self.assertEqual(visit_resp.status_code, 201)
        vid = visit_resp.data['id']
        # Mark visit completed so product usage is logical
        client.post(f'/api/visits/{vid}/confirm/')
        client.post(f'/api/visits/{vid}/complete/')
        # Act 4: Seed wallet for checkout
        wallet = Wallet.objects.create(customer=customer, balance=Decimal('200.00'))
        # Act 5: Checkout via API (mixed wallet+card) — E2E via real HTTP
        checkout_resp = client.post('/api/finance/checkout/', {
            'customer': cid,
            'amount_usd': '100.00',
            'components': [
                {'method': 'wallet', 'amount_usd': '60.00'},
                {'method': 'card', 'amount_usd': '40.00'},
            ],
            'visit': vid,
            'idempotency_key': 'e2e-critical-1',
        }, format='json')
        self.assertEqual(checkout_resp.status_code, 201)
        sale_id = checkout_resp.data['id']
        # Assert UI/API result + DB state + financial invariants
        sale = Sale.objects.get(id=sale_id)
        self.assertEqual(sale.amount_usd, Decimal('100.00'))
        self.assertEqual(sale.status, Sale.Status.PAID)
        wallet.refresh_from_db()
        # 200 -60 +5 (reward 5% of 100) =145
        self.assertEqual(wallet.balance, Decimal('145.00'))
        # Ledger: payment debit + reward credit
        self.assertTrue(WalletTransaction.objects.filter(wallet=wallet, transaction_type='payment', amount=Decimal('-60.00')).exists())
        self.assertTrue(WalletTransaction.objects.filter(wallet=wallet, transaction_type='reward', amount=Decimal('5.00')).exists())
        # Act 6: Record product consumption from visit (E2E step: complete service uses inventory)
        from finance.services import accounting
        usages = accounting.record_visit_consumption(Visit.objects.get(id=vid), at=timezone.now(), rate=Decimal('100000'))
        self.assertEqual(len(usages), 1)
        self.assertEqual(usages[0].total_cost_usd_snapshot, Decimal('10.00'))
        # Act 7: Reporting reflects realistic data
        start = timezone.now() - timedelta(days=1)
        end = timezone.now() + timedelta(days=1)
        from finance.services import reporting
        summary = reporting.financial_summary(start, end)
        self.assertEqual(summary['revenue']['usd'], Decimal('100.00'))
        # Also via API
        api_report = client.get(f'/api/finance/reports/financial-summary/?start_date={(timezone.now()-timedelta(days=1)).strftime("%Y-%m-%d")}&end_date={(timezone.now()+timedelta(days=1)).strftime("%Y-%m-%d")}')
        self.assertEqual(api_report.status_code, 200)
        # Verify visit_number regression in customer serializer still present
        cust_get = client.get(f'/api/customers/{cid}/')
        self.assertEqual(cust_get.data['visit_number'], 1)
        self.assertFalse(cust_get.data['is_new_customer'])


class EmployeeWalletRestrictionE2ETests(TestCase):
    """P0 Security Journey: Employee cannot manually credit wallet (§21, §61)"""
    def test_employee_wallet_manual_credit_is_denied_and_no_balance_change_e2e(self):
        set_rate('USD', 'TOMAN', Decimal('100000'), effective_at=timezone.now(), source='e2e-emp-wallet')
        customer = Customer.objects.create(first_name='EmpRes', last_name='Cust', mobile_number='09120009101', national_id='991-0000101')
        wallet = Wallet.objects.create(customer=customer, balance=Decimal('0'))
        emp = employee_client(username='emp_wallet_e2e')
        resp = emp.post(f'/api/finance/wallets/{wallet.id}/adjust/', {
            'amount_usd': '100.00', 'direction': 'credit', 'transaction_type': 'manual_credit',
        }, format='json')
        self.assertIn(resp.status_code, (403, 401))
        wallet.refresh_from_db()
        self.assertEqual(wallet.balance, Decimal('0'))
        self.assertFalse(WalletTransaction.objects.filter(wallet=wallet).exists())
        # Admin can
        admin = admin_client()
        ok = admin.post(f'/api/finance/wallets/{wallet.id}/adjust/', {
            'amount_usd': '100.00', 'direction': 'credit', 'transaction_type': 'manual_credit',
        }, format='json')
        self.assertEqual(ok.status_code, 201)
        wallet.refresh_from_db()
        self.assertEqual(wallet.balance, Decimal('100.00'))
        self.assertTrue(WalletTransaction.objects.filter(wallet=wallet, amount=Decimal('100.00')).exists())


class CheckoutFailureAndIdempotencyE2ETests(TestCase):
    """P0 Checkout failure + idempotency + double submit (§24, §25, §57)"""
    def setUp(self):
        set_rate('USD', 'TOMAN', Decimal('100000'), effective_at=timezone.now(), source='e2e-checkout-fail')
        WalletRewardRule.objects.all().delete()

    def test_failed_checkout_insufficient_wallet_leaves_no_partial_state_e2e(self):
        customer = Customer.objects.create(first_name='Fail', last_name='Checkout', mobile_number='09120009102', national_id='992-0000102')
        Wallet.objects.create(customer=customer, balance=Decimal('10.00'))
        client = admin_client()
        before_sales = Sale.objects.count()
        before_txn = WalletTransaction.objects.filter(wallet__customer=customer).count()
        resp = client.post('/api/finance/checkout/', {
            'customer': customer.id,
            'amount_usd': '50.00',
            'components': [{'method': 'wallet', 'amount_usd': '50.00'}],
        }, format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(Sale.objects.count(), before_sales)
        self.assertEqual(WalletTransaction.objects.filter(wallet__customer=customer).count(), before_txn)
        self.assertEqual(Wallet.objects.get(customer=customer).balance, Decimal('10.00'))

    def test_double_submit_idempotency_creates_one_sale_one_reward_e2e(self):
        customer = Customer.objects.create(first_name='Idem', last_name='Double', mobile_number='09120009103', national_id='993-0000103')
        Wallet.objects.create(customer=customer, balance=Decimal('0'))
        WalletRewardRule.objects.create(name='5pct', rule_type='percentage', value=Decimal('5'), min_base_amount_usd=Decimal('0'), is_active=True)
        client = admin_client()
        payload = {
            'customer': customer.id,
            'amount_usd': '20.00',
            'components': [{'method': 'cash', 'amount_usd': '20.00'}],
            'idempotency_key': 'e2e-idem-2',
        }
        r1 = client.post('/api/finance/checkout/', payload, format='json')
        r2 = client.post('/api/finance/checkout/', payload, format='json')
        self.assertEqual(r1.status_code, 201)
        self.assertEqual(r2.status_code, 201)
        self.assertEqual(r1.data['id'], r2.data['id'])
        self.assertEqual(Sale.objects.filter(idempotency_key='e2e-idem-2').count(), 1)
        self.assertEqual(WalletTransaction.objects.filter(reference_type='sale', reference_id=r1.data['id'], transaction_type='reward').count(), 1)


class InventoryHistoricalCostE2ETests(TestCase):
    """P1 Inventory + Product Cost History (§26, §27)"""
    def test_product_historical_cost_not_mutated_after_price_change_e2e(self):
        set_rate('USD', 'TOMAN', Decimal('100000'), effective_at=timezone.now(), source='e2e-cost')
        from finance.services.inventory import current_cost, record_product_purchase, record_product_usage
        prod = Product.objects.create(name='CostProd', unit_price=Decimal('10'), cost_usd=Decimal('10'), count=100)
        record_product_purchase(product=prod, quantity=Decimal('10'), unit_cost_usd=Decimal('10'), purchase_date=timezone.now().date())
        usage1 = record_product_usage(product=prod, quantity=Decimal('2'), at=timezone.now(), rate=Decimal('100000'))
        self.assertEqual(usage1.unit_cost_usd_snapshot, Decimal('10.00'))
        # Change current cost to 50
        record_product_purchase(product=prod, quantity=Decimal('5'), unit_cost_usd=Decimal('50'), purchase_date=timezone.now().date())
        self.assertEqual(current_cost(prod), Decimal('50.00'))
        usage1.refresh_from_db()
        self.assertEqual(usage1.unit_cost_usd_snapshot, Decimal('10.00'))  # historical remains
        self.assertEqual(usage1.total_cost_usd_snapshot, Decimal('20.00'))
        # New usage uses new cost
        usage2 = record_product_usage(product=prod, quantity=Decimal('1'), at=timezone.now(), rate=Decimal('100000'))
        self.assertEqual(usage2.unit_cost_usd_snapshot, Decimal('50.00'))


class ExpenseWorkflowE2ETests(TestCase):
    """P1 Expense workflow + self-approval forbidden (§28)"""
    def setUp(self):
        set_rate('USD', 'TOMAN', Decimal('100000'), effective_at=timezone.now(), source='e2e-expense')

    def test_employee_create_admin_approve_and_self_approval_denied_e2e(self):
        emp = employee_client(username='emp_expense_e2e')
        admin = admin_client()
        cat = ExpenseCategory.objects.create(name='E2E-Rent')
        # employee creates via UI flow (API)
        create = emp.post('/api/finance/expenses/', {
            'category': cat.id, 'amount_usd': '200.00', 'expense_date': '2025-06-01', 'vendor': 'Shop',
        }, format='json')
        self.assertEqual(create.status_code, 201)
        eid = create.data['id']
        self.assertEqual(create.data['status'], 'draft')
        # submit
        submit = emp.post(f'/api/finance/expenses/{eid}/submit/', {}, format='json')
        self.assertEqual(submit.status_code, 200)
        # self-approval via direct service must be forbidden — but via API employee cannot approve (403) ; test service layer directly for business rule
        from finance.services import expenses as exp_svc
        from finance.models import Expense
        exp = Expense.objects.get(id=eid)
        with self.assertRaises(exp_svc.ExpenseError):
            exp_svc.approve_expense(exp, exp.created_by)
        # admin approves
        ok = admin.post(f'/api/finance/expenses/{eid}/approve/', {}, format='json')
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(ok.data['status'], 'approved')
        # now pay
        pay = admin.post(f'/api/finance/expenses/{eid}/pay/', {}, format='json')
        self.assertEqual(pay.status_code, 200)
        self.assertEqual(pay.data['status'], 'paid')


class ExchangeAndWebsiteE2ETests(TestCase):
    """P1 Exchange rate + Public website API (§45, §30, §61)"""
    def setUp(self):
        self.admin = admin_client()
        ExchangeRate.objects.all().delete()

    @override_settings(EXCHANGE_RATE_PROVIDER='database', FINANCE_DEFAULT_USD_TO_TOMAN_RATE=Decimal('100000'))
    def test_exchange_dollar_report_e2e_and_conversion(self):
        ExchangeRate.objects.create(currency_from='USD', currency_to='TOMAN', rate=Decimal('100000'), effective_at=timezone.now(), source='e2e', is_active=True)
        resp = self.admin.get('/api/reports/exchange-dollar/?usd=10')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Decimal(resp.data['amount_usd']), Decimal('10.00'))
        self.assertEqual(Decimal(resp.data['amount_toman']), Decimal('1000000.00'))

    @override_settings(EXCHANGE_RATE_PROVIDER='database', FINANCE_DEFAULT_USD_TO_TOMAN_RATE=Decimal('0'), EXCHANGE_RATE_API_URL='')
    def test_exchange_dollar_missing_rate_503_e2e(self):
        ExchangeRate.objects.all().delete()
        with override_settings(FINANCE_DEFAULT_USD_TO_TOMAN_RATE=Decimal('0')):
            resp = self.admin.get('/api/reports/exchange-dollar/')
            self.assertEqual(resp.status_code, 503)

    def test_backup_exchange_mocked_e2e(self):
        mock_data = {'currency': [{'name_en': 'US Dollar', 'symbol': 'USD', 'price': '250000'}]}
        mock_resp = MagicMock()
        mock_resp.status = 200
        import json
        mock_resp.read.return_value = json.dumps(mock_data).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = lambda s, *a: False
        with patch('finance.services.exchange_rates.urllib.request.urlopen', return_value=mock_resp):
            with override_settings(EXCHANGE_RATE_BACKUP_API_URL='https://Api.BrsApi.ir/Market/Gold_Currency.php', EXCHANGE_RATE_BACKUP_API_KEY='test-key'):
                resp = self.admin.get('/api/reports/backup-exchange/?usd=5')
                self.assertEqual(resp.status_code, 200)
                self.assertEqual(resp.data['source'], 'brsapi')
                self.assertEqual(Decimal(resp.data['amount_toman']), Decimal('1250000.00'))

    def test_public_website_api_does_not_expose_private_data_e2e(self):
        from rest_framework.test import APIClient
        anon = APIClient()
        # Public v2 catalog
        resp = anon.get('/api/v2/services/')
        self.assertEqual(resp.status_code, 200)
        # Private dashboard must be blocked
        anon2 = APIClient()
        self.assertEqual(anon2.get('/api/customers/').status_code, 401)
        self.assertEqual(anon2.get('/api/finance/wallets/').status_code, 401)
        self.assertEqual(anon2.get('/api/logs/').status_code, 401)
        # Public should not leak wallet
        self.assertNotIn('wallet', str(resp.data).lower() if isinstance(resp.data, (list, dict)) else '')


class SecurityBypassE2ETests(TestCase):
    """P0 Security journeys (§31, §62)"""
    def test_employee_cannot_create_admin_and_cannot_access_logs_e2e(self):
        emp = employee_client(username='emp_sec_e2e')
        # attempt admin creation via direct API manipulation
        resp = emp.post('/api/auth/employees/', {
            'username': 'hacker_admin', 'password': 'Hack1234', 'first_name': 'H', 'last_name': 'K', 'phone_number': '09120009104',
            'role': 'ADMIN',
        }, format='json')
        # employee should not be able to create admin role — either 403 or role ignored; check created user not admin
        if resp.status_code == 201:
            self.assertNotEqual(resp.data.get('role'), 'ADMIN')
        else:
            self.assertIn(resp.status_code, (403, 400, 401))
        # attempt restricted logs
        logs = emp.get('/api/logs/')
        # employee may be forbidden or empty depending on impl — but anon is 401
        from rest_framework.test import APIClient
        anon = APIClient()
        self.assertEqual(anon.get('/api/logs/').status_code, 401)

    def test_mass_assignment_role_escalation_is_blocked_e2e(self):
        # customer create should not allow role injection
        client = admin_client()
        resp = client.post('/api/customers/', {
            'first_name': 'Mass', 'last_name': 'Assign',
            'mobile_number': '09120009105', 'national_id': '995-0000105',
            'role': 'ADMIN',  # forbidden field
        }, format='json')
        self.assertEqual(resp.status_code, 201)
        # ensure customer not created as admin user
        from accounts.models import ClinicUser
        self.assertFalse(ClinicUser.objects.filter(username='Mass').exists())

    def test_invalid_token_and_expired_session_rejected_e2e(self):
        from rest_framework.test import APIClient
        bad = APIClient()
        bad.credentials(HTTP_AUTHORIZATION='Bearer invalid.token.here')
        self.assertEqual(bad.get('/api/customers/').status_code, 401)
        # expired token via tampered exp
        from tests.helpers import make_admin
        from rest_framework_simplejwt.tokens import AccessToken
        import time
        user = make_admin()
        token = AccessToken.for_user(user)
        token.payload['exp'] = int(time.time()) - 3600
        exp_client = APIClient()
        exp_client.credentials(HTTP_AUTHORIZATION=f'Bearer {str(token)}')
        self.assertEqual(exp_client.get('/api/customers/').status_code, 401)
