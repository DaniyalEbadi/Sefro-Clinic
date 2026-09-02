"""Admin role logic tests.

Verifies every permission boundary for the admin role:
- CAN: everything (CRUD all resources, view logs, manage employees, reports)
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework import status

from customers.models import Customer, Payment, Service
from inventory.models import Product
from tests.helpers import admin_client

User = get_user_model()


class AdminCustomerCRUDTests(TestCase):
    """Admin must have full CRUD on customers."""

    def setUp(self):
        self.client = admin_client()

    def test_list_customers(self):
        self.assertEqual(self.client.get('/api/customers/').status_code, 200)

    def test_create_customer(self):
        response = self.client.post('/api/customers/', {
            'first_name': 'Ali',
            'last_name': 'Rezaei',
            'mobile_number': '09131111111',
            'national_id': '101-0000001',
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_update_customer(self):
        c = Customer.objects.create(
            first_name='Hassan', last_name='Alizadeh',
            mobile_number='09132222222', national_id='102-0000002',
        )
        response = self.client.patch(
            f'/api/customers/{c.id}/', {'first_name': 'Amir'}, format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_delete_customer(self):
        c = Customer.objects.create(
            first_name='Mohammad', last_name='Karimi',
            mobile_number='09133333333', national_id='103-0000003',
        )
        response = self.client.delete(f'/api/customers/{c.id}/')
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)


class AdminServiceCRUDTests(TestCase):
    """Admin must have full CRUD on services."""

    def setUp(self):
        self.client = admin_client()

    def test_list_services(self):
        self.assertEqual(self.client.get('/api/services/').status_code, 200)

    def test_create_service(self):
        response = self.client.post('/api/services/', {
            'name': 'Botox', 'price': '2000000.00', 'time': 15,
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_delete_service(self):
        s = Service.objects.create(name='Delete Me', price='100000.00', time=30)
        response = self.client.delete(f'/api/services/{s.id}/')
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)


class AdminPaymentCRUDTests(TestCase):
    """Admin must have full CRUD on payments."""

    def setUp(self):
        self.client = admin_client()
        self.customer = Customer.objects.create(
            first_name='Zahra', last_name='Hosseini',
            mobile_number='09134444444', national_id='104-0000004',
        )

    def test_list_payments(self):
        self.assertEqual(self.client.get('/api/payments/').status_code, 200)

    def test_create_payment(self):
        from django.utils import timezone
        p = Payment.objects.create(
            customer=self.customer, amount='500000.00',
            payment_method='card', paid_at=timezone.now(),
        )
        response = self.client.get(f'/api/payments/{p.id}/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_delete_payment(self):
        from django.utils import timezone
        p = Payment.objects.create(
            customer=self.customer, amount='300000.00',
            payment_method='cash', paid_at=timezone.now(),
        )
        response = self.client.delete(f'/api/payments/{p.id}/')
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)


class AdminProductCRUDTests(TestCase):
    """Admin must have full CRUD on inventory products."""

    def setUp(self):
        self.client = admin_client()

    def test_list_products(self):
        self.assertEqual(self.client.get('/api/inventory/products/').status_code, 200)

    def test_create_product(self):
        response = self.client.post('/api/inventory/products/', {
            'name': 'Retinol', 'sku': 'ADM-001',
            'unit_price': '600000.00', 'count': 30,
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_delete_product(self):
        p = Product.objects.create(
            name='Delete Me', sku='ADM-002', unit_price='100000.00', count=1,
        )
        response = self.client.delete(f'/api/inventory/products/{p.id}/')
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)


class AdminLogsAccessTests(TestCase):
    """Admin must be able to view audit logs."""

    def setUp(self):
        self.client = admin_client()

    def test_view_logs(self):
        self.assertEqual(self.client.get('/api/logs/').status_code, 200)

    def test_search_logs(self):
        self.assertEqual(self.client.get('/api/logs/?search=CREATE').status_code, 200)


class AdminReportsAccessTests(TestCase):
    """Admin must be able to view all reports."""

    def setUp(self):
        self.client = admin_client()

    def test_reports_summary(self):
        self.assertEqual(self.client.get('/api/reports/').status_code, 200)

    def test_reports_all(self):
        self.assertEqual(self.client.get('/api/reports/all/').status_code, 200)

    def test_reports_daily(self):
        self.assertEqual(self.client.get('/api/reports/daily/').status_code, 200)

    def test_reports_weekly(self):
        self.assertEqual(self.client.get('/api/reports/weekly/').status_code, 200)

    def test_reports_monthly(self):
        self.assertEqual(self.client.get('/api/reports/monthly/').status_code, 200)

    def test_reports_quarterly(self):
        self.assertEqual(self.client.get('/api/reports/quarterly/').status_code, 200)

    def test_reports_yearly(self):
        self.assertEqual(self.client.get('/api/reports/yearly/').status_code, 200)

    def test_reports_customers(self):
        self.assertEqual(self.client.get('/api/reports/customers/').status_code, 200)

    def test_reports_referral(self):
        self.assertEqual(self.client.get('/api/reports/referral/').status_code, 200)

    def test_reports_visits(self):
        self.assertEqual(self.client.get('/api/reports/visits/').status_code, 200)


class AdminDashboardTests(TestCase):
    """Admin must be able to view dashboard."""

    def setUp(self):
        self.client = admin_client()

    def test_view_dashboard(self):
        self.assertEqual(self.client.get('/api/dashboard/').status_code, 200)


class AdminEmployeeManagementTests(TestCase):
    """Admin must be able to list, create, update, delete employees."""

    def setUp(self):
        self.client = admin_client()
        self.emp = User.objects.create_user(
            username='logic_managed_emp', password='TestPass-2026!',
            role=User.Role.EMPLOYEE,
        )

    def test_list_employees(self):
        response = self.client.get('/api/auth/employees/list/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data.get('results', response.data)
        usernames = [u['username'] for u in results]
        self.assertIn('logic_managed_emp', usernames)

    def test_create_employee(self):
        response = self.client.post('/api/auth/employees/', {
            'username': 'new_emp_logic',
            'password': 'TestPass-2026!',
            'first_name': 'New',
            'last_name': 'Employee',
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(User.objects.filter(username='new_emp_logic').exists())

    def test_update_employee(self):
        response = self.client.patch(
            f'/api/auth/employees/{self.emp.id}/',
            {'first_name': 'Updated'}, format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.emp.refresh_from_db()
        self.assertEqual(self.emp.first_name, 'Updated')

    def test_delete_employee(self):
        response = self.client.delete(f'/api/auth/employees/{self.emp.id}/')
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(User.objects.filter(id=self.emp.id).exists())


class AdminAuthTests(TestCase):
    """Admin authentication flow."""

    def test_login_returns_admin_role(self):
        client = admin_client()
        me_resp = client.get('/api/auth/me/')
        self.assertEqual(me_resp.status_code, status.HTTP_200_OK)
        self.assertEqual(me_resp.data['role'], 'admin')


class AnonymousAccessTests(TestCase):
    """Unauthenticated users must be blocked from all protected endpoints."""

    def setUp(self):
        from rest_framework.test import APIClient
        self.client = APIClient()

    def test_customers_blocked(self):
        self.assertEqual(self.client.get('/api/customers/').status_code, 401)

    def test_visits_blocked(self):
        self.assertEqual(self.client.get('/api/visits/').status_code, 401)

    def test_payments_blocked(self):
        self.assertEqual(self.client.get('/api/payments/').status_code, 401)

    def test_products_blocked(self):
        self.assertEqual(self.client.get('/api/inventory/products/').status_code, 401)

    def test_dashboard_blocked(self):
        self.assertEqual(self.client.get('/api/dashboard/').status_code, 401)

    def test_reports_blocked(self):
        self.assertEqual(self.client.get('/api/reports/').status_code, 401)

    def test_logs_blocked(self):
        self.assertEqual(self.client.get('/api/logs/').status_code, 401)

    def test_employees_blocked(self):
        self.assertEqual(self.client.get('/api/auth/employees/list/').status_code, 401)

    def test_me_blocked(self):
        self.assertEqual(self.client.get('/api/auth/me/').status_code, 401)

    def test_services_blocked(self):
        self.assertEqual(self.client.get('/api/services/').status_code, 401)

    def test_service_categories_blocked(self):
        self.assertEqual(self.client.get('/api/service-categories/').status_code, 401)

    def test_service_items_blocked(self):
        self.assertEqual(self.client.get('/api/finance/service-items/').status_code, 401)


class AdminServiceCategoryLogicTests(TestCase):
    """Admin logic for ServiceCategory: full control, protection of referenced categories."""

    def setUp(self):
        self.client = admin_client()

    def test_admin_can_create_and_update_category(self):
        create = self.client.post('/api/service-categories/', {'name': 'Logic Laser', 'slug': 'logic-laser', 'sort_order': 1}, format='json')
        self.assertEqual(create.status_code, status.HTTP_201_CREATED)
        cid = create.data['id']
        upd = self.client.patch(f'/api/service-categories/{cid}/', {'description': 'updated', 'is_active': False}, format='json')
        self.assertEqual(upd.status_code, 200)
        self.assertFalse(upd.data['is_active'])

    def test_admin_delete_referenced_category_blocked(self):
        from customers.models import Service, ServiceCategory
        cat = ServiceCategory.objects.create(name='Protected', slug='protected')
        Service.objects.create(name='Svc Protected', price='1000', category=cat)
        resp = self.client.delete(f'/api/service-categories/{cat.id}/')
        self.assertEqual(resp.status_code, 400)
        self.assertTrue(ServiceCategory.objects.filter(id=cat.id).exists())

    def test_admin_can_manage_service_product_link(self):
        from customers.models import Service
        from inventory.models import Product
        svc = Service.objects.create(name='Logic Svc', price_usd='50')
        prod = Product.objects.create(name='LogicProd', unit_price='100', cost_usd='5', count=10)
        resp = self.client.post('/api/finance/service-items/', {'service': svc.id, 'product': prod.id, 'quantity': '2.5'}, format='json')
        self.assertEqual(resp.status_code, 201)
        # duplicate blocked
        dup = self.client.post('/api/finance/service-items/', {'service': svc.id, 'product': prod.id, 'quantity': '1'}, format='json')
        self.assertEqual(dup.status_code, 400)
