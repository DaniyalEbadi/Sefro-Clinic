from datetime import datetime, time, timedelta
from collections import defaultdict

import jdatetime
from django.db.models import Avg, Count, Q, Sum
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, OpenApiTypes, extend_schema, inline_serializer
from rest_framework import filters, permissions, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import IsAdmin, IsAdminOrReadOnly
from Sefro_Clinic.fields import greg_to_shamsi_date, shamsi_to_greg_date, shamsi_to_greg_dt

from .models import Customer, Payment, Service, Visit, WorkTime
from .serializers import (CustomerSerializer, PaymentSerializer,
                          ServiceSerializer, VisitSerializer, WorkTimeSerializer)


def _shamsi_today_range():
    """Return (start, end) datetime range for today in Shamsi calendar."""
    now = timezone.localtime(timezone.now())
    shamsi_date = jdatetime.datetime.fromgregorian(datetime=now).date()
    greg_date = shamsi_date.togregorian()
    day_start = timezone.make_aware(datetime.combine(greg_date, time.min))
    day_end = day_start + timedelta(days=1)
    return day_start, day_end


def _shamsi_period_key(shamsi_date, period):
    if period == 'daily':
        return shamsi_date.strftime('%Y-%m-%d')
    elif period == 'weekly':
        doy = shamsi_date.timetuple().tm_yday
        wn = (doy - 1) // 7 + 1
        return f"{shamsi_date.year}-W{wn:02d}"
    elif period == 'monthly':
        return shamsi_date.strftime('%Y-%m')
    elif period == 'quarterly':
        q = (shamsi_date.month - 1) // 3 + 1
        return f"{shamsi_date.year}-Q{q}"
    elif period == 'yearly':
        return str(shamsi_date.year)
    return ''


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
                'today_visits': serializers.IntegerField(),
                'new_customers': serializers.IntegerField(),
            },
        ),
    )
    def get(self, request):
        today = timezone.now().date()
        shamsi_start, shamsi_end = _shamsi_today_range()
        payments = Payment.objects.all()
        data = {
            'customer_count': Customer.objects.count(),
            'loyal_customer_count': sum(1 for customer in Customer.objects.all() if customer.is_loyal_customer),
            'today_sales': payments.filter(paid_at__date=today).aggregate(total=Sum('amount'))['total'] or 0,
            'today_visits': Visit.objects.filter(start_at__gte=shamsi_start, start_at__lt=shamsi_end).count(),
            'new_customers': Customer.objects.filter(created_at__gte=shamsi_start, created_at__lt=shamsi_end).count(),
        }
        return Response(data)


def _filtered_payments(date_from=None, date_to=None):
    qs = Payment.objects.all()
    if date_from:
        qs = qs.filter(paid_at__gte=shamsi_to_greg_date(date_from))
    if date_to:
        qs = qs.filter(paid_at__lt=shamsi_to_greg_date(date_to) + timedelta(days=1))
    return qs


def _build_sales_chart(payments_qs, periods):
    buckets = {p: defaultdict(float) for p in periods}
    for payment in payments_qs.iterator():
        shamsi_dt = jdatetime.datetime.fromgregorian(datetime=timezone.localtime(payment.paid_at))
        sdate = shamsi_dt.date()
        for period in buckets:
            key = _shamsi_period_key(sdate, period)
            buckets[period][key] += float(payment.amount)
    return {p: [{'period': k, 'total': v} for k, v in sorted(d.items())] for p, d in buckets.items()}


def _shamsi_period_range(period):
    """Return (greg_start, greg_end) for current Shamsi period."""
    now = timezone.localtime(timezone.now())
    shamsi_now = jdatetime.datetime.fromgregorian(datetime=now)
    syear, smonth, sday = shamsi_now.year, shamsi_now.month, shamsi_now.day

    if period == 'daily':
        start = jdatetime.date(syear, smonth, sday)
        end = start + timedelta(days=1)
    elif period == 'weekly':
        # Find start of current Shamsi week (Saturday = 1 in Shamsi)
        weekday = shamsi_now.date().isoweekday()  # 1=Mon...7=Sun
        days_since_saturday = (weekday + 1) % 7  # Saturday=0
        start = shamsi_now.date() - timedelta(days=days_since_saturday)
        end = start + timedelta(days=7)
    elif period == 'monthly':
        start = jdatetime.date(syear, smonth, 1)
        if smonth == 12:
            end = jdatetime.date(syear + 1, 1, 1)
        else:
            end = jdatetime.date(syear, smonth + 1, 1)
    elif period == 'quarterly':
        sq = (smonth - 1) // 3
        start = jdatetime.date(syear, sq * 3 + 1, 1)
        if sq == 3:
            end = jdatetime.date(syear + 1, 1, 1)
        else:
            end = jdatetime.date(syear, (sq + 1) * 3 + 1, 1)
    elif period == 'yearly':
        start = jdatetime.date(syear, 1, 1)
        end = jdatetime.date(syear + 1, 1, 1)
    else:
        return None, None

    gs = timezone.make_aware(datetime.combine(start.togregorian(), time.min))
    ge = timezone.make_aware(datetime.combine(end.togregorian(), time.min))
    return gs, ge


@extend_schema(tags=['Reports'])
class ReportsAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsAdmin]

    @extend_schema(
        parameters=[
            OpenApiParameter('date_from', OpenApiTypes.STR, OpenApiParameter.QUERY, description='Shamsi date YYYY-MM-DD'),
            OpenApiParameter('date_to', OpenApiTypes.STR, OpenApiParameter.QUERY, description='Shamsi date YYYY-MM-DD'),
        ],
        responses=inline_serializer(
            name='Reports',
            fields={
                'daily': serializers.ListField(),
                'weekly': serializers.ListField(),
                'monthly': serializers.ListField(),
                'quarterly': serializers.ListField(),
                'yearly': serializers.ListField(),
                'total_sales': serializers.DecimalField(max_digits=14, decimal_places=2),
                'avg_satisfaction': serializers.FloatField(),
                'service_popularity': serializers.ListField(),
                'total_visits': serializers.IntegerField(),
                'customer_breakdown': serializers.DictField(),
            },
        ),
    )
    def get(self, request):
        date_from = request.query_params.get('date_from')
        date_to = request.query_params.get('date_to')
        qs = _filtered_payments(date_from, date_to)
        all_periods = ['daily', 'weekly', 'monthly', 'quarterly', 'yearly']
        result = _build_sales_chart(qs, all_periods)

        # Total sales
        result['total_sales'] = qs.aggregate(total=Sum('amount'))['total'] or 0

        # Average satisfaction
        avg = Customer.objects.exclude(satisfaction__isnull=True).aggregate(avg=Avg('satisfaction'))['avg']
        result['avg_satisfaction'] = float(avg) if avg else 0

        # Service popularity
        svc_pop = Service.objects.annotate(usage=Count('visits')).order_by('-usage').values('id', 'name', 'usage')
        result['service_popularity'] = list(svc_pop)

        # Total visits in range
        visit_qs = Visit.objects.all()
        if date_from:
            visit_qs = visit_qs.filter(start_at__gte=shamsi_to_greg_date(date_from))
        if date_to:
            visit_qs = visit_qs.filter(start_at__lt=shamsi_to_greg_date(date_to) + timedelta(days=1))
        result['total_visits'] = visit_qs.count()

        # Customer breakdown
        result['customer_breakdown'] = {
            'total': Customer.objects.count(),
        }
        return Response(result)


@extend_schema(tags=['Reports'])
class DailyReportView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsAdmin]

    def get(self, request):
        gs, ge = _shamsi_period_range('daily')
        qs = _filtered_payments(None, None).filter(paid_at__gte=gs, paid_at__lt=ge)
        chart = _build_sales_chart(qs, ['daily'])
        return Response({
            'period': jdatetime.datetime.fromgregorian(datetime=timezone.localtime(timezone.now())).strftime('%Y-%m-%d'),
            'sales': chart.get('daily', []),
            'total': qs.aggregate(total=Sum('amount'))['total'] or 0,
            'visits': Visit.objects.filter(start_at__gte=gs, start_at__lt=ge).count(),
        })


@extend_schema(tags=['Reports'])
class WeeklyReportView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsAdmin]

    def get(self, request):
        gs, ge = _shamsi_period_range('weekly')
        qs = _filtered_payments(None, None).filter(paid_at__gte=gs, paid_at__lt=ge)
        chart = _build_sales_chart(qs, ['daily'])
        return Response({
            'period': f"{_shamsi_period_key(jdatetime.datetime.fromgregorian(datetime=timezone.localtime(timezone.now())).date(), 'weekly')}",
            'days': chart.get('daily', []),
            'total': qs.aggregate(total=Sum('amount'))['total'] or 0,
            'visits': Visit.objects.filter(start_at__gte=gs, start_at__lt=ge).count(),
        })


@extend_schema(tags=['Reports'])
class MonthlyReportView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsAdmin]

    def get(self, request):
        gs, ge = _shamsi_period_range('monthly')
        qs = _filtered_payments(None, None).filter(paid_at__gte=gs, paid_at__lt=ge)
        chart = _build_sales_chart(qs, ['daily'])
        return Response({
            'period': jdatetime.datetime.fromgregorian(datetime=timezone.localtime(timezone.now())).strftime('%Y-%m'),
            'days': chart.get('daily', []),
            'total': qs.aggregate(total=Sum('amount'))['total'] or 0,
            'visits': Visit.objects.filter(start_at__gte=gs, start_at__lt=ge).count(),
        })


@extend_schema(tags=['Reports'])
class QuarterlyReportView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsAdmin]

    def get(self, request):
        gs, ge = _shamsi_period_range('quarterly')
        qs = _filtered_payments(None, None).filter(paid_at__gte=gs, paid_at__lt=ge)
        chart = _build_sales_chart(qs, ['monthly'])
        return Response({
            'period': _shamsi_period_key(jdatetime.datetime.fromgregorian(datetime=timezone.localtime(timezone.now())).date(), 'quarterly'),
            'months': chart.get('monthly', []),
            'total': qs.aggregate(total=Sum('amount'))['total'] or 0,
            'visits': Visit.objects.filter(start_at__gte=gs, start_at__lt=ge).count(),
        })


@extend_schema(tags=['Reports'])
class YearlyReportView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsAdmin]

    def get(self, request):
        gs, ge = _shamsi_period_range('yearly')
        qs = _filtered_payments(None, None).filter(paid_at__gte=gs, paid_at__lt=ge)
        chart = _build_sales_chart(qs, ['monthly'])
        return Response({
            'period': str(jdatetime.datetime.fromgregorian(datetime=timezone.localtime(timezone.now())).year),
            'months': chart.get('monthly', []),
            'total': qs.aggregate(total=Sum('amount'))['total'] or 0,
            'visits': Visit.objects.filter(start_at__gte=gs, start_at__lt=ge).count(),
        })


@extend_schema(tags=['Reports'])
class AllReportsView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsAdmin]

    def get(self, request):
        qs = Payment.objects.all()
        all_periods = ['daily', 'weekly', 'monthly', 'quarterly', 'yearly']
        chart = _build_sales_chart(qs, all_periods)

        # Average satisfaction
        avg = Customer.objects.exclude(satisfaction__isnull=True).aggregate(avg=Avg('satisfaction'))['avg']

        # Service popularity
        svc_pop = Service.objects.annotate(usage=Count('visits')).order_by('-usage').values('id', 'name', 'usage')

        # Customer visit status breakdown
        status_breakdown = {}
        for label in ['pending', 'confirmed', 'completed', 'canceled']:
            status_breakdown[label] = Visit.objects.filter(status=label).count()

        return Response({
            'sales_chart': chart,
            'total_sales': qs.aggregate(total=Sum('amount'))['total'] or 0,
            'avg_satisfaction': float(avg) if avg else 0,
            'service_popularity': list(svc_pop),
            'customer_status': status_breakdown,
            'total_customers': Customer.objects.count(),
            'total_visits': Visit.objects.count(),
        })


@extend_schema(tags=['Reports'])
class VisitReportView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsAdmin]

    @extend_schema(
        parameters=[
            OpenApiParameter('date_from', OpenApiTypes.STR, OpenApiParameter.QUERY, description='Shamsi date YYYY-MM-DD'),
            OpenApiParameter('date_to', OpenApiTypes.STR, OpenApiParameter.QUERY, description='Shamsi date YYYY-MM-DD'),
        ],
    )
    def get(self, request):
        date_from = request.query_params.get('date_from')
        date_to = request.query_params.get('date_to')

        current_qs = Visit.objects.all()
        if date_from:
            g_start = shamsi_to_greg_date(date_from)
            current_qs = current_qs.filter(start_at__gte=g_start)
        if date_to:
            g_end = shamsi_to_greg_date(date_to)
            current_qs = current_qs.filter(start_at__lt=g_end + timedelta(days=1))

        current_count = current_qs.count()

        # Previous period (same length)
        if date_from and date_to:
            g_start = shamsi_to_greg_date(date_from)
            g_end = shamsi_to_greg_date(date_to)
            span = (g_end - g_start).days + 1
            prev_start = g_start - timedelta(days=span)
            prev_end = g_start
            prev_count = Visit.objects.filter(start_at__gte=prev_start, start_at__lt=prev_end + timedelta(days=1)).count()
            change = ((current_count - prev_count) / prev_count * 100) if prev_count else None
        else:
            prev_count = None
            change = None

        return Response({
            'current_count': current_count,
            'previous_count': prev_count,
            'change_percent': round(change, 1) if change is not None else None,
        })


@extend_schema(tags=['Reports'])
class CustomerReportView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsAdmin]

    def get(self, request):
        status_breakdown = {}
        for label in ['pending', 'confirmed', 'completed', 'canceled']:
            status_breakdown[label] = Visit.objects.filter(status=label).count()

        annotated = Customer.objects.annotate(vc=Count('visits'))
        return Response({
            'by_visit_status': status_breakdown,
            'new_customers': annotated.filter(vc=0).count(),
            'loyal_customers': annotated.filter(vc__gte=5).count(),
            'total': Customer.objects.count(),
        })


@extend_schema(tags=['Reports'])
class ReferralReportView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsAdmin]

    @extend_schema(
        parameters=[
            OpenApiParameter('date_from', OpenApiTypes.STR, OpenApiParameter.QUERY, description='Shamsi date YYYY-MM-DD'),
            OpenApiParameter('date_to', OpenApiTypes.STR, OpenApiParameter.QUERY, description='Shamsi date YYYY-MM-DD'),
        ],
    )
    def get(self, request):
        date_from = request.query_params.get('date_from')
        date_to = request.query_params.get('date_to')

        visit_qs = Visit.objects.all()
        if date_from:
            visit_qs = visit_qs.filter(start_at__gte=shamsi_to_greg_date(date_from))
        if date_to:
            visit_qs = visit_qs.filter(start_at__lt=shamsi_to_greg_date(date_to) + timedelta(days=1))

        total_visits = visit_qs.count()
        total_customers = Customer.objects.count()
        returning = Customer.objects.annotate(vc=Count('visits')).filter(vc__gte=2).count()

        return Response({
            'total_visits': total_visits,
            'total_customers': total_customers,
            'returning_customers': returning,
            'referral_rate': round(returning / total_customers * 100, 1) if total_customers else 0,
        })


def validate_visit_work_time(start_dt, end_dt):
    wt = WorkTime.objects.first()
    if not wt:
        return
    start_t = start_dt.time()
    end_t = end_dt.time()
    if start_t < wt.start_time or end_t > wt.end_time:
        raise serializers.ValidationError(
            f'ساعت کاری کلینیک از {wt.start_time:%H:%M} تا {wt.end_time:%H:%M} می‌باشد. '
            'لطفاً در ساعات کاری وقت رزرو کنید.'
        )


@extend_schema(tags=['Work Time'])
class WorkTimeViewSet(viewsets.ModelViewSet):
    queryset = WorkTime.objects.all()
    serializer_class = WorkTimeSerializer
    permission_classes = [permissions.IsAuthenticated, IsAdmin]
    pagination_class = None


@extend_schema(tags=['Customers'])
class CustomerViewSet(viewsets.ModelViewSet):
    queryset = Customer.objects.all()
    serializer_class = CustomerSerializer
    permission_classes = [permissions.IsAuthenticated, IsAdminOrReadOnly]
    filter_backends = [filters.SearchFilter]
    search_fields = ['first_name', 'last_name', 'mobile_number', 'national_id', 'bitmoji_code']


@extend_schema(tags=['Services'])
class ServiceViewSet(viewsets.ModelViewSet):
    queryset = Service.objects.all()
    serializer_class = ServiceSerializer
    permission_classes = [permissions.IsAuthenticated, IsAdminOrReadOnly]


@extend_schema(
    tags=['Visits'],
    parameters=[
        OpenApiParameter('year', OpenApiTypes.INT, OpenApiParameter.QUERY, description='Shamsi year'),
        OpenApiParameter('month', OpenApiTypes.INT, OpenApiParameter.QUERY, description='Shamsi month (1-12)'),
        OpenApiParameter('date_from', OpenApiTypes.STR, OpenApiParameter.QUERY, description='Shamsi date YYYY-MM-DD'),
        OpenApiParameter('date_to', OpenApiTypes.STR, OpenApiParameter.QUERY, description='Shamsi date YYYY-MM-DD'),
        OpenApiParameter('status', OpenApiTypes.STR, OpenApiParameter.QUERY, description='Visit status'),
    ],
)
class VisitViewSet(viewsets.ModelViewSet):
    queryset = Visit.objects.select_related('customer', 'staff').prefetch_related('services')
    serializer_class = VisitSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['customer__first_name', 'customer__last_name', 'customer__mobile_number', 'notes', 'status']
    ordering_fields = ['start_at', 'end_at', 'status', 'customer__first_name']
    ordering = ['-start_at']

    def perform_create(self, serializer):
        start_at = serializer.validated_data.get('start_at')
        end_at = serializer.validated_data.get('end_at')
        if start_at and end_at:
            validate_visit_work_time(start_at, end_at)
        serializer.save()

    def perform_update(self, serializer):
        start_at = serializer.validated_data.get('start_at')
        end_at = serializer.validated_data.get('end_at')
        if start_at and end_at:
            validate_visit_work_time(start_at, end_at)
        serializer.save()

    def get_queryset(self):
        qs = super().get_queryset()
        status = self.request.query_params.get('status')
        if status:
            qs = qs.filter(status=status)

        # Shamsi year/month filter
        year = self.request.query_params.get('year')
        month = self.request.query_params.get('month')
        if year and month:
            try:
                sdate = jdatetime.date(int(year), int(month), 1)
                gstart = sdate.togregorian()
                if month == '12':
                    smonth_end = jdatetime.date(int(year) + 1, 1, 1)
                else:
                    smonth_end = jdatetime.date(int(year), int(month) + 1, 1)
                gend = smonth_end.togregorian()
                day_start = timezone.make_aware(datetime.combine(gstart, time.min))
                day_end = timezone.make_aware(datetime.combine(gend, time.min))
                qs = qs.filter(start_at__gte=day_start, start_at__lt=day_end)
            except ValueError:
                pass

        date_from = self.request.query_params.get('date_from')
        if date_from:
            try:
                gdate = shamsi_to_greg_date(date_from)
                qs = qs.filter(start_at__date__gte=gdate)
            except (ValueError, TypeError, serializers.ValidationError):
                pass
        date_to = self.request.query_params.get('date_to')
        if date_to:
            try:
                gdate = shamsi_to_greg_date(date_to)
                qs = qs.filter(start_at__date__lte=gdate)
            except (ValueError, TypeError, serializers.ValidationError):
                pass
        return qs

    @action(detail=True, methods=['post'])
    @extend_schema(responses=VisitSerializer)
    def confirm(self, request, pk=None):
        visit = self.get_object()
        visit.status = Visit.Status.CONFIRMED
        visit.save(update_fields=['status'])
        return Response(self.get_serializer(visit).data)

    @action(detail=True, methods=['post'])
    @extend_schema(responses=VisitSerializer)
    def complete(self, request, pk=None):
        visit = self.get_object()
        visit.status = Visit.Status.COMPLETED
        visit.save(update_fields=['status'])
        return Response(self.get_serializer(visit).data)

    @action(detail=True, methods=['post'])
    @extend_schema(responses=VisitSerializer)
    def cancel(self, request, pk=None):
        visit = self.get_object()
        visit.status = Visit.Status.CANCELED
        visit.save(update_fields=['status'])
        return Response(self.get_serializer(visit).data)

    @action(detail=False, methods=['post'])
    @extend_schema(
        request=inline_serializer('ReserveRequest', fields={
            'customer': serializers.IntegerField(),
            'services': serializers.ListField(child=serializers.IntegerField()),
            'date': serializers.CharField(help_text='Shamsi date YYYY-MM-DD'),
            'time': serializers.CharField(help_text='HH:MM'),
            'notes': serializers.CharField(required=False, allow_blank=True),
        }),
        responses=VisitSerializer,
    )
    def reserve(self, request):
        customer_id = request.data.get('customer')
        service_ids = request.data.get('services', [])
        shamsi_date_str = request.data.get('date')
        time_str = request.data.get('time')
        notes = request.data.get('notes', '')

        try:
            greg_date = shamsi_to_greg_date(shamsi_date_str)
            hour, minute = map(int, time_str.split(':'))
            start_dt = timezone.make_aware(datetime.combine(greg_date, time(hour=hour, minute=minute)))
        except (ValueError, TypeError, serializers.ValidationError):
            return Response({'error': 'Invalid date or time format'}, status=status.HTTP_400_BAD_REQUEST)

        if start_dt < timezone.now():
            return Response({'error': 'Reservation must be in the future'}, status=status.HTTP_400_BAD_REQUEST)

        services = list(Service.objects.filter(id__in=service_ids))
        if not services:
            return Response({'error': 'No valid services found'}, status=status.HTTP_400_BAD_REQUEST)

        total_minutes = sum(s.time for s in services)
        end_dt = start_dt + timedelta(minutes=total_minutes)

        validate_visit_work_time(start_dt, end_dt)

        visit = Visit.objects.create(
            customer_id=customer_id,
            start_at=start_dt,
            end_at=end_dt,
            status=Visit.Status.PENDING,
            notes=notes,
        )
        visit.services.set(services)
        visit.save()
        return Response(VisitSerializer(visit).data, status=status.HTTP_201_CREATED)


@extend_schema(tags=['Payments'])
class PaymentViewSet(viewsets.ModelViewSet):
    queryset = Payment.objects.select_related('customer', 'visit')
    serializer_class = PaymentSerializer
    permission_classes = [permissions.IsAuthenticated, IsAdminOrReadOnly]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['customer__first_name', 'customer__last_name', 'customer__id', 'customer__mobile_number']
    ordering_fields = ['paid_at', 'amount', 'payment_method']
    ordering = ['-paid_at']

    @action(detail=False, methods=['get'])
    @extend_schema(
        tags=['Payments'],
        responses=inline_serializer('ServicePaymentSummary', fields={
            'service_id': serializers.IntegerField(),
            'service_name': serializers.CharField(),
            'total_payments': serializers.DecimalField(max_digits=14, decimal_places=2),
            'count': serializers.IntegerField(),
        }),
    )
    def by_service(self, request):
        qs = Payment.objects.select_related('visit').prefetch_related('visit__services')
        date_from = request.query_params.get('date_from')
        date_to = request.query_params.get('date_to')
        if date_from:
            qs = qs.filter(paid_at__gte=shamsi_to_greg_date(date_from))
        if date_to:
            qs = qs.filter(paid_at__lt=shamsi_to_greg_date(date_to) + timedelta(days=1))

        service_totals = {}
        for payment in qs.all():
            if not payment.visit:
                continue
            for service in payment.visit.services.all():
                key = service.id
                if key not in service_totals:
                    service_totals[key] = {
                        'service_id': service.id,
                        'service_name': service.name,
                        'total_payments': 0,
                        'count': 0,
                    }
                service_totals[key]['total_payments'] += float(payment.amount)
                service_totals[key]['count'] += 1
        return Response(list(service_totals.values()))
