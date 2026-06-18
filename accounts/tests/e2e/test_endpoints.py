from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from accounts.models import ClinicUser


class AccountsE2ETest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin, _ = ClinicUser.objects.get_or_create(
            username='sefro_admin',
            defaults={'role': ClinicUser.Role.ADMIN, 'is_staff': True, 'is_superuser': True},
        )
        if not self.admin.check_password('SefroClinic@2026'):
            self.admin.set_password('SefroClinic@2026')
            self.admin.save()
        self.employee_data = {
            'username': 'emp1',
            'password': 'TestPass123',
            'first_name': 'John',
            'last_name': 'Doe',
            'phone_number': '09120000000',
        }

    def _login_as_admin(self):
        resp = self.client.post(reverse('accounts:token-obtain-pair'), {
            'username': 'sefro_admin',
            'password': 'SefroClinic@2026',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        return resp

    def test_01_token_obtain_and_refresh_and_logout(self):
        resp = self._login_as_admin()
        self.assertIn('access', resp.data)
        self.assertIn('refresh', resp.data)
        self.assertIn('access_token', resp.cookies)
        self.assertIn('refresh_token', resp.cookies)

        refresh_resp = self.client.post(reverse('accounts:token-refresh'), {
            'refresh': resp.data['refresh'],
        }, format='json')
        self.assertEqual(refresh_resp.status_code, status.HTTP_200_OK)
        self.assertIn('access', refresh_resp.data)

        logout_resp = self.client.post(reverse('accounts:logout'), format='json')
        self.assertEqual(logout_resp.status_code, status.HTTP_200_OK)

    def test_02_me_endpoint(self):
        self._login_as_admin()
        resp = self.client.get(reverse('accounts:me'), format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['username'], 'sefro_admin')

    def test_03_employee_full_crud(self):
        self._login_as_admin()

        create_resp = self.client.post(
            reverse('accounts:employee-create'), self.employee_data, format='json'
        )
        self.assertEqual(create_resp.status_code, status.HTTP_201_CREATED)
        emp_id = create_resp.data['id']
        self.assertEqual(create_resp.data['username'], 'emp1')

        list_resp = self.client.get(reverse('accounts:employee-list'), format='json')
        self.assertEqual(list_resp.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(list_resp.data['results']), 1)

        detail_resp = self.client.get(
            reverse('accounts:employee-detail', args=[emp_id]), format='json'
        )
        self.assertEqual(detail_resp.status_code, status.HTTP_200_OK)
        self.assertEqual(detail_resp.data['username'], 'emp1')

        update_resp = self.client.put(
            reverse('accounts:employee-detail', args=[emp_id]),
            {'username': 'emp1_updated', 'first_name': 'Johnny', 'last_name': 'Doe', 'phone_number': '09120000001'},
            format='json',
        )
        self.assertEqual(update_resp.status_code, status.HTTP_200_OK)
        self.assertEqual(update_resp.data['first_name'], 'Johnny')

        partial_resp = self.client.patch(
            reverse('accounts:employee-detail', args=[emp_id]),
            {'phone_number': '09120000002'},
            format='json',
        )
        self.assertEqual(partial_resp.status_code, status.HTTP_200_OK)
        self.assertEqual(partial_resp.data['phone_number'], '09120000002')

        delete_resp = self.client.delete(
            reverse('accounts:employee-detail', args=[emp_id]), format='json'
        )
        self.assertEqual(delete_resp.status_code, status.HTTP_204_NO_CONTENT)

        get_deleted = self.client.get(
            reverse('accounts:employee-detail', args=[emp_id]), format='json'
        )
        self.assertEqual(get_deleted.status_code, status.HTTP_404_NOT_FOUND)

    def test_04_unauthenticated_access_fails(self):
        resp = self.client.get(reverse('accounts:me'), format='json')
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)
