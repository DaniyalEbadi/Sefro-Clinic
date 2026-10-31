import os
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from tests.helpers import website_manager_client
from website.models import SiteProduct


class ProductDollarRepricingFlowTests(TestCase):
    def test_product_with_image_rises_and_falls_with_usd_rate(self):
        image_url = os.environ.get('SITE_PRICE_TEST_IMAGE_URL', 'https://example.com/test-product.png')
        manager = website_manager_client()
        sync_url = '/api/v2/site-dashboard/price-sync/run/'
        product_url = '/api/v2/products/dollar-test-product/'

        initial = manager.post(sync_url, {'rate': '200000'}, format='json')
        self.assertEqual(initial.status_code, 200, initial.data)

        created = manager.post('/api/v2/site-dashboard/products/', {
            'name': 'Dollar test product', 'slug': 'dollar-test-product',
            'price_usd': '10.00', 'image_url': image_url,
        }, format='json')
        self.assertEqual(created.status_code, 201, created.data)
        self.assertEqual(created.data['price'], '2000000.00')

        for rate, expected in [('300000', '3000000.00'), ('150000', '1500000.00')]:
            synced = manager.post(sync_url, {'rate': rate}, format='json')
            self.assertEqual(synced.status_code, 200, synced.data)
            public = APIClient().get(product_url)
            self.assertEqual(public.status_code, 200, public.data)
            self.assertEqual(public.data['price'], expected)
            self.assertEqual(Decimal(public.data['price_usd']), Decimal('10.00'))
            self.assertEqual(public.data['image_url'], image_url)

        product = SiteProduct.objects.get(slug='dollar-test-product')
        self.assertEqual(product.price, Decimal('1500000'))
        self.assertEqual(product.price_usd, Decimal('10.00'))
