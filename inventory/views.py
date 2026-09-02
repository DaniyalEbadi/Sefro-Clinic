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
    filter_backends = [filters.SearchFilter]
    search_fields = ['name']

    def destroy(self, request, *args, **kwargs):
        self.get_object()  # ensure exists and check permissions
        try:
            return super().destroy(request, *args, **kwargs)
        except ProtectedError:
            return Response(
                {'detail': 'Cannot delete product used by a service. Deactivate it instead.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
