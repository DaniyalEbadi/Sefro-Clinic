"""ProductUsage freezes the price of every stock draw-down.

Decision under test: whenever stock goes down the row it leaves behind records
the dollar cost, the toman cost at the exchange rate of that moment, and the
customer the product was given to. ``/api/finance/product-usages/`` is the
warehouse consumption log, so it must answer "who used what, and what was it
worth then" without re-reading live product costs or live rates.
"""
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from customers.models import Service, Visit
from finance.models import ProductCostHistory, ProductUsage, Sale, ServiceItem, WelcomePack, WelcomePackItem
from finance.services import accounting
from finance.services.accounting import ConsumptionError
from finance.services.exchange_rates import set_rate
from finance.services.inventory import InventoryError, record_product_purchase, record_product_usage
from finance.services.welcome_pack import issue_welcome_pack
from inventory.models import Product
from tests.helpers import make_customer

RATE = Decimal('100000')


def make_product(**overrides):
    base = {
        'name': 'Serum', 'sku': 'SKU-SNAP', 'unit_price': Decimal('100'),
        'cost_usd': Decimal('20.00'), 'count': Decimal('10'),
    }
    base.update(overrides)
    return Product.objects.create(**base)


def make_visit(customer, service=None):
    visit = Visit.objects.create(
        customer=customer, start_at=timezone.now(),
        end_at=timezone.now() + timedelta(hours=1),
    )
    if service is not None:
        visit.services.add(service)
    return visit


class StockDecrementPriceSnapshotTests(TestCase):
    """A stock draw-down writes the USD and Toman price of that moment."""

    def setUp(self):
        set_rate('USD', 'TOMAN', RATE, effective_at=timezone.now(), source='snapshot-test')
        self.customer = make_customer()
        self.product = make_product()
        self.visit = make_visit(self.customer)

    def _consume(self, quantity, **kwargs):
        return record_product_usage(
            product=self.product, quantity=quantity, visit=self.visit,
            decrement_stock=True, **kwargs,
        )

    def test_decrement_writes_unit_and_total_price_in_usd_and_toman(self):
        usage = self._consume(Decimal('1'))

        self.assertEqual(usage.unit_cost_usd_snapshot, Decimal('20.00'))
        self.assertEqual(usage.total_cost_usd_snapshot, Decimal('20.00'))
        self.assertEqual(usage.exchange_rate_snapshot, RATE)
        self.assertEqual(usage.unit_cost_toman_snapshot, Decimal('2000000.00'))
        self.assertEqual(usage.total_cost_toman_snapshot, Decimal('2000000.00'))

    def test_decrement_also_draws_stock_down(self):
        self._consume(Decimal('2.5'))
        self.product.refresh_from_db()
        self.assertEqual(self.product.count, Decimal('7.500'))

    def test_total_price_is_unit_price_times_quantity(self):
        usage = self._consume(Decimal('2.5'))

        self.assertEqual(usage.quantity, Decimal('2.500'))
        self.assertEqual(usage.unit_cost_usd_snapshot, Decimal('20.00'))
        self.assertEqual(usage.total_cost_usd_snapshot, Decimal('50.00'))
        self.assertEqual(usage.unit_cost_toman_snapshot, Decimal('2000000.00'))
        self.assertEqual(usage.total_cost_toman_snapshot, Decimal('5000000.00'))

    def test_toman_price_is_taken_from_the_rate_in_effect_at_that_moment(self):
        from finance.models import ExchangeRate

        ExchangeRate.objects.all().delete()
        now = timezone.now()
        set_rate('USD', 'TOMAN', Decimal('90000'), effective_at=now - timedelta(hours=3), source='earlier')
        set_rate('USD', 'TOMAN', Decimal('120000'), effective_at=now - timedelta(hours=1), source='later')

        current = record_product_usage(product=self.product, quantity=Decimal('1'), visit=self.visit)
        backdated = record_product_usage(
            product=self.product, quantity=Decimal('1'), visit=self.visit,
            at=now - timedelta(hours=2),
        )

        self.assertEqual(current.exchange_rate_snapshot, Decimal('120000'))
        self.assertEqual(current.total_cost_toman_snapshot, Decimal('2400000.00'))
        self.assertEqual(backdated.exchange_rate_snapshot, Decimal('90000'))
        self.assertEqual(backdated.total_cost_toman_snapshot, Decimal('1800000.00'))

    def test_explicit_rate_overrides_the_stored_one(self):
        usage = record_product_usage(
            product=self.product, quantity=Decimal('1'), visit=self.visit, rate=Decimal('50000'),
        )
        self.assertEqual(usage.exchange_rate_snapshot, Decimal('50000'))
        self.assertEqual(usage.total_cost_toman_snapshot, Decimal('1000000.00'))

    def test_price_snapshots_survive_a_later_cost_change(self):
        usage = self._consume(Decimal('1'))
        Product.objects.filter(pk=self.product.pk).update(cost_usd=Decimal('99.00'))
        ProductCostHistory.objects.all().delete()

        usage.refresh_from_db()
        self.assertEqual(usage.unit_cost_usd_snapshot, Decimal('20.00'))
        self.assertEqual(usage.total_cost_toman_snapshot, Decimal('2000000.00'))

    def test_a_later_purchase_does_not_reprice_an_existing_usage(self):
        first = self._consume(Decimal('1'))
        record_product_purchase(
            product=self.product, quantity=Decimal('5'), unit_cost_usd=Decimal('35.00'),
        )
        second = self._consume(Decimal('1'))

        first.refresh_from_db()
        self.assertEqual(first.unit_cost_usd_snapshot, Decimal('20.00'))
        self.assertEqual(first.unit_cost_toman_snapshot, Decimal('2000000.00'))
        self.assertEqual(second.unit_cost_usd_snapshot, Decimal('35.00'))
        self.assertEqual(second.unit_cost_toman_snapshot, Decimal('3500000.00'))

    def test_insufficient_stock_writes_nothing_at_all(self):
        with self.assertRaises(InventoryError):
            self._consume(Decimal('999'))

        self.assertEqual(ProductUsage.objects.count(), 0)
        self.product.refresh_from_db()
        self.assertEqual(self.product.count, Decimal('10.000'))


class CustomerLinkTests(TestCase):
    """Every consumption row knows which customer the product went to."""

    def setUp(self):
        set_rate('USD', 'TOMAN', RATE, effective_at=timezone.now(), source='customer-link-test')
        self.customer = make_customer(mobile_number='09121111111', national_id='111-1111111')
        self.product = make_product(sku='SKU-CUST')

    def test_usage_taken_from_a_visit_carries_that_visits_customer(self):
        visit = make_visit(self.customer)
        usage = record_product_usage(
            product=self.product, quantity=Decimal('1'), visit=visit, decrement_stock=True,
        )
        self.assertEqual(usage.customer_id, self.customer.id)

    def test_usage_taken_from_a_package_sale_carries_that_sales_customer(self):
        sale = Sale.objects.create(customer=self.customer, amount_usd=Decimal('100.00'))
        usage = record_product_usage(
            product=self.product, quantity=Decimal('1'), package_sale=sale, decrement_stock=True,
        )
        self.assertEqual(usage.customer_id, self.customer.id)

    def test_usage_taken_from_a_welcome_pack_issuance_carries_that_customers_pack(self):
        pack = WelcomePack.objects.create(name='Snapshot pack')
        WelcomePackItem.objects.create(welcome_pack=pack, product=self.product, quantity=Decimal('2'))

        issue_welcome_pack(welcome_pack=pack, customer=self.customer, quantity='1', rate=RATE)

        usage = ProductUsage.objects.get(product=self.product)
        self.assertEqual(usage.customer_id, self.customer.id)
        self.assertIsNotNone(usage.welcome_pack_usage_id)
        self.assertEqual(usage.total_cost_usd_snapshot, Decimal('40.00'))
        self.assertEqual(usage.total_cost_toman_snapshot, Decimal('4000000.00'))

    def test_an_explicit_customer_wins_over_the_linked_source(self):
        other = make_customer(mobile_number='09122222222', national_id='222-2222222')
        visit = make_visit(self.customer)
        usage = record_product_usage(
            product=self.product, quantity=Decimal('1'), visit=visit, customer=other,
        )
        self.assertEqual(usage.customer_id, other.id)

    def test_a_usage_with_no_source_has_no_customer(self):
        usage = record_product_usage(product=self.product, quantity=Decimal('1'))
        self.assertIsNone(usage.customer_id)

    def test_visit_consumption_records_the_customer_for_recipe_and_extra_items(self):
        service = Service.objects.create(name='Peel', price_usd=Decimal('120'))
        recipe = make_product(sku='SKU-RECIPE')
        extra = make_product(sku='SKU-EXTRA')
        ServiceItem.objects.create(service=service, product=recipe, quantity=Decimal('1'))
        visit = make_visit(self.customer, service)

        accounting.record_visit_consumption(
            visit,
            selected_products={str(service.id): [[recipe.id, '1']]},
            extra_products=[[extra.id, '2']], rate=RATE,
        )

        rows = ProductUsage.objects.filter(visit=visit)
        self.assertEqual(rows.count(), 2)
        self.assertEqual({r.customer_id for r in rows}, {self.customer.id})
        recipe_row = rows.get(product=recipe)
        extra_row = rows.get(product=extra)
        self.assertEqual(recipe_row.service_id, service.id)
        self.assertIsNone(extra_row.service_id)
        self.assertEqual(recipe_row.total_cost_usd_snapshot, Decimal('20.00'))
        self.assertEqual(recipe_row.total_cost_toman_snapshot, Decimal('2000000.00'))
        self.assertEqual(extra_row.total_cost_usd_snapshot, Decimal('40.00'))
        self.assertEqual(extra_row.total_cost_toman_snapshot, Decimal('4000000.00'))

    def test_re_recording_consumption_for_a_visit_is_still_blocked(self):
        service = Service.objects.create(name='Massage', price_usd=Decimal('80'))
        ServiceItem.objects.create(service=service, product=self.product, quantity=Decimal('1'))
        visit = make_visit(self.customer, service)

        accounting.record_visit_consumption(
            visit, selected_products={str(service.id): [[self.product.id, '1']]}, rate=RATE,
        )
        with self.assertRaises(ConsumptionError):
            accounting.record_visit_consumption(visit, rate=RATE)

        self.assertEqual(ProductUsage.objects.filter(visit=visit).count(), 1)
        self.assertEqual(ProductUsage.objects.filter(visit=visit).first().customer_id, self.customer.id)
