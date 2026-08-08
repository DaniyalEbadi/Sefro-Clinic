from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models


class Service(models.Model):
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    price = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal('0'))], default=Decimal('0'))
    time = models.PositiveIntegerField(default=0, help_text='Duration in minutes')
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class Customer(models.Model):
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    mobile_number = models.CharField(max_length=20, unique=True)
    national_id = models.CharField(max_length=20, unique=True)
    bitmoji_code = models.CharField(max_length=50, unique=True, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    satisfaction = models.PositiveSmallIntegerField(null=True, blank=True, help_text='Customer satisfaction rating 1-5')
    notes = models.TextField(blank=True)

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
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['-start_at']

    def __str__(self):
        return f'{self.customer} - {self.start_at:%Y-%m-%d %H:%M}'


class Payment(models.Model):
    class Method(models.TextChoices):
        CASH = 'cash', 'Cash'
        CARD = 'card', 'Card'
        TRANSFER = 'transfer', 'Transfer'

    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name='payments')
    visit = models.ForeignKey(Visit, on_delete=models.SET_NULL, related_name='payments', null=True, blank=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal('0'))])
    payment_method = models.CharField(max_length=20, choices=Method.choices, default=Method.CARD)
    paid_at = models.DateTimeField()
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['-paid_at']

    def __str__(self):
        return f'{self.customer} - {self.amount}'
