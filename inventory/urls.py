from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import InventoryItemViewSet, ProductViewSet, StockMovementViewSet


router = DefaultRouter()
router.register('products', ProductViewSet, basename='product')
router.register('items', InventoryItemViewSet, basename='inventory-item')
router.register('movements', StockMovementViewSet, basename='stock-movement')

urlpatterns = [
    path('', include(router.urls)),
]
