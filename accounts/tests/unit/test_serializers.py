from django.test import TestCase

from accounts.models import ClinicUser
from accounts.serializers import (
    ClinicUserSerializer,
    EmployeeCreateSerializer,
    EmployeeUpdateSerializer,
)


class EmployeeCreateSerializerTest(TestCase):
    def test_create_employee_sets_role(self):
        data = {
            'username': 'emp1',
            'password': 'Test1234',
            'first_name': 'John',
            'last_name': 'Doe',
            'phone_number': '09120000000',
        }
        serializer = EmployeeCreateSerializer(data=data)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        user = serializer.save()
        self.assertEqual(user.role, ClinicUser.Role.EMPLOYEE)
        self.assertTrue(user.check_password('Test1234'))
        self.assertEqual(user.first_name, 'John')


class EmployeeUpdateSerializerTest(TestCase):
    def setUp(self):
        self.user = ClinicUser.objects.create_user(
            username='emp1', password='OldPass123',
            first_name='Old', role=ClinicUser.Role.EMPLOYEE,
        )

    def test_update_fields(self):
        serializer = EmployeeUpdateSerializer(
            instance=self.user,
            data={'first_name': 'New', 'phone_number': '09120000001'},
            partial=True,
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        updated = serializer.save()
        self.assertEqual(updated.first_name, 'New')
        self.assertEqual(updated.phone_number, '09120000001')

    def test_update_password(self):
        serializer = EmployeeUpdateSerializer(
            instance=self.user,
            data={'password': 'NewPass456'},
            partial=True,
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        updated = serializer.save()
        self.assertTrue(updated.check_password('NewPass456'))
