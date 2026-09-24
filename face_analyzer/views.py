from django.conf import settings
from django.db import transaction
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiExample, extend_schema
from rest_framework import generics, status
from rest_framework.exceptions import NotFound
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from .exceptions import FaceAnalyzerError
from .models import FaceAnalysis
from .serializers import (
    FaceAnalysisHistorySerializer,
    FaceAnalysisRequestSerializer,
    FaceAnalysisResponseSerializer,
    SkinCarePlanSerializer,
)
from .services import generate_and_store_plan, get_backend


class FaceAnalyzerThrottle(ScopedRateThrottle):
    """Scoped throttle reading FACE_ANALYZER_THROTTLE_RATE live so tests can override_settings it."""

    def get_rate(self):
        rate = getattr(settings, 'FACE_ANALYZER_THROTTLE_RATE', None)
        if rate:
            return rate
        return super().get_rate()


ANALYZE_EXAMPLES = [
    OpenApiExample(
        'Successful analysis',
        value={
            'id': 42,
            'overall_score': 7.8,
            'symmetry_score': 8.2,
            'skin_clarity_score': 7.5,
            'youthfulness_score': 8.0,
            'harmony_score': 7.6,
            'detected_attributes': {
                'face_shape': 'oval',
                'skin_tone': 'medium',
                'skin_undertone': 'warm',
                'eye_shape': 'almond',
                'lip_fullness': 'medium',
                'concerns': ['hyperpigmentation', 'dullness', 'acne'],
            },
            'suggestions': [
                {
                    'category': 'skincare',
                    'title': 'Skincare routine',
                    'detail': 'Even proportions respond well to basics: daily sunscreen and a gentle cleanser. '
                              'Use a vitamin C serum each morning and a retinoid at night to fade dark spots evenly.',
                },
                {
                    'category': 'makeup',
                    'title': 'Cheekbone-focused makeup',
                    'detail': 'Soft contour along the cheekbones keeps your balanced proportions defined without '
                              'heaviness. Choose warm-undertone products to match your coloring.',
                },
                {
                    'category': 'hairstyle',
                    'title': 'Soft layered cut',
                    'detail': 'Layers starting at the jawline will complement your oval face shape.',
                },
            ],
            'skin_plan': {
                'summary': 'Your combination skin shows hyperpigmentation, dullness, acne. '
                           'Overall aesthetic score 7.8/10 (good).',
                'skin_type': 'combination',
                'primary_concerns': ['hyperpigmentation', 'dullness', 'acne'],
                'recommended_frequency': 'SPF daily, actives 3x weekly',
                'provider': 'rule_based',
                'model_used': 'sefro-rules-v1',
                'morning': [
                    {
                        'period': 'morning',
                        'sort_order': 1,
                        'title': 'Gentle morning cleanser',
                        'description': 'Wash with a mild sulfate-free cleanser to start the day without stripping the skin.',
                        'priority': 'high',
                        'category': 'cleanser',
                        'key_ingredients': ['glycerin'],
                        'avoid_ingredients': ['sulfates'],
                        'related_service_slug': '',
                        'related_service': None,
                    },
                ],
                'evening': [],
                'weekly': [],
                'lifestyle': [],
                'professional': [],
            },
            'created_at': '1404-07-01 14:30',
            'provider': 'local',
            'model_version': 'mediapipe-0.10.14+sefro-local-v1',
        },
        status_codes=[200],
    ),
    OpenApiExample(
        'Invalid or missing image',
        value={'image': ['فایل ارسال‌شده یک تصویر معتبر نیست.']},
        status_codes=[400],
    ),
    OpenApiExample(
        'Image too large',
        value={'image': ['حجم تصویر بیش از حد مجاز است. حداکثر 5 مگابایت.']},
        status_codes=[400],
    ),
    OpenApiExample(
        'No face detected',
        value={'detail': 'No face detected'},
        status_codes=[400],
    ),
    OpenApiExample(
        'Analysis failed',
        value={'detail': 'تحلیل چهره ناموفق بود. لطفاً تصویر واضحتری ارسال کنید.'},
        status_codes=[400],
    ),
    OpenApiExample(
        'Throttled',
        value={'detail': 'Request was throttled.'},
        status_codes=[429],
    ),
]


def _can_view_all(user) -> bool:
    """Admin-role users see every analysis; other staff see only their own."""
    return getattr(user, 'role', None) == 'admin'


class OwnedHistoryQuerysetMixin:
    """Scope querysets to the requesting user unless the user has the admin role."""

    def get_queryset(self):
        if not getattr(settings, 'FACE_ANALYZER_ENABLE_HISTORY', True):
            raise NotFound('Face analysis history is disabled.')
        queryset = FaceAnalysis.objects.select_related('skin_plan').prefetch_related('skin_tips')
        user = self.request.user
        if not getattr(user, 'is_authenticated', False):
            # Unauthenticated access is blocked by IsAuthenticated; queryset is
            # also consumed during OpenAPI schema generation.
            return queryset.none()
        if not _can_view_all(user):
            queryset = queryset.filter(user=user)
        return queryset


class FaceAnalyzeView(APIView):
    """Public, throttled face analysis. Staff callers get their analysis linked."""

    permission_classes = [AllowAny]
    throttle_classes = [FaceAnalyzerThrottle]
    throttle_scope = 'face_analyzer'
    parser_classes = [MultiPartParser, FormParser]

    @extend_schema(
        tags=['Face Analyzer'],
        summary='Analyze a face image',
        request={
            'multipart/form-data': {
                'type': 'object',
                'properties': {'image': {'type': 'string', 'format': 'binary'}},
                'required': ['image'],
            },
        },
        responses={
            200: FaceAnalysisResponseSerializer,
            400: {'type': 'object', 'properties': {'detail': {'type': 'string'}}},
            429: {'type': 'object', 'properties': {'detail': {'type': 'string'}}},
        },
        examples=ANALYZE_EXAMPLES,
    )
    @transaction.atomic
    def post(self, request):
        serializer = FaceAnalysisRequestSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        image = serializer.validated_data['image']
        image.seek(0)
        image_bytes = image.read()

        try:
            backend = get_backend()
            result = backend.analyze(image_bytes)
        except FaceAnalyzerError as exc:
            return Response({'detail': str(exc.detail)}, status=status.HTTP_400_BAD_REQUEST)

        user = request.user if getattr(request.user, 'is_authenticated', False) else None
        analysis = FaceAnalysis.objects.create(
            user=user,
            image=image,
            overall_score=result.overall_score,
            symmetry_score=result.symmetry_score,
            skin_clarity_score=result.skin_clarity_score,
            youthfulness_score=result.youthfulness_score,
            harmony_score=result.harmony_score,
            detected_attributes=result.detected_attributes,
            suggestions=result.suggestions,
            raw_model_output=result.raw_output,
            provider=backend.provider,
            model_version=result.model_version,
        )
        plan = generate_and_store_plan(analysis)
        analysis.skin_plan = plan  # cache reverse one-to-one for the response
        return Response(FaceAnalysisResponseSerializer(analysis, context={'request': request}).data)


class FaceAnalysisTipsView(APIView):
    """Public, throttled regeneration of the skin-care plan for an existing analysis."""

    permission_classes = [AllowAny]
    throttle_classes = [FaceAnalyzerThrottle]
    throttle_scope = 'face_analyzer'

    @extend_schema(
        tags=['Face Analyzer'],
        summary='Regenerate skin-care tips for an analysis',
        responses={
            200: SkinCarePlanSerializer,
            404: {'type': 'object', 'properties': {'detail': {'type': 'string'}}},
            429: {'type': 'object', 'properties': {'detail': {'type': 'string'}}},
        },
    )
    def post(self, request, pk):
        analysis = get_object_or_404(FaceAnalysis, pk=pk)
        plan = generate_and_store_plan(analysis)
        return Response(SkinCarePlanSerializer(plan, context={'request': request}).data)


class FaceAnalysisHistoryView(OwnedHistoryQuerysetMixin, generics.ListAPIView):
    """Authenticated staff history, scoped to the caller (admin role sees all)."""

    permission_classes = [IsAuthenticated]
    serializer_class = FaceAnalysisHistorySerializer

    @extend_schema(tags=['Face Analyzer'], summary='List own face analyses')
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)


class FaceAnalysisDetailView(OwnedHistoryQuerysetMixin, generics.RetrieveAPIView):
    """Retrieve a single analysis: own records only, admins may view any."""

    permission_classes = [IsAuthenticated]
    serializer_class = FaceAnalysisResponseSerializer

    @extend_schema(tags=['Face Analyzer'], summary='Retrieve one face analysis')
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)
