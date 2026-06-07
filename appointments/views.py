from drf_spectacular.utils import extend_schema
from rest_framework import permissions, viewsets

from .models import Appointment
from .serializers import AppointmentSerializer


@extend_schema(tags=['Appointments'])
class AppointmentViewSet(viewsets.ModelViewSet):
    queryset = Appointment.objects.select_related('customer', 'staff', 'service').all()
    serializer_class = AppointmentSerializer
    permission_classes = [permissions.IsAuthenticated]
