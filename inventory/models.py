from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models


class Product(models.Model):
    class ProductType(models.TextChoices):
        TREATMENT = 'treatment', 'Treatment'
        CONSUMABLE = 'consumable', 'Consumable'
        OTHER = 'other', 'Other'

    class StatusChoices(models.TextChoices):
        AVAILABLE = 'available', 'Available'
        LESS = 'less', 'Less'
        FINISHED = 'finished', 'Finished'

    name = models.CharField(max_length=120)
    sku = models.CharField(max_length=50, unique=True, blank=True, null=True)
    description = models.TextField(blank=True)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal('0'))], default=Decimal('0'))
    cost_usd = models.DecimalField(
        max_digits=14, decimal_places=2,
        validators=[MinValueValidator(Decimal('0'))], default=Decimal('0'),
        help_text='Current clinic acquisition cost in USD. Historical costs are tracked via ProductCostHistory.',
    )
    # Recipe and usage quantities are Decimal values, so stock must retain the
    # same precision (for example, partially used vials).
    count = models.DecimalField(
        max_digits=12, decimal_places=3, default=Decimal('0'),
        validators=[MinValueValidator(Decimal('0'))],
    )
    status = models.CharField(max_length=20, choices=StatusChoices.choices, default=StatusChoices.AVAILABLE)
    unit = models.CharField(max_length=50, blank=True, default='')
    brand = models.CharField(max_length=100, blank=True, default='')
    product_type = models.CharField(
        max_length=30, choices=ProductType.choices, default=ProductType.TREATMENT,
        db_index=True,
    )

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name
