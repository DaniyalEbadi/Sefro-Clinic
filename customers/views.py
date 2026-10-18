import re
from collections import defaultdict
from datetime import datetime, time, timedelta
from decimal import Decimal

import jdatetime
from django.db import transaction
from django.db.models import (
    Avg,
    Count,
    DecimalField,
    IntegerField,
    OuterRef,
    Prefetch,
    Subquery,
    Sum,
    Value,
)
from django.db.models.functions import Coalesce
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, OpenApiTypes, extend_schema, inline_serializer
from rest_framework import filters, permissions, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import IsAdminOrEmployee, IsAdminOrReadOnly
from Sefro_Clinic.fields import SHAMSI_DATE_FORMAT, shamsi_to_greg_date
from Sefro_Clinic.periods import (
    shamsi_month_bounds,
)
from Sefro_Clinic.periods import (
    shamsi_period_key as _period_key,
)
from Sefro_Clinic.periods import (
    shamsi_period_range as _period_range,
)

from .models import Customer, Payment, Service, ServiceCategory, Visit, VisitService
from .serializers import (
    CustomerSerializer,
    PaymentSerializer,
    ServiceCategorySerializer,
    ServiceSerializer,
    VisitSerializer,
)


def _uncovered_operator_message(uncovered_roles):
    """Shared 400 text for a visit missing the operator(s) its services need."""
    roles = ', '.join(uncovered_roles)
    return (
        'This visit has a service that requires an operator, but no matching staff '
        f'member is assigned for: {roles}. Assign staff (or an operator per service) '
        'before completing it.'
    )


def _shamsi_today_range():
    """Return (start, end) datetime range for today in Shamsi calendar.

    Half-open: ``end`` is tomorrow 00:00, for ``__lt`` filters.
    """
    return _period_range('daily')


def _shamsi_period_key(shamsi_date, period):
    """Bucket a Shamsi date into its period key. See Sefro_Clinic.periods."""
    return _period_key(shamsi_date, period)


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
        # One Shamsi day for every KPI in this payload: sales, visits and
        # new customers all bucket on the same Jalali calendar day.
        shamsi_start, shamsi_end = _shamsi_today_range()
        data = {
            'customer_count': Customer.objects.count(),
            'loyal_customer_count': Customer.objects.annotate(
                vc=Count('visits'),
            ).filter(vc__gte=5).count(),
            'today_sales': Payment.objects.filter(
                paid_at__gte=shamsi_start, paid_at__lt=shamsi_end,
            ).aggregate(total=Sum('amount'))['total'] or 0,
            'today_visits': Visit.objects.filter(
                start_at__gte=shamsi_start, start_at__lt=shamsi_end,
            ).count(),
            'new_customers': Customer.objects.filter(
                created_at__gte=shamsi_start, created_at__lt=shamsi_end,
            ).count(),
        }
        return Response(data)


def _filtered_sales(date_from=None, date_to=None):
    """Authoritative revenue rows: sales ledger, net of refunds."""
    from finance.models import Sale
    from finance.services.financials import REVENUE_STATUSES

    qs = Sale.objects.filter(status__in=REVENUE_STATUSES)
    if date_from:
        qs = qs.filter(created_at__gte=shamsi_to_greg_date(date_from))
    if date_to:
        qs = qs.filter(created_at__lt=shamsi_to_greg_date(date_to) + timedelta(days=1))
    return qs


def _build_sales_chart(sales_qs, periods):
    """Bucket authoritative sale amounts (Toman) by Shamsi period."""
    buckets = {p: defaultdict(Decimal) for p in periods}
    for sale in sales_qs.iterator():
        shamsi_dt = jdatetime.datetime.fromgregorian(datetime=timezone.localtime(sale.created_at))
        sdate = shamsi_dt.date()
        for period in buckets:
            key = _shamsi_period_key(sdate, period)
            buckets[period][key] += sale.amount_toman
    return {p: [{'period': k, 'total': float(v)} for k, v in sorted(d.items())] for p, d in buckets.items()}


def _shamsi_period_range(period):
    """Return (greg_start, greg_end) for current Shamsi period.

    Half-open: ``end`` is the first instant of the next period, for ``__lt``
    filters. Delegates to Sefro_Clinic.periods so finance reports bucket the
    same days identically.
    """
    return _period_range(period)


@extend_schema(tags=['Reports (Activity)'])
class ReportsAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]

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
        qs = _filtered_sales(date_from, date_to)
        all_periods = ['daily', 'weekly', 'monthly', 'quarterly', 'yearly']
        result = _build_sales_chart(qs, all_periods)

        # Total sales
        result['total_sales'] = qs.aggregate(total=Sum('amount_toman'))['total'] or 0

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


@extend_schema(tags=['Reports (Activity)'])
class DailyReportView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        gs, ge = _shamsi_period_range('daily')
        qs = _filtered_sales(None, None).filter(created_at__gte=gs, created_at__lt=ge)
        chart = _build_sales_chart(qs, ['daily'])
        return Response({
            'period': jdatetime.datetime.fromgregorian(datetime=timezone.localtime(timezone.now())).strftime('%Y-%m-%d'),
            'sales': chart.get('daily', []),
            'total': qs.aggregate(total=Sum('amount_toman'))['total'] or 0,
            'visits': Visit.objects.filter(start_at__gte=gs, start_at__lt=ge).count(),
        })


@extend_schema(tags=['Reports (Activity)'])
class WeeklyReportView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        gs, ge = _shamsi_period_range('weekly')
        qs = _filtered_sales(None, None).filter(created_at__gte=gs, created_at__lt=ge)
        chart = _build_sales_chart(qs, ['daily'])
        return Response({
            'period': f"{_shamsi_period_key(jdatetime.datetime.fromgregorian(datetime=timezone.localtime(timezone.now())).date(), 'weekly')}",
            'days': chart.get('daily', []),
            'total': qs.aggregate(total=Sum('amount_toman'))['total'] or 0,
            'visits': Visit.objects.filter(start_at__gte=gs, start_at__lt=ge).count(),
        })


@extend_schema(tags=['Reports (Activity)'])
class MonthlyReportView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        gs, ge = _shamsi_period_range('monthly')
        qs = _filtered_sales(None, None).filter(created_at__gte=gs, created_at__lt=ge)
        chart = _build_sales_chart(qs, ['daily'])
        return Response({
            'period': jdatetime.datetime.fromgregorian(datetime=timezone.localtime(timezone.now())).strftime('%Y-%m'),
            'days': chart.get('daily', []),
            'total': qs.aggregate(total=Sum('amount_toman'))['total'] or 0,
            'visits': Visit.objects.filter(start_at__gte=gs, start_at__lt=ge).count(),
        })


@extend_schema(tags=['Reports (Activity)'])
class QuarterlyReportView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        gs, ge = _shamsi_period_range('quarterly')
        qs = _filtered_sales(None, None).filter(created_at__gte=gs, created_at__lt=ge)
        chart = _build_sales_chart(qs, ['monthly'])
        return Response({
            'period': _shamsi_period_key(jdatetime.datetime.fromgregorian(datetime=timezone.localtime(timezone.now())).date(), 'quarterly'),
            'months': chart.get('monthly', []),
            'total': qs.aggregate(total=Sum('amount_toman'))['total'] or 0,
            'visits': Visit.objects.filter(start_at__gte=gs, start_at__lt=ge).count(),
        })


@extend_schema(tags=['Reports (Activity)'], deprecated=True)
class YearlyReportView(APIView):
    """Deprecated: a yearly *activity* total is not financial reporting.

    Use ``/api/finance/reports/monthly-close/?year=<shamsi_year>`` for the
    complete yearly picture — 12 frozen-month P&Ls, purchases, operators,
    payouts, and a year total. This endpoint now answers **410 Gone**.
    """

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        return Response(
            {
                'error': 'This endpoint is deprecated.',
                'use': '/api/finance/reports/monthly-close/?year=<shamsi_year>',
                'detail': (
                    'The monthly-close report is the complete yearly financial '
                    'view: per-month P&L, purchases, operators, payouts, and a '
                    'year total, all bucketed on the Shamsi calendar.'
                ),
            },
            status=410,
        )


@extend_schema(tags=['Reports (Activity)'])
class AllReportsView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        qs = _filtered_sales()
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
            'total_sales': qs.aggregate(total=Sum('amount_toman'))['total'] or 0,
            'avg_satisfaction': float(avg) if avg else 0,
            'service_popularity': list(svc_pop),
            'customer_status': status_breakdown,
            'total_customers': Customer.objects.count(),
            'total_visits': Visit.objects.count(),
        })


@extend_schema(tags=['Reports (Activity)'])
class VisitReportView(APIView):
    permission_classes = [permissions.IsAuthenticated]

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


@extend_schema(tags=['Reports (Activity)'])
class CustomerReportView(APIView):
    permission_classes = [permissions.IsAuthenticated]

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


@extend_schema(tags=['Reports (Activity)'])
class ReferralReportView(APIView):
    permission_classes = [permissions.IsAuthenticated]

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


@extend_schema(tags=['Customers'])
class CustomerViewSet(viewsets.ModelViewSet):
    serializer_class = CustomerSerializer
    permission_classes = [IsAdminOrEmployee]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['first_name', 'last_name', 'mobile_number', 'national_id', 'bitmoji_code', 'file_sys_id']
    ordering_fields = ['first_name', 'last_name', 'created_at', 'num_visits']
    ordering = ['first_name', 'last_name']

    def get_queryset(self):
        # Aggregates are computed by independent correlated subqueries, one
        # per relation. Annotating Count('visits') and Sum('payments__amount')
        # in a single .annotate() call joins both relations in the same FROM
        # clause, so a customer with 4 visits and 4 payments yields 4 x 4 = 16
        # joined rows and both aggregates are inflated (num_visits = 16).
        # Separate subqueries each see only their own relation, so neither can
        # multiply the other, and the whole page still costs one SQL statement.
        visit_count_qs = (
            Visit.objects
            .filter(customer=OuterRef('pk'))
            .order_by()
            .values('customer')
            .annotate(n=Count('pk'))
            .values('n')
        )
        payment_sum_qs = (
            Payment.objects
            .filter(customer=OuterRef('pk'))
            .order_by()
            .values('customer')
            .annotate(t=Sum('amount'))
            .values('t')
        )
        last_visit_subquery = Subquery(
            Visit.objects.filter(customer=OuterRef('pk')).order_by('-start_at').values('start_at')[:1],
        )
        last_payment_qs = Payment.objects.filter(customer=OuterRef('pk')).order_by('-paid_at')
        return Customer.objects.annotate(
            num_visits=Coalesce(
                Subquery(visit_count_qs, output_field=IntegerField()),
                Value(0),
                output_field=IntegerField(),
            ),
            sum_payments=Coalesce(
                Subquery(
                    payment_sum_qs,
                    output_field=DecimalField(max_digits=14, decimal_places=2),
                ),
                Value(0),
                output_field=DecimalField(max_digits=14, decimal_places=2),
            ),
            last_visit_at=last_visit_subquery,
            last_payment_id=Subquery(last_payment_qs.values('id')[:1]),
            last_payment_amount=Subquery(last_payment_qs.values('amount')[:1]),
            last_payment_amount_usd=Subquery(last_payment_qs.values('amount_usd')[:1]),
            last_payment_method=Subquery(last_payment_qs.values('payment_method')[:1]),
            last_payment_paid_at=Subquery(last_payment_qs.values('paid_at')[:1]),
        )


@extend_schema(tags=['Services'])
class ServiceCategoryViewSet(viewsets.ModelViewSet):
    queryset = ServiceCategory.objects.all()
    serializer_class = ServiceCategorySerializer
    permission_classes = [IsAdminOrReadOnly]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['name', 'slug', 'description']
    ordering_fields = ['name', 'slug', 'sort_order', 'is_active']
    ordering = ['sort_order', 'name']

    def destroy(self, request, *args, **kwargs):
        category = self.get_object()
        if category.services.exists():
            return Response(
                {'detail': 'Cannot delete category with existing services. Deactivate it instead.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return super().destroy(request, *args, **kwargs)


@extend_schema(
    tags=['Services'],
    parameters=[
        OpenApiParameter('category', OpenApiTypes.STR, OpenApiParameter.QUERY, description='Filter by category id or slug'),
        OpenApiParameter('is_active', OpenApiTypes.BOOL, OpenApiParameter.QUERY, description='Filter by active status'),
        OpenApiParameter('search', OpenApiTypes.STR, OpenApiParameter.QUERY, description='Search by service or category name'),
    ],
)
class ServiceViewSet(viewsets.ModelViewSet):
    serializer_class = ServiceSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['name', 'description', 'category__name', 'category__slug']
    ordering_fields = ['name', 'price_usd', 'time', 'is_active', 'category__name']
    ordering = ['name']

    def get_queryset(self):
        qs = Service.objects.select_related('category').prefetch_related('items__product')
        # Filtering per spec: ?category=2 and ?is_active=, ?search=
        params = self.request.query_params
        category = params.get('category')
        if category:
            try:
                # allow filtering by id or slug
                if category.isdigit():
                    qs = qs.filter(category_id=int(category))
                else:
                    qs = qs.filter(category__slug=category)
            except ValueError:
                pass
        is_active = params.get('is_active')
        if is_active is not None:
            if is_active.lower() in ('true', '1', 'yes'):
                qs = qs.filter(is_active=True)
            elif is_active.lower() in ('false', '0', 'no'):
                qs = qs.filter(is_active=False)
        return qs


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
    queryset = (
        Visit.objects
        .select_related('customer', 'staff')
        .prefetch_related(
            'services',
            Prefetch('payments', queryset=Payment.objects.select_related('customer')),
            # Serializes the per-service operator rows without an N+1 on list.
            Prefetch(
                'service_links',
                queryset=VisitService.objects.select_related('service', 'staff'),
            ),
        )
    )
    serializer_class = VisitSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['customer__first_name', 'customer__last_name', 'customer__mobile_number', 'notes', 'status']
    ordering_fields = ['start_at', 'end_at', 'status', 'customer__first_name']
    ordering = ['-start_at']

    def perform_create(self, serializer):
        """Save, then settle compensation if the visit arrives completed.

        A payload may carry ``status: "completed"`` in its POST; without this
        the visit reached COMPLETED with no payout at all — the same bypass
        ``perform_update`` closes for PATCH. The atomic block keeps a
        rejected visit (compensable services, no operator) from persisting.
        """
        from finance.services import staff_compensation

        with transaction.atomic():
            visit = serializer.save()
            if visit.status != Visit.Status.COMPLETED:
                return
            uncovered = visit.resolve_operators()
            if uncovered:
                raise ValidationError({'status': _uncovered_operator_message(uncovered)})
            staff_compensation.generate_visit_payouts(visit, actor=self.request.user)

    def perform_update(self, serializer):
        """Update, then settle compensation if this write completed the visit.

        Without this, ``PATCH {"status": "completed"}`` reached COMPLETED with no
        staff payout at all, so compensation could be bypassed entirely by
        editing instead of using the complete action.
        """
        previous_status = serializer.instance.status
        visit = serializer.save()
        becoming_completed = (previous_status != Visit.Status.COMPLETED) and (
            visit.status == Visit.Status.COMPLETED
        )
        if not becoming_completed:
            return
        from finance.services import staff_compensation

        uncovered = visit.resolve_operators()
        if uncovered:
            # Keep the row consistent with the complete action: a compensable
            # visit is never left completed without its operators' payouts.
            visit.status = previous_status
            visit.save(update_fields=['status'])
            raise ValidationError({'status': _uncovered_operator_message(uncovered)})
        staff_compensation.generate_visit_payouts(visit, actor=self.request.user)

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
                day_start, day_end = shamsi_month_bounds(int(year), int(month))
            except ValueError:
                pass
            else:
                qs = qs.filter(start_at__gte=day_start, start_at__lte=day_end)

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
        # A visit whose services carry a compensation role must resolve an
        # operator for each of them (explicit, auto-assigned from the role, or
        # the primary staff fallback), otherwise compensation would be silently
        # skipped or booked against the wrong person. Rejected up front.
        from finance.services import staff_compensation

        uncovered = visit.resolve_operators()
        if uncovered:
            return Response(
                {'error': _uncovered_operator_message(uncovered)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        visit.status = Visit.Status.COMPLETED
        visit.save(update_fields=['status'])
        # Generate staff commission payouts for the services performed. The
        # service is idempotent (per visit/staff/service, and one row per
        # staff/role/month for fixed salaries) so a repeated completion updates
        # rather than duplicates.
        staff_compensation.generate_visit_payouts(visit, actor=request.user)
        return Response(self.get_serializer(visit).data)

    @action(detail=True, methods=['post'])
    @extend_schema(responses=VisitSerializer)
    def cancel(self, request, pk=None):
        visit = self.get_object()
        visit.status = Visit.Status.CANCELED
        visit.save(update_fields=['status'])
        # Revenue the clinic no longer keeps must not leave live compensation
        # behind, so any session payout for this visit is voided (not deleted,
        # and monthly salaries are untouched because they cover the whole month).
        from finance.services import staff_compensation

        staff_compensation.cancel_payouts_for_visit(visit, reason='visit cancelled')
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

        if not isinstance(notes, str):
            return Response({'error': 'notes must be a string'}, status=status.HTTP_400_BAD_REQUEST)

        if not isinstance(time_str, str) or not re.fullmatch(r'\d{1,2}:\d{2}', time_str.strip()):
            return Response({'error': 'Invalid date or time format'}, status=status.HTTP_400_BAD_REQUEST)

        # Contract: `date` MUST be a Jalali (Shamsi) date in YYYY-MM-DD form
        # (e.g. "1405-07-08"). A Gregorian value such as "2026-09-28" used to
        # be accepted and reinterpreted as Jalali year 2647 — the corruption
        # behind the legacy out-of-range Visits. It is now rejected with an
        # explicit message instead of being silently converted.
        if not shamsi_date_str:
            return Response(
                {'error': f'date is required and must be a Shamsi date ({SHAMSI_DATE_FORMAT}, e.g. 1405-07-08)'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            greg_date = shamsi_to_greg_date(shamsi_date_str)
        except serializers.ValidationError as exc:
            detail = exc.detail[0] if isinstance(exc.detail, list) and exc.detail else exc.detail
            return Response({'error': str(detail)}, status=status.HTTP_400_BAD_REQUEST)

        try:
            hour, minute = (int(part) for part in time_str.strip().split(':'))
            start_dt = timezone.make_aware(datetime.combine(greg_date, time(hour=hour, minute=minute)))
        except (ValueError, TypeError):
            return Response({'error': 'Invalid date or time format'}, status=status.HTTP_400_BAD_REQUEST)

        if not isinstance(customer_id, int):
            return Response({'error': 'Valid customer is required'}, status=status.HTTP_400_BAD_REQUEST)
        customer = Customer.objects.filter(id=customer_id).first()
        if customer is None:
            return Response({'error': 'Customer not found'}, status=status.HTTP_400_BAD_REQUEST)

        if (
            not isinstance(service_ids, list)
            or not service_ids
            or not all(isinstance(sid, int) for sid in service_ids)
        ):
            return Response({'error': 'services must be a non-empty list of ids'}, status=status.HTTP_400_BAD_REQUEST)

        services = list(Service.objects.filter(id__in=service_ids))
        if not services:
            return Response({'error': 'No valid services found'}, status=status.HTTP_400_BAD_REQUEST)

        total_minutes = sum(s.time for s in services)
        end_dt = start_dt + timedelta(minutes=total_minutes)

        visit = Visit.objects.create(
            customer=customer,
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
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['customer__first_name', 'customer__last_name', 'customer__id', 'customer__mobile_number']
    ordering_fields = ['paid_at', 'amount', 'payment_method']
    ordering = ['-paid_at']

    def get_queryset(self):
        qs = super().get_queryset()
        params = self.request.query_params
        visit = params.get('visit')
        if visit and visit.isdigit():
            qs = qs.filter(visit_id=int(visit))
        customer = params.get('customer')
        if customer and customer.isdigit():
            qs = qs.filter(customer_id=int(customer))
        return qs

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
                        'total_payments': Decimal('0'),
                        'count': 0,
                    }
                service_totals[key]['total_payments'] += payment.amount
                service_totals[key]['count'] += 1
        for row in service_totals.values():
            row['total_payments'] = float(row['total_payments'])
        return Response(list(service_totals.values()))
