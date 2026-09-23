from django.db.models import ProtectedError
from drf_spectacular.utils import extend_schema
from rest_framework import filters, permissions, status, viewsets
from rest_framework.response import Response

from .models import Product
from .serializers import ProductSerializer


@extend_schema(tags=['Products'])
class ProductViewSet(viewsets.ModelViewSet):
    queryset = Product.objects.all()
    serializer_class = ProductSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['name', 'sku', 'brand', 'description']
    ordering_fields = ['name', 'unit_price', 'cost_usd', 'count', 'brand', 'product_type', 'status']
    ordering = ['name']

    def get_queryset(self):
        qs = super().get_queryset()
        params = self.request.query_params
        product_type = params.get('product_type')
        if product_type:
            qs = qs.filter(product_type=product_type)
        status = params.get('status')
        if status:
            qs = qs.filter(status=status)
        brand = params.get('brand')
        if brand:
            qs = qs.filter(brand__icontains=brand)
        return qs

    def destroy(self, request, *args, **kwargs):
        self.get_object()  # ensure exists and check permissions
        try:
            return super().destroy(request, *args, **kwargs)
        except ProtectedError:
            return Response(
                {'detail': 'Cannot delete product used by a service. Deactivate it instead.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
