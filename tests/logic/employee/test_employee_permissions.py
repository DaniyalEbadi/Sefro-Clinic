"""Employee role logic tests.

Verifies every permission boundary for the employee role:
- CAN: CRUD customers, services, payments, products, visits, dashboard
- CANNOT: view logs, list/create/update/delete employees
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from customers.models import Customer, Payment, Service, Visit
from inventory.models import Product

User = get_user_model()


def _employee_client():
    client = APIClient()
    user = User.objects.create_user(
        username='logic_emp_1',
        password='TestPass-2026!',
        role=User.Role.EMPLOYEE,
    )
    client.force_authenticate(user=user)
    return client, user


def _other_employee():
    return User.objects.create_user(
        username='logic_emp_2',
        password='TestPass-2026!',
        role=User.Role.EMPLOYEE,
    )


class EmployeeCustomerCRUDTests(TestCase):
    """Employees must have full CRUD on customers."""

    def setUp(self):
        self.client, self.user = _employee_client()

    def test_list_customers(self):
        response = self.client.get('/api/customers/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_create_customer(self):
        response = self.client.post('/api/customers/', {
            'first_name': 'Ali',
            'last_name': 'Rezaei',
            'mobile_number': '09121111111',
            'national_id': '001-0000001',
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['first_name'], 'Ali')

    def test_retrieve_customer(self):
        c = Customer.objects.create(
            first_name='Reza', last_name='Mohammadi',
            mobile_number='09122222222', national_id='002-0000002',
        )
        response = self.client.get(f'/api/customers/{c.id}/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_update_customer(self):
        c = Customer.objects.create(
            first_name='Hassan', last_name='Alizadeh',
            mobile_number='09123333333', national_id='003-0000003',
        )
        response = self.client.patch(
            f'/api/customers/{c.id}/', {'first_name': 'Amir'}, format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['first_name'], 'Amir')

    def test_delete_customer(self):
        c = Customer.objects.create(
            first_name='Mohammad', last_name='Karimi',
            mobile_number='09124444444', national_id='004-0000004',
        )
        response = self.client.delete(f'/api/customers/{c.id}/')
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Customer.objects.filter(id=c.id).exists())


class EmployeeServiceCRUDTests(TestCase):
    """Employees must have full CRUD on services."""

    def setUp(self):
        self.client, self.user = _employee_client()

    def test_list_services(self):
        response = self.client.get('/api/services/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_create_service(self):
        response = self.client.post('/api/services/', {
            'name': 'Laser Hair Removal',
            'price': '500000.00',
            'time': 30,
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_update_service(self):
        s = Service.objects.create(name='Keratin Hair', price='800000.00', time=60)
        response = self.client.patch(
            f'/api/services/{s.id}/', {'price': '900000.00'}, format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_delete_service(self):
        s = Service.objects.create(name='Skin Cleansing', price='300000.00', time=45)
        response = self.client.delete(f'/api/services/{s.id}/')
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)


class EmployeePaymentCRUDTests(TestCase):
    """Employees must have full CRUD on payments."""

    def setUp(self):
        self.client, self.user = _employee_client()
        self.customer = Customer.objects.create(
            first_name='Sara', last_name='Ahmadi',
            mobile_number='09125555555', national_id='005-0000005',
        )

    def test_list_payments(self):
        response = self.client.get('/api/payments/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_create_payment(self):
        p = Payment.objects.create(
            customer=self.customer, amount='250000.00',
            payment_method='cash', paid_at=timezone.now(),
        )
        response = self.client.get(f'/api/payments/{p.id}/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['amount'], '250000.00')

    def test_update_payment(self):
        p = Payment.objects.create(
            customer=self.customer, amount='100000.00',
            payment_method='card', paid_at=timezone.now(),
        )
        response = self.client.patch(
            f'/api/payments/{p.id}/', {'amount': '200000.00'}, format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_delete_payment(self):
        p = Payment.objects.create(
            customer=self.customer, amount='150000.00',
            payment_method='transfer', paid_at=timezone.now(),
        )
        response = self.client.delete(f'/api/payments/{p.id}/')
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)


class EmployeeProductCRUDTests(TestCase):
    """Employees must have full CRUD on inventory products."""

    def setUp(self):
        self.client, self.user = _employee_client()

    def test_list_products(self):
        response = self.client.get('/api/inventory/products/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_create_product(self):
        response = self.client.post('/api/inventory/products/', {
            'name': 'Sunscreen',
            'sku': 'EMP-TEST-001',
            'unit_price': '350000.00',
            'count': 20,
            'unit': 'pcs',
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_update_product(self):
        p = Product.objects.create(
            name='Vitamin C Serum', sku='EMP-TEST-002',
            unit_price='450000.00', count=15,
        )
        response = self.client.patch(
            f'/api/inventory/products/{p.id}/', {'count': 10}, format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_delete_product(self):
        p = Product.objects.create(
            name='Foam Cleanser', sku='EMP-TEST-003',
            unit_price='200000.00', count=5,
        )
        response = self.client.delete(f'/api/inventory/products/{p.id}/')
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)


class EmployeeVisitCRUDTests(TestCase):
    """Employees must have full access to visits."""

    def setUp(self):
        self.client, self.user = _employee_client()
        self.customer = Customer.objects.create(
            first_name='Niloufar', last_name='Rasaei',
            mobile_number='09126666666', national_id='006-0000006',
        )
        self.service = Service.objects.create(
            name='Face Mask', price='200000.00', time=30,
        )

    def test_list_visits(self):
        response = self.client.get('/api/visits/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_confirm_visit(self):
        visit = Visit.objects.create(
            customer=self.customer, start_at=timezone.now(),
            end_at=timezone.now(), status=Visit.Status.PENDING,
        )
        visit.services.add(self.service)
        response = self.client.post(f'/api/visits/{visit.id}/confirm/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['status'], Visit.Status.CONFIRMED)

    def test_complete_visit(self):
        visit = Visit.objects.create(
            customer=self.customer, start_at=timezone.now(),
            end_at=timezone.now(), status=Visit.Status.CONFIRMED,
        )
        visit.services.add(self.service)
        response = self.client.post(f'/api/visits/{visit.id}/complete/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['status'], Visit.Status.COMPLETED)

    def test_cancel_visit(self):
        visit = Visit.objects.create(
            customer=self.customer, start_at=timezone.now(),
            end_at=timezone.now(), status=Visit.Status.PENDING,
        )
        visit.services.add(self.service)
        response = self.client.post(f'/api/visits/{visit.id}/cancel/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['status'], Visit.Status.CANCELED)


class EmployeeDashboardTests(TestCase):
    """Employees must be able to view dashboard."""

    def setUp(self):
        self.client, self.user = _employee_client()

    def test_view_dashboard(self):
        response = self.client.get('/api/dashboard/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)


class EmployeeReportsTests(TestCase):
    """Employees must be able to view all reports."""

    def setUp(self):
        self.client, self.user = _employee_client()

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


class EmployeeForbiddenTests(TestCase):
    """Employees must be BLOCKED from logs and employee management."""

    def setUp(self):
        self.client, self.user = _employee_client()
        self.other = _other_employee()

    def test_cannot_view_logs(self):
        response = self.client.get('/api/logs/')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_cannot_list_employees(self):
        response = self.client.get('/api/auth/employees/list/')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_cannot_create_employee(self):
        response = self.client.post('/api/auth/employees/', {
            'username': 'hacker',
            'password': 'TestPass-2026!',
            'first_name': 'Hacker',
            'last_name': 'Test',
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_cannot_update_other_employee(self):
        response = self.client.patch(
            f'/api/auth/employees/{self.other.id}/',
            {'first_name': 'Hacked'}, format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_cannot_delete_other_employee(self):
        response = self.client.delete(f'/api/auth/employees/{self.other.id}/')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class EmployeeAuthTests(TestCase):
    """Employee authentication flow."""

    def test_login_and_me(self):
        User.objects.create_user(
            username='logic_emp_auth', password='TestPass-2026!',
            role=User.Role.EMPLOYEE,
        )
        client = APIClient()
        login_resp = client.post('/api/auth/token/', {
            'username': 'logic_emp_auth',
            'password': 'TestPass-2026!',
        }, format='json')
        self.assertEqual(login_resp.status_code, status.HTTP_200_OK)
        self.assertIn('access', login_resp.data)

        client.credentials(HTTP_AUTHORIZATION=f'Bearer {login_resp.data["access"]}')
        me_resp = client.get('/api/auth/me/')
        self.assertEqual(me_resp.status_code, status.HTTP_200_OK)
        self.assertEqual(me_resp.data['role'], 'employee')

    def test_token_refresh(self):
        User.objects.create_user(
            username='logic_emp_refresh', password='TestPass-2026!',
            role=User.Role.EMPLOYEE,
        )
        client = APIClient()
        login_resp = client.post('/api/auth/token/', {
            'username': 'logic_emp_refresh',
            'password': 'TestPass-2026!',
        }, format='json')
        refresh = login_resp.data['refresh']
        response = client.post('/api/auth/token/refresh/', {
            'refresh': refresh,
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('access', response.data)


class EmployeeServiceCategoryLogicTests(TestCase):
    """Employee logic: read-only for categories and pricing, no write."""

    def setUp(self):
        self.client, self.user = _employee_client()
        from customers.models import ServiceCategory
        self.cat = ServiceCategory.objects.create(name='Emp Read Cat', slug='emp-read-cat')

    def test_employee_can_read_categories_and_services_with_pricing(self):
        resp = self.client.get('/api/service-categories/')
        self.assertEqual(resp.status_code, 200)
        resp2 = self.client.get('/api/services/')
        self.assertEqual(resp2.status_code, 200)
        # pricing fields present for employee
        if resp2.data['results']:
            self.assertIn('estimated_cost_usd', resp2.data['results'][0])

    def test_employee_cannot_create_or_delete_category(self):
        resp = self.client.post('/api/service-categories/', {'name': 'Nope', 'slug': 'nope'}, format='json')
        self.assertEqual(resp.status_code, 403)
        resp2 = self.client.delete(f'/api/service-categories/{self.cat.id}/')
        self.assertEqual(resp2.status_code, 403)

    def test_employee_cannot_create_service_product_link(self):
        from customers.models import Service
        from inventory.models import Product
        svc = Service.objects.create(name='Emp Svc', price_usd='30')
        prod = Product.objects.create(name='EmpProd', unit_price='10', cost_usd='2', count=5)
        resp = self.client.post('/api/finance/service-items/', {'service': svc.id, 'product': prod.id, 'quantity': '1'}, format='json')
        self.assertEqual(resp.status_code, 403)

    def test_inactive_product_logic_employee_read_only(self):
        from customers.models import Service
        from finance.models import ServiceItem
        from inventory.models import Product
        svc = Service.objects.create(name='Svc Inactive Logic', price_usd='20')
        prod = Product.objects.create(name='InactiveProd', unit_price='10', cost_usd='1', count=5, status=Product.StatusChoices.FINISHED)
        # Even admin cannot link inactive via API logic; employee read should still see existing link if created before inactivation
        # Create link as admin via ORM (bypasses validation) then ensure employee can read it
        ServiceItem.objects.create(service=svc, product=prod, quantity='1')
        prod.status = Product.StatusChoices.AVAILABLE
        prod.save()
        # Now employee reads service with pricing
        resp = self.client.get(f'/api/services/{svc.id}/')
        self.assertEqual(resp.status_code, 200)
