from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient
from django.test import TestCase

from accounts.models import ClinicUser
from customers.models import Customer, Service
from appointments.models import Appointment


class AppointmentsE2ETest(TestCase):
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

        self.service = Service.objects.create(name='Consultation')
        self.customer = Customer.objects.create(
            first_name='Ali', last_name='Rezaei',
            mobile_number='09121111111', national_id='001-0000001',
            bitmoji_code='B001',
        )

    def test_01_appointment_full_crud(self):
        start = timezone.now() + timezone.timedelta(hours=1)
        end = start + timezone.timedelta(hours=1)

        create_resp = self.client.post('/api/appointments/', {
            'customer': self.customer.id,
            'service': self.service.id,
            'start_at': start.isoformat(),
            'end_at': end.isoformat(),
            'status': 'pending',
        }, format='json')
        self.assertEqual(create_resp.status_code, status.HTTP_201_CREATED)
        aid = create_resp.data['id']

        list_resp = self.client.get('/api/appointments/')
        self.assertEqual(list_resp.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(list_resp.data), 1)

        detail_resp = self.client.get(f'/api/appointments/{aid}/')
        self.assertEqual(detail_resp.status_code, status.HTTP_200_OK)

        update_resp = self.client.put(f'/api/appointments/{aid}/', {
            'customer': self.customer.id,
            'service': self.service.id,
            'start_at': start.isoformat(),
            'end_at': end.isoformat(),
            'status': 'confirmed',
        }, format='json')
        self.assertEqual(update_resp.status_code, status.HTTP_200_OK)
        self.assertEqual(update_resp.data['status'], 'confirmed')

        patch_resp = self.client.patch(f'/api/appointments/{aid}/', {
            'status': 'completed',
        }, format='json')
        self.assertEqual(patch_resp.status_code, status.HTTP_200_OK)
        self.assertEqual(patch_resp.data['status'], 'completed')

        delete_resp = self.client.delete(f'/api/appointments/{aid}/')
        self.assertEqual(delete_resp.status_code, status.HTTP_204_NO_CONTENT)

        get_deleted = self.client.get(f'/api/appointments/{aid}/')
        self.assertEqual(get_deleted.status_code, status.HTTP_404_NOT_FOUND)

    def test_02_unauthenticated_access_fails(self):
        self.client.credentials()
        self.client.cookies.clear()
        resp = self.client.get('/api/appointments/')
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)
