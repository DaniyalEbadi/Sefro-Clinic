from django.contrib.auth.models import AnonymousUser
from django.test import TestCase

from accounts.permissions import CanManageVisits, IsAdmin, IsAdminOrReadOnly
from tests.helpers import make_admin, make_employee


class IsAdminPermissionTests(TestCase):
    def setUp(self):
        self.admin = make_admin()
        self.employee = make_employee()

    def test_is_admin_for_admin_user(self):
        self.assertTrue(IsAdmin().has_permission(
            type('Request', (), {'user': self.admin})(), None))

    def test_is_admin_for_employee_user(self):
        self.assertFalse(IsAdmin().has_permission(
            type('Request', (), {'user': self.employee})(), None))

    def test_is_admin_for_anonymous(self):
        self.assertFalse(IsAdmin().has_permission(
            type('Request', (), {'user': AnonymousUser()})(), None))


class IsAdminOrReadOnlyPermissionTests(TestCase):
    def setUp(self):
        self.admin = make_admin()
        self.employee = make_employee()

    def test_allows_get_for_employee(self):
        self.assertTrue(IsAdminOrReadOnly().has_permission(
            type('Request', (), {'user': self.employee, 'method': 'GET'})(), None))

    def test_allows_get_for_admin(self):
        self.assertTrue(IsAdminOrReadOnly().has_permission(
            type('Request', (), {'user': self.admin, 'method': 'GET'})(), None))

    def test_allows_post_only_for_admin(self):
        self.assertTrue(IsAdminOrReadOnly().has_permission(
            type('Request', (), {'user': self.admin, 'method': 'POST'})(), None))

    def test_denies_post_for_employee(self):
        self.assertFalse(IsAdminOrReadOnly().has_permission(
            type('Request', (), {'user': self.employee, 'method': 'POST'})(), None))

    def test_denies_for_anonymous(self):
        self.assertFalse(IsAdminOrReadOnly().has_permission(
            type('Request', (), {'user': AnonymousUser(), 'method': 'POST'})(), None))


class CanManageVisitsPermissionTests(TestCase):
    def setUp(self):
        self.admin = make_admin()
        self.employee = make_employee()

    def test_allows_authenticated_employee(self):
        self.assertTrue(CanManageVisits().has_permission(
            type('Request', (), {'user': self.employee})(), None))

    def test_allows_authenticated_admin(self):
        self.assertTrue(CanManageVisits().has_permission(
            type('Request', (), {'user': self.admin})(), None))

    def test_denies_anonymous(self):
        self.assertFalse(CanManageVisits().has_permission(
            type('Request', (), {'user': AnonymousUser()})(), None))
