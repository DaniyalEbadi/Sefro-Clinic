from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models

from Sefro_Clinic.validators import TEXT_SANITIZERS


class ServiceCategory(models.Model):
    name = models.CharField(max_length=80, unique=True, validators=TEXT_SANITIZERS)
    slug = models.SlugField(max_length=80, unique=True)
    description = models.TextField(blank=True, validators=TEXT_SANITIZERS)
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['sort_order', 'name']
        indexes = [
            models.Index(fields=['sort_order', 'name'], name='svc_cat_sort_idx'),
        ]

    def __str__(self):
        return self.name


class Service(models.Model):
    name = models.CharField(max_length=100, unique=True, validators=TEXT_SANITIZERS)
    description = models.TextField(blank=True, validators=TEXT_SANITIZERS)
    price = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal('0'))], default=Decimal('0'))
    price_usd = models.DecimalField(
        max_digits=14, decimal_places=2,
        validators=[MinValueValidator(Decimal('0'))], default=Decimal('0'),
        help_text='USD base price. Authoritative for the financial system; "price" is the legacy display value.',
    )
    time = models.PositiveIntegerField(default=0, help_text='Duration in minutes')
    is_active = models.BooleanField(default=True)
    category = models.ForeignKey(
        ServiceCategory,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='services',
    )

    class Meta:
        ordering = ['name']
        indexes = [
            models.Index(fields=['category', 'is_active'], name='svc_category_active_idx', condition=models.Q(is_active=True)),
            models.Index(fields=['name'], name='svc_name_idx'),
        ]

    def __str__(self):
        return self.name


class Customer(models.Model):
    first_name = models.CharField(max_length=100, validators=TEXT_SANITIZERS)
    last_name = models.CharField(max_length=100, validators=TEXT_SANITIZERS)
    mobile_number = models.CharField(max_length=20, unique=True, validators=TEXT_SANITIZERS)
    national_id = models.CharField(max_length=20, unique=True, validators=TEXT_SANITIZERS)
    bitmoji_code = models.CharField(max_length=50, unique=True, null=True, blank=True, validators=TEXT_SANITIZERS)
    birthday = models.DateField(null=True, blank=True, help_text='Customer birthday (Shamsi YYYY-MM-DD via API)')
    created_at = models.DateTimeField(auto_now_add=True)
    satisfaction = models.PositiveSmallIntegerField(null=True, blank=True, help_text='Customer satisfaction rating 1-5')
    notes = models.TextField(blank=True, validators=TEXT_SANITIZERS)

    class Meta:
        ordering = ['first_name', 'last_name']

    def __str__(self):
        return f'{self.first_name} {self.last_name}'

    @property
    def full_name(self):
        return str(self)

    @property
    def visit_count(self):
        return self.visits.count()

    @property
    def is_new_customer(self):
        return self.visit_count == 0

    @property
    def is_loyal_customer(self):
        return self.visit_count >= 5

    @property
    def total_payments(self):
        total = self.payments.aggregate(total=models.Sum('amount'))['total']
        return total or Decimal('0')

    @property
    def last_visit_date(self):
        last = self.visits.order_by('-start_at').first()
        if not last:
            return None
        from Sefro_Clinic.fields import greg_to_shamsi_date
        return greg_to_shamsi_date(last.start_at)


class Visit(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        CONFIRMED = 'confirmed', 'Confirmed'
        COMPLETED = 'completed', 'Completed'
        CANCELED = 'canceled', 'Canceled'

    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name='visits')
    staff = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name='visits',
        null=True,
        blank=True,
    )
    services = models.ManyToManyField(Service, related_name='visits')
    start_at = models.DateTimeField()
    end_at = models.DateTimeField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    notes = models.TextField(blank=True, validators=TEXT_SANITIZERS)

    class Meta:
        ordering = ['-start_at']
        indexes = [
            models.Index(fields=['start_at'], name='visits_start_at_idx'),
            models.Index(fields=['customer', 'start_at', 'end_at'], name='visit_overlap_idx'),
        ]

    def __str__(self):
        return f'{self.customer} - {self.start_at:%Y-%m-%d %H:%M}'


class Payment(models.Model):
    class Method(models.TextChoices):
        CASH = 'cash', 'Cash'
        CARD = 'card', 'Card'
        TRANSFER = 'transfer', 'Transfer'
        WALLET = 'wallet', 'Wallet'
        MIXED = 'mixed', 'Mixed'

    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name='payments')
    visit = models.ForeignKey(Visit, on_delete=models.SET_NULL, related_name='payments', null=True, blank=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal('0'))])
    amount_usd = models.DecimalField(
        max_digits=14, decimal_places=2, null=True, blank=True,
        validators=[MinValueValidator(Decimal('0'))],
        help_text='USD snapshot of the paid amount, when recorded through the financial system.',
    )
    exchange_rate = models.DecimalField(
        max_digits=18, decimal_places=6, null=True, blank=True,
        validators=[MinValueValidator(Decimal('0'))],
        help_text='Toman-per-USD exchange rate snapshot at payment time.',
    )
    payment_method = models.CharField(max_length=20, choices=Method.choices, default=Method.CARD)
    paid_at = models.DateTimeField()
    notes = models.TextField(blank=True, validators=TEXT_SANITIZERS)

    class Meta:
        ordering = ['-paid_at']
        indexes = [
            models.Index(fields=['paid_at'], name='payments_paid_at_idx'),
            models.Index(fields=['paid_at', 'customer'], name='payments_paid_at_customer_idx'),
        ]

    def __str__(self):
        return f'{self.customer} - {self.amount}'
