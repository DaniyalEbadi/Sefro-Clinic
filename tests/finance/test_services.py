from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from customers.models import Customer, Service, Visit
from finance.models import Expense, ExpenseCategory, Sale, ServiceItem, Wallet, WalletRewardRule, WalletTransaction
from finance.services import accounting, payments, reporting
from finance.services import expenses as expense_svc
from finance.services.exchange_rates import get_rate, set_rate, to_toman
from finance.services.wallet import InsufficientFunds, credit, current_balance, debit, grant_reward, reverse_reward
from inventory.models import Product
from tests.helpers import employee_client, make_admin, make_employee


def make_customer():
    return Customer.objects.create(
        first_name='Jane', last_name='Doe',
        mobile_number='09120002222', national_id='099-0000099',
    )


USD = Decimal('0.01')


class ExchangeRateServiceTests(TestCase):
    def setUp(self):
        set_rate('USD', 'TOMAN', Decimal('100000'), effective_at=timezone.now(), source='test')

    def test_get_rate(self):
        self.assertEqual(get_rate('USD', 'TOMAN'), Decimal('100000'))

    def test_set_rate(self):
        set_rate('USD', 'TOMAN', Decimal('120000'), effective_at=timezone.now(), source='test')
        self.assertEqual(get_rate('USD', 'TOMAN'), Decimal('120000'))

    def test_to_toman(self):
        self.assertEqual(to_toman(Decimal('100'), Decimal('100000')), Decimal('10000000.00'))


class WalletServiceTests(TestCase):
    def setUp(self):
        set_rate('USD', 'TOMAN', Decimal('100000'), effective_at=timezone.now(), source='test')
        WalletRewardRule.objects.create(
            name='5%', rule_type=WalletRewardRule.RuleType.PERCENTAGE,
            value=Decimal('5'), min_base_amount_usd=Decimal('0'), is_active=True,
        )

    def test_credit(self):
        customer = make_customer()
        txn = credit(customer, Decimal('100'), WalletTransaction.Type.PAYMENT)
        self.assertIsNotNone(txn)
        self.assertEqual(current_balance(customer), Decimal('100.00'))

    def test_debit_sufficient_funds(self):
        customer = make_customer()
        credit(customer, Decimal('200'), WalletTransaction.Type.PAYMENT)
        txn = debit(customer, Decimal('50'), WalletTransaction.Type.PAYMENT)
        self.assertIsNotNone(txn)
        self.assertEqual(current_balance(customer), Decimal('150.00'))

    def test_debit_insufficient_funds(self):
        customer = make_customer()
        with self.assertRaises(InsufficientFunds):
            debit(customer, Decimal('10'), WalletTransaction.Type.PAYMENT)

    def test_grant_reward(self):
        customer = make_customer()
        credit(customer, Decimal('500'), WalletTransaction.Type.PAYMENT)
        txn = grant_reward(customer, Decimal('500'), reference_type='sale', reference_id=4242)
        self.assertIsNotNone(txn)
        self.assertEqual(txn.transaction_type, WalletTransaction.Type.REWARD)
        self.assertEqual(txn.amount, Decimal('25.00'))

    def test_reverse_reward(self):
        customer = make_customer()
        # Don't credit first - just grant reward (matches existing test_finance.py pattern)
        grant_reward(customer, Decimal('500'), reference_type='sale', reference_id=555)
        debit(customer, Decimal('20'), WalletTransaction.Type.PAYMENT, reference_type='spend', reference_id=1)
        rev = reverse_reward(customer, reference_type='sale', reference_id=555, original_reward=Decimal('25'))
        self.assertIsNotNone(rev)
        # only 5 remained (25 reward - 20 spend), so reversal is 5
        self.assertEqual(rev.amount, Decimal('-5.00'))


class AccountingServiceTests(TestCase):
    def setUp(self):
        set_rate('USD', 'TOMAN', Decimal('100000'), effective_at=timezone.now(), source='test')
        self.customer = make_customer()
        self.product = Product.objects.create(
            name='Serum', unit_price=Decimal('500000'), cost_usd=Decimal('10'), count=100,
        )
        self.service = Service.objects.create(name='Facial', price=Decimal('800000'), price_usd=Decimal('100'), time=30)

    def test_record_visit_consumption(self):
        from finance.services.inventory import record_product_purchase
        record_product_purchase(product=self.product, quantity=Decimal('10'), unit_cost_usd=Decimal('10'), purchase_date=timezone.now().date())
        visit = Visit.objects.create(
            customer=self.customer, start_at=timezone.now(), end_at=timezone.now() + timezone.timedelta(minutes=30),
            status=Visit.Status.COMPLETED,
        )
        visit.services.add(self.service)
        ServiceItem.objects.create(service=self.service, product=self.product, quantity=Decimal('3'))
        usages = accounting.record_visit_consumption(visit, at=timezone.now(), rate=Decimal('100000'))
        self.assertEqual(len(usages), 1)
        self.assertEqual(usages[0].total_cost_usd_snapshot, Decimal('30.00'))


class PaymentsServiceTests(TestCase):
    def setUp(self):
        set_rate('USD', 'TOMAN', Decimal('100000'), effective_at=timezone.now(), source='test')
        WalletRewardRule.objects.create(
            name='5%', rule_type=WalletRewardRule.RuleType.PERCENTAGE,
            value=Decimal('5'), min_base_amount_usd=Decimal('0'), is_active=True,
        )

    def _make_customer_with_wallet(self, balance=Decimal('0')):
        customer = make_customer()
        Wallet.objects.create(customer=customer, balance=balance)
        return customer

    def test_checkout_mixed_payment(self):
        from finance.services import payments
        customer = self._make_customer_with_wallet(Decimal('100'))
        payments.checkout(
            customer=customer, amount_usd=Decimal('100'),
            components=[
                {'method': 'wallet', 'amount_usd': Decimal('95')},
                {'method': 'card', 'amount_usd': Decimal('5')},
            ],
        )
        wallet = Wallet.objects.get(customer=customer)
        # 100 - 95 (payment) + 5 (reward) = 10
        self.assertEqual(wallet.balance, Decimal('10.00'))
        self.assertTrue(
            WalletTransaction.objects.filter(transaction_type='payment', amount=Decimal('-95.00')).exists()
        )
        self.assertTrue(
            WalletTransaction.objects.filter(transaction_type='reward', amount=Decimal('5.00')).exists()
        )

    def test_idempotent_checkout(self):
        from finance.services import payments
        customer = self._make_customer_with_wallet()
        params = dict(customer=customer, amount_usd=Decimal('100'),
                      components=[{'method': 'cash', 'amount_usd': Decimal('100')}],
                      idempotency_key='idem-1')
        sale1 = payments.checkout(**params)
        sale2 = payments.checkout(**params)
        self.assertEqual(sale1.id, sale2.id)
        self.assertEqual(Sale.objects.count(), 1)
        self.assertEqual(
            WalletTransaction.objects.filter(reference_type='sale', reference_id=sale1.id, transaction_type='reward').count(),
            1,
        )

    def test_wallet_refund_restores_balance(self):
        from finance.services import payments
        customer = self._make_customer_with_wallet(Decimal('100'))
        before = Wallet.objects.get(customer=customer).balance
        sale = payments.checkout(
            customer=customer, amount_usd=Decimal('100'),
            components=[{'method': 'wallet', 'amount_usd': Decimal('100')}],
        )
        refund = payments.refund_sale(sale)
        after = Wallet.objects.get(customer=customer).balance
        self.assertEqual(before, Decimal('100.00'))
        self.assertEqual(after, Decimal('100.00'))
        self.assertEqual(refund.status, Sale.Status.REFUNDED)


class ReportingServiceTests(TestCase):
    def setUp(self):
        set_rate('USD', 'TOMAN', Decimal('100000'), effective_at=timezone.now(), source='test')
        WalletRewardRule.objects.create(
            name='5%', rule_type=WalletRewardRule.RuleType.PERCENTAGE,
            value=Decimal('5'), min_base_amount_usd=Decimal('0'), is_active=True,
        )
        self.customer = make_customer()
        self.product = Product.objects.create(
            name='Serum', unit_price=Decimal('500000'), cost_usd=Decimal('10'), count=100,
        )
        self.service = Service.objects.create(name='Facial', price=Decimal('800000'), price_usd=Decimal('100'), time=30)

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
        record_product_usage(product=self.product, quantity=Decimal('2'), visit=None, package_sale=sale, at=timezone.now(), rate=Decimal('100000'))
        cat = ExpenseCategory.objects.create(name='Rent')
        creator = make_admin()
        approver = make_employee()
        exp = expense_svc.create_expense(
            created_by=creator, category=cat, amount_usd=Decimal('30'), expense_date=timezone.now().date(), vendor='Shop',
        )
        expense_svc.submit_expense(exp)
        expense_svc.approve_expense(exp, approver)

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
        record_product_usage(product=self.product, quantity=Decimal('2'), package_sale=sale, at=timezone.now(), rate=Decimal('100000'))
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
        accounting.record_visit_consumption(visit, at=timezone.now(), rate=Decimal('100000'))
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


class ExpenseServiceTests(TestCase):
    def setUp(self):
        set_rate('USD', 'TOMAN', Decimal('100000'), effective_at=timezone.now(), source='test')
        self.admin = make_admin()
        self.employee = make_employee()

    def test_full_flow_and_self_approval_blocked(self):
        cat = ExpenseCategory.objects.create(name='Supplies')
        exp = expense_svc.create_expense(
            created_by=self.employee, category=cat, amount_usd=Decimal('200'),
            expense_date=timezone.now().date(), vendor='Shop',
        )
        self.assertEqual(exp.status, expense_svc.Status.DRAFT)
        expense_svc.submit_expense(exp)
        self.assertEqual(exp.status, expense_svc.Status.SUBMITTED)
        with self.assertRaises(expense_svc.ExpenseError):
            expense_svc.approve_expense(exp, self.employee)
        expense_svc.approve_expense(exp, self.admin)
        self.assertEqual(exp.status, expense_svc.Status.APPROVED)
        expense_svc.pay_expense(exp, self.admin)
        self.assertEqual(Expense.objects.get(pk=exp.pk).status, expense_svc.Status.PAID)

    def test_employee_cannot_approve_via_api(self):
        cat = ExpenseCategory.objects.create(name='Utilities')
        exp = expense_svc.create_expense(
            created_by=self.employee, category=cat, amount_usd=Decimal('50'), expense_date=timezone.now().date(),
        )
        expense_svc.submit_expense(exp)
        emp_client = employee_client()
        resp = emp_client.post(f'/api/finance/expenses/{exp.id}/approve/', {}, format='json')
        self.assertIn(resp.status_code, (403, 401))
        self.assertEqual(Expense.objects.get(pk=exp.pk).status, expense_svc.Status.SUBMITTED)


class InventoryServiceTests(TestCase):
    def setUp(self):
        set_rate('USD', 'TOMAN', Decimal('100000'), effective_at=timezone.now(), source='test')
        self.customer = make_customer()
        self.product = Product.objects.create(
            name='Serum', unit_price=Decimal('500000'), cost_usd=Decimal('10'), count=100,
        )
        self.service = Service.objects.create(name='Facial', price=Decimal('800000'), price_usd=Decimal('100'), time=30)

    def test_cost_history_and_snapshot(self):
        from finance.services.inventory import current_cost, record_product_purchase, record_product_usage
        record_product_purchase(product=self.product, quantity=Decimal('10'), unit_cost_usd=Decimal('10'), purchase_date=timezone.now().date())
        self.assertEqual(current_cost(self.product), Decimal('10.00'))
        usage = record_product_usage(product=self.product, quantity=Decimal('2'), at=timezone.now(), rate=Decimal('100000'))
        self.assertEqual(usage.unit_cost_usd_snapshot, Decimal('10.00'))
        self.assertEqual(usage.total_cost_usd_snapshot, Decimal('20.00'))
        # change cost later; new usage uses new cost
        record_product_purchase(product=self.product, quantity=Decimal('5'), unit_cost_usd=Decimal('50'), purchase_date=timezone.now().date())
        usage2 = record_product_usage(product=self.product, quantity=Decimal('1'), at=timezone.now(), rate=Decimal('100000'))
        self.assertEqual(usage2.unit_cost_usd_snapshot, Decimal('50.00'))
        self.assertEqual(usage2.total_cost_usd_snapshot, Decimal('50.00'))

    def test_record_visit_consumption(self):
        from finance.services.inventory import record_product_purchase
        record_product_purchase(product=self.product, quantity=Decimal('10'), unit_cost_usd=Decimal('10'), purchase_date=timezone.now().date())
        ServiceItem.objects.create(service=self.service, product=self.product, quantity=Decimal('3'))
        visit = Visit.objects.create(
            customer=self.customer, start_at=timezone.now(), end_at=timezone.now() + timezone.timedelta(minutes=30),
            status=Visit.Status.COMPLETED,
        )
        visit.services.add(self.service)
        usages = accounting.record_visit_consumption(visit, at=timezone.now(), rate=Decimal('100000'))
        self.assertEqual(len(usages), 1)
        self.assertEqual(usages[0].total_cost_usd_snapshot, Decimal('30.00'))

    def test_selected_product_override(self):
        from inventory.models import Product as InvProduct
        alt = InvProduct.objects.create(name='Alt', unit_price=Decimal('100'), cost_usd=Decimal('7'), count=10)
        from finance.services.inventory import record_product_purchase
        record_product_purchase(product=alt, quantity=Decimal('5'), unit_cost_usd=Decimal('7'), purchase_date=timezone.now().date())
        visit = Visit.objects.create(
            customer=self.customer, start_at=timezone.now(), end_at=timezone.now() + timezone.timedelta(minutes=30),
            status=Visit.Status.COMPLETED,
        )
        visit.services.add(self.service)
        usages = accounting.record_visit_consumption(
            visit, selected_products={self.service.id: [(alt.id, Decimal('2'))]}, at=timezone.now(), rate=Decimal('100000'),
        )
        self.assertEqual(usages[0].product_id, alt.id)
        self.assertEqual(usages[0].total_cost_usd_snapshot, Decimal('14.00'))
