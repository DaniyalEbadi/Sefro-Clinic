from datetime import time, timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from accounts.models import ClinicUser
from customers.models import Customer, Service, Visit, WorkTime

from Sefro_Clinic.fields import greg_to_shamsi_dt


class VisitPastDateAccessTest(TestCase):
    def setUp(self):
        self.admin = ClinicUser.objects.get(username='sefro_admin')
        self.admin_password = 'SefroClinic@2026'
        self.employee = ClinicUser.objects.create_user(
            username='emp_user', password='emp12345',
            role=ClinicUser.Role.EMPLOYEE,
        )

        WorkTime.objects.create(start_time=time(9, 0), end_time=time(18, 0))

        self.customer = Customer.objects.create(
            first_name='Ali', last_name='Rezaei',
            mobile_number='09121111111', national_id='001-0000001',
            bitmoji_code='B001',
        )
        self.service = Service.objects.create(name='Consultation')

        past = timezone.now() - timedelta(days=30)
        past = past.replace(hour=10, minute=0, second=0, microsecond=0)
        self.past_visit = Visit.objects.create(
            customer=self.customer,
            start_at=past,
            end_at=past + timedelta(hours=1),
            status=Visit.Status.COMPLETED,
        )

    def _login(self, username, password):
        client = APIClient()
        resp = client.post('/api/auth/token/', {
            'username': username, 'password': password,
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        client.credentials(HTTP_AUTHORIZATION=f'Bearer {resp.data["access"]}')
        return client

    def _admin_client(self):
        return self._login('sefro_admin', self.admin_password)

    def _employee_client(self):
        return self._login('emp_user', 'emp12345')

    def _past_dt(self, days_ago, hour, minute=0):
        dt = timezone.now() - timedelta(days=days_ago)
        return dt.replace(hour=hour, minute=minute, second=0, microsecond=0)

    def test_employee_can_list_past_visit(self):
        client = self._employee_client()
        resp = client.get('/api/visits/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        ids = [v['id'] for v in resp.data['results']]
        self.assertIn(self.past_visit.id, ids)

    def test_employee_can_retrieve_past_visit(self):
        client = self._employee_client()
        resp = client.get(f'/api/visits/{self.past_visit.id}/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['id'], self.past_visit.id)

    def test_admin_can_list_past_visit(self):
        client = self._admin_client()
        resp = client.get('/api/visits/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        ids = [v['id'] for v in resp.data['results']]
        self.assertIn(self.past_visit.id, ids)

    def test_admin_can_retrieve_past_visit(self):
        client = self._admin_client()
        resp = client.get(f'/api/visits/{self.past_visit.id}/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['id'], self.past_visit.id)

    def test_employee_can_create_forgotten_past_visit_within_work_time(self):
        past = self._past_dt(days_ago=14, hour=10, minute=0)
        resp = self._employee_client().post('/api/visits/', {
            'customer': self.customer.id,
            'start_at': greg_to_shamsi_dt(past),
            'end_at': greg_to_shamsi_dt(past + timedelta(hours=1)),
            'services': [self.service.id],
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

    def test_admin_can_create_forgotten_past_visit_within_work_hours(self):
        past = self._past_dt(days_ago=14, hour=10, minute=0)
        resp = self._admin_client().post('/api/visits/', {
            'customer': self.customer.id,
            'start_at': greg_to_shamsi_dt(past),
            'end_at': greg_to_shamsi_dt(past + timedelta(hours=1)),
            'services': [self.service.id],
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

    def test_employee_past_visit_outside_work_hours_is_rejected(self):
        past = self._past_dt(days_ago=14, hour=20, minute=0)
        resp = self._employee_client().post('/api/visits/', {
            'customer': self.customer.id,
            'start_at': greg_to_shamsi_dt(past),
            'end_at': greg_to_shamsi_dt(past + timedelta(hours=1)),
            'services': [self.service.id],
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_employee_can_reserve_forgotten_past_visit(self):
        past = self._past_dt(days_ago=14, hour=11, minute=0)
        resp = self._employee_client().post('/api/visits/reserve/', {
            'customer': self.customer.id,
            'services': [self.service.id],
            'date': greg_to_shamsi_dt(past)[:10],
            'time': '11:00',
            'notes': 'Forgotten visit from two weeks ago',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

    def test_past_visit_does_not_break_other_endpoints(self):
        client = self._employee_client()
        for url in ['/api/customers/', '/api/services/', '/api/payments/', '/api/dashboard/', '/api/visits/']:
            resp = client.get(url)
            self.assertEqual(resp.status_code, status.HTTP_200_OK, f'{url} failed')

    def test_past_visit_appears_in_date_filters(self):
        client = self._admin_client()
        resp = client.get('/api/visits/')
        total = resp.data['count']
        resp = client.get('/api/visits/?status=completed')
        self.assertGreaterEqual(resp.data['count'], 1)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertLessEqual(resp.data['count'], total)