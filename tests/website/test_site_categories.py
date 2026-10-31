from django.test import TestCase
from rest_framework.test import APIClient

from tests.helpers import admin_client, website_manager_client
from tests.website.test_models import make_package, make_product, make_service
from website.models import SiteCategory


class SiteCategoryApiTests(TestCase):
    def test_live_service_and_package_categories_are_seeded(self):
        self.assertEqual(
            list(SiteCategory.objects.filter(kind='service').order_by('sort_order').values_list('name', flat=True)),
            ['فیلر و بوتاکس', 'لیزر بانوان', 'لیزر آقایان', 'فیشیال'],
        )
        self.assertEqual(
            list(SiteCategory.objects.filter(kind='package').order_by('sort_order').values_list('name', flat=True)),
            ['کربن تراپی', 'لیزر بانوان', 'لیزر آقایان'],
        )
        self.assertEqual(SiteCategory.objects.get(kind='product', slug='skin-care').name, 'مراقبت پوست')

    def test_public_category_lists_counts_and_resource_filters(self):
        service_category = SiteCategory.objects.get(kind='service', slug='filler-botox')
        package_category = SiteCategory.objects.get(kind='package', slug='carbon-therapy')
        product_category = SiteCategory.objects.get(kind='product', slug='skin-care')
        make_service(site_category=service_category)
        make_package(site_category=package_category)
        make_product(site_category=product_category)
        client = APIClient()
        categories = client.get('/api/v2/categories/?kind=service')
        self.assertEqual(categories.status_code, 200)
        self.assertEqual(len(categories.data), 4)
        self.assertEqual(categories.data[0]['item_count'], 1)
        self.assertEqual(client.get('/api/v2/services/?category=filler-botox').data['count'], 1)
        self.assertEqual(client.get('/api/v2/services/?category=face').data['count'], 1)
        self.assertEqual(client.get('/api/v2/packages/?category=carbon-therapy').data['count'], 1)
        self.assertEqual(client.get('/api/v2/products/?category=skin-care').data['count'], 1)
        self.assertEqual(client.get('/api/v2/products/vitamin-c-serum/').data['site_category']['name'], 'مراقبت پوست')

    def test_dashboard_crud_assignment_and_delete_guard(self):
        client = website_manager_client()
        product = make_product()
        created = client.post('/api/v2/site-dashboard/categories/', {
            'kind': 'product', 'slug': 'premium-skin-care', 'name': 'محصولات ویژه', 'sort_order': 2,
        }, format='json')
        self.assertEqual(created.status_code, 201, created.data)
        category_id = created.data['id']
        detail = f'/api/v2/site-dashboard/categories/{category_id}/'
        self.assertEqual(client.get(detail).status_code, 200)
        updated = client.patch(detail, {'name': 'مراقبت ویژه', 'sort_order': 1}, format='json')
        self.assertEqual(updated.status_code, 200, updated.data)
        self.assertEqual(updated.data['name'], 'مراقبت ویژه')
        assigned = client.patch(f'/api/v2/site-dashboard/products/{product.slug}/', {
            'site_category_id': category_id,
        }, format='json')
        self.assertEqual(assigned.status_code, 200, assigned.data)
        self.assertEqual(assigned.data['site_category']['name'], 'مراقبت ویژه')
        self.assertEqual(client.delete(detail).status_code, 409)
        self.assertEqual(client.patch(f'/api/v2/site-dashboard/products/{product.slug}/', {
            'site_category_id': None,
        }, format='json').status_code, 200)
        self.assertEqual(client.delete(detail).status_code, 204)

    def test_wrong_kind_inactive_category_and_financial_session_are_rejected(self):
        manager = website_manager_client()
        product = make_product()
        service_category = SiteCategory.objects.get(kind='service', slug='facial')
        url = f'/api/v2/site-dashboard/products/{product.slug}/'
        self.assertEqual(manager.patch(url, {'site_category_id': service_category.pk}, format='json').status_code, 400)
        service_category.is_active = False
        service_category.save(update_fields=['is_active'])
        service = make_service()
        self.assertEqual(manager.patch(
            f'/api/v2/site-dashboard/services/{service.slug}/',
            {'site_category_id': service_category.pk}, format='json',
        ).status_code, 400)
        self.assertIn(APIClient().get('/api/v2/site-dashboard/categories/').status_code, (401, 403))
        self.assertIn(admin_client().get('/api/v2/site-dashboard/categories/').status_code, (401, 403))

    def test_category_routes_are_only_in_site_v2_schema(self):
        client = admin_client()
        v2 = client.get('/api/v2/schema/').content.decode()
        v1 = client.get('/api/schema/').content.decode()
        self.assertIn('/api/v2/site-dashboard/categories/', v2)
        self.assertIn('/api/v2/categories/', v2)
        self.assertIn('Website Dashboard - Categories', v2)
        self.assertNotIn('/api/v2/site-dashboard/categories/', v1)
