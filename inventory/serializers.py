from rest_framework import serializers

from .models import Product


class ProductSerializer(serializers.ModelSerializer):
    sku = serializers.CharField(required=False, allow_null=True, allow_blank=True)

    class Meta:
        model = Product
        fields = ['id', 'name', 'sku', 'description', 'unit_price', 'count', 'status', 'unit']


