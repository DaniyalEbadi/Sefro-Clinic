from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from customers.models import Customer
from tests.helpers import ADMIN_PASSWORD, ADMIN_USERNAME, make_admin


class CustomerSearchTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        make_admin()
        login_resp = self.client.post('/api/auth/token/', {
            'username': ADMIN_USERNAME, 'password': ADMIN_PASSWORD,
        }, format='json')
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {login_resp.data["access"]}')

        Customer.objects.create(
            first_name='John', last_name='Doe',
            mobile_number='09120000001', national_id='001-0000001',
            bitmoji_code='B001',
        )
        Customer.objects.create(
            first_name='Jane', last_name='Smith',
            mobile_number='09120000002', national_id='002-0000002',
            bitmoji_code='B002',
        )

    def test_search_by_name(self):
        resp = self.client.get('/api/customers/?search=John')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(resp.data['results']), 1)

    def test_search_by_mobile(self):
        resp = self.client.get('/api/customers/?search=09120000002')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(resp.data['results']), 1)
