from django.conf import settings
from PIL import Image
from rest_framework import serializers

from customers.models import Service
from Sefro_Clinic.fields import ShamsiDateTimeField
from Sefro_Clinic.validators import TEXT_SANITIZERS

from .models import FaceAnalysis, SkinCarePlan, SkinCareTip

ALLOWED_MIME_TYPES = ('image/jpeg', 'image/png', 'image/webp')


def sniff_image_format(head: bytes) -> str | None:
    """Identify the real image format from magic bytes (never trust content_type alone)."""
    if head[:3] == b'\xff\xd8\xff':
        return 'image/jpeg'
    if head[:8] == b'\x89PNG\r\n\x1a\n':
        return 'image/png'
    if head[:4] == b'RIFF' and head[8:12] == b'WEBP':
        return 'image/webp'
    return None


class FaceAttributesSerializer(serializers.Serializer):
    """Serializer for detected facial attributes."""

    face_shape = serializers.CharField(
        allow_blank=True, required=False, help_text='oval | round | square | heart | oblong | diamond'
    )
    skin_tone = serializers.CharField(allow_blank=True, required=False, help_text='fair | light | medium | tan | deep')
    skin_undertone = serializers.CharField(allow_blank=True, required=False, help_text='warm | cool | neutral')
    eye_shape = serializers.CharField(allow_blank=True, required=False, help_text='almond | round | hooded')
    lip_fullness = serializers.CharField(allow_blank=True, required=False, help_text='thin | medium | full')
    concerns = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        help_text='Detected skin concerns ordered by severity.',
    )

    def to_representation(self, instance):
        ret = super().to_representation(instance)
        if isinstance(instance, dict):
            for key, value in instance.items():
                if key not in ret:
                    ret[key] = value
        return ret


class SuggestionSerializer(serializers.Serializer):
    """Serializer for beauty suggestions."""

    category = serializers.CharField(validators=TEXT_SANITIZERS)
    title = serializers.CharField(validators=TEXT_SANITIZERS)
    detail = serializers.CharField(validators=TEXT_SANITIZERS)


class FaceAnalysisRequestSerializer(serializers.Serializer):
    """Validates the uploaded face image: size cap, MIME type, magic bytes, Pillow verify."""

    image = serializers.FileField(help_text='Face photo as multipart file (JPEG, PNG or WebP).')

    def validate_image(self, value):
        max_mb = int(getattr(settings, 'FACE_ANALYZER_MAX_IMAGE_MB', 5))
        if value.size > max_mb * 1024 * 1024:
            raise serializers.ValidationError(f'حجم تصویر بیش از حد مجاز است. حداکثر {max_mb} مگابایت.')

        content_type = (getattr(value, 'content_type', '') or '').lower()
        if content_type not in ALLOWED_MIME_TYPES:
            raise serializers.ValidationError(
                'قالب تصویر پشتیبانی نمی‌شود. فرمت‌های مجاز: JPEG، PNG و WebP.'
            )

        head = value.read(16)
        value.seek(0)
        sniffed = sniff_image_format(head)
        if sniffed not in ALLOWED_MIME_TYPES:
            raise serializers.ValidationError('فایل ارسال‌شده یک تصویر معتبر نیست.')

        try:
            image = Image.open(value)
            image.verify()
        except Exception as exc:
            raise serializers.ValidationError('فایل تصویر معتبر نیست.') from exc
        value.seek(0)
        return value


class RelatedServiceSerializer(serializers.ModelSerializer):
    """Compact service reference nested inside tips."""

    class Meta:
        model = Service
        fields = ['id', 'name', 'price_usd']


class SkinCareTipSerializer(serializers.ModelSerializer):
    """One skin-care tip with its optional resolved clinic service."""

    related_service = RelatedServiceSerializer(read_only=True)

    class Meta:
        model = SkinCareTip
        fields = [
            'id',
            'period',
            'sort_order',
            'title',
            'description',
            'priority',
            'category',
            'key_ingredients',
            'avoid_ingredients',
            'related_service_slug',
            'related_service',
        ]
        read_only_fields = fields


class SkinCarePlanSerializer(serializers.ModelSerializer):
    """Skin-care plan with tips grouped into the five periods."""

    morning = serializers.SerializerMethodField()
    evening = serializers.SerializerMethodField()
    weekly = serializers.SerializerMethodField()
    lifestyle = serializers.SerializerMethodField()
    professional = serializers.SerializerMethodField()

    class Meta:
        model = SkinCarePlan
        fields = [
            'summary',
            'skin_type',
            'primary_concerns',
            'recommended_frequency',
            'provider',
            'model_used',
            'morning',
            'evening',
            'weekly',
            'lifestyle',
            'professional',
        ]

    @staticmethod
    def _period_tips(obj, period: str):
        tips = [tip for tip in obj.analysis.skin_tips.all() if tip.period == period]
        tips.sort(key=lambda tip: (tip.sort_order, tip.id))
        return SkinCareTipSerializer(tips, many=True).data

    def get_morning(self, obj):
        return self._period_tips(obj, 'morning')

    def get_evening(self, obj):
        return self._period_tips(obj, 'evening')

    def get_weekly(self, obj):
        return self._period_tips(obj, 'weekly')

    def get_lifestyle(self, obj):
        return self._period_tips(obj, 'lifestyle')

    def get_professional(self, obj):
        return self._period_tips(obj, 'professional')


class FaceAnalysisResponseSerializer(serializers.ModelSerializer):
    """Full face analysis response including the nested skin-care plan."""

    overall_score = serializers.FloatField(
        min_value=0, max_value=10, read_only=True, help_text='Overall aesthetic score (0-10).'
    )
    symmetry_score = serializers.FloatField(
        min_value=0, max_value=10, read_only=True, help_text='Facial symmetry score (0-10).'
    )
    skin_clarity_score = serializers.FloatField(
        min_value=0, max_value=10, read_only=True, help_text='Skin clarity score (0-10).'
    )
    youthfulness_score = serializers.FloatField(
        min_value=0, max_value=10, read_only=True, help_text='Youthfulness score (0-10).'
    )
    harmony_score = serializers.FloatField(
        min_value=0, max_value=10, read_only=True, help_text='Feature harmony score (0-10).'
    )
    detected_attributes = FaceAttributesSerializer(read_only=True)
    suggestions = SuggestionSerializer(many=True, read_only=True)
    skin_plan = serializers.SerializerMethodField()
    created_at = ShamsiDateTimeField(read_only=True, help_text='Shamsi timestamp, YYYY-MM-DD HH:MM.')

    class Meta:
        model = FaceAnalysis
        fields = [
            'id',
            'overall_score',
            'symmetry_score',
            'skin_clarity_score',
            'youthfulness_score',
            'harmony_score',
            'detected_attributes',
            'suggestions',
            'skin_plan',
            'created_at',
            'provider',
            'model_version',
        ]
        read_only_fields = fields

    def get_skin_plan(self, obj):
        plan = getattr(obj, 'skin_plan', None)
        if plan is None:
            return None
        return SkinCarePlanSerializer(plan, context=self.context).data


class FaceAnalysisHistorySerializer(serializers.ModelSerializer):
    """Lightweight history entry: scores + plan summary only (no tips)."""

    skin_plan = serializers.SerializerMethodField()
    created_at = ShamsiDateTimeField(read_only=True, help_text='Shamsi timestamp, YYYY-MM-DD HH:MM.')

    class Meta:
        model = FaceAnalysis
        fields = [
            'id',
            'overall_score',
            'symmetry_score',
            'skin_clarity_score',
            'youthfulness_score',
            'harmony_score',
            'created_at',
            'skin_plan',
        ]
        read_only_fields = fields

    def get_skin_plan(self, obj):
        plan = getattr(obj, 'skin_plan', None)
        if plan is None:
            return None
        return {'summary': plan.summary, 'skin_type': plan.skin_type}
