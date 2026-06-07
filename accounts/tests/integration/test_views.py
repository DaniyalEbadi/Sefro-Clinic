from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from accounts.models import ClinicUser


class EmployeeAPIViewTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin, _ = ClinicUser.objects.get_or_create(
            username='sefro_admin',
            defaults={'role': ClinicUser.Role.ADMIN, 'is_staff': True, 'is_superuser': True},
        )
        if not self.admin.check_password('SefroClinic@2026'):
            self.admin.set_password('SefroClinic@2026')
            self.admin.save()
        login_resp = self.client.post(reverse('accounts:token-obtain-pair'), {
            'username': 'sefro_admin', 'password': 'SefroClinic@2026',
        }, format='json')
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {login_resp.data["access"]}')

    def test_non_admin_cannot_create_employee(self):
        self.client.credentials()
        emp_user = ClinicUser.objects.create_user(
            username='emp', password='pass123', role=ClinicUser.Role.EMPLOYEE
        )
        login_resp = self.client.post(reverse('accounts:token-obtain-pair'), {
            'username': 'emp', 'password': 'pass123',
        }, format='json')
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {login_resp.data["access"]}')

        resp = self.client.post(reverse('accounts:employee-create'), {
            'username': 'emp2', 'password': 'Test1234',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
