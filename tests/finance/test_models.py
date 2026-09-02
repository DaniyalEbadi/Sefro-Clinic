from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from customers.models import Customer
from finance.models import (
    ExchangeRate,
    Expense,
    ExpenseCategory,
    Package,
    PackageService,
    ProductCostHistory,
    Sale,
    ServiceItem,
    WalletRewardRule,
    WalletTransaction,
)
from finance.services.exchange_rates import get_rate, set_rate, to_toman


class ExchangeRateTests(TestCase):
    def setUp(self):
        set_rate('USD', 'TOMAN', Decimal('100000'), effective_at=timezone.now(), source='test')

    def test_exchange_rate_creation(self):
        rate = ExchangeRate.objects.create(
            currency_from='USD', currency_to='TOMAN', rate=Decimal('100000'),
            effective_at=timezone.now(), source='test'
        )
        # Check the string representation matches the model's __str__
        self.assertIn('USD', str(rate))
        self.assertIn('TOMAN', str(rate))
        self.assertIn(str(Decimal('100000')), str(rate))

    def test_exchange_rate_get(self):
        self.assertEqual(get_rate('USD', 'TOMAN'), Decimal('100000'))

    def test_exchange_rate_historical(self):
        past = timezone.now() - timezone.timedelta(days=30)
        set_rate('USD', 'TOMAN', Decimal('50000'), effective_at=past, source='old')
        self.assertEqual(get_rate(at=past), Decimal('50000'))
        self.assertEqual(get_rate(), Decimal('100000'))

    def test_to_toman_conversion(self):
        self.assertEqual(to_toman(Decimal('100'), Decimal('100000')), Decimal('10000000.00'))


class WalletTests(TestCase):
    def setUp(self):
        self.customer = Customer.objects.create(
            first_name='Test', last_name='Customer',
            mobile_number='09120000001', national_id='001-0000001',
        )

    def test_wallet_creation(self):
        from finance.services.wallet import get_or_create_wallet
        wallet = get_or_create_wallet(self.customer)
        self.assertIsNotNone(wallet)
        self.assertEqual(wallet.balance, Decimal('0'))

    def test_wallet_related_name(self):
        from finance.services.wallet import get_or_create_wallet
        wallet = get_or_create_wallet(self.customer)
        self.assertEqual(self.customer.wallet, wallet)

    def test_wallet_balance_default_zero(self):
        from finance.services.wallet import get_or_create_wallet
        wallet = get_or_create_wallet(self.customer)
        self.assertEqual(wallet.balance, Decimal('0'))


class WalletTransactionTests(TestCase):
    def setUp(self):
        set_rate('USD', 'TOMAN', Decimal('100000'), effective_at=timezone.now(), source='test')
        self.customer = Customer.objects.create(
            first_name='Test', last_name='Customer',
            mobile_number='09120000002', national_id='002-0000002',
        )

    def test_wallet_transaction_creation(self):
        from finance.services.wallet import credit
        txn = credit(self.customer, Decimal('100'), WalletTransaction.Type.PAYMENT)
        self.assertIsNotNone(txn)
        self.assertEqual(txn.transaction_type, WalletTransaction.Type.PAYMENT)
        self.assertEqual(txn.amount, Decimal('100.00'))


class WalletRewardRuleTests(TestCase):
    def setUp(self):
        set_rate('USD', 'TOMAN', Decimal('100000'), effective_at=timezone.now(), source='test')

    def test_reward_rule_creation(self):
        rule = WalletRewardRule.objects.create(
            name='5%', rule_type=WalletRewardRule.RuleType.PERCENTAGE,
            value=Decimal('5'), min_base_amount_usd=Decimal('0'), is_active=True,
        )
        self.assertEqual(str(rule), '5%')

    def test_reward_rule_fixed(self):
        rule = WalletRewardRule.objects.create(
            name='Fixed 10', rule_type=WalletRewardRule.RuleType.FIXED,
            value=Decimal('10'), min_base_amount_usd=Decimal('0'), is_active=True,
        )
        self.assertEqual(str(rule), 'Fixed 10')


class ProductCostHistoryTests(TestCase):
    def test_cost_history_creation(self):
        from inventory.models import Product
        product = Product.objects.create(name='Test Product', unit_price=Decimal('500000'), cost_usd=Decimal('100'), count=50)
        history = ProductCostHistory.objects.create(product=product, cost_usd=Decimal('90'), effective_from=timezone.now())
        self.assertEqual(history.product, product)
        self.assertEqual(history.cost_usd, Decimal('90'))


class ServiceItemTests(TestCase):
    def test_service_item_creation(self):
        from customers.models import Service
        from inventory.models import Product
        product = Product.objects.create(name='Test Product', unit_price=Decimal('500000'), cost_usd=Decimal('100'), count=50)
        service = Service.objects.create(name='Facial', price=800000, price_usd=100, time=30)
        item = ServiceItem.objects.create(service=service, product=product, quantity=Decimal('1'))
        self.assertEqual(item.service, service)
        self.assertEqual(item.quantity, Decimal('1'))


class PackageTests(TestCase):
    def test_package_creation(self):
        package = Package.objects.create(name='Gold Package', description='Gold package description', price_usd=Decimal('200'))
        self.assertEqual(package.name, 'Gold Package')
        self.assertEqual(str(package), 'Gold Package')

    def test_package_with_services(self):
        from customers.models import Service
        package = Package.objects.create(name='Gold Package', price_usd=Decimal('200'))
        service = Service.objects.create(name='Facial', price=800000, price_usd=100, time=30)
        PackageService.objects.create(package=package, service=service)
        ps = PackageService.objects.get(package=package, service=service)
        self.assertEqual(ps.service, service)


class SaleTests(TestCase):
    def test_sale_creation(self):
        from customers.models import Customer
        customer = Customer.objects.create(
            first_name='Test', last_name='Customer',
            mobile_number='09120000003', national_id='003-0000003',
        )
        sale = Sale.objects.create(
            customer=customer, amount_usd=Decimal('100'), amount_toman=Decimal('10000000'),
            status=Sale.Status.PENDING,
        )
        self.assertEqual(sale.status, Sale.Status.PENDING)
        self.assertEqual(sale.amount_usd, Decimal('100'))


class ExpenseTests(TestCase):
    def test_expense_creation(self):
        category = ExpenseCategory.objects.create(name='Supplies')
        expense = Expense.objects.create(
            category=category, amount_usd=Decimal('50'), vendor='Test Vendor',
            expense_date=timezone.now().date(), status=Expense.Status.DRAFT
        )
        self.assertEqual(expense.category, category)
        self.assertEqual(expense.amount_usd, Decimal('50'))
        self.assertEqual(expense.status, Expense.Status.DRAFT)
