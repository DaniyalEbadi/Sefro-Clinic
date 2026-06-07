from drf_spectacular.utils import extend_schema
from rest_framework import permissions, viewsets

from .models import InventoryItem, Product, StockMovement
from .serializers import InventoryItemSerializer, ProductSerializer, StockMovementSerializer


@extend_schema(tags=['Products'])
class ProductViewSet(viewsets.ModelViewSet):
    queryset = Product.objects.all()
    serializer_class = ProductSerializer
    permission_classes = [permissions.IsAuthenticated]


@extend_schema(tags=['Inventory'])
class InventoryItemViewSet(viewsets.ModelViewSet):
    queryset = InventoryItem.objects.select_related('product').all()
    serializer_class = InventoryItemSerializer
    permission_classes = [permissions.IsAuthenticated]


@extend_schema(tags=['Stock Movements'])
class StockMovementViewSet(viewsets.ModelViewSet):
    queryset = StockMovement.objects.select_related('inventory_item', 'inventory_item__product').all()
    serializer_class = StockMovementSerializer
    permission_classes = [permissions.IsAuthenticated]
