from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from accounts.models import ClinicUser
from customers.models import Customer, Service, Visit


class CustomerSearchTest(TestCase):
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
        self.assertEqual(len(resp.data), 1)

    def test_search_by_mobile(self):
        resp = self.client.get('/api/customers/?search=09120000002')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(resp.data), 1)
