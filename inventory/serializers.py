from rest_framework import serializers

from Sefro_Clinic.fields import ShamsiDateField, ShamsiDateTimeField

from .models import InventoryItem, Product, StockMovement


class ProductSerializer(serializers.ModelSerializer):
    expiry_date = ShamsiDateField(allow_null=True, required=False)

    class Meta:
        model = Product
        fields = ['id', 'name', 'sku', 'description', 'category', 'expiry_date', 'unit_price']


class InventoryItemSerializer(serializers.ModelSerializer):
    product_detail = ProductSerializer(source='product', read_only=True)
    is_low_stock = serializers.BooleanField(read_only=True)
    updated_at = ShamsiDateTimeField(read_only=True)

    class Meta:
        model = InventoryItem
        fields = ['id', 'product', 'product_detail', 'quantity', 'minimum_quantity', 'updated_at', 'is_low_stock']


class StockMovementSerializer(serializers.ModelSerializer):
    created_at = ShamsiDateTimeField(read_only=True)

    class Meta:
        model = StockMovement
        fields = ['id', 'inventory_item', 'movement_type', 'quantity', 'created_at', 'note']
        read_only_fields = ['created_at']


