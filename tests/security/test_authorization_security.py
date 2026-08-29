from django.test import TestCase

from accounts.models import ClinicUser
from customers.models import Customer, Service
from tests.helpers import admin_client, employee_client, make_admin


class EmployeeWriteRestrictionTests(TestCase):
    def setUp(self):
        self.client = employee_client()
        Customer.objects.create(
            first_name='A', last_name='B',
            mobile_number='09121111111', national_id='001-0000001',
        )
        Service.objects.create(name='Consultation')

    def test_employee_can_create_and_update_operational_customer_records(self):
        create = self.client.post('/api/customers/', {
            'first_name': 'X', 'last_name': 'Y',
            'mobile_number': '09120001111', 'national_id': '020-0000020',
        }, format='json')
        self.assertEqual(create.status_code, 201)

        update = self.client.patch(
            f'/api/customers/{create.data["id"]}/', {'first_name': 'Updated'}, format='json',
        )
        self.assertEqual(update.status_code, 200)
        self.assertEqual(update.data['first_name'], 'Updated')

    def test_employee_can_read_customers(self):
        response = self.client.get('/api/customers/')
        self.assertEqual(response.status_code, 200)

    def test_employee_cannot_modify_own_account_via_employee_endpoint(self):
        me_pk = ClinicUser.objects.get(username='emp_user').id
        response = self.client.patch(f'/api/auth/employees/{me_pk}/', {'first_name': 'Hacker'}, format='json')
        self.assertEqual(response.status_code, 403)

    def test_employee_cannot_delete_another_account(self):
        target = ClinicUser.objects.create_user(username='other_emp', password='Str0ng!Pass9')
        response = self.client.delete(f'/api/auth/employees/{target.id}/')
        self.assertEqual(response.status_code, 403)

    def test_employee_cannot_access_user_administration(self):
        make_admin()
        client = employee_client()
        response = client.get('/api/auth/employees/list/')
        self.assertEqual(response.status_code, 403)


class MassAssignmentTests(TestCase):
    def test_employee_creation_ignores_privileged_fields(self):
        client = admin_client()
        response = client.post('/api/auth/employees/', {
            'username': 'evil_emp',
            'password': 'Str0ng!Pass9',
            'role': ClinicUser.Role.ADMIN,
            'is_superuser': True,
            'is_staff': True,
        }, format='json')
        self.assertEqual(response.status_code, 201)
        user = ClinicUser.objects.get(username='evil_emp')
        self.assertEqual(user.role, ClinicUser.Role.EMPLOYEE)
        self.assertFalse(user.is_superuser)

    def test_customer_creation_ignores_unknown_fields(self):
        client = admin_client()
        response = client.post('/api/customers/', {
            'first_name': 'A', 'last_name': 'B',
            'mobile_number': '09123334444', 'national_id': '030-0000030',
            'id': 99999,
            'visit_number': 42,
            'is_loyal_customer': True,
        }, format='json')
        self.assertEqual(response.status_code, 201)
        self.assertNotEqual(response.data['id'], 99999)
        self.assertEqual(response.data['visit_number'], 0)


class SensitiveDataExposureTests(TestCase):
    def test_employee_payloads_never_include_password_fields(self):
        client = admin_client()
        client.post('/api/auth/employees/', {
            'username': 'emp_vis', 'password': 'Str0ng!Pass9',
        }, format='json')
        listing = client.get('/api/auth/employees/list/')
        for row in listing.data['results']:
            self.assertNotIn('password', row)
        detail = client.get('/api/auth/employees/list/')
        self.assertTrue(all('password' not in row for row in detail.data['results']))

    def test_me_endpoint_exposes_only_documented_fields(self):
        client = admin_client()
        response = client.get('/api/auth/me/')
        self.assertEqual(set(response.data.keys()), {'id', 'username', 'role', 'date_joined'})
