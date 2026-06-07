from rest_framework import status
from rest_framework.test import APIClient
from django.test import TestCase

from accounts.models import ClinicUser
from inventory.models import InventoryItem, Product, StockMovement


class StockMovementIntegrationTest(TestCase):
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

        self.product = Product.objects.create(name='Bandage', sku='SKU-001', unit_price='5000')
        self.item = InventoryItem.objects.create(product=self.product, quantity=10)

    def test_create_movement_updates_inventory(self):
        resp = self.client.post('/api/inventory/movements/', {
            'inventory_item': self.item.id,
            'movement_type': 'in',
            'quantity': 5,
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.item.refresh_from_db()
        self.assertEqual(self.item.quantity, 15)

    def test_create_out_movement_reduces_inventory(self):
        resp = self.client.post('/api/inventory/movements/', {
            'inventory_item': self.item.id,
            'movement_type': 'out',
            'quantity': 3,
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.item.refresh_from_db()
        self.assertEqual(self.item.quantity, 7)
