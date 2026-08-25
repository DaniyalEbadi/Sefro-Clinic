from django.core.exceptions import ValidationError
from django.test import TestCase

from accounts.models import ClinicUser
from tests.helpers import make_admin


class ClinicUserModelTest(TestCase):
    def test_create_employee(self):
        user = ClinicUser.objects.create_user(
            username='emp', password='pass123', role=ClinicUser.Role.EMPLOYEE
        )
        self.assertEqual(user.role, ClinicUser.Role.EMPLOYEE)
        self.assertFalse(user.is_admin_user)
        self.assertTrue(user.is_active)

    def test_create_admin_only_via_superuser(self):
        admin = make_admin()
        self.assertEqual(admin.role, ClinicUser.Role.ADMIN)
        self.assertTrue(admin.is_admin_user)
        self.assertTrue(admin.is_staff)
        self.assertTrue(admin.is_superuser)

    def test_clean_prevents_non_admin_with_admin_role(self):
        user = ClinicUser(
            username='hacker', role=ClinicUser.Role.ADMIN,
        )
        with self.assertRaises(ValidationError):
            user.clean()
