from django.test import TestCase

from inventory.models import InventoryItem, Product, StockMovement


class ProductModelTest(TestCase):
    def test_str(self):
        p = Product.objects.create(name='Bandage', sku='SKU-001', unit_price='5000')
        self.assertEqual(str(p), 'Bandage')


class InventoryItemModelTest(TestCase):
    def setUp(self):
        self.product = Product.objects.create(name='Bandage', sku='SKU-001', unit_price='5000')
        self.item = InventoryItem.objects.create(product=self.product, quantity=5, minimum_quantity=10)

    def test_is_low_stock_true(self):
        self.assertTrue(self.item.is_low_stock)

    def test_is_low_stock_false(self):
        self.item.quantity = 15
        self.item.save()
        self.assertFalse(self.item.is_low_stock)


class StockMovementModelTest(TestCase):
    def setUp(self):
        self.product = Product.objects.create(name='Bandage', sku='SKU-001', unit_price='5000')
        self.item = InventoryItem.objects.create(product=self.product, quantity=10)

    def test_stock_in_increases_quantity(self):
        StockMovement.objects.create(
            inventory_item=self.item, movement_type='in', quantity=5
        )
        self.item.refresh_from_db()
        self.assertEqual(self.item.quantity, 15)

    def test_stock_out_decreases_quantity(self):
        StockMovement.objects.create(
            inventory_item=self.item, movement_type='out', quantity=3
        )
        self.item.refresh_from_db()
        self.assertEqual(self.item.quantity, 7)
