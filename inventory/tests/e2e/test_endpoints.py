from rest_framework import status
from rest_framework.test import APIClient
from django.test import TestCase

from accounts.models import ClinicUser
from inventory.models import Product, InventoryItem, StockMovement


class InventoryE2ETest(TestCase):
    def _ensure_admin(self):
        admin, _ = ClinicUser.objects.get_or_create(
            username='sefro_admin',
            defaults={'role': ClinicUser.Role.ADMIN, 'is_staff': True, 'is_superuser': True},
        )
        if not admin.check_password('SefroClinic@2026'):
            admin.set_password('SefroClinic@2026')
            admin.save()
        return admin

    def setUp(self):
        self.client = APIClient()
        self._ensure_admin()
        login_resp = self.client.post('/api/auth/token/', {
            'username': 'sefro_admin', 'password': 'SefroClinic@2026',
        }, format='json')
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {login_resp.data["access"]}')

        self.product = Product.objects.create(
            name='Bandage', sku='SKU-001', unit_price='5000'
        )
        self.inventory_item = InventoryItem.objects.create(
            product=self.product, quantity=50, minimum_quantity=10
        )

    def test_01_product_full_crud(self):
        list_resp = self.client.get('/api/inventory/products/')
        self.assertEqual(list_resp.status_code, status.HTTP_200_OK)

        create_resp = self.client.post('/api/inventory/products/', {
            'name': 'Gloves', 'sku': 'SKU-002', 'unit_price': '12000',
        }, format='json')
        self.assertEqual(create_resp.status_code, status.HTTP_201_CREATED)
        pid = create_resp.data['id']

        detail_resp = self.client.get(f'/api/inventory/products/{pid}/')
        self.assertEqual(detail_resp.status_code, status.HTTP_200_OK)

        update_resp = self.client.put(f'/api/inventory/products/{pid}/', {
            'name': 'Latex Gloves', 'sku': 'SKU-002', 'unit_price': '15000',
        }, format='json')
        self.assertEqual(update_resp.status_code, status.HTTP_200_OK)
        self.assertEqual(update_resp.data['name'], 'Latex Gloves')

        patch_resp = self.client.patch(f'/api/inventory/products/{pid}/', {
            'description': 'Powder-free latex gloves',
        }, format='json')
        self.assertEqual(patch_resp.status_code, status.HTTP_200_OK)

        delete_resp = self.client.delete(f'/api/inventory/products/{pid}/')
        self.assertEqual(delete_resp.status_code, status.HTTP_204_NO_CONTENT)

    def test_02_inventory_item_full_crud(self):
        new_product = Product.objects.create(name='Gloves', sku='SKU-002', unit_price='12000')
        list_resp = self.client.get('/api/inventory/items/')
        self.assertEqual(list_resp.status_code, status.HTTP_200_OK)

        create_resp = self.client.post('/api/inventory/items/', {
            'product': new_product.id,
            'quantity': 100,
            'minimum_quantity': 20,
        }, format='json')
        self.assertEqual(create_resp.status_code, status.HTTP_201_CREATED)
        iid = create_resp.data['id']

        detail_resp = self.client.get(f'/api/inventory/items/{iid}/')
        self.assertEqual(detail_resp.status_code, status.HTTP_200_OK)

        update_resp = self.client.put(f'/api/inventory/items/{iid}/', {
            'product': new_product.id,
            'quantity': 80,
            'minimum_quantity': 15,
        }, format='json')
        self.assertEqual(update_resp.status_code, status.HTTP_200_OK)
        self.assertEqual(update_resp.data['quantity'], 80)

        patch_resp = self.client.patch(f'/api/inventory/items/{iid}/', {
            'product': new_product.id,
            'minimum_quantity': 25,
        }, format='json')
        self.assertEqual(patch_resp.status_code, status.HTTP_200_OK)
        self.assertEqual(patch_resp.data['minimum_quantity'], 25)

        delete_resp = self.client.delete(f'/api/inventory/items/{iid}/')
        self.assertEqual(delete_resp.status_code, status.HTTP_204_NO_CONTENT)

    def test_03_stock_movement_full_crud(self):
        item = self.inventory_item

        create_in_resp = self.client.post('/api/inventory/movements/', {
            'inventory_item': item.id,
            'movement_type': 'in',
            'quantity': 20,
        }, format='json')
        self.assertEqual(create_in_resp.status_code, status.HTTP_201_CREATED)
        mid_in = create_in_resp.data['id']
        item.refresh_from_db()
        self.assertEqual(item.quantity, 70)

        create_out_resp = self.client.post('/api/inventory/movements/', {
            'inventory_item': item.id,
            'movement_type': 'out',
            'quantity': 10,
        }, format='json')
        self.assertEqual(create_out_resp.status_code, status.HTTP_201_CREATED)
        mid_out = create_out_resp.data['id']
        item.refresh_from_db()
        self.assertEqual(item.quantity, 60)

        list_resp = self.client.get('/api/inventory/movements/')
        self.assertEqual(list_resp.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(list_resp.data['results']), 2)

        detail_resp = self.client.get(f'/api/inventory/movements/{mid_in}/')
        self.assertEqual(detail_resp.status_code, status.HTTP_200_OK)

        delete_resp = self.client.delete(f'/api/inventory/movements/{mid_out}/')
        self.assertEqual(delete_resp.status_code, status.HTTP_204_NO_CONTENT)

    def test_04_unauthenticated_access_fails(self):
        self.client.credentials()
        self.client.cookies.clear()
        resp = self.client.get('/api/inventory/products/')
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)
