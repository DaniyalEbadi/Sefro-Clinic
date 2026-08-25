from django.test import SimpleTestCase, TestCase
from rest_framework import status

from customers.models import Service
from logs.models import AuditLog
from tests.helpers import admin_client


class AuditPasswordHashLeakageTests(TestCase):
    def test_employee_password_change_is_not_persisted_in_audit_changes(self):
        from accounts.models import ClinicUser

        client = admin_client()
        create_resp = client.post('/api/auth/employees/', {
            'username': 'audit_emp', 'password': 'Str0ng!Pass9',
        }, format='json')
        self.assertEqual(create_resp.status_code, status.HTTP_201_CREATED)
        employee_pk = ClinicUser.objects.get(username='audit_emp').pk

        patch_resp = client.patch(
            f'/api/auth/employees/{employee_pk}/',
            {'password': 'R0tated!Pass7'},
            format='json',
        )
        self.assertEqual(patch_resp.status_code, status.HTTP_200_OK)

        audit_rows = AuditLog.objects.filter(model_name='accounts.clinicuser', object_id=employee_pk)
        self.assertTrue(audit_rows.exists())
        for row in audit_rows:
            self.assertNotIn('password', row.changes, 'password hash leaked into audit trail')
            serialized = str(row.changes)
            self.assertNotIn('argon2', serialized.lower())
            self.assertNotIn('pbkdf2', serialized.lower())

    def test_admin_password_set_does_not_leak_hash_via_logs_api(self):
        from accounts.models import ClinicUser
        from tests.helpers import ADMIN_USERNAME, make_admin

        make_admin()
        admin = ClinicUser.objects.get(username=ADMIN_USERNAME)
        admin.set_password('Another!Strong9')
        admin.save()

        client = admin_client()
        response = client.get('/api/logs/?search=accounts.clinicuser')
        self.assertEqual(response.status_code, 200)
        body = response.content.decode().lower()
        self.assertNotIn('argon2', body)
        self.assertNotIn('pbkdf2', body)


class ReserveEndpointRobustnessTests(TestCase):
    def setUp(self):
        self.client = admin_client()
        self.customer_id = self.client.post('/api/customers/', {
            'first_name': 'Res', 'last_name': 'Erve',
            'mobile_number': '09129990000', 'national_id': '300-0000300',
        }, format='json').data['id']
        self.service = Service.objects.create(name='Reserve Service')
        self.base_payload = {
            'customer': self.customer_id,
            'services': [self.service.id],
            'date': '1404-06-15',
            'time': '10:30',
        }

    def _post(self, **overrides):
        payload = {**self.base_payload, **overrides}
        return self.client.post('/api/visits/reserve/', payload, format='json')

    def test_missing_time_returns_400_not_500(self):
        response = self._post(time=None)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_time_wrong_type_returns_400_not_500(self):
        response = self._post(time=1030)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_time_garbage_format_returns_400(self):
        response = self._post(time='ten-thirty')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_missing_customer_returns_400_not_500(self):
        response = self._post(customer=None)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_unknown_customer_returns_400_not_500(self):
        response = self._post(customer=999999999)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_customer_wrong_type_returns_400_not_500(self):
        response = self._post(customer='not-a-number')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_services_as_string_rejected_type_confusion(self):
        response = self._post(services=str(self.service.id))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_notes_wrong_type_returns_400_not_500(self):
        response = self._post(notes={'evil': True})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_valid_payload_still_creates_visit(self):
        response = self._post()
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)


class NullByteInjectionTests(TestCase):
    def setUp(self):
        self.client = admin_client()

    def test_nul_byte_in_customer_name_rejected_not_500(self):
        response = self.client.post('/api/customers/', {
            'first_name': 'Ali\x00evil', 'last_name': 'Rezaei',
            'mobile_number': '09121110000', 'national_id': '310-0000310',
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_invalid_utf8_payload_rejected_cleanly(self):
        import json

        raw = json.dumps({
            'first_name': 'bad', 'last_name': 'X',
            'mobile_number': '09121110001', 'national_id': '311-0000311',
        }).encode('utf-8') + b'\xff\xfe'
        response = self.client.post(
            '/api/customers/', data=raw, content_type='application/json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_validator_rejects_surrogates_directly(self):
        from django.core.exceptions import ValidationError

        from Sefro_Clinic.validators import TEXT_SANITIZERS
        with self.assertRaises(ValidationError):
            for validator in TEXT_SANITIZERS:
                validator('bad\udcffsurrogate')

    def test_nul_byte_in_service_name_rejected(self):
        response = self.client.post('/api/services/', {
            'name': 'Service\x00',
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_normal_unicode_still_accepted(self):
        response = self.client.post('/api/customers/', {
            'first_name': 'علی', 'last_name': 'رضایی',
            'mobile_number': '09121110002', 'national_id': '312-0000312',
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)


class BootstrapPasswordPolicyTests(TestCase):
    def test_weak_bootstrap_password_is_rejected(self):
        from django.core.exceptions import ImproperlyConfigured

        from accounts.signals import validate_bootstrap_credentials
        with self.assertRaises(ImproperlyConfigured):
            validate_bootstrap_credentials('sefro_admin', '123')

    def test_numeric_only_bootstrap_password_is_rejected(self):
        from django.core.exceptions import ImproperlyConfigured

        from accounts.signals import validate_bootstrap_credentials
        with self.assertRaises(ImproperlyConfigured):
            validate_bootstrap_credentials('sefro_admin', '98765432101234')

    def test_strong_bootstrap_password_passes_policy(self):
        from accounts.signals import validate_bootstrap_credentials
        validate_bootstrap_credentials('sefro_admin', 'Str0ng!Boot9')


class ProductionStaticServingTests(SimpleTestCase):
    def test_whitenoise_middleware_enabled(self):
        from django.conf import settings
        self.assertIn(
            'whitenoise.middleware.WhiteNoiseMiddleware',
            settings.MIDDLEWARE,
        )
