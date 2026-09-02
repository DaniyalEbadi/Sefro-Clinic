from django.test import TestCase

from logs.models import AuditLog
from tests.helpers import ADMIN_PASSWORD, ADMIN_USERNAME, admin_client


class FullClinicWorkflowE2ETests(TestCase):
    def test_visit_lifecycle_from_reservation_to_payment_and_audit(self):
        client = admin_client()

        service_resp = client.post('/api/services/', {
            'name': 'Laser Session', 'price': '800000', 'time': 45, 'is_active': True,
        }, format='json')
        self.assertEqual(service_resp.status_code, 201)
        service_id = service_resp.data['id']

        customer_resp = client.post('/api/customers/', {
            'first_name': 'Neda', 'last_name': 'Moradi',
            'mobile_number': '09121000000', 'national_id': '010-0000010',
            'bitmoji_code': 'B010',
        }, format='json')
        self.assertEqual(customer_resp.status_code, 201)
        customer_id = customer_resp.data['id']

        reserve_resp = client.post('/api/visits/reserve/', {
            'customer': customer_id,
            'services': [service_id],
            'date': '1404-06-15',
            'time': '10:30',
            'notes': 'first session',
        }, format='json')
        self.assertEqual(reserve_resp.status_code, 201)
        visit_id = reserve_resp.data['id']
        self.assertEqual(reserve_resp.data['status'], 'pending')

        confirm_resp = client.post(f'/api/visits/{visit_id}/confirm/')
        self.assertEqual(confirm_resp.status_code, 200)
        self.assertEqual(confirm_resp.data['status'], 'confirmed')

        complete_resp = client.post(f'/api/visits/{visit_id}/complete/')
        self.assertEqual(complete_resp.status_code, 200)
        self.assertEqual(complete_resp.data['status'], 'completed')

        payment_resp = client.post('/api/payments/', {
            'customer': customer_id,
            'visit': visit_id,
            'amount': '800000',
            'payment_method': 'card',
            'paid_at': '1404-06-15 11:30',
        }, format='json')
        self.assertEqual(payment_resp.status_code, 201)

        detail_resp = client.get(f'/api/customers/{customer_id}/')
        self.assertEqual(detail_resp.data['visit_number'], 1)
        self.assertEqual(float(detail_resp.data['total_payments']), 800000.0)
        self.assertFalse(detail_resp.data['is_new_customer'])

        dashboard_resp = client.get('/api/dashboard/')
        self.assertGreaterEqual(float(dashboard_resp.data['today_sales']), 0)

        logs_resp = client.get('/api/logs/?search=customers.visit')
        self.assertEqual(logs_resp.status_code, 200)
        actions = [entry['action'] for entry in logs_resp.data['results']]
        self.assertIn('CREATE', actions)
        self.assertIn('UPDATE', actions)

    def test_logout_blacklists_refresh_token(self):
        from rest_framework.test import APIClient

        from tests.helpers import make_admin

        make_admin()
        client = APIClient()
        login_resp = client.post('/api/auth/token/', {
            'username': ADMIN_USERNAME, 'password': ADMIN_PASSWORD,
        }, format='json')
        self.assertEqual(login_resp.status_code, 200)
        refresh_token = login_resp.data['refresh']

        refresh_resp = client.post('/api/auth/token/refresh/', {
            'refresh': refresh_token,
        }, format='json')
        self.assertEqual(refresh_resp.status_code, 200)

        logout_resp = client.post('/api/auth/logout/', {'refresh': refresh_token}, format='json')
        self.assertEqual(logout_resp.status_code, 200)

        replay_resp = client.post('/api/auth/token/refresh/', {
            'refresh': refresh_token,
        }, format='json')
        self.assertEqual(replay_resp.status_code, 401)


class AuditTrailIntegrityE2ETests(TestCase):
    def test_delete_action_is_recorded_with_actor(self):
        client = admin_client()
        create_resp = client.post('/api/services/', {'name': 'Temp Service'}, format='json')
        service_id = create_resp.data['id']

        delete_resp = client.delete(f'/api/services/{service_id}/')
        self.assertEqual(delete_resp.status_code, 204)

        entry = AuditLog.objects.filter(model_name='customers.service', action='DELETE').latest('timestamp')
        self.assertIsNotNone(entry.user)
        self.assertEqual(entry.user.username, ADMIN_USERNAME)


class ServiceCategoryProductPricingE2ETests(TestCase):
    def test_full_category_product_pricing_workflow(self):
        client = admin_client()
        # 1. Create category
        cat = client.post('/api/service-categories/', {'name': 'E2E Laser', 'slug': 'e2e-laser', 'sort_order': 1}, format='json')
        self.assertEqual(cat.status_code, 201)
        cat_id = cat.data['id']
        # 2. Create products
        p1 = client.post('/api/inventory/products/', {'name': 'E2E Gel', 'sku': 'E2E-001', 'unit_price': '100', 'cost_usd': '0.20', 'count': 100}, format='json')
        p2 = client.post('/api/inventory/products/', {'name': 'E2E Cream', 'sku': 'E2E-002', 'unit_price': '100', 'cost_usd': '0.50', 'count': 100}, format='json')
        self.assertEqual(p1.status_code, 201)
        # 3. Create service with category
        svc = client.post('/api/services/', {'name': 'E2E Laser Svc', 'price_usd': '100.00', 'price': '100', 'time': 30, 'category_id': cat_id}, format='json')
        self.assertEqual(svc.status_code, 201)
        svc_id = svc.data['id']
        self.assertEqual(svc.data['category']['slug'], 'e2e-laser')
        # 4. Link products
        link1 = client.post('/api/finance/service-items/', {'service': svc_id, 'product': p1.data['id'], 'quantity': '50'}, format='json')
        link2 = client.post('/api/finance/service-items/', {'service': svc_id, 'product': p2.data['id'], 'quantity': '10'}, format='json')
        self.assertEqual(link1.status_code, 201)
        self.assertEqual(link2.status_code, 201)
        # 5. Verify pricing via API (cost 15, gross 85, margin 85)
        detail = client.get(f'/api/services/{svc_id}/')
        self.assertEqual(detail.data['estimated_cost_usd'], '15.00')
        self.assertEqual(detail.data['estimated_gross_profit_usd'], '85.00')
        self.assertEqual(detail.data['estimated_margin_percent'], '85.00')
        self.assertEqual(len(detail.data['products']), 2)
        # 6. Filter by category
        filtered = client.get(f'/api/services/?category={cat_id}')
        self.assertEqual(filtered.status_code, 200)
        self.assertTrue(any(r['id'] == svc_id for r in filtered.data['results']))
        # 7. Deactivation instead of delete when referenced
        del_resp = client.delete(f'/api/service-categories/{cat_id}/')
        self.assertEqual(del_resp.status_code, 400)
        patch = client.patch(f'/api/service-categories/{cat_id}/', {'is_active': False}, format='json')
        self.assertEqual(patch.status_code, 200)
        self.assertFalse(patch.data['is_active'])
        # 8. Continue lifecycle: customer → visit → payment with new service
        cust = client.post('/api/customers/', {'first_name': 'E2E', 'last_name': 'User', 'mobile_number': '09129990001', 'national_id': '099-0000001'}, format='json')
        cust_id = cust.data['id']
        reserve = client.post('/api/visits/reserve/', {'customer': cust_id, 'services': [svc_id], 'date': '1404-06-15', 'time': '10:30'}, format='json')
        self.assertEqual(reserve.status_code, 201)
        visit_id = reserve.data['id']
        client.post(f'/api/visits/{visit_id}/confirm/')
        client.post(f'/api/visits/{visit_id}/complete/')
        pay = client.post('/api/payments/', {'customer': cust_id, 'visit': visit_id, 'amount': '500000', 'payment_method': 'card', 'paid_at': '1404-06-15 11:30'}, format='json')
        self.assertEqual(pay.status_code, 201)


class AnonymousSurfaceTests(TestCase):
    def test_every_api_route_requires_authentication(self):
        from rest_framework.test import APIClient
        anon = APIClient()
        guarded = [
            ('get', '/api/customers/'),
            ('post', '/api/customers/'),
            ('get', '/api/services/'),
            ('get', '/api/visits/'),
            ('get', '/api/payments/'),
            ('get', '/api/dashboard/'),
            ('get', '/api/logs/'),
            ('get', '/api/auth/me/'),
            ('get', '/api/auth/employees/list/'),
        ]
        for method, url in guarded:
            response = getattr(anon, method)(url)
            self.assertEqual(response.status_code, 401, f'{method.upper()} {url}')
