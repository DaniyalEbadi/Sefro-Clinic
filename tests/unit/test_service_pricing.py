from decimal import Decimal

from django.test import TestCase

from customers.models import Service, ServiceCategory
from customers.services.pricing import (
    calculate_service_cost_usd,
    calculate_service_gross_profit_usd,
    calculate_service_margin_percent,
)
from finance.models import ServiceItem
from inventory.models import Product


class ServiceCostCalculationTests(TestCase):
    def setUp(self):
        self.cat = ServiceCategory.objects.create(name='Laser', slug='laser')
        self.service = Service.objects.create(name='Test Laser', price_usd=Decimal('100.00'), category=self.cat)

    def test_service_cost_calculation_single_product(self):
        p = Product.objects.create(name='Gel', unit_price=Decimal('100'), cost_usd=Decimal('0.20'), count=10)
        ServiceItem.objects.create(service=self.service, product=p, quantity=Decimal('50'))
        self.assertEqual(calculate_service_cost_usd(self.service), Decimal('10.00'))

    def test_service_cost_with_multiple_products(self):
        p1 = Product.objects.create(name='Gel', unit_price=Decimal('100'), cost_usd=Decimal('0.20'), count=10)
        p2 = Product.objects.create(name='Cream', unit_price=Decimal('100'), cost_usd=Decimal('0.50'), count=10)
        p3 = Product.objects.create(name='Disposable', unit_price=Decimal('100'), cost_usd=Decimal('2.00'), count=10)
        ServiceItem.objects.create(service=self.service, product=p1, quantity=Decimal('50'))
        ServiceItem.objects.create(service=self.service, product=p2, quantity=Decimal('10'))
        ServiceItem.objects.create(service=self.service, product=p3, quantity=Decimal('1'))
        self.assertEqual(calculate_service_cost_usd(self.service), Decimal('17.00'))

    def test_service_cost_with_fractional_quantity(self):
        p = Product.objects.create(name='Serum', unit_price=Decimal('100'), cost_usd=Decimal('2.00'), count=10)
        ServiceItem.objects.create(service=self.service, product=p, quantity=Decimal('0.500'))
        # 2.00 * 0.5 = 1.00 with 3-decimal quantity
        cost = calculate_service_cost_usd(self.service)
        self.assertEqual(cost, Decimal('1.00'))
        # also test 3-decimal quantity with multiple
        p2 = Product.objects.create(name='Serum2', unit_price=Decimal('100'), cost_usd=Decimal('1.00'), count=10)
        ServiceItem.objects.create(service=self.service, product=p2, quantity=Decimal('0.333'))
        # total 1.00 + 0.333 = 1.333 -> quantized 1.33
        cost2 = calculate_service_cost_usd(self.service)
        self.assertEqual(cost2, Decimal('1.33'))

    def test_service_cost_no_products(self):
        self.assertEqual(calculate_service_cost_usd(self.service), Decimal('0.00'))

    def test_service_gross_profit(self):
        p = Product.objects.create(name='Gel', unit_price=Decimal('100'), cost_usd=Decimal('10'), count=10)
        ServiceItem.objects.create(service=self.service, product=p, quantity=Decimal('1'))
        # price 100, cost 10 -> gross 90
        self.assertEqual(calculate_service_gross_profit_usd(self.service), Decimal('90.00'))

    def test_zero_service_price(self):
        self.service.price_usd = Decimal('0')
        self.service.save()
        p = Product.objects.create(name='Gel', unit_price=Decimal('100'), cost_usd=Decimal('10'), count=10)
        ServiceItem.objects.create(service=self.service, product=p, quantity=Decimal('1'))
        self.assertEqual(calculate_service_gross_profit_usd(self.service), Decimal('-10.00'))
        self.assertEqual(calculate_service_margin_percent(self.service), Decimal('0.00'))

    def test_negative_gross_profit(self):
        self.service.price_usd = Decimal('50')
        self.service.save()
        p = Product.objects.create(name='Expensive', unit_price=Decimal('100'), cost_usd=Decimal('80'), count=10)
        ServiceItem.objects.create(service=self.service, product=p, quantity=Decimal('1'))
        self.assertEqual(calculate_service_gross_profit_usd(self.service), Decimal('-30.00'))
        self.assertEqual(calculate_service_margin_percent(self.service), Decimal('-60.00'))

    def test_margin_is_not_clamped(self):
        self.service.price_usd = Decimal('10')
        self.service.save()
        p = Product.objects.create(name='Cheap', unit_price=Decimal('100'), cost_usd=Decimal('1'), count=10)
        ServiceItem.objects.create(service=self.service, product=p, quantity=Decimal('1'))
        # gross 9, margin 90%
        self.assertEqual(calculate_service_margin_percent(self.service), Decimal('90.00'))
        # Negative case already tests -60%, over 100% case:
        self.service.price_usd = Decimal('10')
        self.service.save()
        ServiceItem.objects.all().delete()
        p2 = Product.objects.create(name='Neg', unit_price=Decimal('100'), cost_usd=Decimal('0.10'), count=10)
        ServiceItem.objects.create(service=self.service, product=p2, quantity=Decimal('1'))
        # cost 0.10, gross 9.90, margin 99%
        self.assertEqual(calculate_service_margin_percent(self.service), Decimal('99.00'))

    def test_margin_zero_price_returns_zero(self):
        self.service.price_usd = Decimal('0')
        self.service.save()
        self.assertEqual(calculate_service_margin_percent(self.service), Decimal('0.00'))

    def test_service_cost_uses_current_product_cost(self):
        p = Product.objects.create(name='Gel', unit_price=Decimal('100'), cost_usd=Decimal('10'), count=10)
        ServiceItem.objects.create(service=self.service, product=p, quantity=Decimal('2'))
        self.assertEqual(calculate_service_cost_usd(self.service), Decimal('20.00'))
        p.cost_usd = Decimal('15')
        p.save()
        # should reflect updated cost
        # Need to refresh service items: product instance updated, but DB fetch will get new cost
        self.assertEqual(calculate_service_cost_usd(self.service), Decimal('30.00'))
