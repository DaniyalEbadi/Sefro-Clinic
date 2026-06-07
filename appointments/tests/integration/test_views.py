from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from accounts.models import ClinicUser
from appointments.models import Appointment
from customers.models import Customer, Service


class AppointmentFilterTest(TestCase):
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

        self.customer = Customer.objects.create(
            first_name='Ali', last_name='Rezaei',
            mobile_number='09121111111', national_id='001-0000001',
            bitmoji_code='B001',
        )
        self.service = Service.objects.create(name='Consultation')

        Appointment.objects.create(
            customer=self.customer, service=self.service,
            start_at=timezone.now(), end_at=timezone.now() + timezone.timedelta(hours=1),
            status='pending',
        )

    def test_list_appointments(self):
        resp = self.client.get('/api/appointments/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(resp.data), 1)
