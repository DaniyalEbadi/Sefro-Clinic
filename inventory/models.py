from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models


class Product(models.Model):
    class StatusChoices(models.TextChoices):
        AVAILABLE = 'available', 'Available'
        LESS = 'less', 'Less'
        FINISHED = 'finished', 'Finished'

    name = models.CharField(max_length=120)
    sku = models.CharField(max_length=50, unique=True, blank=True, null=True)
    description = models.TextField(blank=True)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal('0'))])
    count = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=20, choices=StatusChoices.choices, default=StatusChoices.AVAILABLE)
    unit = models.CharField(max_length=50, blank=True, default='')

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name
