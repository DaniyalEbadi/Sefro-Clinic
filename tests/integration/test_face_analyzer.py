"""Integration tests for the Face AI Analyzer v3 API.

Covers the 12 required cases: analyze success with plan, oversized/non-image
rejection, throttle 429, auth-gated scoped history, tips regeneration,
audit log, deterministic rule tips, LLM fallback, Shamsi timestamps and
service-linked tips — with get_backend() mocked so CI never needs MediaPipe.
"""
import io
import re
import tempfile
from unittest import mock

from django.conf import settings
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from PIL import Image
from rest_framework import status
from rest_framework.test import APIClient

from customers.models import Service
from face_analyzer.models import FaceAnalysis, SkinCarePlan, SkinCareTip
from face_analyzer.services.analyzer import FaceAnalysisResult
from face_analyzer.services.tips import RuleBasedTipsProvider, generate_and_store_plan
from logs.models import AuditLog
from tests.helpers import admin_client, employee_client, make_employee

ANALYZE_URL = '/api/v3/face/analyze/'
HISTORY_URL = '/api/v3/face/history/'
SHAMSI_PATTERN = re.compile(r'^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$')
SCORE_KEYS = (
    'overall_score',
    'symmetry_score',
    'skin_clarity_score',
    'youthfulness_score',
    'harmony_score',
)
RESPONSE_KEYS = {
    'id',
    *SCORE_KEYS,
    'detected_attributes',
    'suggestions',
    'skin_plan',
    'created_at',
    'provider',
    'model_version',
}
MOCK_CONCERNS = ['hyperpigmentation', 'enlarged_pores', 'dullness']
TEST_MEDIA_ROOT = tempfile.mkdtemp(prefix='face_analyzer_media_')


def make_image_file(name='face.png', image_format='PNG', size=(96, 96), color=(198, 152, 126), content_type=None):
    buffer = io.BytesIO()
    Image.new('RGB', size, color).save(buffer, format=image_format)
    if content_type is None:
        content_type = 'image/png' if image_format == 'PNG' else 'image/jpeg'
    return SimpleUploadedFile(name, buffer.getvalue(), content_type=content_type)


def make_result(concerns=None):
    return FaceAnalysisResult(
        overall_score=7.8,
        symmetry_score=8.2,
        skin_clarity_score=7.5,
        youthfulness_score=8.0,
        harmony_score=7.6,
        detected_attributes={
            'face_shape': 'oval',
            'skin_tone': 'medium',
            'skin_undertone': 'warm',
            'eye_shape': 'almond',
            'lip_fullness': 'medium',
            'concerns': list(MOCK_CONCERNS if concerns is None else concerns),
        },
        suggestions=[
            {'category': 'skincare', 'title': 'Skincare routine', 'detail': 'Keep SPF daily.'},
            {'category': 'makeup', 'title': 'Cheekbone-focused makeup', 'detail': 'Warm contour.'},
            {'category': 'hairstyle', 'title': 'Soft layered cut', 'detail': 'Jaw-length layers.'},
        ],
        raw_output={'method': 'test'},
        model_version='mediapipe-0.10.14+sefro-local-v1',
    )


def make_backend(result=None):
    backend = mock.Mock()
    backend.provider = 'local'
    backend.analyze.return_value = result or make_result()
    return backend


def patched_get_backend(backend=None):
    return mock.patch('face_analyzer.views.get_backend', return_value=backend or make_backend())


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class FaceAnalyzeEndpointTests(TestCase):
    """POST /api/v3/face/analyze/ — public, throttled analysis with skin plan."""

    def setUp(self):
        cache.clear()
        self.client = APIClient()

    def tearDown(self):
        cache.clear()

    def test_analyze_success_returns_scores_and_plan(self):
        with patched_get_backend():
            response = self.client.post(ANALYZE_URL, {'image': make_image_file()}, format='multipart')

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        data = response.data
        self.assertEqual(set(data.keys()), RESPONSE_KEYS)
        for key in SCORE_KEYS:
            self.assertGreaterEqual(data[key], 0, key)
            self.assertLessEqual(data[key], 10, key)

        attributes = data['detected_attributes']
        self.assertEqual(attributes['face_shape'], 'oval')
        self.assertEqual(attributes['concerns'], MOCK_CONCERNS)

        plan = data['skin_plan']
        self.assertIsNotNone(plan)
        self.assertEqual(plan['skin_type'], 'normal')  # no oiliness/dryness in mock concerns
        self.assertEqual(plan['provider'], 'rule_based')
        self.assertEqual(plan['primary_concerns'], MOCK_CONCERNS)
        for period in ('morning', 'evening', 'weekly', 'lifestyle', 'professional'):
            self.assertIn(period, plan)
            self.assertGreaterEqual(len(plan[period]), 1, period)
            for tip in plan[period]:
                self.assertEqual(tip['period'], period)
                self.assertIn(tip['priority'], {'low', 'medium', 'high'})
                self.assertTrue(tip['title'])
                self.assertTrue(tip['description'])

        self.assertRegex(str(data['created_at']), SHAMSI_PATTERN)
        self.assertEqual(data['provider'], 'local')
        self.assertEqual(FaceAnalysis.objects.count(), 1)
        self.assertEqual(SkinCarePlan.objects.count(), 1)
        self.assertGreater(SkinCareTip.objects.count(), 0)

    def test_response_schema_shamsi_timestamp(self):
        with patched_get_backend():
            response = self.client.post(ANALYZE_URL, {'image': make_image_file()}, format='multipart')
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertRegex(str(response.data['created_at']), SHAMSI_PATTERN)

    def test_jpeg_upload_accepted(self):
        with patched_get_backend():
            response = self.client.post(
                ANALYZE_URL,
                {'image': make_image_file(name='face.jpg', image_format='JPEG', content_type='image/jpeg')},
                format='multipart',
            )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data['provider'], 'local')

    def test_analyze_rejects_oversized_file(self):
        oversized = SimpleUploadedFile('huge.jpg', b'x' * (6 * 1024 * 1024), content_type='image/jpeg')
        response = self.client.post(ANALYZE_URL, {'image': oversized}, format='multipart')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.data)
        self.assertEqual(FaceAnalysis.objects.count(), 0)

    def test_analyze_rejects_non_image_file(self):
        text_file = SimpleUploadedFile('notes.txt', b'this is not an image', content_type='text/plain')
        response = self.client.post(ANALYZE_URL, {'image': text_file}, format='multipart')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.data)
        self.assertEqual(FaceAnalysis.objects.count(), 0)

    def test_disallowed_mime_type_rejected_with_400(self):
        disguised = make_image_file(content_type='application/octet-stream')
        response = self.client.post(ANALYZE_URL, {'image': disguised}, format='multipart')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.data)

    def test_corrupt_image_with_allowed_mime_rejected_with_400(self):
        corrupt = SimpleUploadedFile('fake.png', b'definitely not a png', content_type='image/png')
        response = self.client.post(ANALYZE_URL, {'image': corrupt}, format='multipart')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.data)

    def test_missing_image_rejected_with_400(self):
        response = self.client.post(ANALYZE_URL, {}, format='multipart')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.data)
        self.assertIn('image', response.data)

    @override_settings(FACE_ANALYZER_THROTTLE_RATE='5/min')
    def test_analyze_throttle_429(self):
        cache.clear()
        statuses = []
        try:
            with patched_get_backend():
                for index in range(6):
                    response = self.client.post(
                        ANALYZE_URL,
                        {'image': make_image_file(name=f'burst-{index}.png')},
                        format='multipart',
                    )
                    statuses.append(response.status_code)
        finally:
            cache.clear()

        self.assertEqual(statuses, [status.HTTP_200_OK] * 5 + [status.HTTP_429_TOO_MANY_REQUESTS])

    def test_audit_log_row_created(self):
        with patched_get_backend():
            response = self.client.post(ANALYZE_URL, {'image': make_image_file()}, format='multipart')
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)

        analysis = FaceAnalysis.objects.get()
        log = AuditLog.objects.get(model_name='face_analyzer.faceanalysis', action='CREATE')
        self.assertEqual(log.object_id, analysis.pk)
        self.assertIsNone(log.user_id)  # public call -> system

    def test_authenticated_analysis_links_user_and_audit_log(self):
        client = employee_client()
        with patched_get_backend():
            response = client.post(ANALYZE_URL, {'image': make_image_file()}, format='multipart')
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)

        analysis = FaceAnalysis.objects.get()
        employee = make_employee()
        self.assertEqual(analysis.user_id, employee.pk)

        log = AuditLog.objects.get(model_name='face_analyzer.faceanalysis', action='CREATE')
        self.assertEqual(log.user_id, employee.pk)

    def test_unauthenticated_anonymous_analysis_stores_null_user(self):
        with patched_get_backend():
            self.client.post(ANALYZE_URL, {'image': make_image_file()}, format='multipart')
        self.assertIsNone(FaceAnalysis.objects.get().user_id)


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class FaceAnalysisTipsEndpointTests(TestCase):
    """POST /api/v3/face/{id}/tips/ — public regeneration of the skin-care plan."""

    def setUp(self):
        cache.clear()
        self.client = APIClient()

    def tearDown(self):
        cache.clear()

    @staticmethod
    def analyze():
        with patched_get_backend():
            response = APIClient().post(ANALYZE_URL, {'image': make_image_file()}, format='multipart')
        assert response.status_code == 200, response.data
        return response.data

    def test_tips_regeneration_replaces_old_tips(self):
        data = self.analyze()
        analysis_id = data['id']
        tips_url = f'/api/v3/face/{analysis_id}/tips/'
        first_plan = SkinCarePlan.objects.get(analysis_id=analysis_id)
        tip_count = SkinCareTip.objects.filter(analysis_id=analysis_id).count()
        self.assertGreater(tip_count, 0)

        response_one = self.client.post(tips_url)
        self.assertEqual(response_one.status_code, status.HTTP_200_OK, response_one.data)

        second_plan = SkinCarePlan.objects.get(analysis_id=analysis_id)
        self.assertEqual(second_plan.pk, first_plan.pk)
        self.assertEqual(SkinCareTip.objects.filter(analysis_id=analysis_id).count(), tip_count)

        response_two = self.client.post(tips_url)
        self.assertEqual(response_two.status_code, status.HTTP_200_OK, response_two.data)
        third_plan = SkinCarePlan.objects.get(analysis_id=analysis_id)
        self.assertEqual(SkinCareTip.objects.filter(analysis_id=analysis_id).count(), tip_count)
        self.assertGreater(third_plan.created_at, first_plan.created_at)

        plan_payload = response_two.data
        for period in ('morning', 'evening', 'weekly', 'lifestyle', 'professional'):
            self.assertIn(period, plan_payload)

    def test_tips_endpoint_404_for_missing_analysis(self):
        response = self.client.post('/api/v3/face/999999/tips/')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class SkinCareTipsEngineTests(TestCase):
    """Rule determinism, LLM fallback and clinic-service tip linking."""

    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    @staticmethod
    def create_analysis(concerns=None):
        return FaceAnalysis.objects.create(
            image=make_image_file(),
            overall_score=7.8,
            symmetry_score=8.2,
            skin_clarity_score=7.5,
            youthfulness_score=8.0,
            harmony_score=7.6,
            detected_attributes={
                'face_shape': 'oval',
                'skin_tone': 'medium',
                'skin_undertone': 'warm',
                'eye_shape': 'almond',
                'lip_fullness': 'medium',
                'concerns': list(MOCK_CONCERNS if concerns is None else concerns),
            },
            suggestions=[{'category': 'skincare', 'title': 'Routine', 'detail': 'Keep it consistent.'}],
            raw_model_output={'method': 'test'},
            provider='local',
            model_version='test-v1',
        )

    def test_rule_based_tips_are_deterministic(self):
        analysis = self.create_analysis()
        first = RuleBasedTipsProvider().generate(analysis)
        second = RuleBasedTipsProvider().generate(analysis)

        self.assertEqual(first.tips, second.tips)
        self.assertEqual(first.summary, second.summary)
        self.assertEqual(first.provider, 'rule_based')
        self.assertEqual(first.model_used, 'sefro-rules-v1')
        self.assertGreaterEqual(len(first.tips), 8)

    @override_settings(FACE_ANALYZER_TIPS_PROVIDER='llm')
    def test_llm_provider_falls_back_to_rule_based(self):
        with mock.patch(
            'face_analyzer.services.tips.LLMTipsProvider._call_llm', side_effect=RuntimeError('llm down')
        ):
            with patched_get_backend():
                response = APIClient().post(ANALYZE_URL, {'image': make_image_file()}, format='multipart')

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data['skin_plan']['provider'], 'rule_based')
        plan = SkinCarePlan.objects.get()
        self.assertEqual(plan.provider, 'rule_based')

    def test_skin_tips_link_to_existing_services(self):
        service = Service.objects.create(name='Hydrafacial', price_usd=120, is_active=True)
        analysis = self.create_analysis(concerns=['enlarged_pores'])

        plan = generate_and_store_plan(analysis)
        tip = SkinCareTip.objects.get(analysis=analysis, related_service_slug='hydrafacial')
        self.assertEqual(tip.related_service, service)

        payload = {
            'summary': plan.summary,
            'skin_type': plan.skin_type,
            'professional': [
                {
                    'title': tip.title,
                    'related_service_slug': tip.related_service_slug,
                    'related_service': {
                        'id': tip.related_service.id,
                        'name': tip.related_service.name,
                        'price_usd': str(tip.related_service.price_usd),
                    },
                },
            ],
        }
        self.assertEqual(payload['professional'][0]['related_service']['id'], service.id)


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class FaceAnalysisHistoryTests(TestCase):
    """GET /api/v3/face/history/ — auth-gated, own-scoped (admin role sees all)."""

    def setUp(self):
        cache.clear()
        self.employee = make_employee()
        self.other_employee = make_employee(username='emp_other')

    def tearDown(self):
        cache.clear()

    @staticmethod
    def create_analysis(user=None):
        return FaceAnalysis.objects.create(
            user=user,
            image=make_image_file(),
            overall_score=7.0,
            symmetry_score=7.5,
            skin_clarity_score=6.5,
            youthfulness_score=8.0,
            harmony_score=7.2,
            detected_attributes={
                'face_shape': 'oval',
                'skin_tone': 'medium',
                'skin_undertone': 'neutral',
                'eye_shape': 'almond',
                'lip_fullness': 'medium',
                'concerns': [],
            },
            suggestions=[{'category': 'skincare', 'title': 'Routine', 'detail': 'Keep it consistent.'}],
            raw_model_output={'method': 'test'},
            provider='local',
            model_version='test-v1',
        )

    def test_history_requires_auth(self):
        client = APIClient()
        self.assertEqual(client.get(HISTORY_URL).status_code, status.HTTP_401_UNAUTHORIZED)
        analysis = self.create_analysis(self.employee)
        detail_url = f'{HISTORY_URL}{analysis.pk}/'
        self.assertEqual(client.get(detail_url).status_code, status.HTTP_401_UNAUTHORIZED)

    def test_history_scoped_to_user(self):
        mine = self.create_analysis(self.employee)
        self.create_analysis(self.other_employee)

        client = employee_client()
        response = client.get(HISTORY_URL)

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data['count'], 1)
        self.assertEqual(response.data['results'][0]['id'], mine.pk)
        entry = response.data['results'][0]
        self.assertRegex(str(entry['created_at']), SHAMSI_PATTERN)
        self.assertIn('skin_plan', entry)  # light history shape: summary only when a plan exists

        admin_response = admin_client().get(HISTORY_URL)
        self.assertEqual(admin_response.status_code, status.HTTP_200_OK, admin_response.data)
        self.assertEqual(admin_response.data['count'], 2)

    def test_detail_scoped_to_owner_and_admin(self):
        own = self.create_analysis(self.employee)
        other = self.create_analysis(self.other_employee)

        client = employee_client()
        self.assertEqual(client.get(f'{HISTORY_URL}{own.pk}/').status_code, status.HTTP_200_OK)
        self.assertEqual(client.get(f'{HISTORY_URL}{other.pk}/').status_code, status.HTTP_404_NOT_FOUND)

        admin = admin_client()
        self.assertEqual(admin.get(f'{HISTORY_URL}{other.pk}/').status_code, status.HTTP_200_OK)

    @override_settings(FACE_ANALYZER_ENABLE_HISTORY=False)
    def test_history_disabled_returns_404_but_analyze_still_works(self):
        client = employee_client()
        self.create_analysis(self.employee)

        self.assertEqual(client.get(HISTORY_URL).status_code, status.HTTP_404_NOT_FOUND)

        with patched_get_backend():
            response = APIClient().post(ANALYZE_URL, {'image': make_image_file()}, format='multipart')
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)


class FaceAnalyzerDocsTests(TestCase):
    """/api/v3/schema/ and /api/v3/docs/ follow the v2 docs pattern."""

    @staticmethod
    def docs_client():
        if getattr(settings, 'DOCS_PUBLIC', False):
            return APIClient()
        return admin_client()

    def test_v3_schema_exposes_face_endpoints(self):
        response = self.docs_client().get('/api/v3/schema/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        content = response.content.decode()
        self.assertIn('/api/v3/face/analyze/', content)
        self.assertIn('/api/v3/face/history/', content)
        self.assertIn('/api/v3/face/{id}/tips/', content)
        self.assertIn('Face Analyzer', content)
        self.assertIn('multipart/form-data', content)

    def test_v3_schema_documents_scores_and_shamsi_example(self):
        content = self.docs_client().get('/api/v3/schema/').content.decode()
        self.assertIn('minimum', content)
        self.assertIn('1404-07-01 14:30', content)

    def test_v3_swagger_ui_renders(self):
        response = self.docs_client().get('/api/v3/docs/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('text/html', response['Content-Type'])
