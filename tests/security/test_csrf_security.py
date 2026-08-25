from django.test import TestCase
from rest_framework.test import APIClient

from customers.models import Customer, Service
from tests.helpers import ADMIN_PASSWORD, ADMIN_USERNAME, make_admin


class CsrfProtectionTests(TestCase):
    def setUp(self):
        make_admin()
        self.client = APIClient(enforce_csrf_checks=True)
        login_resp = self.client.post('/api/auth/token/', {
            'username': ADMIN_USERNAME, 'password': ADMIN_PASSWORD,
        }, format='json')
        self.assertEqual(login_resp.status_code, 200)
        self.assertIn('csrftoken', self.client.cookies)

    def _visit_payload(self):
        customer = Customer.objects.create(
            first_name='C', last_name='S',
            mobile_number='09121112222', national_id='090-0000090',
        )
        service = Service.objects.create(name='Consultation')
        return {
            'customer': customer.id,
            'start_at': '1404-06-15 10:00',
            'end_at': '1404-06-15 11:00',
            'services': [service.id],
        }

    def test_cookie_authenticated_post_without_csrf_token_rejected(self):
        response = self.client.post('/api/visits/', self._visit_payload(), format='json')
        self.assertEqual(response.status_code, 403)
        self.assertIn('CSRF', str(response.data))

    def test_cookie_authenticated_post_with_valid_csrf_token_succeeds(self):
        csrf = self.client.cookies['csrftoken'].value
        response = self.client.post(
            '/api/visits/',
            self._visit_payload(),
            format='json',
            HTTP_X_CSRFTOKEN=csrf,
        )
        self.assertEqual(response.status_code, 201)

    def test_reused_csrf_token_from_other_session_rejected(self):
        rogue = APIClient(enforce_csrf_checks=True)
        rogue.cookies['csrftoken'] = 'bogus-token-value'
        rogue.cookies['access_token'] = self.client.cookies['access_token'].value
        response = rogue.post(
            '/api/visits/',
            self._visit_payload(),
            format='json',
            HTTP_X_CSRFTOKEN='bogus-token-value',
        )
        self.assertEqual(response.status_code, 403)

    def test_safe_methods_do_not_require_csrf(self):
        response = self.client.get('/api/customers/')
        self.assertEqual(response.status_code, 200)
