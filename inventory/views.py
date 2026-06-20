from drf_spectacular.utils import extend_schema
from rest_framework import filters, permissions, viewsets

from accounts.permissions import IsAdminOrReadOnly

from .models import Product
from .serializers import ProductSerializer


@extend_schema(tags=['Products'])
class ProductViewSet(viewsets.ModelViewSet):
    queryset = Product.objects.all()
    serializer_class = ProductSerializer
    permission_classes = [permissions.IsAuthenticated, IsAdminOrReadOnly]
    filter_backends = [filters.SearchFilter]
    search_fields = ['name']
