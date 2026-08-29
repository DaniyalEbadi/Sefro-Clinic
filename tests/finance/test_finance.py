from decimal import Decimal

from django.test import TestCase, TransactionTestCase
from django.utils import timezone
from rest_framework.test import APIClient

from customers.models import Customer, Service, Visit
from finance.models import (
    Expense,
    ExpenseCategory,
    Sale,
    ServiceItem,
    Wallet,
    WalletRewardRule,
    WalletTransaction,
)
from finance.services import accounting, payments, reporting
from finance.services import expenses as expense_svc
from finance.services.exchange_rates import get_rate, set_rate, to_toman
from finance.services.wallet import InsufficientFunds, grant_reward, reverse_reward
from inventory.models import Product
from tests.helpers import admin_client, employee_client, make_admin, make_employee

USD = Decimal('0.01')


def make_customer():
    return Customer.objects.create(
        first_name='Jane', last_name='Doe',
        mobile_number='09120002222', national_id='099-0000099',
    )


def auth_client():
    return admin_client()


class FinanceBase(TestCase):
    def setUp(self):
        set_rate('USD', 'TOMAN', Decimal('100000'), effective_at=timezone.now(), source='test')
        self.rate = Decimal('100000')
        self.customer = make_customer()
        self.product = Product.objects.create(
            name='Serum', unit_price=Decimal('500000'), cost_usd=Decimal('10'), count=100,
        )
        self.service = Service.objects.create(name='Facial', price=Decimal('800000'), price_usd=Decimal('100'), time=30)
        self.reward_rule = WalletRewardRule.objects.create(
            name='Default 5%', rule_type=WalletRewardRule.RuleType.PERCENTAGE,
            value=Decimal('5'), min_base_amount_usd=Decimal('0'), is_active=True,
        )
        self.admin = make_admin()
        self.employee = make_employee()


class ExchangeRateTests(FinanceBase):
    def test_conversion(self):
        self.assertEqual(to_toman(Decimal('100'), self.rate), Decimal('10000000.00'))
        self.assertEqual(get_rate('USD', 'TOMAN'), Decimal('100000'))

    def test_historical_rate(self):
        past = timezone.now() - timezone.timedelta(days=30)
        set_rate('USD', 'TOMAN', Decimal('50000'), effective_at=past, source='old')
        self.assertEqual(get_rate(at=past), Decimal('50000'))
        self.assertEqual(get_rate(), Decimal('100000'))
        self.assertEqual(to_toman(Decimal('100'), get_rate(at=past)), Decimal('5000000.00'))


class WalletRewardTests(FinanceBase):
    def test_reward_granted_and_idempotent(self):
        txn1 = grant_reward(self.customer, Decimal('500'), reference_type='sale', reference_id=4242, rate=self.rate)
        txn2 = grant_reward(self.customer, Decimal('500'), reference_type='sale', reference_id=4242, rate=self.rate)
        self.assertIsNotNone(txn1)
        self.assertIsNone(txn2)
        self.assertEqual(Wallet.objects.get(customer=self.customer).balance, Decimal('25.00'))
        self.assertEqual(
            WalletTransaction.objects.filter(reference_type='sale', reference_id=4242, transaction_type='reward').count(),
            1,
        )

    def test_reward_reversal_clamps_to_available(self):
        grant_reward(self.customer, Decimal('500'), reference_type='sale', reference_id=555, rate=self.rate)
        # spend 20 of the 25 reward
        from finance.services.wallet import debit
        debit(self.customer, Decimal('20'), WalletTransaction.Type.PAYMENT, reference_type='spend', reference_id=1)
        rev = reverse_reward(self.customer, reference_type='sale', reference_id=555, original_reward=Decimal('25'), rate=self.rate)
        self.assertIsNotNone(rev)
        # only 5 remained, so reversal is 5
        self.assertEqual(rev.amount, Decimal('-5.00'))
        self.assertEqual(Wallet.objects.get(customer=self.customer).balance, Decimal('0.00'))

    def test_insufficient_funds_raises(self):
        Wallet.objects.create(customer=self.customer, balance=Decimal('10'))
        with self.assertRaises(InsufficientFunds):
            payments.checkout(
                customer=self.customer, amount_usd=Decimal('80'),
                components=[{'method': 'wallet', 'amount_usd': Decimal('80')}],
            )


class CheckoutAndWalletPaymentTests(FinanceBase):
    def test_mixed_payment(self):
        Wallet.objects.create(customer=self.customer, balance=Decimal('40'))
        sale = payments.checkout(
            customer=self.customer, amount_usd=Decimal('100'),
            components=[
                {'method': 'wallet', 'amount_usd': Decimal('40')},
                {'method': 'card', 'amount_usd': Decimal('60')},
            ],
            visit=None,
        )
        wallet = Wallet.objects.get(customer=self.customer)
        self.assertEqual(wallet.balance, Decimal('5.00'))  # 5% of 100 reward
        self.assertTrue(
            WalletTransaction.objects.filter(transaction_type=WalletTransaction.Type.PAYMENT, amount=Decimal('-40.00')).exists()
        )
        self.assertTrue(
            WalletTransaction.objects.filter(transaction_type=WalletTransaction.Type.REWARD, amount=Decimal('5.00')).exists()
        )
        self.assertEqual(sale.components.filter(method='card').count(), 1)
        from customers.models import Payment
        self.assertEqual(Payment.objects.filter(payment_method='card').count(), 1)

    def test_idempotent_checkout(self):
        params = dict(customer=self.customer, amount_usd=Decimal('100'),
                      components=[{'method': 'cash', 'amount_usd': Decimal('100')}],
                      idempotency_key='idem-1')
        sale1 = payments.checkout(**params)
        sale2 = payments.checkout(**params)
        self.assertEqual(sale1.id, sale2.id)
        self.assertEqual(Sale.objects.count(), 1)
        # reward only once
        self.assertEqual(
            WalletTransaction.objects.filter(reference_type='sale', reference_id=sale1.id, transaction_type='reward').count(),
            1,
        )

    def test_wallet_refund_restores_balance(self):
        Wallet.objects.create(customer=self.customer, balance=Decimal('100'))
        sale = payments.checkout(
            customer=self.customer, amount_usd=Decimal('100'),
            components=[{'method': 'wallet', 'amount_usd': Decimal('100')}],
        )
        before = Wallet.objects.get(customer=self.customer).balance
        refund = payments.refund_sale(sale)
        after = Wallet.objects.get(customer=self.customer).balance
        # wallet started at 100, spent 100, earned 5 reward (balance 5).
        # refund reverses the 5 reward and returns the 100 wallet payment -> back to 100.
        self.assertEqual(before, Decimal('5.00'))
        self.assertEqual(after, Decimal('100.00'))
        self.assertEqual(refund.status, Sale.Status.REFUNDED)

    def test_manual_adjust_admin(self):
        wallet = Wallet.objects.create(customer=self.customer, balance=Decimal('0'))
        client = admin_client()
        resp = client.post(f'/api/finance/wallets/{wallet.pk}/adjust/', {
            'amount_usd': '100', 'direction': 'credit', 'transaction_type': 'manual_credit',
        }, format='json')
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(Wallet.objects.get(pk=wallet.pk).balance, Decimal('100.00'))


class ProductCostAndConsumptionTests(FinanceBase):
    def test_cost_history_and_snapshot(self):
        from finance.services.inventory import current_cost, record_product_purchase, record_product_usage
        record_product_purchase(product=self.product, quantity=Decimal('10'), unit_cost_usd=Decimal('10'), purchase_date=timezone.now().date())
        self.assertEqual(current_cost(self.product), Decimal('10.00'))
        usage = record_product_usage(product=self.product, quantity=Decimal('2'), at=timezone.now(), rate=self.rate)
        self.assertEqual(usage.unit_cost_usd_snapshot, Decimal('10.00'))
        self.assertEqual(usage.total_cost_usd_snapshot, Decimal('20.00'))
        # change cost later; snapshot stays
        record_product_purchase(product=self.product, quantity=Decimal('5'), unit_cost_usd=Decimal('50'), purchase_date=timezone.now().date())
        usage2 = record_product_usage(product=self.product, quantity=Decimal('1'), at=timezone.now(), rate=self.rate)
        self.assertEqual(usage2.unit_cost_usd_snapshot, Decimal('50.00'))
        self.assertEqual(usage.total_cost_usd_snapshot, Decimal('20.00'))

    def test_record_visit_consumption(self):
        from finance.services.inventory import record_product_purchase
        record_product_purchase(product=self.product, quantity=Decimal('10'), unit_cost_usd=Decimal('10'), purchase_date=timezone.now().date())
        ServiceItem.objects.create(service=self.service, product=self.product, quantity=Decimal('3'))
        visit = Visit.objects.create(
            customer=self.customer, start_at=timezone.now(), end_at=timezone.now() + timezone.timedelta(minutes=30),
            status=Visit.Status.COMPLETED,
        )
        visit.services.add(self.service)
        usages = accounting.record_visit_consumption(visit, at=timezone.now(), rate=self.rate)
        self.assertEqual(len(usages), 1)
        self.assertEqual(usages[0].total_cost_usd_snapshot, Decimal('30.00'))

    def test_selected_product_override(self):
        alt = Product.objects.create(name='Alt', unit_price=Decimal('100'), cost_usd=Decimal('7'), count=10)
        from finance.services.inventory import record_product_purchase
        record_product_purchase(product=alt, quantity=Decimal('5'), unit_cost_usd=Decimal('7'), purchase_date=timezone.now().date())
        visit = Visit.objects.create(
            customer=self.customer, start_at=timezone.now(), end_at=timezone.now() + timezone.timedelta(minutes=30),
            status=Visit.Status.COMPLETED,
        )
        visit.services.add(self.service)
        usages = accounting.record_visit_consumption(
            visit, selected_products={self.service.id: [(alt.id, Decimal('2'))]}, at=timezone.now(), rate=self.rate,
        )
        self.assertEqual(usages[0].product_id, alt.id)
        self.assertEqual(usages[0].total_cost_usd_snapshot, Decimal('14.00'))


class ExpenseTests(FinanceBase):
    def test_full_flow_and_self_approval_blocked(self):
        cat = ExpenseCategory.objects.create(name='Supplies')
        exp = expense_svc.create_expense(
            created_by=self.employee, category=cat, amount_usd=Decimal('200'),
            expense_date=timezone.now().date(), vendor='Shop',
        )
        self.assertEqual(exp.status, Expense.Status.DRAFT)
        expense_svc.submit_expense(exp)
        self.assertEqual(exp.status, Expense.Status.SUBMITTED)
        with self.assertRaises(expense_svc.ExpenseError):
            expense_svc.approve_expense(exp, self.employee)  # self approval blocked
        expense_svc.approve_expense(exp, self.admin)
        self.assertEqual(exp.status, Expense.Status.APPROVED)
        expense_svc.pay_expense(exp, self.admin)
        self.assertEqual(Expense.objects.get(pk=exp.pk).status, Expense.Status.PAID)

    def test_employee_cannot_approve_via_api(self):
        cat = ExpenseCategory.objects.create(name='Utilities')
        exp = expense_svc.create_expense(
            created_by=self.employee, category=cat, amount_usd=Decimal('50'), expense_date=timezone.now().date(),
        )
        expense_svc.submit_expense(exp)
        emp_client = employee_client()
        resp = emp_client.post(f'/api/finance/expenses/{exp.id}/approve/', {}, format='json')
        self.assertIn(resp.status_code, (403, 401))
        self.assertEqual(Expense.objects.get(pk=exp.pk).status, Expense.Status.SUBMITTED)


class ReportingTests(FinanceBase):
    def _seed_sale(self, amount, wallet_part=Decimal('0')):
        comps = []
        if wallet_part > 0:
            comps.append({'method': 'wallet', 'amount_usd': wallet_part})
            comps.append({'method': 'card', 'amount_usd': amount - wallet_part})
        else:
            comps.append({'method': 'cash', 'amount_usd': amount})
        return payments.checkout(customer=self.customer, amount_usd=amount, components=comps)

    def test_financial_summary(self):
        from finance.services.inventory import record_product_purchase, record_product_usage
        record_product_purchase(product=self.product, quantity=Decimal('10'), unit_cost_usd=Decimal('10'), purchase_date=timezone.now().date())
        sale = self._seed_sale(Decimal('100'))
        record_product_usage(product=self.product, quantity=Decimal('2'), visit=None, package_sale=sale, at=timezone.now(), rate=self.rate)
        cat = ExpenseCategory.objects.create(name='Rent')
        exp = expense_svc.create_expense(created_by=self.employee, category=cat, amount_usd=Decimal('30'), expense_date=timezone.now().date())
        expense_svc.submit_expense(exp)
        expense_svc.approve_expense(exp, self.admin)

        start = timezone.now() - timezone.timedelta(days=1)
        end = timezone.now() + timezone.timedelta(days=1)
        summary = reporting.financial_summary(start, end)
        self.assertEqual(summary['revenue']['usd'], Decimal('100.00'))
        self.assertEqual(summary['product_cost']['usd'], Decimal('20.00'))
        self.assertEqual(summary['gross_profit']['usd'], Decimal('80.00'))
        self.assertEqual(summary['expenses']['usd'], Decimal('30.00'))
        self.assertEqual(summary['net_profit']['usd'], Decimal('50.00'))
        self.assertEqual(summary['wallet']['rewards_issued'], Decimal('5.00'))

    def test_historical_exchange_rate_stability(self):
        from finance.services.inventory import record_product_purchase, record_product_usage
        record_product_purchase(product=self.product, quantity=Decimal('10'), unit_cost_usd=Decimal('10'), purchase_date=timezone.now().date())
        sale = self._seed_sale(Decimal('100'))
        record_product_usage(product=self.product, quantity=Decimal('2'), package_sale=sale, at=timezone.now(), rate=self.rate)
        # change the rate drastically
        set_rate('USD', 'TOMAN', Decimal('200000'), effective_at=timezone.now() + timezone.timedelta(seconds=1), source='new')
        start = timezone.now() - timezone.timedelta(days=1)
        end = timezone.now() + timezone.timedelta(days=2)
        summary = reporting.financial_summary(start, end)
        # product cost uses snapshot, still 20 USD
        self.assertEqual(summary['product_cost']['usd'], Decimal('20.00'))

    def test_profit_by_service(self):
        from finance.services.inventory import record_product_purchase
        record_product_purchase(product=self.product, quantity=Decimal('10'), unit_cost_usd=Decimal('10'), purchase_date=timezone.now().date())
        visit = Visit.objects.create(
            customer=self.customer, start_at=timezone.now(), end_at=timezone.now() + timezone.timedelta(minutes=30),
            status=Visit.Status.COMPLETED,
        )
        visit.services.add(self.service)
        ServiceItem.objects.create(service=self.service, product=self.product, quantity=Decimal('3'))
        accounting.record_visit_consumption(visit, at=timezone.now(), rate=self.rate)
        rows = reporting.profit_by_service(timezone.now() - timezone.timedelta(days=1), timezone.now() + timezone.timedelta(days=1))
        self.assertTrue(any(r['service_id'] == self.service.id for r in rows))
        svc_row = next(r for r in rows if r['service_id'] == self.service.id)
        self.assertEqual(svc_row['revenue_usd'], Decimal('100.00'))
        self.assertEqual(svc_row['product_cost_usd'], Decimal('30.00'))
        self.assertEqual(svc_row['profit_usd'], Decimal('70.00'))

    def test_wallet_summary(self):
        self._seed_sale(Decimal('100'))
        ws = reporting.wallet_summary()
        self.assertEqual(ws['rewards_issued_usd'], Decimal('5.00'))
        self.assertEqual(ws['total_liability_usd'], Decimal('5.00'))


class ApiAuthTests(FinanceBase):
    def test_checkout_requires_auth(self):
        client = APIClient()
        resp = client.post('/api/finance/checkout/', {
            'customer': self.customer.id, 'amount_usd': '100',
            'components': [{'method': 'cash', 'amount_usd': '100'}],
        }, format='json')
        self.assertEqual(resp.status_code, 401)

    def test_employee_can_checkout(self):
        client = employee_client()
        resp = client.post('/api/finance/checkout/', {
            'customer': self.customer.id, 'amount_usd': '100',
            'components': [{'method': 'cash', 'amount_usd': '100'}],
        }, format='json')
        self.assertEqual(resp.status_code, 201)

    def test_exchange_rate_admin_only_write(self):
        emp = employee_client()
        resp = emp.post('/api/finance/exchange-rates/', {
            'currency_from': 'USD', 'currency_to': 'TOMAN', 'rate': '120000',
            'effective_at': timezone.now().isoformat(), 'is_active': True,
        }, format='json')
        self.assertIn(resp.status_code, (403, 401))
        admin = admin_client()
        resp = admin.post('/api/finance/exchange-rates/', {
            'currency_from': 'USD', 'currency_to': 'TOMAN', 'rate': '120000',
            'effective_at': timezone.now().isoformat(), 'is_active': True,
        }, format='json')
        self.assertEqual(resp.status_code, 201)

    def test_financial_summary_endpoint(self):
        client = employee_client()
        resp = client.get('/api/finance/reports/financial-summary/')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('net_profit', resp.data)

    def test_report_endpoint_forbidden_for_anon(self):
        client = APIClient()
        resp = client.get('/api/finance/reports/financial-summary/')
        self.assertEqual(resp.status_code, 401)


class WalletConcurrencyTests(TransactionTestCase):
    def setUp(self):
        set_rate('USD', 'TOMAN', Decimal('100000'), effective_at=timezone.now(), source='test')
        WalletRewardRule.objects.create(
            name='5%', rule_type=WalletRewardRule.RuleType.PERCENTAGE, value=Decimal('5'),
            min_base_amount_usd=Decimal('0'), is_active=True,
        )
        self.customer = Customer.objects.create(
            first_name='Con', last_name='Cur', mobile_number='09120003333', national_id='088-0000088',
        )
        Wallet.objects.create(customer=self.customer, balance=Decimal('100'))
        self.user = make_admin()

    def _thread_checkout(self, amount):
        client = APIClient()
        from tests.helpers import login
        login(client, self.user.username, 'SefroAdmin-Test-2026!')
        return client.post('/api/finance/checkout/', {
            'customer': self.customer.id, 'amount_usd': str(amount),
            'components': [{'method': 'wallet', 'amount_usd': str(amount)}],
        }, format='json')

    def test_concurrent_wallet_spend(self):
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=2) as ex:
            f1 = ex.submit(self._thread_checkout, Decimal('80'))
            f2 = ex.submit(self._thread_checkout, Decimal('80'))
            r1, r2 = f1.result(), f2.result()
        statuses = {r1.status_code, r2.status_code}
        self.assertIn(201, statuses)
        self.assertIn(400, statuses)
        # wallet ends at 100 - 80 + reward(80*5%=4) = 24
        self.assertEqual(Wallet.objects.get(customer=self.customer).balance, Decimal('24.00'))
