from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from tests.website.test_models import make_package, make_service
from website.models import ContactMessage


class SeededCatalogTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.botox = make_service()
        self.peel = make_service(
            name='لایه‌برداری', slug='chemical-peel',
            category='skin', price='1800000.00', sort_order=2,
        )
        self.hidden = make_service(
            name='مخفی', slug='hidden', category='hair',
            is_active=False, sort_order=3,
        )

    def test_inactive_services_never_listed(self):
        response = self.client.get('/api/v2/services/')
        slugs = [row['slug'] for row in response.data['results']]
        self.assertIn('botox', slugs)
        self.assertNotIn('hidden', slugs)

    def test_inactive_service_detail_returns_404(self):
        response = self.client.get('/api/v2/services/hidden/')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_category_filter_returns_only_matching(self):
        response = self.client.get('/api/v2/services/?category=skin')
        slugs = [row['slug'] for row in response.data['results']]
        self.assertEqual(slugs, ['chemical-peel'])

    def test_detail_payload_shape(self):
        response = self.client.get('/api/v2/services/botox/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        for field in ['id', 'name', 'slug', 'category', 'short_description',
                      'description', 'price', 'duration_label', 'image_url']:
            self.assertIn(field, response.data)
        self.assertEqual(response.data['price'], '2500000.00')

    def test_package_includes_nested_services_and_discount(self):
        package = make_package()
        package.services.add(self.botox, self.peel)
        response = self.client.get('/api/v2/packages/rejuvenation/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['discount_percent'], 19)
        nested_slugs = [row['slug'] for row in response.data['services']]
        self.assertEqual(nested_slugs, ['botox', 'chemical-peel'])

    def test_pagination_kicks_in_after_twenty_services(self):
        for index in range(25):
            make_service(name=f'خدمت {index}', slug=f'service-{index}', sort_order=100 + index)
        response = self.client.get('/api/v2/services/')
        self.assertEqual(response.data['count'], 27)
        self.assertEqual(len(response.data['results']), 20)
        second_page = self.client.get('/api/v2/services/?page=2')
        self.assertEqual(len(second_page.data['results']), 7)

    def test_contact_message_lands_in_database_with_timestamp(self):
        response = self.client.post('/api/v2/contact/', {
            'full_name': 'مراجعه کننده', 'phone': '09121112222',
            'message': 'سلام',
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        stored = ContactMessage.objects.get(phone='09121112222')
        self.assertIsNotNone(stored.created_at)
        self.assertFalse(stored.is_handled)
