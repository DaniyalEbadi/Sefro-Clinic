from decimal import Decimal

from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from accounts.models import ClinicUser
from customers.models import Customer
from finance.models import WelcomePack, WelcomePackItem, WelcomePackUsage
from inventory.models import Product
from tests.helpers import make_admin


class WelcomePackModelTests(TestCase):
    def setUp(self):
        self.user = make_admin()
        self.product1 = Product.objects.create(
            name='Product A', sku='PROD-A', cost_usd='10.00', count=100, unit='piece'
        )
        self.product2 = Product.objects.create(
            name='Product B', sku='PROD-B', cost_usd='25.50', count=50, unit='piece'
        )

    def test_create_welcome_pack(self):
        pack = WelcomePack.objects.create(
            name='Welcome Pack 1',
            description='First welcome pack',
            is_active=True,
            created_by=self.user,
        )
        self.assertEqual(pack.name, 'Welcome Pack 1')
        self.assertTrue(pack.is_active)
        self.assertEqual(pack.created_by, self.user)

    def test_welcome_pack_unique_name(self):
        WelcomePack.objects.create(name='Pack 1', created_by=self.user)
        with transaction.atomic():
            with self.assertRaises(IntegrityError):
                WelcomePack.objects.create(name='Pack 1', created_by=self.user)

    def test_welcome_pack_ordering(self):
        p2 = WelcomePack.objects.create(name='B Pack', created_by=self.user)
        p1 = WelcomePack.objects.create(name='A Pack', created_by=self.user)
        listed = list(WelcomePack.objects.all())
        self.assertEqual(listed, [p1, p2])

    def test_welcome_pack_str(self):
        pack = WelcomePack.objects.create(name='Test Pack', created_by=self.user)
        self.assertEqual(str(pack), 'Test Pack')


class WelcomePackItemModelTests(TestCase):
    def setUp(self):
        self.user = make_admin()
        self.pack = WelcomePack.objects.create(name='Test Pack', created_by=self.user)
        self.product1 = Product.objects.create(
            name='Product A', sku='PROD-A', cost_usd='10.00', count=100, unit='piece'
        )
        self.product2 = Product.objects.create(
            name='Product B', sku='PROD-B', cost_usd='25.50', count=50, unit='piece'
        )

    def test_create_welcome_pack_item(self):
        item = WelcomePackItem.objects.create(
            welcome_pack=self.pack, product=self.product1, quantity=Decimal('2.500')
        )
        self.assertEqual(item.welcome_pack, self.pack)
        self.assertEqual(item.product, self.product1)
        self.assertEqual(item.quantity, Decimal('2.500'))

    def test_welcome_pack_item_unique_per_pack(self):
        WelcomePackItem.objects.create(
            welcome_pack=self.pack, product=self.product1, quantity=Decimal('1')
        )
        with transaction.atomic():
            with self.assertRaises(IntegrityError):
                WelcomePackItem.objects.create(
                    welcome_pack=self.pack, product=self.product1, quantity=Decimal('2')
                )

    def test_welcome_pack_item_quantity_positive_constraint(self):
        with transaction.atomic():
            with self.assertRaises(IntegrityError):
                WelcomePackItem.objects.create(
                    welcome_pack=self.pack, product=self.product1, quantity=Decimal('0')
                )

    def test_welcome_pack_item_str(self):
        item = WelcomePackItem.objects.create(
            welcome_pack=self.pack, product=self.product1, quantity=Decimal('2.500')
        )
        self.assertIn('Test Pack', str(item))
        self.assertIn('Product A', str(item))
        self.assertIn('2.500', str(item))


class WelcomePackUsageModelTests(TestCase):
    def setUp(self):
        self.user = make_admin()
        self.employee = ClinicUser.objects.create_user(
            username='test_emp', password='TestPass123!', role=ClinicUser.Role.EMPLOYEE
        )
        self.customer = Customer.objects.create(
            first_name='John', last_name='Doe',
            mobile_number='09120000001', national_id='001-0000001'
        )
        self.pack = WelcomePack.objects.create(name='Usage Pack', created_by=self.user)
        self.product = Product.objects.create(
            name='Usage Product', sku='USAGE-PROD', cost_usd='15.00', count=100, unit='piece'
        )
        WelcomePackItem.objects.create(
            welcome_pack=self.pack, product=self.product, quantity=Decimal('2.000')
        )

    def test_create_welcome_pack_usage(self):
        usage = WelcomePackUsage.objects.create(
            welcome_pack=self.pack,
            customer=self.customer,
            issued_by=self.employee,
            quantity=Decimal('3.000'),
            total_cost_usd_snapshot=Decimal('90.00'),
            exchange_rate_snapshot=Decimal('50000.000000'),
            total_cost_toman_snapshot=Decimal('4500000.00'),
        )
        self.assertEqual(usage.welcome_pack, self.pack)
        self.assertEqual(usage.customer, self.customer)
        self.assertEqual(usage.issued_by, self.employee)
        self.assertEqual(usage.quantity, Decimal('3.000'))
        self.assertEqual(usage.total_cost_usd_snapshot, Decimal('90.00'))

    def test_welcome_pack_usage_ordering(self):
        u1 = WelcomePackUsage.objects.create(
            welcome_pack=self.pack, customer=self.customer, issued_by=self.employee,
            quantity=Decimal('1'), total_cost_usd_snapshot=Decimal('30.00'),
            exchange_rate_snapshot=Decimal('50000'), total_cost_toman_snapshot=Decimal('1500000'),
            issued_at=timezone.now() - timezone.timedelta(days=1),
        )
        u2 = WelcomePackUsage.objects.create(
            welcome_pack=self.pack, customer=self.customer, issued_by=self.employee,
            quantity=Decimal('2'), total_cost_usd_snapshot=Decimal('60.00'),
            exchange_rate_snapshot=Decimal('50000'), total_cost_toman_snapshot=Decimal('3000000'),
        )
        listed = list(WelcomePackUsage.objects.all())
        self.assertEqual(listed[0].id, u2.id)
        self.assertEqual(listed[1].id, u1.id)

    def test_welcome_pack_usage_str(self):
        usage = WelcomePackUsage.objects.create(
            welcome_pack=self.pack, customer=self.customer, issued_by=self.employee,
            quantity=Decimal('1'), total_cost_usd_snapshot=Decimal('30.00'),
            exchange_rate_snapshot=Decimal('50000'), total_cost_toman_snapshot=Decimal('1500000'),
        )
        self.assertIn('Usage Pack', str(usage))
        self.assertIn('John', str(usage))

    def test_welcome_pack_usage_visit_optional(self):
        usage = WelcomePackUsage.objects.create(
            welcome_pack=self.pack, customer=self.customer, issued_by=self.employee,
            visit=None, quantity=Decimal('1'),
            total_cost_usd_snapshot=Decimal('30.00'),
            exchange_rate_snapshot=Decimal('50000'), total_cost_toman_snapshot=Decimal('1500000'),
        )
        self.assertIsNone(usage.visit)


class WelcomePackCostCalculationTests(TestCase):
    def setUp(self):
        self.user = make_admin()
        self.pack = WelcomePack.objects.create(name='Cost Pack', created_by=self.user)
        self.product1 = Product.objects.create(
            name='Prod 1', sku='P1', cost_usd='10.00', count=100, unit='piece'
        )
        self.product2 = Product.objects.create(
            name='Prod 2', sku='P2', cost_usd='20.00', count=50, unit='piece'
        )
        WelcomePackItem.objects.create(
            welcome_pack=self.pack, product=self.product1, quantity=Decimal('2.000')
        )
        WelcomePackItem.objects.create(
            welcome_pack=self.pack, product=self.product2, quantity=Decimal('1.500')
        )

    def test_calculate_welcome_pack_cost_usd(self):
        from finance.services.welcome_pack import calculate_welcome_pack_cost_usd
        cost = calculate_welcome_pack_cost_usd(self.pack)
        self.assertEqual(cost, Decimal('50.00'))

    def test_calculate_welcome_pack_cost_toman_with_rate(self):
        from finance.services.welcome_pack import calculate_welcome_pack_cost_toman
        cost = calculate_welcome_pack_cost_toman(self.pack, rate=Decimal('50000'))
        self.assertEqual(cost, Decimal('2500000.00'))

    def test_calculate_welcome_pack_cost_toman_none_without_rate(self):
        from unittest.mock import patch

        from finance.services.welcome_pack import calculate_welcome_pack_cost_toman
        with patch('finance.services.welcome_pack.get_current_usd_to_toman_rate', return_value=None):
            cost = calculate_welcome_pack_cost_toman(self.pack, rate=None)
            self.assertIsNone(cost)

    def test_empty_pack_cost_is_zero(self):
        from finance.services.welcome_pack import calculate_welcome_pack_cost_usd
        empty_pack = WelcomePack.objects.create(name='Empty', created_by=self.user)
        cost = calculate_welcome_pack_cost_usd(empty_pack)
        self.assertEqual(cost, Decimal('0.00'))
