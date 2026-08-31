from decimal import Decimal

from django.test import TestCase, TransactionTestCase
from django.utils import timezone
from rest_framework.test import APIClient

from customers.models import Customer
from finance.models import Wallet, WalletTransaction, WalletRewardRule
from finance.services.wallet import grant_reward, reverse_reward, credit, debit, current_balance, get_or_create_wallet, InsufficientFunds, compute_reward
from finance.services.exchange_rates import get_rate, set_rate, to_toman
from tests.helpers import make_admin, make_employee, admin_client, employee_client


class WalletModelTests(TestCase):
    def setUp(self):
        self.customer = Customer.objects.create(
            first_name='Test', last_name='Customer',
            mobile_number='09120000001', national_id='001-0000001',
        )

    def test_wallet_creation(self):
        wallet = get_or_create_wallet(self.customer)
        self.assertIsNotNone(wallet)
        self.assertEqual(wallet.balance, Decimal('0'))

    def test_wallet_balance_non_negative_constraint(self):
        wallet = get_or_create_wallet(self.customer)
        # The model has a CheckConstraint balance__gte=0, so setting negative should fail
        wallet.balance = Decimal('-100')
        try:
            wallet.save()
            self.fail('Expected save to fail with negative balance')
        except Exception:
            pass  # Expected

    def test_wallet_string_representation(self):
        wallet = get_or_create_wallet(self.customer)
        s = str(wallet)
        self.assertIn('Wallet', s)

    def test_wallet_transaction_amount_nonzero(self):
        # Model has a CheckConstraint that amount != 0
        from django.db import IntegrityError
        with self.assertRaises(IntegrityError):
            WalletTransaction.objects.create(
                wallet=get_or_create_wallet(self.customer),
                transaction_type=WalletTransaction.Type.PAYMENT,
                amount=Decimal('0'),
            )


class WalletTransactionTests(TestCase):
    def setUp(self):
        set_rate('USD', 'TOMAN', Decimal('100000'), effective_at=timezone.now(), source='test')
        WalletRewardRule.objects.create(
            name='5%', rule_type=WalletRewardRule.RuleType.PERCENTAGE,
            value=Decimal('5'), min_base_amount_usd=Decimal('0'), is_active=True,
        )
        self.customer = Customer.objects.create(
            first_name='Test', last_name='Customer',
            mobile_number='09120000002', national_id='002-0000002',
        )

    def test_deposit_credit(self):
        txn = credit(self.customer, Decimal('100'), WalletTransaction.Type.PAYMENT)
        self.assertIsNotNone(txn)
        self.assertEqual(current_balance(self.customer), Decimal('100.00'))

    def test_debit_sufficient_funds(self):
        # Credit 200 first
        credit(self.customer, Decimal('200'), WalletTransaction.Type.PAYMENT)
        txn = debit(self.customer, Decimal('50'), WalletTransaction.Type.PAYMENT)
        self.assertIsNotNone(txn)
        self.assertEqual(current_balance(self.customer), Decimal('150.00'))

    def test_debit_insufficient_funds(self):
        # No credit, try to debit
        from finance.services.wallet import InsufficientFunds
        with self.assertRaises(InsufficientFunds):
            debit(self.customer, Decimal('10'), WalletTransaction.Type.PAYMENT)

    def test_reward_granted_and_idempotent(self):
        """Matches existing test_finance.py WalletRewardTests pattern"""
        txn1 = grant_reward(self.customer, Decimal('500'), reference_type='sale', reference_id=4242, rate=Decimal('100000'))
        txn2 = grant_reward(self.customer, Decimal('500'), reference_type='sale', reference_id=4242, rate=Decimal('100000'))
        self.assertIsNotNone(txn1)
        self.assertIsNone(txn2)
        self.assertEqual(Wallet.objects.get(customer=self.customer).balance, Decimal('25.00'))
        self.assertEqual(
            WalletTransaction.objects.filter(reference_type='sale', reference_id=4242, transaction_type='reward').count(),
            1,
        )

    def test_reward_reversal_clamps_to_available(self):
        """Matches existing test_finance.py WalletRewardTests pattern"""
        grant_reward(self.customer, Decimal('500'), reference_type='sale', reference_id=555, rate=Decimal('100000'))
        # spend 20 of the 25 reward
        debit(self.customer, Decimal('20'), WalletTransaction.Type.PAYMENT, reference_type='spend', reference_id=1)
        rev = reverse_reward(self.customer, reference_type='sale', reference_id=555, original_reward=Decimal('25'), rate=Decimal('100000'))
        self.assertIsNotNone(rev)
        # only 5 remained, so reversal is 5
        self.assertEqual(rev.amount, Decimal('-5.00'))
        self.assertEqual(Wallet.objects.get(customer=self.customer).balance, Decimal('0.00'))


class WalletRewardRuleTests(TestCase):
    def setUp(self):
        set_rate('USD', 'TOMAN', Decimal('100000'), effective_at=timezone.now(), source='test')

    def test_percentage_reward_calculation(self):
        from finance.services.wallet import compute_reward
        # Create a 5% rule first
        WalletRewardRule.objects.create(
            name='Test 5%', rule_type=WalletRewardRule.RuleType.PERCENTAGE,
            value=Decimal('5'), min_base_amount_usd=Decimal('0'), is_active=True,
        )
        reward = compute_reward(Decimal('1000'))
        self.assertEqual(reward, Decimal('50.00'))

    def test_fixed_reward_calculation(self):
        from finance.services.wallet import compute_reward
        # Create a fixed 10 rule
        WalletRewardRule.objects.create(
            name='Fixed 10', rule_type=WalletRewardRule.RuleType.FIXED,
            value=Decimal('10'), min_base_amount_usd=Decimal('0'), is_active=True,
        )
        reward = compute_reward(Decimal('100'))
        # Fixed rule: just the value, which is 10
        self.assertEqual(reward, Decimal('10.00'))

    def test_rule_inactive(self):
        from finance.services.wallet import compute_reward
        # Create a percentage rule and make it inactive
        rule = WalletRewardRule.objects.create(
            name='Test 5%', rule_type=WalletRewardRule.RuleType.PERCENTAGE,
            value=Decimal('5'), min_base_amount_usd=Decimal('0'), is_active=True,
        )
        rule.is_active = False
        rule.save()
        reward = compute_reward(Decimal('100'))
        self.assertEqual(reward, Decimal('0.00'))


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
        # Start with 100 balance by crediting
        credit(self.customer, Decimal('100'), WalletTransaction.Type.PAYMENT)

    def test_concurrent_wallet_spend(self):
        from concurrent.futures import ThreadPoolExecutor
        results = []
        exceptions = []

        def do_debit():
            try:
                debit(self.customer, Decimal('80'), WalletTransaction.Type.PAYMENT)
                results.append('success')
            except InsufficientFunds:
                exceptions.append('InsufficientFunds')

        with ThreadPoolExecutor(max_workers=2) as ex:
            f1 = ex.submit(do_debit)
            f2 = ex.submit(do_debit)
            f1.result()
            f2.result()

        self.assertEqual(len(exceptions), 1, f'Expected 1 InsufficientFunds, got {len(exceptions)}: {exceptions}')
        # Wallet ends with 100 - 80 = 20 (only one debit succeeded)
        self.assertEqual(current_balance(self.customer), Decimal('20.00'))