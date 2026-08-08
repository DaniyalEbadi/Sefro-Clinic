import jdatetime
from rest_framework import status
from rest_framework.test import APIClient
from django.test import TestCase

from accounts.models import ClinicUser
from customers.models import Customer, Service
from logs.models import AuditLog


class AuditLogTest(TestCase):
    def setUp(self):
        self.admin = ClinicUser.objects.get(username='sefro_admin')
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

    def _client(self, username, password):
        client = APIClient()
        resp = client.post('/api/auth/token/', {
            'username': username, 'password': password,
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        client.credentials(HTTP_AUTHORIZATION=f'Bearer {resp.data["access"]}')
        return client

    def _employee_client(self):
        return self._client('emp_user', 'emp12345')

    def _admin_client(self):
        return self._client('sefro_admin', 'SefroClinic@2026')

    def test_employee_crud_is_logged(self):
        client = self._employee_client()

        create_resp = client.post('/api/visits/', {
            'customer': self.customer.id,
            'start_at': '1404-03-23 10:00',
            'end_at': '1404-03-23 11:00',
            'services': [self.service.id],
        }, format='json')
        self.assertEqual(create_resp.status_code, status.HTTP_201_CREATED)
        vid = create_resp.data['id']

        client.put(f'/api/visits/{vid}/', {
            'customer': self.customer.id,
            'start_at': '1404-03-24 10:00',
            'end_at': '1404-03-24 11:00',
            'services': [self.service.id],
            'status': 'confirmed',
        }, format='json')

        client.delete(f'/api/visits/{vid}/')

        logs = AuditLog.objects.filter(user=self.employee, model_name='customers.visit').order_by('timestamp')
        self.assertEqual(logs.count(), 3)
        actions = list(logs.values_list('action', flat=True))
        self.assertEqual(actions, ['CREATE', 'UPDATE', 'DELETE'])
        self.assertEqual(logs.get(action='CREATE').object_id, vid)
        self.assertIn('start_at', logs.get(action='CREATE').changes)

    def test_log_list_exposes_expected_fields(self):
        client = self._employee_client()
        client.post('/api/visits/', {
            'customer': self.customer.id,
            'start_at': '1404-03-23 10:00',
            'end_at': '1404-03-23 11:00',
            'services': [self.service.id],
        }, format='json')

        admin_client = self._admin_client()
        resp = admin_client.get('/api/logs/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        log = resp.data['results'][0]
        for field in ['id', 'user', 'username', 'action', 'model_name', 'object_id', 'object_repr', 'changes', 'timestamp']:
            self.assertIn(field, log)
        self.assertEqual(log['username'], 'emp_user')
        self.assertEqual(log['action'], 'CREATE')
        self.assertEqual(log['model_name'], 'customers.visit')

    def test_timestamp_is_shamsi(self):
        client = self._employee_client()
        client.post('/api/visits/', {
            'customer': self.customer.id,
            'start_at': '1404-03-23 10:00',
            'end_at': '1404-03-23 11:00',
            'services': [self.service.id],
        }, format='json')

        resp = self._admin_client().get('/api/logs/')
        ts = resp.data['results'][0]['timestamp']
        jdt = jdatetime.datetime.strptime(ts, '%Y-%m-%d %H:%M')
        now_shamsi = jdatetime.datetime.now()
        diff = (now_shamsi - jdt).total_seconds()
        self.assertLess(abs(diff), 300)

    def test_employee_cannot_access_logs(self):
        resp = self._employee_client().get('/api/logs/')
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
