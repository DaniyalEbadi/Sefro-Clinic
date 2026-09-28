from datetime import date
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from finance.models import ProductPurchase, PurchaseOrder
from finance.services.exchange_rates import set_rate
from finance.services.inventory import current_cost
from finance.services.purchases import (
    PurchaseOrderError,
    cancel_purchase_order,
    create_purchase_order,
    mark_ordered,
    purchase_summary,
    receive_purchase_order,
    update_purchase_order,
)
from inventory.models import Product
from tests.helpers import make_admin, make_employee

RATE = Decimal('100000')


class PurchaseOrderServiceTests(TestCase):
    def setUp(self):
        set_rate('USD', 'TOMAN', RATE, effective_at=timezone.now(), source='purchase-order-test')
        self.admin = make_admin()
        self.employee = make_employee(username='po_employee')
        self.product = Product.objects.create(
            name='Botox vial', sku='PO-VIAL', unit_price=Decimal('50'),
            cost_usd=Decimal('10.00'), count=Decimal('5'),
        )
        self.other_product = Product.objects.create(
            name='Peel serum', sku='PO-SERUM', unit_price=Decimal('30'),
            cost_usd=Decimal('8.00'), count=Decimal('2'),
        )

    def create_order(self, **overrides):
        payload = {
            'supplier': 'Beauty Supply Co',
            'items_data': [
                {'product': self.product.id, 'quantity': '3', 'unit_cost_usd': '12.50'},
            ],
            'created_by': self.admin,
        }
        payload.update(overrides)
        return create_purchase_order(**payload)

    def test_create_draft_stores_usd_and_touches_nothing(self):
        order, created = self.create_order()
        self.assertTrue(created)
        self.assertEqual(order.status, PurchaseOrder.Status.DRAFT)
        self.assertEqual(order.order_date, timezone.now().date())
        self.assertEqual(order.total_cost_usd, Decimal('37.50'))
        # Toman is only a snapshot once received — still zero while drafting.
        self.assertEqual(order.total_cost_toman, Decimal('0'))
        self.assertIsNone(order.exchange_rate_snapshot)

        item = order.items.get()
        self.assertEqual(item.quantity, Decimal('3.000'))
        self.assertEqual(item.unit_cost_usd, Decimal('12.50'))
        self.assertEqual(item.total_cost_usd, Decimal('37.50'))
        self.assertEqual(item.unit_cost_toman, Decimal('0'))

        self.product.refresh_from_db()
        self.assertEqual(self.product.count, Decimal('5'))
        self.assertEqual(self.product.cost_usd, Decimal('10.00'))

    def test_create_is_idempotent_on_key(self):
        first, created = self.create_order(idempotency_key='restock-001')
        second, created_again = self.create_order(idempotency_key='restock-001')
        self.assertTrue(created)
        self.assertFalse(created_again)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(PurchaseOrder.objects.count(), 1)

    def test_duplicate_product_line_is_rejected(self):
        with self.assertRaises(PurchaseOrderError):
            self.create_order(items_data=[
                {'product': self.product.id, 'quantity': '1', 'unit_cost_usd': '5'},
                {'product': self.product.id, 'quantity': '2', 'unit_cost_usd': '6'},
            ])
        self.assertEqual(PurchaseOrder.objects.count(), 0)

    def test_invalid_lines_are_rejected(self):
        for items in (
            [],
            [{'product': 999999, 'quantity': '1', 'unit_cost_usd': '5'}],
            [{'product': self.product.id, 'quantity': '0', 'unit_cost_usd': '5'}],
            [{'product': self.product.id, 'quantity': '-2', 'unit_cost_usd': '5'}],
            [{'product': self.product.id, 'quantity': '1.1234', 'unit_cost_usd': '5'}],
            [{'product': self.product.id, 'quantity': '1', 'unit_cost_usd': '-1'}],
            [{'quantity': '1', 'unit_cost_usd': '5'}],
        ):
            with self.assertRaises(PurchaseOrderError, msg=f'accepted {items}'):
                self.create_order(items_data=items)
        self.assertEqual(PurchaseOrder.objects.count(), 0)

    def test_order_date_can_be_supplied(self):
        order, _ = self.create_order(order_date=date(2026, 1, 15))
        self.assertEqual(order.order_date, date(2026, 1, 15))

    def test_update_replaces_lines_and_recomputes_total(self):
        order, _ = self.create_order()
        updated = update_purchase_order(order, supplier='New Supplier', items_data=[
            {'product': self.product.id, 'quantity': '1', 'unit_cost_usd': '11.00'},
            {'product': self.other_product.id, 'quantity': '4', 'unit_cost_usd': '2.50'},
        ])
        self.assertEqual(updated.supplier, 'New Supplier')
        self.assertEqual(updated.items.count(), 2)
        self.assertEqual(updated.total_cost_usd, Decimal('21.00'))
        self.assertEqual(PurchaseOrder.objects.count(), 1)

    def test_mark_ordered_then_receive_applies_stock_cost_and_toman(self):
        order, _ = self.create_order()
        order = mark_ordered(order)
        self.assertEqual(order.status, PurchaseOrder.Status.ORDERED)
        # Ordered still has no inventory effect.
        self.product.refresh_from_db()
        self.assertEqual(self.product.count, Decimal('5'))

        received = receive_purchase_order(order)
        self.assertEqual(received.status, PurchaseOrder.Status.RECEIVED)
        self.assertEqual(received.received_date, timezone.now().date())
        self.assertEqual(received.exchange_rate_snapshot, RATE)

        self.product.refresh_from_db()
        self.assertEqual(self.product.count, Decimal('8'))
        self.assertEqual(self.product.cost_usd, Decimal('12.50'))
        self.assertEqual(current_cost(self.product), Decimal('12.50'))

        item = received.items.get()
        self.assertEqual(item.unit_cost_toman, (Decimal('12.50') * RATE).quantize(Decimal('0.01')))
        self.assertEqual(item.total_cost_toman, (Decimal('37.50') * RATE).quantize(Decimal('0.01')))
        self.assertEqual(received.total_cost_usd, Decimal('37.50'))
        self.assertEqual(received.total_cost_toman, (Decimal('37.50') * RATE).quantize(Decimal('0.01')))
        # Receiving must not pollute the legacy one-shot purchase ledger.
        self.assertEqual(ProductPurchase.objects.count(), 0)

    def test_receive_handles_multiple_products(self):
        order, _ = self.create_order(items_data=[
            {'product': self.product.id, 'quantity': '3', 'unit_cost_usd': '12.50'},
            {'product': self.other_product.id, 'quantity': '10', 'unit_cost_usd': '1.00'},
        ])
        receive_purchase_order(order)

        self.product.refresh_from_db()
        self.other_product.refresh_from_db()
        self.assertEqual(self.product.count, Decimal('8'))
        self.assertEqual(self.other_product.count, Decimal('12'))
        self.assertEqual(self.other_product.cost_usd, Decimal('1.00'))
        self.assertEqual(order.total_cost_usd, Decimal('47.50'))

    def test_receive_can_be_repeated_transitions_are_guarded(self):
        order, _ = self.create_order()
        receive_purchase_order(order)

        with self.assertRaises(PurchaseOrderError):
            receive_purchase_order(order)
        with self.assertRaises(PurchaseOrderError):
            cancel_purchase_order(order)
        with self.assertRaises(PurchaseOrderError):
            update_purchase_order(order, supplier='Nope')
        with self.assertRaises(PurchaseOrderError):
            mark_ordered(order)

        self.assertEqual(Product.objects.get(pk=self.product.pk).count, Decimal('8'))

    def test_cancel_blocks_receive_and_allows_drafts(self):
        order, _ = self.create_order()
        cancelled = cancel_purchase_order(order)
        self.assertEqual(cancelled.status, PurchaseOrder.Status.CANCELLED)
        with self.assertRaises(PurchaseOrderError):
            receive_purchase_order(cancelled)
        self.assertEqual(Product.objects.get(pk=self.product.pk).count, Decimal('5'))

    def test_receive_rejects_an_invalid_rate(self):
        order, _ = self.create_order()
        # get_rate() always falls back to a positive default, so only an
        # explicitly unusable rate can reach the guard.
        with self.assertRaises(PurchaseOrderError):
            receive_purchase_order(order, rate=Decimal('0'))
        with self.assertRaises(PurchaseOrderError):
            receive_purchase_order(order, rate=Decimal('-5'))
        self.assertEqual(Product.objects.get(pk=self.product.pk).count, Decimal('5'))

    def test_summary_totals_filters_and_groupings(self):
        first, _ = self.create_order(supplier='Alpha Traders')
        receive_purchase_order(first)

        second, _ = self.create_order(
            supplier='Beta Traders',
            items_data=[{'product': self.other_product.id, 'quantity': '4', 'unit_cost_usd': '2.00'}],
        )
        receive_purchase_order(second)

        draft, _ = self.create_order(supplier='Gamma Traders')
        self.assertEqual(draft.status, PurchaseOrder.Status.DRAFT)

        summary = purchase_summary(timezone.now().date(), timezone.now().date())
        self.assertEqual(summary['order_count'], 2)
        self.assertEqual(summary['total_cost_usd'], Decimal('45.50'))
        self.assertEqual(
            summary['total_cost_toman'],
            (Decimal('45.50') * RATE).quantize(Decimal('0.01')),
        )
        self.assertEqual(len(summary['by_product']), 2)
        self.assertEqual({row['supplier'] for row in summary['by_supplier']}, {'Alpha Traders', 'Beta Traders'})

        filtered = purchase_summary(
            timezone.now().date(), timezone.now().date(), supplier='alpha',
        )
        self.assertEqual(filtered['order_count'], 1)
        self.assertEqual(filtered['total_cost_usd'], Decimal('37.50'))

        by_product = purchase_summary(
            timezone.now().date(), timezone.now().date(), product_id=self.other_product.id,
        )
        self.assertEqual(by_product['total_cost_usd'], Decimal('8.00'))
        self.assertEqual(by_product['by_product'][0]['product_name'], 'Peel serum')

    def test_summary_ignores_orders_outside_range(self):
        order, _ = self.create_order()
        receive_purchase_order(order, received_date=date(2020, 1, 1))
        summary = purchase_summary(date(2026, 1, 1), date(2026, 12, 31))
        self.assertEqual(summary['order_count'], 0)
        self.assertEqual(summary['total_cost_usd'], Decimal('0'))
