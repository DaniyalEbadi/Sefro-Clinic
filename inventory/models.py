from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models


class Product(models.Model):
    name = models.CharField(max_length=120)
    sku = models.CharField(max_length=50, unique=True)
    description = models.TextField(blank=True)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal('0'))])

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class InventoryItem(models.Model):
    product = models.OneToOneField(Product, on_delete=models.CASCADE, related_name='inventory_item')
    quantity = models.PositiveIntegerField(default=0)
    minimum_quantity = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['product__name']

    def __str__(self):
        return f'{self.product} ({self.quantity})'

    @property
    def is_low_stock(self):
        return self.quantity <= self.minimum_quantity


class StockMovement(models.Model):
    class MovementType(models.TextChoices):
        IN = 'in', 'In'
        OUT = 'out', 'Out'

    inventory_item = models.ForeignKey(InventoryItem, on_delete=models.CASCADE, related_name='movements')
    movement_type = models.CharField(max_length=10, choices=MovementType.choices)
    quantity = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)
    note = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ['-created_at']

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        super().save(*args, **kwargs)
        if is_new:
            item = self.inventory_item
            if self.movement_type == StockMovement.MovementType.IN:
                item.quantity += self.quantity
            else:
                item.quantity = max(0, item.quantity - self.quantity)
            item.save()

    def __str__(self):
        return f'{self.inventory_item.product} - {self.movement_type} - {self.quantity}'
