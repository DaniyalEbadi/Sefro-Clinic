"""Site API v2 face routes and live website-catalog recommendations."""

import io
import json
import tempfile
from decimal import Decimal
from unittest import mock

from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from PIL import Image
from rest_framework.test import APIClient

from face_analyzer.exceptions import AnalyzerUnavailable, FaceAnalyzerError
from face_analyzer.models import FaceAnalysis, SkinCareTip
from face_analyzer.services.tips import SkinCarePlanDraft, generate_and_store_plan
from tests.helpers import admin_client, employee_client
from tests.integration.test_face_analyzer import make_backend, make_result
from website.models import SitePackage, SitePackagePriceOption, SiteProduct, SiteService

TEST_MEDIA_ROOT = tempfile.mkdtemp(prefix='face_site_media_')


def face_image():
    buffer = io.BytesIO()
    Image.new('RGB', (96, 96), (198, 152, 126)).save(buffer, format='PNG')
    return SimpleUploadedFile('face.png', buffer.getvalue(), content_type='image/png')


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class SiteFaceAnalyzerTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()

    def tearDown(self):
        cache.clear()

    def analyze(self, client=None, version='v2', concerns=None, backend=None):
        backend = backend or make_backend(make_result(concerns=concerns))
        with mock.patch('face_analyzer.views.get_backend', return_value=backend):
            return (client or self.client).post(
                f'/api/{version}/face/analyze/', {'image': face_image()}, format='multipart',
            )

    @staticmethod
    def seed_catalog():
        service = SiteService.objects.create(
            name='پاکسازی پوست', slug='skin-cleansing', category='skin',
            price=1500000, price_usd=10, is_from_price=True, is_active=True,
            source_url='https://barancliniccenter.com/services/skin-cleansing',
        )
        SiteService.objects.create(
            name='اسیدتراپی', slug='acid-therapy', category='skin',
            price=2000000, price_usd=12, is_active=False,
        )
        product = SiteProduct.objects.create(
            name='ضدآفتاب', slug='sunscreen-spf50', price=320000, price_usd=2,
            source_url='https://barancliniccenter.com/products/sunscreen-spf50',
        )
        package = SitePackage.objects.create(
            name='پکیج مراقبت', slug='skin-bundle', price=2800000, price_usd=18,
            source_url='https://barancliniccenter.com/packages/skin-bundle',
        )
        package.services.add(service)
        option = SitePackagePriceOption.objects.create(
            package=package, label='۲ جلسه', session_count=2, gift_session_count=1,
            price=2800000, price_usd=18,
        )
        SitePackagePriceOption.objects.create(
            package=package, label='غیرفعال', price=3500000, price_usd=21, is_active=False,
        )
        return service, product, package, option

    def test_v2_analyze_recommends_active_site_catalog_with_toman_prices(self):
        service, product, package, option = self.seed_catalog()
        response = self.analyze(concerns=['enlarged_pores', 'dullness'])

        self.assertEqual(response.status_code, 200, response.data)
        recommendations = response.data['recommendations']
        self.assertIn('بر اساس تصویر', recommendations['summary'])
        self.assertTrue(recommendations['next_steps'])
        self.assertIn('تشخیص پزشکی نیست', recommendations['disclaimer'])
        self.assertEqual([item['slug'] for item in recommendations['services']], [service.slug])
        self.assertEqual(recommendations['services'][0]['price_toman'], '1500000')
        self.assertTrue(recommendations['services'][0]['is_from_price'])
        self.assertEqual(recommendations['services'][0]['source_url'], service.source_url)
        self.assertEqual(recommendations['products'][0]['slug'], product.slug)
        self.assertEqual(recommendations['products'][0]['price_toman'], '320000')
        self.assertEqual(recommendations['packages'][0]['slug'], package.slug)
        self.assertEqual(recommendations['packages'][0]['price_options'][0]['price_toman'], '2800000')
        self.assertEqual(recommendations['packages'][0]['price_options'][0]['gift_session_count'], 1)
        self.assertEqual(len(recommendations['packages'][0]['price_options']), 1)
        self.assertEqual(option.package_id, package.pk)
        self.assertNotIn('acid-therapy', [item['slug'] for item in recommendations['services']])
        self.assertEqual(FaceAnalysis.objects.count(), 1)

    def test_detail_recomputes_current_prices_and_filters_inactive_items(self):
        service, product, package, option = self.seed_catalog()
        client = employee_client()
        response = self.analyze(client=client, concerns=['enlarged_pores'])
        self.assertEqual(response.status_code, 200, response.data)

        service.price = 1700000
        service.save(update_fields=['price'])
        product.price = Decimal('350000.01')
        product.save(update_fields=['price'])
        option.price = 3000000
        option.save(update_fields=['price'])
        detail = client.get(f"/api/v2/face/history/{response.data['id']}/")
        self.assertEqual(detail.status_code, 200, detail.data)
        self.assertEqual(detail.data['recommendations']['services'][0]['price_toman'], '1700000')
        self.assertEqual(detail.data['recommendations']['products'][0]['price_toman'], '350001')
        self.assertEqual(detail.data['recommendations']['packages'][0]['price_options'][0]['price_toman'], '3000000')

        service.is_active = False
        service.save(update_fields=['is_active'])
        product.is_active = False
        product.save(update_fields=['is_active'])
        package.is_active = False
        package.save(update_fields=['is_active'])
        detail = client.get(f"/api/v2/face/history/{response.data['id']}/")
        self.assertEqual(detail.data['recommendations']['services'], [])
        self.assertEqual(detail.data['recommendations']['products'], [])
        self.assertEqual(detail.data['recommendations']['packages'], [])

    def test_no_unrelated_package_or_score_only_procedure(self):
        service, _product, package, _option = self.seed_catalog()
        package.services.clear()
        response = self.analyze(concerns=['enlarged_pores'])
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['recommendations']['packages'], [])
        self.assertEqual(response.data['recommendations']['services'][0]['slug'], service.slug)

        low_scores = make_result(concerns=[])
        low_scores.skin_clarity_score = 4.0
        response = self.analyze(backend=make_backend(low_scores))
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['recommendations']['services'], [])
        self.assertEqual(response.data['recommendations']['packages'], [])
        self.assertTrue(any('شفافیت' in step for step in response.data['recommendations']['next_steps']))

    def test_scores_reorder_detected_concerns_without_creating_new_ones(self):
        self.seed_catalog()
        SiteService.objects.create(
            name='Peptide Therapy', slug='peptide-therapy', category='skin', price=900000,
        )
        result = make_result(concerns=['fine_lines', 'dullness'])
        result.skin_clarity_score = 4.0
        result.youthfulness_score = 8.0
        response = self.analyze(backend=make_backend(result))
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['recommendations']['services'][0]['slug'], 'skin-cleansing')

        result.skin_clarity_score = 8.0
        result.youthfulness_score = 3.0
        response = self.analyze(backend=make_backend(result))
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['recommendations']['services'][0]['slug'], 'peptide-therapy')

    def test_llm_professional_tips_must_match_active_concern_services(self):
        self.seed_catalog()
        SiteService.objects.create(
            name='Hair Filler', slug='hair-filler', category='hair', price=1000000,
        )
        response = self.analyze(concerns=['acne'])
        self.assertEqual(response.status_code, 200, response.data)
        analysis = FaceAnalysis.objects.get(pk=response.data['id'])
        draft = SkinCarePlanDraft(
            summary='Test', skin_type='normal', primary_concerns=['acne'],
            recommended_frequency='Daily', provider='llm', model_used='test',
            tips=[
                {'period': 'professional', 'category': 'in_clinic', 'title': 'Hair filler cures acne',
                 'description': 'Invented claim', 'related_service_slug': 'hair-filler'},
                {'period': 'professional', 'category': 'in_clinic', 'title': 'A cure',
                 'description': 'Invented claim', 'related_service_slug': 'skin-cleansing'},
                {'period': 'professional', 'category': 'in_clinic', 'title': 'Unknown',
                 'description': 'Invented claim', 'related_service_slug': 'made-up-treatment'},
            ],
        )
        with mock.patch('face_analyzer.services.tips.get_tips_provider') as provider:
            provider.return_value.generate.return_value = draft
            generate_and_store_plan(analysis)
        professional = list(SkinCareTip.objects.filter(analysis=analysis, period='professional'))
        self.assertEqual([tip.related_service_slug for tip in professional], ['skin-cleansing'])
        self.assertEqual(professional[0].title, 'Consultation: پاکسازی پوست')
        self.assertNotIn('cure', professional[0].description)

    def test_v2_and_v3_share_storage_and_permissions(self):
        self.seed_catalog()
        self.assertEqual(self.client.get('/api/v2/face/history/').status_code, 401)
        client = employee_client()
        response = self.analyze(client=client, concerns=['enlarged_pores'])
        self.assertEqual(response.status_code, 200, response.data)
        analysis_id = response.data['id']
        self.assertEqual(client.get('/api/v3/face/history/').data['count'], 1)
        self.assertEqual(client.get(f'/api/v2/face/history/{analysis_id}/').status_code, 200)
        self.assertEqual(self.client.post(f'/api/v2/face/{analysis_id}/tips/').status_code, 404)
        self.assertEqual(client.post(f'/api/v2/face/{analysis_id}/tips/').status_code, 200)
        other = employee_client(username='site_face_other')
        self.assertEqual(other.get(f'/api/v2/face/history/{analysis_id}/').status_code, 404)
        self.assertEqual(admin_client().get(f'/api/v2/face/history/{analysis_id}/').status_code, 200)
        self.assertEqual(FaceAnalysis.objects.count(), 1)

    def test_v2_invalid_image_and_no_face_are_client_errors(self):
        invalid = SimpleUploadedFile('not-face.txt', b'invalid', content_type='text/plain')
        self.assertEqual(self.client.post(
            '/api/v2/face/analyze/', {'image': invalid}, format='multipart',
        ).status_code, 400)
        backend = make_backend()
        backend.analyze.side_effect = FaceAnalyzerError('No face detected')
        self.assertEqual(self.analyze(backend=backend).status_code, 400)
        self.assertEqual(FaceAnalysis.objects.count(), 0)

    @override_settings(FACE_ANALYZER_THROTTLE_RATE='2/min')
    def test_v2_and_v3_share_analyzer_throttle(self):
        responses = [
            self.analyze(version='v2'),
            self.analyze(version='v3'),
            self.analyze(version='v2'),
        ]
        self.assertEqual([response.status_code for response in responses], [200, 200, 429])

    def test_v2_reports_unavailable_model_as_503(self):
        backend = make_backend()
        backend.analyze.side_effect = AnalyzerUnavailable()
        response = self.analyze(backend=backend)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(FaceAnalysis.objects.count(), 0)

    def test_v2_schema_has_face_group_and_v1_does_not(self):
        client = admin_client()
        v2 = client.get('/api/v2/schema/')
        self.assertEqual(v2.status_code, 200)
        paths = json.loads(v2.content)['paths']
        for path in (
            '/api/v2/face/analyze/', '/api/v2/face/{id}/tips/',
            '/api/v2/face/history/', '/api/v2/face/history/{id}/',
        ):
            self.assertIn(path, paths)
        self.assertEqual(paths['/api/v2/face/analyze/']['post']['tags'], ['Site Face Analyzer'])
        self.assertIn('recommendations', v2.content.decode())
        self.assertEqual(client.get('/api/v2/docs/').status_code, 200)
        v1 = client.get('/api/schema/')
        self.assertEqual(v1.status_code, 200)
        self.assertNotIn('/api/v2/face/', v1.content.decode())
