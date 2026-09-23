from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from accounts.models import ClinicUser
from customers.models import Customer
from finance.models import WelcomePack, WelcomePackItem
from finance.services.welcome_pack import (
    WelcomePackError,
    create_welcome_pack_with_items,
    get_welcome_pack_items,
    get_welcome_pack_usage_summary,
    issue_welcome_pack,
    update_welcome_pack_with_items,
    validate_welcome_pack_items,
)
from inventory.models import Product
from tests.helpers import make_admin


class WelcomePackServiceValidationTests(TestCase):
    def setUp(self):
        self.user = make_admin()
        self.product1 = Product.objects.create(
            name='Product A', sku='PROD-A', cost_usd='10.00', count=100, unit='piece'
        )
        self.product2 = Product.objects.create(
            name='Product B', sku='PROD-B', cost_usd='25.50', count=50, unit='piece'
        )
        self.finished_product = Product.objects.create(
            name='Finished Product', sku='FINISHED', cost_usd='5.00', count=0,
            unit='piece', status=Product.StatusChoices.FINISHED
        )

    def test_validate_items_valid(self):
        items = [
            {'product': self.product1.id, 'quantity': '2.5'},
            {'product': self.product2.id, 'quantity': '1'},
        ]
        validated = validate_welcome_pack_items(items)
        self.assertEqual(len(validated), 2)
        self.assertEqual(validated[0][0], self.product1)
        self.assertEqual(validated[0][1], Decimal('2.5'))
        self.assertEqual(validated[1][0], self.product2)
        self.assertEqual(validated[1][1], Decimal('1'))

    def test_validate_items_missing_product(self):
        items = [{'quantity': '1'}]
        with self.assertRaises(WelcomePackError) as ctx:
            validate_welcome_pack_items(items)
        self.assertIn('product is required', str(ctx.exception))

    def test_validate_items_missing_quantity(self):
        items = [{'product': self.product1.id}]
        with self.assertRaises(WelcomePackError) as ctx:
            validate_welcome_pack_items(items)
        self.assertIn('quantity is required', str(ctx.exception))

    def test_validate_items_invalid_quantity(self):
        items = [{'product': self.product1.id, 'quantity': 'invalid'}]
        with self.assertRaises(WelcomePackError) as ctx:
            validate_welcome_pack_items(items)
        self.assertIn('valid decimal', str(ctx.exception))

    def test_validate_items_zero_quantity(self):
        items = [{'product': self.product1.id, 'quantity': '0'}]
        with self.assertRaises(WelcomePackError) as ctx:
            validate_welcome_pack_items(items)
        self.assertIn('greater than zero', str(ctx.exception))

    def test_validate_items_negative_quantity(self):
        items = [{'product': self.product1.id, 'quantity': '-1'}]
        with self.assertRaises(WelcomePackError) as ctx:
            validate_welcome_pack_items(items)
        self.assertIn('greater than zero', str(ctx.exception))

    def test_validate_items_nonexistent_product(self):
        items = [{'product': 99999, 'quantity': '1'}]
        with self.assertRaises(WelcomePackError) as ctx:
            validate_welcome_pack_items(items)
        self.assertIn('does not exist', str(ctx.exception))

    def test_validate_items_finished_product(self):
        items = [{'product': self.finished_product.id, 'quantity': '1'}]
        with self.assertRaises(WelcomePackError) as ctx:
            validate_welcome_pack_items(items)
        self.assertIn('finished/inactive', str(ctx.exception))

    def test_validate_items_duplicate_product(self):
        items = [
            {'product': self.product1.id, 'quantity': '1'},
            {'product': self.product1.id, 'quantity': '2'},
        ]
        with self.assertRaises(WelcomePackError) as ctx:
            validate_welcome_pack_items(items)
        self.assertIn('duplicate product', str(ctx.exception))

    def test_validate_items_empty_list(self):
        validated = validate_welcome_pack_items([])
        self.assertEqual(validated, [])


class WelcomePackServiceCreateTests(TestCase):
    def setUp(self):
        self.user = make_admin()
        self.product1 = Product.objects.create(
            name='Product A', sku='PROD-A', cost_usd='10.00', count=100, unit='piece'
        )
        self.product2 = Product.objects.create(
            name='Product B', sku='PROD-B', cost_usd='25.50', count=50, unit='piece'
        )

    def test_create_welcome_pack_with_items(self):
        items = [
            {'product': self.product1.id, 'quantity': '2.000'},
            {'product': self.product2.id, 'quantity': '1.500'},
        ]
        pack = create_welcome_pack_with_items(
            name='New Pack', description='Description', is_active=True,
            items_data=items, created_by=self.user
        )
        self.assertEqual(pack.name, 'New Pack')
        self.assertEqual(pack.description, 'Description')
        self.assertTrue(pack.is_active)
        self.assertEqual(pack.created_by, self.user)
        self.assertEqual(pack.items.count(), 2)

    def test_create_welcome_pack_without_items(self):
        pack = create_welcome_pack_with_items(
            name='Empty Pack', items_data=[], created_by=self.user
        )
        self.assertEqual(pack.items.count(), 0)

    def test_create_welcome_pack_invalid_items_raises(self):
        items = [{'product': 99999, 'quantity': '1'}]
        with self.assertRaises(WelcomePackError):
            create_welcome_pack_with_items(
                name='Bad Pack', items_data=items, created_by=self.user
            )
        self.assertEqual(WelcomePack.objects.count(), 0)


class WelcomePackServiceUpdateTests(TestCase):
    def setUp(self):
        self.user = make_admin()
        self.product1 = Product.objects.create(
            name='Product A', sku='PROD-A', cost_usd='10.00', count=100, unit='piece'
        )
        self.product2 = Product.objects.create(
            name='Product B', sku='PROD-B', cost_usd='25.50', count=50, unit='piece'
        )
        self.pack = WelcomePack.objects.create(name='Original', created_by=self.user)
        WelcomePackItem.objects.create(
            welcome_pack=self.pack, product=self.product1, quantity=Decimal('1')
        )

    def test_update_welcome_pack_name(self):
        pack = update_welcome_pack_with_items(self.pack, name='Updated Name')
        self.assertEqual(pack.name, 'Updated Name')

    def test_update_welcome_pack_description(self):
        pack = update_welcome_pack_with_items(self.pack, description='New desc')
        self.assertEqual(pack.description, 'New desc')

    def test_update_welcome_pack_is_active(self):
        pack = update_welcome_pack_with_items(self.pack, is_active=False)
        self.assertFalse(pack.is_active)

    def test_update_welcome_pack_replace_items(self):
        pack = update_welcome_pack_with_items(
            self.pack, items_data=[{'product': self.product2.id, 'quantity': '3'}]
        )
        self.assertEqual(pack.items.count(), 1)
        self.assertEqual(pack.items.first().product, self.product2)
        self.assertEqual(pack.items.first().quantity, Decimal('3'))

    def test_update_welcome_pack_remove_all_items(self):
        pack = update_welcome_pack_with_items(self.pack, items_data=[])
        self.assertEqual(pack.items.count(), 0)

    def test_update_welcome_pack_partial_fields(self):
        pack = update_welcome_pack_with_items(self.pack, is_active=False)
        self.assertEqual(pack.name, 'Original')
        self.assertFalse(pack.is_active)

    def test_update_welcome_pack_invalid_items_raises(self):
        with self.assertRaises(WelcomePackError):
            update_welcome_pack_with_items(
                self.pack, items_data=[{'product': 99999, 'quantity': '1'}]
            )
        self.pack.refresh_from_db()
        self.assertEqual(self.pack.items.count(), 1)


class WelcomePackServiceIssueTests(TestCase):
    def setUp(self):
        self.user = make_admin()
        self.employee = ClinicUser.objects.create_user(
            username='emp_issue', password='TestPass123!', role=ClinicUser.Role.EMPLOYEE
        )
        self.customer = Customer.objects.create(
            first_name='Jane', last_name='Smith',
            mobile_number='09120000002', national_id='002-0000002'
        )
        self.pack = WelcomePack.objects.create(name='Issue Pack', created_by=self.user)
        self.product = Product.objects.create(
            name='Issue Product', sku='ISSUE-PROD', cost_usd='15.00', count=100, unit='piece'
        )
        WelcomePackItem.objects.create(
            welcome_pack=self.pack, product=self.product, quantity=Decimal('2.000')
        )

    def test_issue_welcome_pack_basic(self):
        usage = issue_welcome_pack(
            welcome_pack=self.pack, customer=self.customer, quantity=Decimal('1'),
            issued_by=self.employee, rate=Decimal('50000')
        )
        self.assertEqual(usage.welcome_pack, self.pack)
        self.assertEqual(usage.customer, self.customer)
        self.assertEqual(usage.issued_by, self.employee)
        self.assertEqual(usage.quantity, Decimal('1'))
        self.assertEqual(usage.total_cost_usd_snapshot, Decimal('30.00'))
        self.assertEqual(usage.exchange_rate_snapshot, Decimal('50000'))
        self.assertEqual(usage.total_cost_toman_snapshot, Decimal('1500000.00'))

    def test_issue_welcome_pack_multiple_quantity(self):
        usage = issue_welcome_pack(
            welcome_pack=self.pack, customer=self.customer, quantity=Decimal('3'),
            issued_by=self.employee, rate=Decimal('50000')
        )
        self.assertEqual(usage.quantity, Decimal('3'))
        self.assertEqual(usage.total_cost_usd_snapshot, Decimal('90.00'))
        self.assertEqual(usage.total_cost_toman_snapshot, Decimal('4500000.00'))

    def test_issue_welcome_pack_with_visit(self):
        from datetime import datetime

        from customers.models import Visit
        visit = Visit.objects.create(
            customer=self.customer, staff=self.employee,
            start_at=timezone.make_aware(datetime(2026, 1, 1, 10, 0)),
            end_at=timezone.make_aware(datetime(2026, 1, 1, 11, 0)),
            status=Visit.Status.COMPLETED,
        )
        usage = issue_welcome_pack(
            welcome_pack=self.pack, customer=self.customer, quantity=Decimal('1'),
            visit=visit, issued_by=self.employee, rate=Decimal('50000')
        )
        self.assertEqual(usage.visit, visit)

    def test_issue_welcome_pack_inactive_pack_raises(self):
        self.pack.is_active = False
        self.pack.save()
        with self.assertRaises(WelcomePackError) as ctx:
            issue_welcome_pack(
                welcome_pack=self.pack, customer=self.customer, quantity=Decimal('1'),
                issued_by=self.employee, rate=Decimal('50000')
            )
        self.assertIn('not active', str(ctx.exception))

    def test_issue_welcome_pack_no_rate_raises(self):
        from unittest.mock import patch
        with patch('finance.services.welcome_pack.get_current_usd_to_toman_rate', return_value=None):
            with self.assertRaises(WelcomePackError) as ctx:
                issue_welcome_pack(
                    welcome_pack=self.pack, customer=self.customer, quantity=Decimal('1'),
                    issued_by=self.employee, rate=None
                )
            self.assertIn('Exchange rate unavailable', str(ctx.exception))

    def test_issue_welcome_pack_creates_snapshot(self):
        usage = issue_welcome_pack(
            welcome_pack=self.pack, customer=self.customer, quantity=Decimal('1'),
            issued_by=self.employee, rate=Decimal('50000')
        )
        usage.refresh_from_db()
        self.assertEqual(usage.total_cost_usd_snapshot, Decimal('30.00'))
        self.assertEqual(usage.exchange_rate_snapshot, Decimal('50000'))
        self.assertEqual(usage.total_cost_toman_snapshot, Decimal('1500000.00'))


class WelcomePackServiceReportTests(TestCase):
    def setUp(self):
        self.user = make_admin()
        self.employee = ClinicUser.objects.create_user(
            username='emp_report', password='TestPass123!', role=ClinicUser.Role.EMPLOYEE
        )
        self.customer = Customer.objects.create(
            first_name='Report', last_name='User',
            mobile_number='09120000003', national_id='003-0000003'
        )
        self.pack1 = WelcomePack.objects.create(name='Pack 1', created_by=self.user)
        self.pack2 = WelcomePack.objects.create(name='Pack 2', created_by=self.user)
        self.product1 = Product.objects.create(
            name='Product 1', sku='P1', cost_usd='10.00', count=100, unit='piece'
        )
        self.product2 = Product.objects.create(
            name='Product 2', sku='P2', cost_usd='20.00', count=50, unit='piece'
        )
        WelcomePackItem.objects.create(
            welcome_pack=self.pack1, product=self.product1, quantity=Decimal('2')
        )
        WelcomePackItem.objects.create(
            welcome_pack=self.pack2, product=self.product2, quantity=Decimal('1')
        )

    def test_get_welcome_pack_usage_summary_empty(self):
        start = timezone.now() - timezone.timedelta(days=30)
        end = timezone.now()
        result = get_welcome_pack_usage_summary(start, end)
        self.assertEqual(result['total_usage_count'], 0)
        self.assertEqual(result['total_packs_issued'], Decimal('0'))
        self.assertEqual(result['total_cost_usd'], Decimal('0'))
        self.assertEqual(result['total_cost_toman'], Decimal('0'))
        self.assertEqual(result['by_pack'], [])

    def test_get_welcome_pack_usage_summary_with_data(self):
        issue_welcome_pack(
            welcome_pack=self.pack1, customer=self.customer, quantity=Decimal('2'),
            issued_by=self.employee, rate=Decimal('50000')
        )
        issue_welcome_pack(
            welcome_pack=self.pack2, customer=self.customer, quantity=Decimal('1'),
            issued_by=self.employee, rate=Decimal('50000')
        )
        start = timezone.now() - timezone.timedelta(days=30)
        end = timezone.now()
        result = get_welcome_pack_usage_summary(start, end)
        self.assertEqual(result['total_usage_count'], 2)
        self.assertEqual(result['total_packs_issued'], Decimal('3'))
        # pack1: 10*2=20 *2 =40, pack2: 20*1=20 *1 =20 => total 60
        self.assertEqual(result['total_cost_usd'], Decimal('60.00'))
        self.assertEqual(result['total_cost_toman'], Decimal('3000000.00'))
        self.assertEqual(len(result['by_pack']), 2)
        self.assertEqual(result['by_pack'][0]['welcome_pack__name'], 'Pack 1')

    def test_get_welcome_pack_usage_summary_filters_by_date(self):
        issue_welcome_pack(
            welcome_pack=self.pack1, customer=self.customer, quantity=Decimal('1'),
            issued_by=self.employee, rate=Decimal('50000'),
            at=timezone.now() - timezone.timedelta(days=40)
        )
        issue_welcome_pack(
            welcome_pack=self.pack1, customer=self.customer, quantity=Decimal('1'),
            issued_by=self.employee, rate=Decimal('50000')
        )
        start = timezone.now() - timezone.timedelta(days=30)
        end = timezone.now()
        result = get_welcome_pack_usage_summary(start, end)
        self.assertEqual(result['total_usage_count'], 1)
        self.assertEqual(result['total_packs_issued'], Decimal('1'))


class WelcomePackServiceGetItemsTests(TestCase):
    def setUp(self):
        self.user = make_admin()
        self.pack = WelcomePack.objects.create(name='Items Pack', created_by=self.user)
        self.product1 = Product.objects.create(
            name='Product 1', sku='IP1', cost_usd='10.00', count=100, unit='piece'
        )
        self.product2 = Product.objects.create(
            name='Product 2', sku='IP2', cost_usd='20.00', count=50, unit='piece'
        )
        WelcomePackItem.objects.create(
            welcome_pack=self.pack, product=self.product1, quantity=Decimal('2')
        )
        WelcomePackItem.objects.create(
            welcome_pack=self.pack, product=self.product2, quantity=Decimal('1')
        )

    def test_get_welcome_pack_items(self):
        items = get_welcome_pack_items(self.pack)
        self.assertEqual(items.count(), 2)
        product_ids = [item.product_id for item in items]
        self.assertIn(self.product1.id, product_ids)
        self.assertIn(self.product2.id, product_ids)
