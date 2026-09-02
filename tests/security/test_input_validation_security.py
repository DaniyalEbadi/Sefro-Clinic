from django.test import TestCase
from rest_framework.test import APIClient

from customers.models import Service
from tests.helpers import admin_client, make_admin

SQLI_PAYLOADS = [
    "' OR 1=1 --",
    '"; DROP TABLE customers_customer; --',
    "1' UNION SELECT NULL, NULL, NULL --",
    "' AND SLEEP(5) --",
]


class SqlInjectionTests(TestCase):
    def test_search_filter_ignores_injection_payloads(self):
        client = admin_client()
        for payload in SQLI_PAYLOADS:
            response = client.get(f'/api/customers/?search={payload}')
            self.assertEqual(response.status_code, 200, payload)
            self.assertEqual(response.data['results'], [], payload)

    def test_login_with_injection_payload_fails_cleanly(self):
        make_admin()
        client = APIClient()
        for payload in SQLI_PAYLOADS:
            response = client.post('/api/auth/token/', {
                'username': payload, 'password': payload,
            }, format='json')
            self.assertIn(response.status_code, [400, 401], payload)


class XssTests(TestCase):
    def test_stored_script_is_returned_as_plain_json_data_only(self):
        client = admin_client()
        create = client.post('/api/customers/', {
            'first_name': '<script>alert(1)</script>', 'last_name': 'Benign',
            'mobile_number': '09124445555', 'national_id': '040-0000040',
            'notes': '<img src=x onerror=alert(2)>',
        }, format='json')
        self.assertEqual(create.status_code, 201)
        detail = client.get(f"/api/customers/{create.data['id']}/")
        self.assertEqual(detail['Content-Type'], 'application/json')
        self.assertEqual(detail.data['first_name'], '<script>alert(1)</script>')
        self.assertEqual(detail.data['notes'], '<img src=x onerror=alert(2)>')


class MalformedRequestTests(TestCase):
    def test_malformed_json_returns_parse_error_not_500(self):
        client = admin_client()
        response = client.post(
            '/api/customers/',
            data='{not valid json',
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 400)

    def test_wrong_field_types_rejected(self):
        client = admin_client()
        response = client.post('/api/customers/', {
            'first_name': ['array-not-string'],
            'last_name': {'dict': 'not-string'},
            'mobile_number': '09125556666',
            'national_id': '050-0000050',
        }, format='json')
        self.assertEqual(response.status_code, 400)

    def test_missing_required_fields_rejected(self):
        client = admin_client()
        response = client.post('/api/customers/', {
            'first_name': 'OnlyFirst',
        }, format='json')
        self.assertEqual(response.status_code, 400)
        for field in ['last_name', 'mobile_number', 'national_id']:
            self.assertIn(field, response.data)

    def test_path_traversal_query_param_is_harmless(self):
        client = admin_client()
        response = client.get('/api/customers/?search=../../etc/passwd')
        self.assertEqual(response.status_code, 200)

    def test_unknown_query_params_are_ignored(self):
        client = admin_client()
        response = client.get('/api/customers/?fake_admin=1&debug=1')
        self.assertEqual(response.status_code, 200)


class BoundaryValidationTests(TestCase):
    def test_satisfaction_bounds_enforced(self):
        client = admin_client()
        for bad in [0, 6, -1]:
            response = client.post('/api/customers/', {
                'first_name': 'S', 'last_name': 'B',
                'mobile_number': f'0912000{bad:04d}',
                'national_id': f'060-0000{abs(bad)}60',
                'satisfaction': bad,
            }, format='json')
            self.assertEqual(response.status_code, 400, f'satisfaction={bad}')

    def test_negative_payment_amount_rejected(self):
        client = admin_client()
        customer = client.post('/api/customers/', {
            'first_name': 'P', 'last_name': 'N',
            'mobile_number': '09126667777', 'national_id': '070-0000070',
        }, format='json').data
        response = client.post('/api/payments/', {
            'customer': customer['id'],
            'amount': '-5000',
            'paid_at': '1404-06-15 10:00',
        }, format='json')
        self.assertEqual(response.status_code, 400)

    def test_visit_end_before_start_rejected(self):
        client = admin_client()
        service = Service.objects.create(name='Consultation')
        customer = client.post('/api/customers/', {
            'first_name': 'V', 'last_name': 'E',
            'mobile_number': '09127778888', 'national_id': '080-0000080',
        }, format='json').data
        response = client.post('/api/visits/', {
            'customer': customer['id'],
            'start_at': '1404-06-15 12:00',
            'end_at': '1404-06-15 11:00',
            'services': [service.id],
        }, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertIn('end_at', response.data)

    def test_reserve_with_invalid_time_rejected(self):
        client = admin_client()
        response = client.post('/api/visits/reserve/', {
            'customer': 1,
            'services': [1],
            'date': '1404-06-15',
            'time': '25:99',
        }, format='json')
        self.assertEqual(response.status_code, 400)

    def test_reserve_with_no_valid_services_rejected(self):
        client = admin_client()
        response = client.post('/api/visits/reserve/', {
            'customer': 1,
            'services': [999999],
            'date': '1404-06-15',
            'time': '10:00',
        }, format='json')
        self.assertEqual(response.status_code, 400)

    def test_reserve_with_invalid_date_rejected(self):
        client = admin_client()
        response = client.post('/api/visits/reserve/', {
            'customer': 1,
            'services': [1],
            'date': '2025/07/01',
            'time': '10:00',
        }, format='json')
        self.assertEqual(response.status_code, 400)


class WeakPasswordPolicyTests(TestCase):
    def test_common_password_rejected_on_employee_creation(self):
        client = admin_client()
        for weak in ['12345678', 'password', 'Test1234']:
            response = client.post('/api/auth/employees/', {
                'username': f'weak_{abs(hash(weak)) % 1000}',
                'password': weak,
            }, format='json')
            self.assertEqual(response.status_code, 400, weak)

    def test_numeric_only_password_rejected(self):
        client = admin_client()
        response = client.post('/api/auth/employees/', {
            'username': 'numeric_pw', 'password': '9876543210',
        }, format='json')
        self.assertEqual(response.status_code, 400)


class ServiceCategoryInputValidationTests(TestCase):
    def test_category_xss_stored_is_plain_text(self):
        client = admin_client()
        create = client.post('/api/service-categories/', {'name': '<script>alert(1)</script>', 'slug': 'xss-cat'}, format='json')
        self.assertEqual(create.status_code, 201)
        detail = client.get(f"/api/service-categories/{create.data['id']}/")
        self.assertEqual(detail.data['name'], '<script>alert(1)</script>')

    def test_category_search_ignores_sql_injection(self):
        client = admin_client()
        client.post('/api/service-categories/', {'name': 'Safe', 'slug': 'safe'}, format='json')
        for payload in ["' OR 1=1 --", "'; DROP TABLE customers_servicecategory; --"]:
            resp = client.get(f'/api/service-categories/?search={payload}')
            self.assertEqual(resp.status_code, 200, payload)

    def test_service_product_quantity_validation(self):
        client = admin_client()
        from customers.models import Service
        from inventory.models import Product
        svc = Service.objects.create(name='Sec Svc2', price_usd='10')
        prod = Product.objects.create(name='Sec Prod2', unit_price='10', cost_usd='1', count=5)
        for bad_qty in ['0', '-2', '0.000', 'abc', '']:
            resp = client.post('/api/finance/service-items/', {'service': svc.id, 'product': prod.id, 'quantity': bad_qty}, format='json')
            self.assertEqual(resp.status_code, 400, f'qty {bad_qty}')

    def test_service_product_duplicate_rejected(self):
        client = admin_client()
        from customers.models import Service
        from inventory.models import Product
        svc = Service.objects.create(name='Dup Svc', price_usd='10')
        prod = Product.objects.create(name='Dup Prod', unit_price='10', cost_usd='1', count=5)
        first = client.post('/api/finance/service-items/', {'service': svc.id, 'product': prod.id, 'quantity': '1'}, format='json')
        self.assertEqual(first.status_code, 201)
        dup = client.post('/api/finance/service-items/', {'service': svc.id, 'product': prod.id, 'quantity': '1'}, format='json')
        self.assertEqual(dup.status_code, 400)

    def test_exchange_rate_key_not_leaked_in_response(self):
        from django.test import override_settings
        client = admin_client()
        # Trigger external provider failure with key set, ensure key not in error response
        with override_settings(EXCHANGE_RATE_PROVIDER='external', EXCHANGE_RATE_API_URL='http://invalid/', EXCHANGE_RATE_API_KEY='super-secret-key'):
            resp = client.get('/api/services/')
            self.assertEqual(resp.status_code, 200)
            body = str(resp.data)
            self.assertNotIn('super-secret-key', body)
