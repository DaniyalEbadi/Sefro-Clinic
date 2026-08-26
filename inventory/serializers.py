from rest_framework import serializers
from rest_framework.validators import UniqueValidator

from .models import Product


class ProductSerializer(serializers.ModelSerializer):
    sku = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        validators=[UniqueValidator(queryset=Product.objects.all())],
    )

    class Meta:
        model = Product
        fields = ['id', 'name', 'sku', 'description', 'unit_price', 'count', 'status', 'unit']


