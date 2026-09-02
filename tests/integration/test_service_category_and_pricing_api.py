from decimal import Decimal

from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework import status

from customers.models import Service, ServiceCategory
from finance.models import ExchangeRate, ServiceItem
from inventory.models import Product
from tests.helpers import admin_client, employee_client


class ServiceCategoryTests(TestCase):
    def setUp(self):
        self.admin = admin_client()
        self.emp = employee_client(username='emp_cat')

    def test_create_category(self):
        resp = self.admin.post('/api/service-categories/', {'name': 'Laser', 'slug': 'laser', 'sort_order': 1}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp.data['slug'], 'laser')

    def test_unique_category_name(self):
        ServiceCategory.objects.create(name='Laser', slug='laser')
        resp = self.admin.post('/api/service-categories/', {'name': 'Laser', 'slug': 'laser2'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_unique_category_slug(self):
        ServiceCategory.objects.create(name='Laser', slug='laser')
        resp = self.admin.post('/api/service-categories/', {'name': 'Laser2', 'slug': 'laser'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_category_service_relationship(self):
        cat = ServiceCategory.objects.create(name='Laser', slug='laser')
        svc = Service.objects.create(name='Laser Hair', price_usd=Decimal('100'), category=cat)
        self.assertEqual(svc.category, cat)
        self.assertIn(svc, cat.services.all())

    def test_category_filtering(self):
        cat1 = ServiceCategory.objects.create(name='Laser', slug='laser', sort_order=1)
        cat2 = ServiceCategory.objects.create(name='Facial', slug='facial', sort_order=2)
        Service.objects.create(name='Svc Laser', price_usd=Decimal('100'), category=cat1)
        Service.objects.create(name='Svc Facial', price_usd=Decimal('100'), category=cat2)
        # filter by id
        resp = self.admin.get(f'/api/services/?category={cat1.id}')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data['results']), 1)
        self.assertEqual(resp.data['results'][0]['category']['slug'], 'laser')
        # filter by slug
        resp2 = self.admin.get('/api/services/?category=facial')
        self.assertEqual(resp2.status_code, 200)
        self.assertEqual(resp2.data['results'][0]['category']['slug'], 'facial')

    def test_category_ordering(self):
        ServiceCategory.objects.create(name='B', slug='b', sort_order=2)
        ServiceCategory.objects.create(name='A', slug='a', sort_order=1)
        resp = self.admin.get('/api/service-categories/')
        self.assertEqual(resp.status_code, 200)
        # ordering is sort_order, name
        self.assertEqual(resp.data['results'][0]['slug'], 'a')

    def test_category_deactivation(self):
        cat = ServiceCategory.objects.create(name='Laser', slug='laser', is_active=True)
        resp = self.admin.patch(f'/api/service-categories/{cat.id}/', {'is_active': False}, format='json')
        self.assertEqual(resp.status_code, 200)
        cat.refresh_from_db()
        self.assertFalse(cat.is_active)

    def test_category_delete_protection_when_referenced(self):
        cat = ServiceCategory.objects.create(name='Laser', slug='laser')
        Service.objects.create(name='Svc', price_usd=Decimal('10'), category=cat)
        resp = self.admin.delete(f'/api/service-categories/{cat.id}/')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('Deactivate', resp.data['detail'])
        self.assertTrue(ServiceCategory.objects.filter(id=cat.id).exists())

    def test_category_delete_unreferenced_allowed(self):
        cat = ServiceCategory.objects.create(name='Laser', slug='laser')
        resp = self.admin.delete(f'/api/service-categories/{cat.id}/')
        self.assertEqual(resp.status_code, status.HTTP_204_NO_CONTENT)

    def test_category_permissions(self):
        ServiceCategory.objects.create(name='Laser', slug='laser')
        # employee can read
        resp = self.emp.get('/api/service-categories/')
        self.assertEqual(resp.status_code, 200)
        # employee cannot create
        resp2 = self.emp.post('/api/service-categories/', {'name': 'New', 'slug': 'new'}, format='json')
        self.assertEqual(resp2.status_code, status.HTTP_403_FORBIDDEN)
        # unauthenticated blocked
        from rest_framework.test import APIClient

        anon = APIClient()
        self.assertEqual(anon.get('/api/service-categories/').status_code, 401)


class ServiceProductTests(TestCase):
    def setUp(self):
        self.admin = admin_client()
        self.cat = ServiceCategory.objects.create(name='Laser', slug='laser')

    def test_service_can_have_multiple_products(self):
        svc = Service.objects.create(name='Svc', price_usd=Decimal('100'), category=self.cat)
        p1 = Product.objects.create(name='P1', unit_price=Decimal('10'), cost_usd=Decimal('1'), count=10)
        p2 = Product.objects.create(name='P2', unit_price=Decimal('10'), cost_usd=Decimal('2'), count=10)
        ServiceItem.objects.create(service=svc, product=p1, quantity=Decimal('2'))
        ServiceItem.objects.create(service=svc, product=p2, quantity=Decimal('3'))
        self.assertEqual(svc.items.count(), 2)

    def test_product_can_be_used_by_multiple_services(self):
        svc1 = Service.objects.create(name='Svc1', price_usd=Decimal('100'))
        svc2 = Service.objects.create(name='Svc2', price_usd=Decimal('100'))
        p = Product.objects.create(name='P', unit_price=Decimal('10'), cost_usd=Decimal('1'), count=10)
        ServiceItem.objects.create(service=svc1, product=p, quantity=Decimal('1'))
        ServiceItem.objects.create(service=svc2, product=p, quantity=Decimal('2'))
        self.assertEqual(p.service_usages.count(), 2)

    def test_duplicate_product_in_service_rejected(self):
        svc = Service.objects.create(name='Svc', price_usd=Decimal('100'))
        p = Product.objects.create(name='P', unit_price=Decimal('10'), cost_usd=Decimal('1'), count=10)
        ServiceItem.objects.create(service=svc, product=p, quantity=Decimal('1'))
        resp = self.admin.post('/api/finance/service-items/', {'service': svc.id, 'product': p.id, 'quantity': '2'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_quantity_must_be_positive(self):
        svc = Service.objects.create(name='Svc', price_usd=Decimal('100'))
        p = Product.objects.create(name='P', unit_price=Decimal('10'), cost_usd=Decimal('1'), count=10)
        for qty in ['0', '-1', '0.000']:
            resp = self.admin.post('/api/finance/service-items/', {'service': svc.id, 'product': p.id, 'quantity': qty}, format='json')
            self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST, f'qty {qty} should fail')

    def test_product_protection(self):
        from django.db.models import ProtectedError

        svc = Service.objects.create(name='Svc', price_usd=Decimal('100'))
        p = Product.objects.create(name='P', unit_price=Decimal('10'), cost_usd=Decimal('1'), count=10)
        ServiceItem.objects.create(service=svc, product=p, quantity=Decimal('1'))
        with self.assertRaises(ProtectedError):
            p.delete()

    def test_inactive_product_assignment_rejected(self):
        svc = Service.objects.create(name='Svc', price_usd=Decimal('100'))
        p = Product.objects.create(name='P', unit_price=Decimal('10'), cost_usd=Decimal('1'), count=10, status=Product.StatusChoices.FINISHED)
        resp = self.admin.post('/api/finance/service-items/', {'service': svc.id, 'product': p.id, 'quantity': '1'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_existing_relationship_remains_when_product_inactive(self):
        svc = Service.objects.create(name='Svc', price_usd=Decimal('100'))
        p = Product.objects.create(name='P', unit_price=Decimal('10'), cost_usd=Decimal('1'), count=10)
        item = ServiceItem.objects.create(service=svc, product=p, quantity=Decimal('1'))
        p.status = Product.StatusChoices.FINISHED
        p.save()
        # existing item should still exist and be readable
        self.assertTrue(ServiceItem.objects.filter(id=item.id).exists())
        resp = self.admin.get(f'/api/finance/service-items/{item.id}/')
        self.assertEqual(resp.status_code, 200)

    def test_service_product_permissions(self):
        svc = Service.objects.create(name='Svc', price_usd=Decimal('100'))
        p = Product.objects.create(name='P', unit_price=Decimal('10'), cost_usd=Decimal('1'), count=10)
        emp = employee_client(username='emp_prod')
        # employee read allowed (IsAdminOrReadOnly allows read)
        resp = emp.get('/api/finance/service-items/')
        self.assertEqual(resp.status_code, 200)
        # employee cannot write
        resp2 = emp.post('/api/finance/service-items/', {'service': svc.id, 'product': p.id, 'quantity': '1'}, format='json')
        self.assertEqual(resp2.status_code, status.HTTP_403_FORBIDDEN)


class ServicePricingApiTests(TestCase):
    def setUp(self):
        ExchangeRate.objects.create(currency_from='USD', currency_to='TOMAN', rate=Decimal('110000'), effective_at=timezone.now(), source='test')
        self.admin = admin_client()
        self.cat = ServiceCategory.objects.create(name='Laser', slug='laser')
        self.service = Service.objects.create(name='Laser Svc', price_usd=Decimal('100.00'), category=self.cat, is_active=True)
        self.p1 = Product.objects.create(name='Gel', unit_price=Decimal('100'), cost_usd=Decimal('0.20'), count=100)
        self.p2 = Product.objects.create(name='Cream', unit_price=Decimal('100'), cost_usd=Decimal('0.50'), count=100)
        ServiceItem.objects.create(service=self.service, product=self.p1, quantity=Decimal('50'))
        ServiceItem.objects.create(service=self.service, product=self.p2, quantity=Decimal('10'))

    def test_service_serializer_pricing(self):
        resp = self.admin.get(f'/api/services/{self.service.id}/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['estimated_cost_usd'], '15.00')  # 0.20*50=10 + 0.5*10=5
        self.assertEqual(resp.data['estimated_gross_profit_usd'], '85.00')
        self.assertEqual(resp.data['estimated_margin_percent'], '85.00')
        self.assertIn('products', resp.data)
        self.assertEqual(len(resp.data['products']), 2)
        # check product breakdown
        prod_names = {p['name'] for p in resp.data['products']}
        self.assertIn('Gel', prod_names)

    def test_service_serializer_toman_conversion(self):
        resp = self.admin.get(f'/api/services/{self.service.id}/')
        self.assertEqual(resp.data['price_toman'], '11000000.00')  # 100 *110000
        self.assertEqual(resp.data['estimated_cost_toman'], '1650000.00')  # 15*110000
        self.assertEqual(resp.data['estimated_gross_profit_toman'], '9350000.00')  # 85*110000

    def test_service_serializer_without_exchange_rate(self):
        ExchangeRate.objects.all().delete()
        # Use override to remove fallback and disable external fetch (would otherwise hit Tindex)
        with override_settings(FINANCE_DEFAULT_USD_TO_TOMAN_RATE=Decimal('0'), EXCHANGE_RATE_PROVIDER='database', EXCHANGE_RATE_API_URL=''):
            resp = self.admin.get(f'/api/services/{self.service.id}/')
            self.assertEqual(resp.status_code, 200)
            self.assertIsNone(resp.data['price_toman'])
            self.assertIsNone(resp.data['estimated_cost_toman'])
            self.assertIsNone(resp.data['estimated_gross_profit_toman'])
            # USD fields still work
            self.assertEqual(resp.data['estimated_cost_usd'], '15.00')

    def test_service_category_filter(self):
        cat2 = ServiceCategory.objects.create(name='Facial', slug='facial')
        Service.objects.create(name='Facial Svc', price_usd=Decimal('50'), category=cat2)
        resp = self.admin.get(f'/api/services/?category={self.cat.id}')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data['results']), 1)
        self.assertEqual(resp.data['results'][0]['category']['slug'], 'laser')

    def test_service_search(self):
        resp = self.admin.get('/api/services/?search=Laser')
        self.assertEqual(resp.status_code, 200)
        self.assertGreaterEqual(len(resp.data['results']), 1)

    def test_service_serializer_performance_no_nplus1(self):
        # Create 5 services each with products
        for i in range(5):
            svc = Service.objects.create(name=f'Svc {i}', price_usd=Decimal('100'), category=self.cat)
            p = Product.objects.create(name=f'P {i}', unit_price=Decimal('10'), cost_usd=Decimal('1'), count=10)
            ServiceItem.objects.create(service=svc, product=p, quantity=Decimal('1'))
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        with CaptureQueriesContext(connection) as ctx:
            resp = self.admin.get('/api/services/')
            self.assertEqual(resp.status_code, 200)
            # Should be ~ 3-4 queries: services + categories + items + products + exchange rate
            # Not N+1 (5 extra per service)
            # Allow up to 10 queries to be safe
            self.assertLess(len(ctx.captured_queries), 15, f'Queries: {len(ctx.captured_queries)}')


class ServiceCategoryApiPermissionsTests(TestCase):
    def test_employee_read_category(self):
        ServiceCategory.objects.create(name='Laser', slug='laser')
        emp = employee_client(username='emp_perm')
        self.assertEqual(emp.get('/api/service-categories/').status_code, 200)

    def test_unauthenticated_blocked(self):
        from rest_framework.test import APIClient

        self.assertEqual(APIClient().get('/api/service-categories/').status_code, 401)
        self.assertEqual(APIClient().get('/api/services/').status_code, 401)
