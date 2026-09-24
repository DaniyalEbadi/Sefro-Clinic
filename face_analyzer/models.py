from decimal import Decimal

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from Sefro_Clinic.validators import TEXT_SANITIZERS


class FaceAnalysis(models.Model):
    """Immutable record of one face analysis run."""

    class Provider(models.TextChoices):
        LOCAL = 'local', 'Local (MediaPipe)'
        EXTERNAL = 'external', 'External API'

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='face_analyses',
    )
    image = models.ImageField(upload_to='face_analyses/%Y/%m/')

    # Scores (0-10, float)
    overall_score = models.FloatField(
        validators=[MinValueValidator(Decimal('0')), MaxValueValidator(Decimal('10'))]
    )
    symmetry_score = models.FloatField(
        validators=[MinValueValidator(Decimal('0')), MaxValueValidator(Decimal('10'))]
    )
    skin_clarity_score = models.FloatField(
        validators=[MinValueValidator(Decimal('0')), MaxValueValidator(Decimal('10'))]
    )
    youthfulness_score = models.FloatField(
        validators=[MinValueValidator(Decimal('0')), MaxValueValidator(Decimal('10'))]
    )
    harmony_score = models.FloatField(
        validators=[MinValueValidator(Decimal('0')), MaxValueValidator(Decimal('10'))]
    )

    # Structured JSON output
    detected_attributes = models.JSONField(
        default=dict,
        help_text='Face shape, skin tone, undertone, eye shape, lip fullness, etc.',
    )
    suggestions = models.JSONField(
        default=list,
        help_text='List of {category, title, detail} objects.',
    )
    raw_model_output = models.JSONField(
        default=dict,
        help_text='Full provider payload for debugging.',
    )
    provider = models.CharField(max_length=32, choices=Provider.choices)
    model_version = models.CharField(max_length=64, blank=True, validators=TEXT_SANITIZERS)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', '-created_at']),
            models.Index(fields=['created_at']),
        ]

    def __str__(self):
        return f'FaceAnalysis #{self.pk} \u2014 {self.overall_score:.1f}'


class SkinCarePlan(models.Model):
    """Personalized skin-care plan generated for one face analysis."""

    class SkinType(models.TextChoices):
        OILY = 'oily', 'Oily'
        DRY = 'dry', 'Dry'
        COMBINATION = 'combination', 'Combination'
        NORMAL = 'normal', 'Normal'

    class Provider(models.TextChoices):
        RULE_BASED = 'rule_based', 'Rule based'
        LLM = 'llm', 'LLM'

    analysis = models.OneToOneField(
        FaceAnalysis,
        related_name='skin_plan',
        on_delete=models.CASCADE,
    )
    summary = models.TextField(validators=TEXT_SANITIZERS)
    skin_type = models.CharField(max_length=20, choices=SkinType.choices)
    primary_concerns = models.JSONField(
        default=list,
        help_text='Top concerns in priority order, e.g. ["acne", "dullness"].',
    )
    recommended_frequency = models.CharField(max_length=120, validators=TEXT_SANITIZERS)
    provider = models.CharField(max_length=20, choices=Provider.choices)
    model_used = models.CharField(max_length=64)
    # auto_now so regeneration visibly refreshes the timestamp (tips endpoint contract).
    created_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'SkinCarePlan for analysis #{self.analysis_id} ({self.skin_type})'


class SkinCareTip(models.Model):
    """One actionable tip belonging to a skin-care plan."""

    class Period(models.TextChoices):
        MORNING = 'morning', 'Morning'
        EVENING = 'evening', 'Evening'
        WEEKLY = 'weekly', 'Weekly'
        LIFESTYLE = 'lifestyle', 'Lifestyle'
        PROFESSIONAL = 'professional', 'Professional'

    class Priority(models.TextChoices):
        LOW = 'low', 'Low'
        MEDIUM = 'medium', 'Medium'
        HIGH = 'high', 'High'

    class Category(models.TextChoices):
        CLEANSER = 'cleanser', 'Cleanser'
        TONER = 'toner', 'Toner'
        SERUM = 'serum', 'Serum'
        MOISTURIZER = 'moisturizer', 'Moisturizer'
        SUNSCREEN = 'sunscreen', 'Sunscreen'
        EXFOLIANT = 'exfoliant', 'Exfoliant'
        MASK = 'mask', 'Mask'
        EYE_CARE = 'eye_care', 'Eye care'
        TREATMENT = 'treatment', 'Treatment'
        LIFESTYLE = 'lifestyle', 'Lifestyle'
        DIET = 'diet', 'Diet'
        IN_CLINIC = 'in_clinic', 'In-clinic'

    analysis = models.ForeignKey(
        FaceAnalysis,
        related_name='skin_tips',
        on_delete=models.CASCADE,
    )
    plan = models.ForeignKey(
        SkinCarePlan,
        related_name='tips',
        on_delete=models.CASCADE,
    )
    period = models.CharField(max_length=20, choices=Period.choices)
    sort_order = models.PositiveIntegerField(default=0)
    title = models.CharField(max_length=200, validators=TEXT_SANITIZERS)
    description = models.TextField(validators=TEXT_SANITIZERS)
    priority = models.CharField(max_length=10, choices=Priority.choices)
    category = models.CharField(max_length=20, choices=Category.choices)
    key_ingredients = models.JSONField(default=list)
    avoid_ingredients = models.JSONField(default=list)
    related_service_slug = models.CharField(max_length=100, blank=True, default='')
    related_service = models.ForeignKey(
        'customers.Service',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='skin_tips',
    )

    class Meta:
        ordering = ['sort_order', 'id']

    def __str__(self):
        return f'{self.period}: {self.title}'
