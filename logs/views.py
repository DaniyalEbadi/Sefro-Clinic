from drf_spectacular.utils import extend_schema
from rest_framework import filters, permissions, viewsets

from accounts.permissions import IsAdmin

from .models import AuditLog
from .serializers import AuditLogSerializer


@extend_schema(tags=['Logs'])
class AuditLogViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = AuditLog.objects.select_related('user')
    serializer_class = AuditLogSerializer
    permission_classes = [permissions.IsAuthenticated, IsAdmin]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['model_name', 'action', 'object_repr', 'user__username']
    ordering_fields = ['timestamp']
    ordering = ['-timestamp']
