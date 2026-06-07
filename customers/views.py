from django.db import models
from django.db.models import Sum
from django.db.models.functions import TruncDate, TruncMonth, TruncWeek, TruncYear
from django.utils import timezone
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import filters, permissions, serializers, viewsets
from rest_framework.response import Response
from rest_framework.views import APIView

from inventory.models import InventoryItem

from .models import Customer, Payment, Service, Visit
from .serializers import CustomerSerializer, PaymentSerializer, ServiceSerializer, VisitSerializer


class DashboardAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        tags=['Dashboard'],
        responses=inline_serializer(
            name='Dashboard',
            fields={
                'customer_count': serializers.IntegerField(),
                'loyal_customer_count': serializers.IntegerField(),
                'today_sales': serializers.DecimalField(max_digits=12, decimal_places=2),
                'weekly_sales': serializers.DecimalField(max_digits=12, decimal_places=2),
                'monthly_sales': serializers.DecimalField(max_digits=12, decimal_places=2),
                'yearly_sales': serializers.DecimalField(max_digits=12, decimal_places=2),
                'low_stock_items': serializers.IntegerField(),
                'daily_sales_chart': serializers.ListField(),
                'weekly_sales_chart': serializers.ListField(),
                'monthly_sales_chart': serializers.ListField(),
                'yearly_sales_chart': serializers.ListField(),
            },
        ),
    )
    def get(self, request):
        today = timezone.now().date()
        payments = Payment.objects.all()
        weekly_totals = payments.annotate(period=TruncWeek('paid_at'))
        data = {
            'customer_count': Customer.objects.count(),
            'loyal_customer_count': sum(1 for customer in Customer.objects.all() if customer.is_loyal_customer),
            'today_sales': payments.filter(paid_at__date=today).aggregate(total=Sum('amount'))['total'] or 0,
            'weekly_sales': weekly_totals.filter(period__date__lte=today).order_by('-period').values('period').annotate(total=Sum('amount')).first()['total'] if weekly_totals.exists() else 0,
            'monthly_sales': payments.annotate(period=TruncMonth('paid_at')).filter(period__month=today.month, period__year=today.year).aggregate(total=Sum('amount'))['total'] or 0,
            'yearly_sales': payments.annotate(period=TruncYear('paid_at')).filter(period__year=today.year).aggregate(total=Sum('amount'))['total'] or 0,
            'low_stock_items': InventoryItem.objects.filter(quantity__lte=models.F('minimum_quantity')).count(),
            'daily_sales_chart': list(payments.annotate(period=TruncDate('paid_at')).values('period').annotate(total=Sum('amount')).order_by('-period')[:7]),
            'weekly_sales_chart': list(payments.annotate(period=TruncWeek('paid_at')).values('period').annotate(total=Sum('amount')).order_by('-period')[:8]),
            'monthly_sales_chart': list(payments.annotate(period=TruncMonth('paid_at')).values('period').annotate(total=Sum('amount')).order_by('-period')[:12]),
            'yearly_sales_chart': list(payments.annotate(period=TruncYear('paid_at')).values('period').annotate(total=Sum('amount')).order_by('-period')[:5]),
        }
        return Response(data)


@extend_schema(tags=['Customers'])
class CustomerViewSet(viewsets.ModelViewSet):
    queryset = Customer.objects.all()
    serializer_class = CustomerSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [filters.SearchFilter]
    search_fields = ['first_name', 'last_name', 'mobile_number', 'national_id', 'bitmoji_code']


@extend_schema(tags=['Services'])
class ServiceViewSet(viewsets.ModelViewSet):
    queryset = Service.objects.all()
    serializer_class = ServiceSerializer
    permission_classes = [permissions.IsAuthenticated]


@extend_schema(tags=['Visits'])
class VisitViewSet(viewsets.ModelViewSet):
    queryset = Visit.objects.select_related('customer', 'staff').prefetch_related('services')
    serializer_class = VisitSerializer
    permission_classes = [permissions.IsAuthenticated]


@extend_schema(tags=['Payments'])
class PaymentViewSet(viewsets.ModelViewSet):
    queryset = Payment.objects.select_related('customer', 'visit')
    serializer_class = PaymentSerializer
    permission_classes = [permissions.IsAuthenticated]
