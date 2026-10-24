from decimal import Decimal
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from PIL import Image
from rest_framework.test import APIClient

from tests.helpers import admin_client, website_manager_client
from tests.website.test_models import make_service
from website.models import SiteService
from website.services.sync import sync_website_prices


class ServicePageTests(TestCase):
    @patch('website.views.get_current_usd_to_toman_rate', return_value=Decimal('100000'))
    def test_create_full_page_in_toman_then_sync(self, _rate):
        response = website_manager_client().post('/api/v2/site-dashboard/services/', {
            'name': 'بوتاکس صورت', 'slug': 'botox-face', 'category': 'face',
            'short_description': 'خطوط صورت را کاهش می‌دهد',
            'description': 'با تزریق دقیق در عضلات هدف، خطوط اخم و چروک پیشانی کاهش می‌یابد.',
            'price': '799.001', 'image_url': 'https://example.com/photo.jpg',
            'source_url': 'https://barancliniccenter.com/services/botox-face',
        }, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        service = SiteService.objects.get(slug='botox-face')
        self.assertEqual(service.price, Decimal('800'))
        self.assertTrue(service.is_manually_managed)
        public = APIClient().get('/api/v2/services/botox-face/')
        self.assertEqual(public.status_code, 200)
        self.assertEqual(public.data['description'], service.description)
        self.assertEqual(public.data['image_url'], service.image_url)
        with patch('website.services.sync.fetch_website_rate', return_value=(Decimal('200000'), 'test')):
            sync_website_prices()
        service.refresh_from_db()
        self.assertEqual(service.price, Decimal('1600'))

    @patch('website.views.get_current_usd_to_toman_rate', return_value=None)
    def test_text_edit_needs_no_rate_but_price_edit_does(self, _rate):
        service = make_service()
        url = f'/api/v2/site-dashboard/services/{service.slug}/'
        self.assertEqual(website_manager_client().patch(url, {'description': 'جدید'}, format='json').status_code, 200)
        self.assertEqual(website_manager_client().patch(url, {'price': '1000'}, format='json').status_code, 503)
        service.refresh_from_db()
        self.assertEqual(service.description, 'جدید')
        self.assertEqual(service.price, Decimal('2500000'))

    def test_anonymous_cannot_create_or_upload(self):
        service = make_service()
        self.assertEqual(APIClient().post('/api/v2/site-dashboard/services/', {}, format='json').status_code, 401)
        self.assertEqual(APIClient().post(f'/api/v2/site-dashboard/services/{service.slug}/image/', {}).status_code, 401)

    def test_external_image_link_clears_previous_object_key(self):
        service = make_service(
            image_url='https://storage.c2.liara.site/farabaks3/baran-clinic/services/old.png',
            image_object_key='baran-clinic/services/old.png',
        )
        response = website_manager_client().patch(
            f'/api/v2/site-dashboard/services/{service.slug}/',
            {'image_url': 'https://example.com/new.jpg'}, format='json',
        )
        self.assertEqual(response.status_code, 200)
        service.refresh_from_db()
        self.assertEqual(service.image_url, 'https://example.com/new.jpg')
        self.assertEqual(service.image_object_key, '')

    @override_settings(LIARA_ACCESS_KEY='test-key', LIARA_SECRET_KEY='test-secret')
    def test_upload_uses_only_scoped_bucket_key_and_saves_permanent_url(self):
        service = make_service()
        content = BytesIO()
        Image.new('RGB', (4, 4), 'red').save(content, format='PNG')
        image = SimpleUploadedFile('anything.png', content.getvalue(), content_type='image/png')
        client_factory = Mock()
        with patch.dict('sys.modules', {'boto3': SimpleNamespace(client=client_factory)}):
            response = website_manager_client().post(
                f'/api/v2/site-dashboard/services/{service.slug}/image/', {'image': image}, format='multipart',
            )
        self.assertEqual(response.status_code, 200, response.data)
        service.refresh_from_db()
        self.assertTrue(service.image_object_key.startswith('baran-clinic/services/botox/'))
        self.assertTrue(service.image_object_key.endswith('.png'))
        self.assertEqual(service.image_url, f'https://storage.c2.liara.site/farabaks3/{service.image_object_key}')
        self.assertEqual(client_factory.call_args.kwargs['endpoint_url'], 'https://storage.c2.liara.site')
        self.assertEqual(client_factory.return_value.put_object.call_args.kwargs['Bucket'], 'farabaks3')
        self.assertEqual(client_factory.return_value.put_object.call_args.kwargs['Key'], service.image_object_key)
        self.assertEqual(APIClient().get('/api/v2/services/botox/').data['image_url'], service.image_url)

    def test_upload_without_keys_or_invalid_image_does_not_change_page(self):
        service = make_service()
        url = f'/api/v2/site-dashboard/services/{service.slug}/image/'
        content = BytesIO()
        Image.new('RGB', (4, 4), 'red').save(content, format='PNG')
        image = SimpleUploadedFile('photo.png', content.getvalue(), content_type='image/png')
        self.assertEqual(website_manager_client().post(url, {'image': image}, format='multipart').status_code, 503)
        with override_settings(LIARA_ACCESS_KEY='test', LIARA_SECRET_KEY='test'):
            image = SimpleUploadedFile('bad.png', b'not-image', content_type='image/png')
            self.assertEqual(website_manager_client().post(url, {'image': image}, format='multipart').status_code, 400)
        service.refresh_from_db()
        self.assertEqual(service.image_url, '')

    def test_v2_schema_contains_editor_and_upload_but_v1_does_not(self):
        v2 = admin_client().get('/api/v2/schema/').content.decode()
        v1 = admin_client().get('/api/schema/').content.decode()
        self.assertIn('/api/v2/site-dashboard/services/{slug}/image/', v2)
        self.assertIn('description', v2)
        self.assertNotIn('/api/v2/site-dashboard/services/{slug}/image/', v1)
