from django.test import TestCase
from rest_framework import status

from inventory.models import Product
from tests.helpers import admin_client, employee_client


def make_product(**overrides):
    data = {
        'name': 'Vitamin C Serum',
        'sku': 'SKU-001',
        'unit_price': '450000.00',
        'count': 10,
        'unit': 'عدد',
    }
    data.update(overrides)
    return Product.objects.create(**data)


class ProductCrudTests(TestCase):
    def setUp(self):
        self.client = admin_client()

    def test_admin_can_create_product(self):
        response = self.client.post('/api/inventory/products/', {
            'name': 'Sunscreen SPF50', 'sku': 'SKU-002',
            'unit_price': '320000.00', 'count': 25,
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['name'], 'Sunscreen SPF50')

    def test_full_crud_cycle(self):
        make_product()
        listing = self.client.get('/api/inventory/products/')
        self.assertEqual(listing.status_code, 200)
        pid = listing.data['results'][0]['id']

        detail = self.client.get(f'/api/inventory/products/{pid}/')
        self.assertEqual(detail.status_code, 200)

        update = self.client.patch(
            f'/api/inventory/products/{pid}/', {'count': 7}, format='json',
        )
        self.assertEqual(update.status_code, 200)
        self.assertEqual(update.data['count'], 7)

        delete = self.client.delete(f'/api/inventory/products/{pid}/')
        self.assertEqual(delete.status_code, status.HTTP_204_NO_CONTENT)

    def test_search_by_name(self):
        make_product(name='Hyaluronic Cream', sku='SKU-003')
        response = self.client.get('/api/inventory/products/?search=hyaluronic')
        self.assertEqual(response.status_code, 200)
        self.assertGreaterEqual(len(response.data['results']), 1)


class ProductPermissionTests(TestCase):
    def test_employee_can_read_but_not_write(self):
        make_product()
        client = employee_client()
        self.assertEqual(client.get('/api/inventory/products/').status_code, 200)
        response = client.post('/api/inventory/products/', {
            'name': 'Sneaky Product', 'unit_price': '1000',
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_anonymous_blocked(self):
        from rest_framework.test import APIClient
        self.assertEqual(APIClient().get('/api/inventory/products/').status_code, 401)


class ProductValidationTests(TestCase):
    def test_negative_price_rejected(self):
        response = admin_client().post('/api/inventory/products/', {
            'name': 'Bad Price Item', 'unit_price': '-5',
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_duplicate_sku_rejected(self):
        make_product(sku='DUP-1')
        response = admin_client().post('/api/inventory/products/', {
            'name': 'Second Item', 'sku': 'DUP-1', 'unit_price': '1000',
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
