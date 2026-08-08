from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from accounts.models import ClinicUser
from customers.models import Customer, Service, Visit

from Sefro_Clinic.fields import greg_to_shamsi_dt


class VisitUnrestrictedTimeTest(TestCase):
    def setUp(self):
        self.employee = ClinicUser.objects.create_user(
            username='emp_user', password='emp12345',
            role=ClinicUser.Role.EMPLOYEE,
        )
        self.customer = Customer.objects.create(
            first_name='Ali', last_name='Rezaei',
            mobile_number='09121111111', national_id='001-0000001',
            bitmoji_code='B001',
        )
        self.service = Service.objects.create(name='Consultation')

        past = timezone.now() - timedelta(days=30)
        past = past.replace(hour=23, minute=30, second=0, microsecond=0)
        self.old_visit = Visit.objects.create(
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

    def _employee_client(self):
        return self._login('emp_user', 'emp12345')

    def _create_visit(self, client, start_at, end_at):
        return client.post('/api/visits/', {
            'customer': self.customer.id,
            'start_at': start_at,
            'end_at': end_at,
            'services': [self.service.id],
        }, format='json')

    def test_employee_can_list_old_visit(self):
        resp = self._employee_client().get('/api/visits/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        ids = [v['id'] for v in resp.data['results']]
        self.assertIn(self.old_visit.id, ids)

    def test_employee_can_create_today_current_time(self):
        now = timezone.now()
        resp = self._create_visit(self._employee_client(),
                                  greg_to_shamsi_dt(now),
                                  greg_to_shamsi_dt(now + timedelta(hours=1)))
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

    def test_employee_can_create_today_past_time(self):
        now = timezone.now().replace(hour=0, minute=5, second=0, microsecond=0)
        resp = self._create_visit(self._employee_client(),
                                  greg_to_shamsi_dt(now),
                                  greg_to_shamsi_dt(now + timedelta(hours=1)))
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

    def test_employee_can_create_today_future_time(self):
        now = timezone.now().replace(hour=23, minute=55, second=0, microsecond=0)
        resp = self._create_visit(self._employee_client(),
                                  greg_to_shamsi_dt(now),
                                  greg_to_shamsi_dt(now + timedelta(hours=1)))
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

    def test_employee_can_create_previous_date(self):
        dt = (timezone.now() - timedelta(days=1)).replace(hour=23, minute=30, second=0, microsecond=0)
        resp = self._create_visit(self._employee_client(),
                                  greg_to_shamsi_dt(dt),
                                  greg_to_shamsi_dt(dt + timedelta(hours=1)))
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

    def test_employee_can_create_old_historical_date(self):
        dt = (timezone.now() - timedelta(days=365 * 3)).replace(hour=1, minute=30, second=0, microsecond=0)
        resp = self._create_visit(self._employee_client(),
                                  greg_to_shamsi_dt(dt),
                                  greg_to_shamsi_dt(dt + timedelta(hours=1)))
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

    def test_employee_can_create_cross_midnight_after_hours(self):
        dt = (timezone.now() - timedelta(days=7)).replace(hour=23, minute=0, second=0, microsecond=0)
        resp = self._create_visit(self._employee_client(),
                                  greg_to_shamsi_dt(dt),
                                  greg_to_shamsi_dt(dt + timedelta(hours=2)))
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

    def test_employee_can_edit_old_entry(self):
        client = self._employee_client()
        dt = (timezone.now() - timedelta(days=20)).replace(hour=20, minute=0, second=0, microsecond=0)
        resp = client.put(f'/api/visits/{self.old_visit.id}/', {
            'customer': self.customer.id,
            'start_at': greg_to_shamsi_dt(dt),
            'end_at': greg_to_shamsi_dt(dt + timedelta(hours=1)),
            'services': [self.service.id],
            'status': 'confirmed',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['status'], 'confirmed')

    def test_employee_can_edit_entry_at_night_after_hours(self):
        client = self._employee_client()
        dt = timezone.now().replace(hour=22, minute=0, second=0, microsecond=0)
        resp = client.patch(f'/api/visits/{self.old_visit.id}/', {
            'start_at': greg_to_shamsi_dt(dt),
            'end_at': greg_to_shamsi_dt(dt + timedelta(hours=1)),
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_employee_can_reserve_forgotten_past_visit_any_time(self):
        dt = (timezone.now() - timedelta(days=14)).replace(hour=20, minute=0, second=0, microsecond=0)
        resp = self._employee_client().post('/api/visits/reserve/', {
            'customer': self.customer.id,
            'services': [self.service.id],
            'date': greg_to_shamsi_dt(dt)[:10],
            'time': '20:00',
            'notes': 'Forgotten visit from two weeks ago',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

    def test_invalid_shamsi_datetime_rejected(self):
        resp = self._create_visit(self._employee_client(), 'not-a-date', 'also-bad')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_invalid_reserve_rejected(self):
        resp = self._employee_client().post('/api/visits/reserve/', {
            'customer': self.customer.id,
            'services': [self.service.id],
            'date': '13-13-99',
            'time': '25:99',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_unauthorized_access_rejected(self):
        client = APIClient()
        self.assertEqual(client.get('/api/visits/').status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(client.post('/api/visits/', {}).status_code, status.HTTP_401_UNAUTHORIZED)

    def test_work_time_endpoint_no_longer_exists(self):
        client = self._login('sefro_admin', 'SefroClinic@2026')
        resp = client.get('/api/work-time/')
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_other_endpoints_unchanged(self):
        client = self._employee_client()
        for url in ['/api/customers/', '/api/services/', '/api/payments/', '/api/dashboard/']:
            resp = client.get(url)
            self.assertEqual(resp.status_code, status.HTTP_200_OK, f'{url} failed')
