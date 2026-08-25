from django.test import TestCase

from logs.models import AuditLog
from tests.helpers import ADMIN_PASSWORD, ADMIN_USERNAME, admin_client


class FullClinicWorkflowE2ETests(TestCase):
    def test_visit_lifecycle_from_reservation_to_payment_and_audit(self):
        client = admin_client()

        service_resp = client.post('/api/services/', {
            'name': 'Laser Session', 'price': '800000', 'time': 45, 'is_active': True,
        }, format='json')
        self.assertEqual(service_resp.status_code, 201)
        service_id = service_resp.data['id']

        customer_resp = client.post('/api/customers/', {
            'first_name': 'Neda', 'last_name': 'Moradi',
            'mobile_number': '09121000000', 'national_id': '010-0000010',
            'bitmoji_code': 'B010',
        }, format='json')
        self.assertEqual(customer_resp.status_code, 201)
        customer_id = customer_resp.data['id']

        reserve_resp = client.post('/api/visits/reserve/', {
            'customer': customer_id,
            'services': [service_id],
            'date': '1404-06-15',
            'time': '10:30',
            'notes': 'first session',
        }, format='json')
        self.assertEqual(reserve_resp.status_code, 201)
        visit_id = reserve_resp.data['id']
        self.assertEqual(reserve_resp.data['status'], 'pending')

        confirm_resp = client.post(f'/api/visits/{visit_id}/confirm/')
        self.assertEqual(confirm_resp.status_code, 200)
        self.assertEqual(confirm_resp.data['status'], 'confirmed')

        complete_resp = client.post(f'/api/visits/{visit_id}/complete/')
        self.assertEqual(complete_resp.status_code, 200)
        self.assertEqual(complete_resp.data['status'], 'completed')

        payment_resp = client.post('/api/payments/', {
            'customer': customer_id,
            'visit': visit_id,
            'amount': '800000',
            'payment_method': 'card',
            'paid_at': '1404-06-15 11:30',
        }, format='json')
        self.assertEqual(payment_resp.status_code, 201)

        detail_resp = client.get(f'/api/customers/{customer_id}/')
        self.assertEqual(detail_resp.data['visit_number'], 1)
        self.assertEqual(float(detail_resp.data['total_payments']), 800000.0)
        self.assertFalse(detail_resp.data['is_new_customer'])

        dashboard_resp = client.get('/api/dashboard/')
        self.assertGreaterEqual(float(dashboard_resp.data['today_sales']), 0)

        logs_resp = client.get('/api/logs/?search=customers.visit')
        self.assertEqual(logs_resp.status_code, 200)
        actions = [entry['action'] for entry in logs_resp.data['results']]
        self.assertIn('CREATE', actions)
        self.assertIn('UPDATE', actions)

    def test_logout_blacklists_refresh_token(self):
        from rest_framework.test import APIClient

        from tests.helpers import make_admin

        make_admin()
        client = APIClient()
        login_resp = client.post('/api/auth/token/', {
            'username': ADMIN_USERNAME, 'password': ADMIN_PASSWORD,
        }, format='json')
        self.assertEqual(login_resp.status_code, 200)
        refresh_token = login_resp.data['refresh']

        refresh_resp = client.post('/api/auth/token/refresh/', {
            'refresh': refresh_token,
        }, format='json')
        self.assertEqual(refresh_resp.status_code, 200)

        logout_resp = client.post('/api/auth/logout/', {'refresh': refresh_token}, format='json')
        self.assertEqual(logout_resp.status_code, 200)

        replay_resp = client.post('/api/auth/token/refresh/', {
            'refresh': refresh_token,
        }, format='json')
        self.assertEqual(replay_resp.status_code, 401)


class AuditTrailIntegrityE2ETests(TestCase):
    def test_delete_action_is_recorded_with_actor(self):
        client = admin_client()
        create_resp = client.post('/api/services/', {'name': 'Temp Service'}, format='json')
        service_id = create_resp.data['id']

        delete_resp = client.delete(f'/api/services/{service_id}/')
        self.assertEqual(delete_resp.status_code, 204)

        entry = AuditLog.objects.filter(model_name='customers.service', action='DELETE').latest('timestamp')
        self.assertIsNotNone(entry.user)
        self.assertEqual(entry.user.username, ADMIN_USERNAME)


class AnonymousSurfaceTests(TestCase):
    def test_every_api_route_requires_authentication(self):
        from rest_framework.test import APIClient
        anon = APIClient()
        guarded = [
            ('get', '/api/customers/'),
            ('post', '/api/customers/'),
            ('get', '/api/services/'),
            ('get', '/api/visits/'),
            ('get', '/api/payments/'),
            ('get', '/api/dashboard/'),
            ('get', '/api/logs/'),
            ('get', '/api/auth/me/'),
            ('get', '/api/auth/employees/list/'),
        ]
        for method, url in guarded:
            response = getattr(anon, method)(url)
            self.assertEqual(response.status_code, 401, f'{method.upper()} {url}')
