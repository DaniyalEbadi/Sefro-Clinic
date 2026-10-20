from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models

from Sefro_Clinic.validators import TEXT_SANITIZERS


class SiteService(models.Model):
    class Category(models.TextChoices):
        FACE = 'face', 'صورت'
        SKIN = 'skin', 'پوست'
        HAIR = 'hair', 'مو'
        BODY = 'body', 'بدن'

    name = models.CharField(max_length=100, validators=TEXT_SANITIZERS)
    slug = models.SlugField(max_length=100, unique=True)
    category = models.CharField(max_length=20, choices=Category.choices)
    source_category = models.CharField(max_length=80, blank=True, validators=TEXT_SANITIZERS)
    short_description = models.CharField(max_length=255, blank=True, validators=TEXT_SANITIZERS)
    description = models.TextField(blank=True, validators=TEXT_SANITIZERS)
    price = models.DecimalField(
        max_digits=12, decimal_places=2,
        validators=[MinValueValidator(0)],
    )
    is_from_price = models.BooleanField(default=False)
    source_url = models.URLField(blank=True)
    price_usd = models.DecimalField(
        max_digits=24, decimal_places=12, default=Decimal('0.00'),
        validators=[MinValueValidator(0)],
        help_text='Editable USD base price. The public Toman price is derived from this value.',
    )
    duration_label = models.CharField(max_length=40, blank=True, validators=TEXT_SANITIZERS)
    image_url = models.URLField(blank=True)
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['sort_order', 'name']

    def __str__(self):
        return self.name


class SitePackage(models.Model):
    class Tier(models.TextChoices):
        BASE = 'base', 'پایه'
        STANDARD = 'standard', 'استاندارد'
        SPECIAL = 'special', 'ویژه'

    name = models.CharField(max_length=120, unique=True, validators=TEXT_SANITIZERS)
    slug = models.SlugField(max_length=120, unique=True)
    tier = models.CharField(max_length=20, choices=Tier.choices, default=Tier.BASE)
    tagline = models.CharField(max_length=180, blank=True, validators=TEXT_SANITIZERS)
    badge = models.CharField(max_length=30, blank=True, validators=TEXT_SANITIZERS)
    price = models.DecimalField(max_digits=14, decimal_places=2, validators=[MinValueValidator(0)])
    price_usd = models.DecimalField(
        max_digits=24, decimal_places=12, default=Decimal('0.00'),
        validators=[MinValueValidator(0)],
        help_text='Editable USD base price. The public Toman price is derived from this value.',
    )
    original_price = models.DecimalField(
        max_digits=14, decimal_places=2, null=True, blank=True,
        validators=[MinValueValidator(0)],
    )
    original_price_usd = models.DecimalField(
        max_digits=24, decimal_places=12, null=True, blank=True,
        validators=[MinValueValidator(0)],
        help_text='Editable USD list price used to derive original_price.',
    )
    free_service_count = models.PositiveSmallIntegerField(default=0)
    services = models.ManyToManyField(SiteService, related_name='packages')
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)
    source_url = models.URLField(blank=True)

    class Meta:
        ordering = ['sort_order', 'price']

    def __str__(self):
        return self.name

    @property
    def discount_percent(self):
        if self.original_price is None:
            return 0
        price = Decimal(self.price)
        original = Decimal(self.original_price)
        if original > price:
            saved = (original - price) / original * 100
            return round(float(saved))
        return 0


class SiteProduct(models.Model):
    name = models.CharField(max_length=120, unique=True, validators=TEXT_SANITIZERS)
    slug = models.SlugField(max_length=120, unique=True)
    short_description = models.CharField(max_length=255, blank=True, validators=TEXT_SANITIZERS)
    price = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(0)])
    price_usd = models.DecimalField(
        max_digits=24, decimal_places=12, default=Decimal('0.00'),
        validators=[MinValueValidator(0)],
        help_text='Editable USD base price. The public Toman price is derived from this value.',
    )
    image_url = models.URLField(blank=True)
    source_url = models.URLField(blank=True)
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['sort_order', 'name']

    def __str__(self):
        return self.name


class TeamMember(models.Model):
    name = models.CharField(max_length=120, validators=TEXT_SANITIZERS)
    role = models.CharField(max_length=120, blank=True, validators=TEXT_SANITIZERS)
    bio = models.TextField(blank=True, validators=TEXT_SANITIZERS)
    image_url = models.URLField(blank=True)
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['sort_order', 'id']

    def __str__(self):
        return self.name


class Testimonial(models.Model):
    customer_name = models.CharField(max_length=120, validators=TEXT_SANITIZERS)
    label = models.CharField(max_length=60, blank=True, validators=TEXT_SANITIZERS)
    text = models.TextField(validators=TEXT_SANITIZERS)
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['sort_order', 'id']

    def __str__(self):
        return f'{self.customer_name}: {self.text[:40]}'


class SitePackagePriceOption(models.Model):
    package = models.ForeignKey(SitePackage, on_delete=models.CASCADE, related_name='price_options')
    label = models.CharField(max_length=180, validators=TEXT_SANITIZERS)
    session_count = models.PositiveSmallIntegerField(null=True, blank=True)
    gift_session_count = models.PositiveSmallIntegerField(default=0)
    price = models.DecimalField(max_digits=14, decimal_places=2, validators=[MinValueValidator(0)])
    price_usd = models.DecimalField(
        max_digits=24, decimal_places=12, default=Decimal('0.00'),
        validators=[MinValueValidator(0)],
    )
    source_url = models.URLField(blank=True)
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['sort_order', 'id']
        constraints = [
            models.UniqueConstraint(fields=['package', 'label'], name='unique_site_package_price_option'),
        ]

    def __str__(self):
        return f'{self.package.name}: {self.label}'


class SiteSettings(models.Model):
    singleton_key = models.CharField(max_length=20, unique=True, default='default', editable=False)
    address = models.TextField(blank=True, validators=TEXT_SANITIZERS)
    phone_numbers = models.JSONField(default=list, blank=True)
    working_hours = models.CharField(max_length=180, blank=True, validators=TEXT_SANITIZERS)
    about_title = models.CharField(max_length=180, blank=True, validators=TEXT_SANITIZERS)
    about_text = models.TextField(blank=True, validators=TEXT_SANITIZERS)
    statistics = models.JSONField(default=dict, blank=True)
    hero_image_url = models.URLField(blank=True)
    about_image_url = models.URLField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return 'Website settings'


class ContactMessage(models.Model):
    full_name = models.CharField(max_length=120, validators=TEXT_SANITIZERS)
    phone = models.CharField(max_length=15)
    message = models.TextField(blank=True, validators=TEXT_SANITIZERS)
    created_at = models.DateTimeField(auto_now_add=True)
    is_handled = models.BooleanField(default=False)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.full_name} ({self.phone})'


class WebsitePriceSyncRun(models.Model):
    class Status(models.TextChoices):
        RUNNING = 'running', 'Running'
        SUCCEEDED = 'succeeded', 'Succeeded'
        FAILED = 'failed', 'Failed'

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.RUNNING)
    provider = models.CharField(max_length=40, blank=True)
    rate = models.DecimalField(max_digits=18, decimal_places=6, null=True, blank=True)
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    updated_services = models.PositiveIntegerField(default=0)
    updated_packages = models.PositiveIntegerField(default=0)
    updated_products = models.PositiveIntegerField(default=0)
    error = models.TextField(blank=True)

    class Meta:
        ordering = ['-started_at']

    def __str__(self):
        return f'Website price sync {self.started_at:%Y-%m-%d %H:%M:%S} ({self.status})'
