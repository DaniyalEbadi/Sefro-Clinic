from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from tests.website.test_models import make_package, make_product, make_service
from website.models import ContactMessage


class AnonymousVisitorJourneyE2ETests(TestCase):
    """Simulates the real website visitor: browse catalog, then leave a
    consultation request - all without any authentication."""

    def setUp(self):
        self.client = APIClient()
        self.botox = make_service()
        self.facial = make_service(
            name='پاکسازی پوست', slug='facial', category='skin',
            price='1500000.00', sort_order=2,
        )
        self.package = make_package()
        self.package.services.add(self.botox, self.facial)
        self.product = make_product()

    def test_full_visitor_flow(self):
        services = self.client.get('/api/v2/services/')
        self.assertEqual(services.status_code, status.HTTP_200_OK)
        self.assertEqual(services.data['count'], 2)

        skin_only = self.client.get('/api/v2/services/?category=skin')
        self.assertEqual([row['slug'] for row in skin_only.data['results']], ['facial'])

        detail = self.client.get('/api/v2/services/botox/')
        self.assertEqual(detail.status_code, status.HTTP_200_OK)
        self.assertEqual(detail.data['name'], 'بوتاکس')

        packages = self.client.get('/api/v2/packages/')
        row = packages.data['results'][0]
        self.assertEqual(row['discount_percent'], 19)
        self.assertEqual(len(row['services']), 2)

        products = self.client.get('/api/v2/products/')
        self.assertEqual(products.data['results'][0]['slug'], self.product.slug)

        contact = self.client.post('/api/v2/contact/', {
            'full_name': 'بازدیدکننده سایت',
            'phone': '09129876543',
            'message': 'می‌خواهم برای بوتاکس وقت رزرو کنم.',
        }, format='json')
        self.assertEqual(contact.status_code, status.HTTP_201_CREATED)

        stored = ContactMessage.objects.get(phone='09129876543')
        self.assertEqual(stored.full_name, 'بازدیدکننده سایت')
        self.assertFalse(stored.is_handled)

    def test_visitor_cannot_mutate_catalog(self):
        for method, url in [
            ('post', '/api/v2/services/'),
            ('delete', '/api/v2/services/botox/'),
            ('put', '/api/v2/packages/rejuvenation/'),
            ('patch', '/api/v2/products/vitamin-c-serum/'),
        ]:
            payload = {'name': 'hack'} if method in ('post', 'put', 'patch') else None
            if payload:
                response = getattr(self.client, method)(url, payload, format='json')
            else:
                response = getattr(self.client, method)(url)
            self.assertIn(response.status_code, [status.HTTP_403_FORBIDDEN, status.HTTP_405_METHOD_NOT_ALLOWED], url)
