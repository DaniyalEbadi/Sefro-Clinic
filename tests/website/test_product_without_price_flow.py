from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from rest_framework.test import APIClient

from tests.helpers import website_manager_client
from website.models import SiteProduct


class ProductWithoutPriceFlowTests(TestCase):
    @patch('website.views.get_current_usd_to_toman_rate', return_value=None)
    def test_product_create_edit_and_sync_have_no_price(self, rate):
        manager = website_manager_client()
        product_url = '/api/v2/products/unpriced-product/'
        dashboard_url = '/api/v2/site-dashboard/products/unpriced-product/'

        created = manager.post('/api/v2/site-dashboard/products/', {
            'name': 'Unpriced product', 'slug': 'unpriced-product',
            'image_url': 'https://example.com/product.png',
        }, format='json')
        self.assertEqual(created.status_code, 201, created.data)
        rate.assert_not_called()
        self.assertEqual(SiteProduct.objects.get(slug='unpriced-product').price, Decimal('0'))

        for response in (created, manager.get(dashboard_url), APIClient().get(product_url)):
            self.assertIn(response.status_code, (200, 201))
            self.assertNotIn('price', response.data)
            self.assertNotIn('price_usd', response.data)

        for field in ('price', 'price_usd'):
            response = manager.patch(dashboard_url, {field: '10'}, format='json')
            self.assertEqual(response.status_code, 400, response.data)

        edited = manager.patch(dashboard_url, {'description': 'No listed price'}, format='json')
        self.assertEqual(edited.status_code, 200, edited.data)
        self.assertEqual(APIClient().get(product_url).data['description'], 'No listed price')

        synced = manager.post('/api/v2/site-dashboard/price-sync/run/', {'rate': '200000'}, format='json')
        self.assertEqual(synced.status_code, 200, synced.data)
        self.assertEqual(synced.data['updated_products'], 0)
        product = SiteProduct.objects.get(slug='unpriced-product')
        self.assertEqual((product.price, product.price_usd), (Decimal('0'), Decimal('0')))

    def test_public_list_and_detail_omit_legacy_product_prices(self):
        SiteProduct.objects.create(
            name='Legacy product', slug='legacy-product',
            price=Decimal('450000'), price_usd=Decimal('2'),
        )
        manager = website_manager_client()
        for response in (
            APIClient().get('/api/v2/products/'),
            APIClient().get('/api/v2/products/legacy-product/'),
            manager.get('/api/v2/site-dashboard/products/'),
            manager.get('/api/v2/site-dashboard/products/legacy-product/'),
        ):
            self.assertEqual(response.status_code, 200, response.data)
            data = response.data
            if isinstance(data, dict):
                data = data.get('results', data)
            item = data[0] if isinstance(data, list) else data
            self.assertNotIn('price', item)
            self.assertNotIn('price_usd', item)

        schema = manager.get('/api/v2/schema/')
        self.assertEqual(schema.status_code, 200)
        for name in ('SiteProduct', 'SiteProductDashboard', 'PatchedSiteProductDashboard'):
            fields = schema.data['components']['schemas'][name]['properties']
            self.assertNotIn('price', fields)
            self.assertNotIn('price_usd', fields)
