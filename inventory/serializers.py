from decimal import Decimal

from rest_framework import serializers
from rest_framework.validators import UniqueValidator

from .models import Product


class ProductSerializer(serializers.ModelSerializer):
    # Keep the established numeric API representation while accepting the
    # Decimal precision used by inventory consumption.
    count = serializers.DecimalField(
        max_digits=12, decimal_places=3, min_value=0, coerce_to_string=False,
        required=False, default=Decimal('0'),
    )
    sku = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        validators=[UniqueValidator(queryset=Product.objects.all())],
    )

    class Meta:
        model = Product
        fields = [
            'id', 'name', 'sku', 'description', 'unit_price', 'cost_usd', 'count',
            'status', 'unit', 'brand', 'product_type',
        ]


