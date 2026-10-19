from datetime import date, datetime
from decimal import Decimal

import jdatetime
from django.db.models import Sum
from django.utils import timezone
from drf_spectacular.utils import OpenApiExample, OpenApiParameter, OpenApiTypes, extend_schema, inline_serializer
from rest_framework import filters, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import IsAdmin, IsAdminOrReadOnly
from Sefro_Clinic.fields import greg_to_shamsi_date, greg_to_shamsi_dt, shamsi_to_greg_date
from Sefro_Clinic.periods import (
    SHAMSI_YEAR_MAX,
    SHAMSI_YEAR_MIN,
    parse_shamsi_date,
    shamsi_day_bounds,
    shamsi_month_bounds,
    shamsi_of,
    shamsi_period_bounds,
    shamsi_prev_month,
)

from .models import (
    ExchangeRate,
    Expense,
    ExpenseCategory,
    OperatingExpense,
    OperatingExpenseCategory,
    Package,
    PackageItem,
    PackageService,
    ProductCostHistory,
    ProductPurchase,
    ProductUsage,
    PurchaseOrder,
    Sale,
    ServiceItem,
    StaffCompensationRule,
    StaffPayout,
    Wallet,
    WalletRewardRule,
    WalletTransaction,
    WelcomePack,
    WelcomePackItem,
    WelcomePackUsage,
)
from .permissions import IsEmployeeOrAdmin
from .serializers import (
    CheckoutSerializer,
    ExchangeRateSerializer,
    ExpenseCategorySerializer,
    ExpenseSerializer,
    MonthlyCloseReopenSerializer,
    MonthlyCloseRequestSerializer,
    OperatingExpenseCategorySerializer,
    OperatingExpenseSerializer,
    PackageItemSerializer,
    PackageSerializer,
    PackageServiceSerializer,
    ProductCostHistorySerializer,
    ProductPurchaseSerializer,
    ProductUsageSerializer,
    PurchaseOrderSerializer,
    RefundSerializer,
    SaleSerializer,
    ServiceItemSerializer,
    StaffCompensationRuleSerializer,
    StaffPayoutSerializer,
    WalletRewardRuleSerializer,
    WalletSerializer,
    WalletTransactionSerializer,
    WelcomePackItemSerializer,
    WelcomePackSerializer,
    WelcomePackUsageSerializer,
)
from .services import accounting, closing, financials, payments, reporting, staff_compensation
from .services import expenses as expense_svc
from .services import operating_expenses as opex_svc
from .services import purchases as purchase_svc
from .services import welcome_pack as welcome_pack_svc
from .services.exchange_rates import get_rate
from .services.periods_guard import PeriodClosedError, ensure_open
from .services.wallet import InsufficientFunds


def _stringify(obj):
    """JSON-safe rendering for report payloads.

    Dates and datetimes render as **Shamsi** strings — the same calendar
    every request parameter uses — never as Gregorian ISO.
    """
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, dict):
        return {k: _stringify(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_stringify(v) for v in obj]
    if isinstance(obj, datetime):
        return greg_to_shamsi_dt(obj)
    if isinstance(obj, date):
        return greg_to_shamsi_date(obj)
    return obj


def _resolve_range(request):
    """The window a report request asks for, as aware ``(start, end)``.

    **Every calendar in here is Shamsi.** Priority order:

    1. ``?year=&month=`` — any Shamsi month, ever (month navigation);
    2. ``?period=`` — Shamsi windows of *now*: ``today``, ``this_week``
       (Saturday-start), ``this_month``, ``prev_month``, ``this_year``
       (Farvardin..Esfand);
    3. ``?start_date=&end_date=`` — explicit **Shamsi** ``YYYY-MM-DD`` days;
    4. fallback: the current Shamsi day.
    """
    period = request.query_params.get('period')

    # Shamsi month navigation (?year=1405&month=5), the same convention the
    # customers report endpoints already use. Checked before `period` so a
    # caller can jump to any past month, not just the built-in windows.
    shamsi_year = request.query_params.get('year')
    shamsi_month = request.query_params.get('month')
    if shamsi_year and shamsi_month:
        try:
            month_number = int(str(shamsi_month).split('-')[-1])
            return shamsi_month_bounds(int(shamsi_year), month_number)
        except (TypeError, ValueError):
            pass

    now = timezone.localtime(timezone.now())
    if period == 'today':
        return shamsi_period_bounds('daily', now)
    if period == 'this_week':
        return shamsi_period_bounds('weekly', now)
    if period == 'this_month':
        return shamsi_period_bounds('monthly', now)
    if period == 'prev_month':
        return shamsi_month_bounds(*shamsi_prev_month(*shamsi_of(now)))
    if period == 'this_year':
        return shamsi_period_bounds('yearly', now)

    def _shamsi_bound(value, *, as_end=False):
        """An explicit query date as one end of a Shamsi-day window.

        Garbage (``not-a-date``) is ignored so the fallback below applies —
        that tolerance is a tested contract. A structurally valid date whose
        year falls outside the Shamsi window is rejected loudly: it is a
        Gregorian date, and silently reinterpreting it would shift the report
        by centuries.
        """
        day = parse_shamsi_date(value)
        if day is None:
            return None
        if not SHAMSI_YEAR_MIN <= day.year <= SHAMSI_YEAR_MAX:
            raise serializers.ValidationError(
                f'Invalid Shamsi (Jalali) date: "{value}". Shamsi year must be '
                f'between {SHAMSI_YEAR_MIN} and {SHAMSI_YEAR_MAX}; {day.year} '
                f'looks like a Gregorian year. Send a Jalali date (e.g. 1405-07-08).'
            )
        start_dt, end_dt = shamsi_day_bounds(day)
        return end_dt if as_end else start_dt

    start_dt = _shamsi_bound(request.query_params.get('start_date'))
    end_dt = _shamsi_bound(request.query_params.get('end_date'), as_end=True)

    # Fall back to the current Shamsi day when no usable range was supplied.
    # This mirrors the service-layer convention (services/reporting.py::_range
    # and services/staff_compensation.py::staff_payout_summary).
    if not start_dt or not end_dt:
        fallback_start, fallback_end = shamsi_day_bounds(
            jdatetime.date.fromgregorian(date=now.date()),
        )
        start_dt = start_dt or fallback_start
        end_dt = end_dt or fallback_end

    return start_dt, end_dt


def _query_int(params, name):
    """A numeric query param as int, or None when absent/empty.

    Garbage is a client error (400), never a 500 bubbling out of the ORM's
    int coercion. A well-formed but nonexistent id is left to the filter:
    it matches nothing and the report comes back zero-filled (200).
    """
    raw = params.get(name)
    if raw in (None, ''):
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise serializers.ValidationError({name: 'Must be an integer.'})


@extend_schema(tags=['Exchange Rates'])
class ExchangeRateViewSet(viewsets.ModelViewSet):
    queryset = ExchangeRate.objects.all()
    serializer_class = ExchangeRateSerializer
    permission_classes = [IsAdminOrReadOnly]
    filter_backends = [filters.OrderingFilter]
    ordering = ['-effective_at']


@extend_schema(tags=['Wallet'])
class WalletRewardRuleViewSet(viewsets.ModelViewSet):
    queryset = WalletRewardRule.objects.all()
    serializer_class = WalletRewardRuleSerializer
    permission_classes = [IsAdminOrReadOnly]


@extend_schema(tags=['Packages'])
class PackageViewSet(viewsets.ModelViewSet):
    queryset = Package.objects.all()
    serializer_class = PackageSerializer
    permission_classes = [IsAdminOrReadOnly]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['name']
    ordering_fields = ['name', 'price_usd', 'created_at']


@extend_schema(tags=['Services'])
class ServiceItemViewSet(viewsets.ModelViewSet):
    queryset = ServiceItem.objects.select_related('service', 'product')
    serializer_class = ServiceItemSerializer
    permission_classes = [IsAdminOrReadOnly]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['service__name', 'product__name']
    ordering_fields = ['service__name', 'product__name', 'quantity']


@extend_schema(tags=['Packages'])
class PackageItemViewSet(viewsets.ModelViewSet):
    queryset = PackageItem.objects.all()
    serializer_class = PackageItemSerializer
    permission_classes = [IsAdminOrReadOnly]


@extend_schema(tags=['Packages'])
class PackageServiceViewSet(viewsets.ModelViewSet):
    queryset = PackageService.objects.all()
    serializer_class = PackageServiceSerializer
    permission_classes = [IsAdminOrReadOnly]


@extend_schema(tags=['Finance'])
class ProductCostHistoryViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = ProductCostHistory.objects.all()
    serializer_class = ProductCostHistorySerializer
    permission_classes = [IsEmployeeOrAdmin]


DATE_PARAMS = [
    OpenApiParameter('date_from', OpenApiTypes.STR, OpenApiParameter.QUERY,
                     description='Jalali (Shamsi) date YYYY-MM-DD, inclusive.'),
    OpenApiParameter('date_to', OpenApiTypes.STR, OpenApiParameter.QUERY,
                     description='Jalali (Shamsi) date YYYY-MM-DD, inclusive.'),
    OpenApiParameter('start_date', OpenApiTypes.STR, OpenApiParameter.QUERY,
                     description='Jalali (Shamsi) inclusive start — same calendar as date_from.'),
    OpenApiParameter('end_date', OpenApiTypes.STR, OpenApiParameter.QUERY,
                     description='Jalali (Shamsi) inclusive end — same calendar as date_to.'),
]


#: Shamsi year/month navigation, shared by every period report that accepts it.
SHAMSI_MONTH_PARAMS = [
    OpenApiParameter(
        'year', OpenApiTypes.INT, OpenApiParameter.QUERY,
        description='Shamsi (Jalali) year, e.g. 1405. Only used together with `month`.',
    ),
    OpenApiParameter(
        'month', OpenApiTypes.STR, OpenApiParameter.QUERY,
        description="Shamsi month: 1-12, or a full key such as '1405-05'. Only used with `year`.",
    ),
]


def _apply_date_range(qs, request, field='created_at'):
    """Narrow ``qs`` by the period the caller asked for.

    All four date parameters are Jalali ``YYYY-MM-DD`` strings and inclusive:
    ``date_from``/``date_to`` are the list-filter names, ``start_date``/
    ``end_date`` are the same Shamsi dates under the report-window names —
    one calendar everywhere. A Gregorian value is rejected with 400 rather
    than silently reinterpreted. Omitting every parameter leaves the
    queryset untouched, so unfiltered list calls are unaffected.
    """

    params = request.query_params
    date_from = params.get('date_from')
    date_to = params.get('date_to')
    if date_from:
        qs = qs.filter(**{f'{field}__date__gte': shamsi_to_greg_date(date_from)})
    if date_to:
        qs = qs.filter(**{f'{field}__date__lte': shamsi_to_greg_date(date_to)})
    if params.get('start_date'):
        qs = qs.filter(**{f'{field}__date__gte': shamsi_to_greg_date(params['start_date'])})
    if params.get('end_date'):
        qs = qs.filter(**{f'{field}__date__lte': shamsi_to_greg_date(params['end_date'])})
    return qs


@extend_schema(tags=['Finance'], parameters=DATE_PARAMS)
class ProductUsageViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = ProductUsage.objects.all()
    serializer_class = ProductUsageSerializer
    permission_classes = [IsEmployeeOrAdmin]

    def get_queryset(self):
        qs = super().get_queryset()
        params = self.request.query_params
        if params.get('visit'):
            qs = qs.filter(visit_id=params['visit'])
        if params.get('service'):
            qs = qs.filter(service_id=params['service'])
        if params.get('product'):
            qs = qs.filter(product_id=params['product'])
        if params.get('package_sale'):
            qs = qs.filter(package_sale_id=params['package_sale'])
        if params.get('customer'):
            qs = qs.filter(customer_id=params['customer'])
        qs = _apply_date_range(qs, self.request)
        return qs.select_related(
            'product', 'visit', 'service', 'package_sale', 'welcome_pack_usage', 'customer',
        )


@extend_schema(tags=['Wallet'])
class WalletViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Wallet.objects.all()
    serializer_class = WalletSerializer
    permission_classes = [IsEmployeeOrAdmin]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['customer__first_name', 'customer__last_name', 'customer__mobile_number']
    ordering_fields = ['balance', 'created_at']

    @extend_schema(
        request=inline_serializer(
            'WalletAdjustRequest',
            fields={
                'amount_usd': serializers.DecimalField(max_digits=14, decimal_places=2),
                'direction': serializers.ChoiceField(choices=['credit', 'debit']),
                'transaction_type': serializers.ChoiceField(
                    choices=['manual_credit', 'manual_debit', 'adjustment']
                ),
                'description': serializers.CharField(required=False, allow_blank=True),
            },
        ),
        responses=WalletTransactionSerializer,
    )
    @action(detail=True, methods=['post'], permission_classes=[IsAdmin])
    def adjust(self, request, pk=None):
        from .services.wallet import InsufficientFunds, manual_adjust
        wallet = self.get_object()
        try:
            amount = Decimal(str(request.data.get('amount_usd', '0')))
            direction = request.data.get('direction', 'credit')
            txn_type = request.data.get('transaction_type', 'manual_credit')
            if direction == 'debit':
                amount = -amount
            if txn_type not in (WalletTransaction.Type.MANUAL_CREDIT, WalletTransaction.Type.MANUAL_DEBIT, WalletTransaction.Type.ADJUSTMENT):
                txn_type = WalletTransaction.Type.MANUAL_CREDIT if amount >= 0 else WalletTransaction.Type.MANUAL_DEBIT
            txn = manual_adjust(
                wallet, amount, txn_type,
                description=request.data.get('description', ''),
            )
        except InsufficientFunds as exc:
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as exc:
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(WalletTransactionSerializer(txn).data, status=status.HTTP_201_CREATED)


@extend_schema(tags=['Wallet'])
class WalletTransactionViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = WalletTransaction.objects.all()
    serializer_class = WalletTransactionSerializer
    permission_classes = [IsEmployeeOrAdmin]
    filter_backends = [filters.OrderingFilter]
    ordering = ['-created_at']

    def get_queryset(self):
        qs = super().get_queryset()
        wallet_id = self.request.query_params.get('wallet')
        if wallet_id:
            qs = qs.filter(wallet_id=wallet_id)
        return qs.select_related('wallet', 'wallet__customer')


@extend_schema(tags=['Finance'])
class SaleViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Sale.objects.all()
    serializer_class = SaleSerializer
    permission_classes = [IsEmployeeOrAdmin]
    filter_backends = [filters.OrderingFilter, filters.SearchFilter]
    ordering = ['-created_at']
    search_fields = ['customer__first_name', 'customer__last_name']

    def get_queryset(self):
        qs = super().get_queryset()
        params = self.request.query_params
        if params.get('customer'):
            qs = qs.filter(customer_id=params['customer'])
        if params.get('status'):
            qs = qs.filter(status=params['status'])
        if params.get('package'):
            qs = qs.filter(package_id=params['package'])
        return qs.select_related('customer', 'visit', 'package')

    @extend_schema(request=RefundSerializer, responses=SaleSerializer)
    @action(detail=True, methods=['post'], permission_classes=[IsEmployeeOrAdmin])
    def refund(self, request, pk=None):
        sale = self.get_object()
        serializer = RefundSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            refund = payments.refund_sale(
                sale,
                refund_amount_usd=serializer.validated_data.get('refund_amount_usd'),
                reason=serializer.validated_data.get('reason', ''),
                user=request.user,
            )
        except payments.PaymentError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except PeriodClosedError as exc:
            # The sale's month is closed: refunds are frozen until reopened.
            return Response({'error': str(exc)}, status=status.HTTP_409_CONFLICT)
        return Response(SaleSerializer(refund).data, status=status.HTTP_201_CREATED)


@extend_schema(tags=['Expenses'])
class ExpenseCategoryViewSet(viewsets.ModelViewSet):
    queryset = ExpenseCategory.objects.all()
    serializer_class = ExpenseCategorySerializer
    permission_classes = [IsAdminOrReadOnly]


@extend_schema(tags=['Expenses'])
class ExpenseViewSet(viewsets.ModelViewSet):
    queryset = Expense.objects.all()
    serializer_class = ExpenseSerializer
    permission_classes = [IsEmployeeOrAdmin]
    filter_backends = [filters.OrderingFilter, filters.SearchFilter]
    ordering = ['-expense_date', '-created_at']
    search_fields = ['vendor', 'description']

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        params = self.request.query_params
        if not user.is_admin_user:
            qs = qs.filter(created_by=user)
        if params.get('status'):
            qs = qs.filter(status=params['status'])
        if params.get('category'):
            qs = qs.filter(category_id=params['category'])
        return qs.select_related('created_by', 'approved_by', 'category')

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            expense = expense_svc.create_expense(
                created_by=request.user,
                category=data['category'],
                amount_usd=data['amount_usd'],
                expense_date=data['expense_date'],
                vendor=data.get('vendor', ''),
                description=data.get('description', ''),
            )
        except expense_svc.ExpenseError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(ExpenseSerializer(expense, context=self.get_serializer_context()).data, status=status.HTTP_201_CREATED)

    def _update(self, request, *args, **kwargs):
        """Update a claim, re-pricing it when the USD amount changes.

        ``amount_toman`` and ``exchange_rate_snapshot`` are read-only, so
        without this a PATCH of ``amount_usd`` would leave the claim priced at
        the old rate and silently corrupt the expense reports.
        """
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        # Guard BEFORE serializer.save(): otherwise a PATCH into a closed
        # month would write the fields first and only then fail on re-price.
        ensure_open(
            instance.expense_date, action='edit an expense claim',
            user=request.user, object_repr=f'Expense#{instance.id}',
        )
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        new_amount_usd = data.get('amount_usd')
        reprice = new_amount_usd is not None and Decimal(new_amount_usd) != instance.amount_usd
        expense = serializer.save()
        if reprice:
            try:
                expense = expense_svc.reprice_expense(expense, new_amount_usd)
            except Exception as exc:  # noqa: BLE001 - surface as 400, never 500
                return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(ExpenseSerializer(expense, context=self.get_serializer_context()).data)

    def update(self, request, *args, **kwargs):
        kwargs['partial'] = False
        return self._update(request, *args, **kwargs)

    def partial_update(self, request, *args, **kwargs):
        kwargs['partial'] = True
        return self._update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        # Deleting a claim rewrites the month it was booked into; the default
        # ModelViewSet path would bypass the service guard entirely.
        expense = self.get_object()
        ensure_open(
            expense.expense_date, action='delete an expense claim',
            user=request.user, object_repr=f'Expense#{expense.id}',
        )
        return super().destroy(request, *args, **kwargs)

    @action(detail=True, methods=['post'], permission_classes=[IsEmployeeOrAdmin])
    def submit(self, request, pk=None):
        expense = self.get_object()
        try:
            expense_svc.submit_expense(expense)
        except expense_svc.ExpenseError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(ExpenseSerializer(expense, context=self.get_serializer_context()).data)

    @action(detail=True, methods=['post'], permission_classes=[IsAdmin])
    def approve(self, request, pk=None):
        expense = self.get_object()
        try:
            expense_svc.approve_expense(expense, request.user)
        except expense_svc.ExpenseError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(ExpenseSerializer(expense, context=self.get_serializer_context()).data)

    @action(detail=True, methods=['post'], permission_classes=[IsAdmin])
    def reject(self, request, pk=None):
        expense = self.get_object()
        try:
            expense_svc.reject_expense(expense, request.user)
        except expense_svc.ExpenseError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(ExpenseSerializer(expense, context=self.get_serializer_context()).data)

    @action(detail=True, methods=['post'], permission_classes=[IsAdmin])
    def pay(self, request, pk=None):
        expense = self.get_object()
        try:
            expense_svc.pay_expense(expense, request.user)
        except expense_svc.ExpenseError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(ExpenseSerializer(expense, context=self.get_serializer_context()).data)

    @action(detail=True, methods=['post'], permission_classes=[IsEmployeeOrAdmin])
    def cancel(self, request, pk=None):
        expense = self.get_object()
        if not request.user.is_admin_user and expense.created_by_id != request.user.id:
            return Response({'error': 'Not allowed.'}, status=status.HTTP_403_FORBIDDEN)
        try:
            expense_svc.cancel_expense(expense)
        except expense_svc.ExpenseError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(ExpenseSerializer(expense, context=self.get_serializer_context()).data)


@extend_schema(tags=['Finance'])
class ProductPurchaseViewSet(viewsets.ModelViewSet):
    queryset = ProductPurchase.objects.all()
    serializer_class = ProductPurchaseSerializer
    permission_classes = [IsAdminOrReadOnly]
    filter_backends = [filters.OrderingFilter]
    ordering = ['-purchase_date', '-created_at']

    def perform_create(self, serializer):
        from .services.inventory import record_product_purchase
        data = serializer.validated_data
        purchase = record_product_purchase(
            product=data['product'],
            quantity=data['quantity'],
            unit_cost_usd=data['unit_cost_usd'],
            supplier=data.get('supplier', ''),
            purchase_date=data.get('purchase_date'),
        )
        serializer.instance = purchase

    def destroy(self, request, *args, **kwargs):
        purchase = self.get_object()
        ensure_open(
            purchase.purchase_date, action='delete a product purchase',
            user=request.user, object_repr=f'ProductPurchase#{purchase.id}',
        )
        return super().destroy(request, *args, **kwargs)


@extend_schema(tags=['Finance'])
class CheckoutView(APIView):
    permission_classes = [IsEmployeeOrAdmin]

    @extend_schema(request=CheckoutSerializer, responses=SaleSerializer)
    def post(self, request):
        serializer = CheckoutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        from customers.models import Customer, Visit

        from .models import Package as PackageModel
        try:
            customer = Customer.objects.get(id=data['customer'])
        except Customer.DoesNotExist:
            return Response({'error': 'Customer not found.'}, status=status.HTTP_400_BAD_REQUEST)
        visit = None
        if data.get('visit'):
            visit = Visit.objects.filter(id=data['visit']).first()
        package = None
        if data.get('package'):
            package = PackageModel.objects.filter(id=data['package']).first()
        try:
            sale = payments.checkout(
                customer=customer,
                amount_usd=data['amount_usd'],
                components=data['components'],
                discount_usd=data.get('discount_usd', Decimal('0')),
                visit=visit,
                package=package,
                idempotency_key=data.get('idempotency_key') or None,
                description=data.get('description', ''),
            )
        except (payments.PaymentError, InsufficientFunds) as exc:
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(SaleSerializer(sale).data, status=status.HTTP_201_CREATED)


@extend_schema(tags=['Finance'])
class RecordConsumptionView(APIView):
    permission_classes = [IsEmployeeOrAdmin]

    @extend_schema(
        parameters=[OpenApiParameter('pk', OpenApiTypes.INT, OpenApiParameter.PATH)],
        request=inline_serializer(
            name='RecordConsumptionRequest',
            fields={
                'selected_products': serializers.DictField(
                    required=False,
                    help_text=(
                        'Mapping of service ID to actual [product ID, quantity] pairs. '
                        'Recipe quantities are estimates; submit actual quantities.'
                    ),
                ),
                'zero_consumption': serializers.DictField(
                    required=False,
                    help_text='Mapping of service ID to a required reason when no recipe product was used.',
                ),
                'extra_products': serializers.ListField(
                    required=False,
                    help_text=(
                        'Optional list of [product_id, quantity] pairs for billable '
                        'non-recipe products (manual invoice extras). Deducts stock '
                        'and records cost snapshots.'
                    ),
                ),
            },
        ),
        responses=ProductUsageSerializer(many=True),
        examples=[
            OpenApiExample(
                'Alternative selections',
                value={'selected_products': {'10': [[21, '1.000'], [35, '1.000']]}},
                request_only=True,
            ),
            OpenApiExample(
                'Manual extras',
                value={'selected_products': {'10': [[21, '1.000']]}, 'extra_products': [[99, '2']]},
                request_only=True,
            ),
        ],
    )
    def post(self, request, pk):
        from customers.models import Visit
        visit = Visit.objects.filter(id=pk).first()
        if not visit:
            return Response({'error': 'Visit not found.'}, status=status.HTTP_404_NOT_FOUND)
        selected = request.data.get('selected_products')
        extras = request.data.get('extra_products')
        zero_consumption = request.data.get('zero_consumption')
        try:
            usages = accounting.record_visit_consumption(
                visit, selected_products=selected, extra_products=extras,
                zero_consumption=zero_consumption,
            )
        except Exception as exc:
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(ProductUsageSerializer(usages, many=True).data, status=status.HTTP_201_CREATED)


@extend_schema(tags=['Reports'])
class FinancialSummaryView(APIView):
    permission_classes = [IsEmployeeOrAdmin]

    @extend_schema(
        parameters=[
            *SHAMSI_MONTH_PARAMS,
            OpenApiParameter('start_date', OpenApiTypes.STR, OpenApiParameter.QUERY),
            OpenApiParameter('end_date', OpenApiTypes.STR, OpenApiParameter.QUERY),
            OpenApiParameter('period', OpenApiTypes.STR, OpenApiParameter.QUERY),
            OpenApiParameter('service', OpenApiTypes.INT, OpenApiParameter.QUERY),
            OpenApiParameter('package', OpenApiTypes.INT, OpenApiParameter.QUERY),
            OpenApiParameter('product', OpenApiTypes.INT, OpenApiParameter.QUERY),
            OpenApiParameter('personnel', OpenApiTypes.INT, OpenApiParameter.QUERY),
        ],
    )
    def get(self, request):
        start, end = _resolve_range(request)
        params = request.query_params
        result = reporting.financial_summary(
            start, end,
            service_id=_query_int(params, 'service'),
            package_id=_query_int(params, 'package'),
            product_id=_query_int(params, 'product'),
            personnel_id=_query_int(params, 'personnel'),
        )
        return Response(_stringify(result))


@extend_schema(tags=['Reports'])
class ProfitByServiceView(APIView):
    permission_classes = [IsEmployeeOrAdmin]

    @extend_schema(
        parameters=[
            OpenApiParameter('start_date', OpenApiTypes.STR, OpenApiParameter.QUERY),
            OpenApiParameter('end_date', OpenApiTypes.STR, OpenApiParameter.QUERY),
            OpenApiParameter('period', OpenApiTypes.STR, OpenApiParameter.QUERY),
        ],
    )
    def get(self, request):
        start, end = _resolve_range(request)
        return Response(_stringify(reporting.profit_by_service(start, end)))


@extend_schema(tags=['Reports'])
class ProfitByPackageView(APIView):
    permission_classes = [IsEmployeeOrAdmin]

    @extend_schema(
        parameters=[
            OpenApiParameter('start_date', OpenApiTypes.STR, OpenApiParameter.QUERY),
            OpenApiParameter('end_date', OpenApiTypes.STR, OpenApiParameter.QUERY),
            OpenApiParameter('period', OpenApiTypes.STR, OpenApiParameter.QUERY),
        ],
    )
    def get(self, request):
        start, end = _resolve_range(request)
        return Response(_stringify(reporting.profit_by_package(start, end)))


@extend_schema(tags=['Wallet'])
class WalletSummaryView(APIView):
    permission_classes = [IsEmployeeOrAdmin]

    def get(self, request):
        return Response(_stringify(reporting.wallet_summary()))


@extend_schema(tags=['Reports'])
class ExchangeRateReportView(APIView):
    permission_classes = [IsEmployeeOrAdmin]

    @extend_schema(
        parameters=[
            OpenApiParameter('usd', OpenApiTypes.NUMBER, OpenApiParameter.QUERY, description='Optional USD amount to convert to Toman'),
            OpenApiParameter('amount', OpenApiTypes.NUMBER, OpenApiParameter.QUERY, description='Alias for usd'),
            OpenApiParameter('amount_usd', OpenApiTypes.NUMBER, OpenApiParameter.QUERY, description='Alias for usd'),
        ],
        responses=inline_serializer(
            name='ExchangeRateReport',
            fields={
                'currency_from': serializers.CharField(),
                'currency_to': serializers.CharField(),
                'rate': serializers.CharField(),
                'rate_toman_per_usd': serializers.CharField(),
                'effective_at': serializers.CharField(allow_null=True),
                'source': serializers.CharField(),
                'amount_usd': serializers.CharField(required=False),
                'amount_toman': serializers.CharField(required=False),
            },
        ),
    )
    def get(self, request):
        from .services.exchange_rates import convert_usd_to_toman, get_current_usd_to_toman_rate

        rate = get_current_usd_to_toman_rate()
        if rate is None:
            return Response({'detail': 'Exchange rate unavailable. Configure a valid rate via /api/finance/exchange-rates/ or external provider.'}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        latest = ExchangeRate.objects.filter(currency_from='USD', currency_to='TOMAN', is_active=True).order_by('-effective_at').first()
        data = {
            'currency_from': 'USD',
            'currency_to': 'TOMAN',
            'rate': str(rate),
            'rate_toman_per_usd': str(rate),
            'effective_at': greg_to_shamsi_dt(latest.effective_at) if latest else None,
            'source': latest.source if latest and latest.source else 'fallback',
        }
        # Optional conversion: ?usd=100 or ?amount=100
        raw_amount = request.query_params.get('usd') or request.query_params.get('amount') or request.query_params.get('amount_usd')
        if raw_amount is not None:
            try:
                amt = Decimal(str(raw_amount))
            except Exception:
                return Response({'detail': 'Invalid amount. Must be numeric.'}, status=status.HTTP_400_BAD_REQUEST)
            if amt < 0:
                return Response({'detail': 'Amount must be non-negative.'}, status=status.HTTP_400_BAD_REQUEST)
            data['amount_usd'] = str(amt.quantize(Decimal('0.01')))
            data['amount_toman'] = str(convert_usd_to_toman(amt, rate))
        return Response(data)


@extend_schema(tags=['Reports'])
class BackupExchangeRateReportView(APIView):
    permission_classes = [IsEmployeeOrAdmin]

    @extend_schema(
        parameters=[
            OpenApiParameter('usd', OpenApiTypes.NUMBER, OpenApiParameter.QUERY, description='Optional USD amount to convert to Toman (via backup provider)'),
            OpenApiParameter('amount', OpenApiTypes.NUMBER, OpenApiParameter.QUERY, description='Alias for usd'),
            OpenApiParameter('amount_usd', OpenApiTypes.NUMBER, OpenApiParameter.QUERY, description='Alias for usd'),
        ],
        responses=inline_serializer(
            name='BackupExchangeRateReport',
            fields={
                'currency_from': serializers.CharField(),
                'currency_to': serializers.CharField(),
                'rate': serializers.CharField(),
                'rate_toman_per_usd': serializers.CharField(),
                'effective_at': serializers.CharField(allow_null=True),
                'source': serializers.CharField(),
                'provider': serializers.CharField(),
                'amount_usd': serializers.CharField(required=False),
                'amount_toman': serializers.CharField(required=False),
            },
        ),
    )
    def get(self, request):
        from .services.exchange_rates import BrsApiExchangeRateProvider, convert_usd_to_toman

        provider = BrsApiExchangeRateProvider()
        rate = provider.get_usd_to_toman_rate()
        if rate is None:
            return Response(
                {'detail': 'Backup exchange rate unavailable. Configure EXCHANGE_RATE_BACKUP_API_KEY and check BrsApi connectivity.'},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        data = {
            'currency_from': 'USD',
            'currency_to': 'TOMAN',
            'rate': str(rate),
            'rate_toman_per_usd': str(rate),
            'effective_at': greg_to_shamsi_dt(timezone.now()),
            'source': 'brsapi',
            'provider': 'BrsApi.ir',
        }
        raw_amount = request.query_params.get('usd') or request.query_params.get('amount') or request.query_params.get('amount_usd')
        if raw_amount is not None:
            try:
                amt = Decimal(str(raw_amount))
            except Exception:
                return Response({'detail': 'Invalid amount. Must be numeric.'}, status=status.HTTP_400_BAD_REQUEST)
            if amt < 0:
                return Response({'detail': 'Amount must be non-negative.'}, status=status.HTTP_400_BAD_REQUEST)
            data['amount_usd'] = str(amt.quantize(Decimal('0.01')))
            data['amount_toman'] = str(convert_usd_to_toman(amt, rate))
        return Response(data)


@extend_schema(tags=['Staff Compensation'])
class StaffCompensationRuleViewSet(viewsets.ModelViewSet):
    queryset = StaffCompensationRule.objects.prefetch_related('product_lines__product')
    serializer_class = StaffCompensationRuleSerializer
    permission_classes = [IsAdmin]
    filter_backends = [filters.OrderingFilter]
    ordering = ['role']


#: Date/period query parameters shared by every payout report.
PAYOUT_RANGE_PARAMS = [
    OpenApiParameter('start_date', OpenApiTypes.STR, OpenApiParameter.QUERY),
    OpenApiParameter('end_date', OpenApiTypes.STR, OpenApiParameter.QUERY),
    OpenApiParameter('period', OpenApiTypes.STR, OpenApiParameter.QUERY),
]
#: ``status`` documents the default: only payouts still owed.
PAYOUT_STATUS_PARAM = OpenApiParameter(
    'status', OpenApiTypes.STR, OpenApiParameter.QUERY,
    description="Defaults to the payouts still owed (pending, approved, paid). "
                "Pass 'all' to include cancelled rows in the ledger.",
)
PAYOUT_SUMMARY_PARAMS = PAYOUT_RANGE_PARAMS + [
    OpenApiParameter('staff', OpenApiTypes.INT, OpenApiParameter.QUERY),
    OpenApiParameter('role', OpenApiTypes.STR, OpenApiParameter.QUERY),
    PAYOUT_STATUS_PARAM,
]
PAYOUT_DETAIL_PARAMS = PAYOUT_RANGE_PARAMS + [
    OpenApiParameter('staff', OpenApiTypes.INT, OpenApiParameter.QUERY),
    PAYOUT_STATUS_PARAM,
]


def _staff_payout_summary_payload(request):
    """The single implementation behind both payout-summary routes.

    ``/api/finance/reports/staff-payout-summary/`` (Reports) and
    ``/api/finance/staff-payouts/summary/`` (Staff Compensation) are two
    documented doors onto the same number, so the range resolution and
    parameter parsing live here rather than drifting apart in two views.
    """
    start, end = _resolve_range(request)
    params = request.query_params
    return _stringify(staff_compensation.staff_payout_summary(
        start, end,
        staff_id=_query_int(params, 'staff'),
        role=params.get('role'),
        status=params.get('status'),
    ))


@extend_schema(tags=['Staff Compensation'], parameters=DATE_PARAMS)
class StaffPayoutViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = StaffPayout.objects.select_related('staff', 'visit', 'service', 'payout_product').prefetch_related(
        'product_lines__product',
    )
    serializer_class = StaffPayoutSerializer
    permission_classes = [IsEmployeeOrAdmin]
    filter_backends = [filters.OrderingFilter, filters.SearchFilter]
    ordering = ['-created_at']
    search_fields = ['staff__username', 'staff__first_name', 'staff__last_name', 'service__name']

    def get_queryset(self):
        qs = super().get_queryset()
        params = self.request.query_params
        if params.get('staff'):
            qs = qs.filter(staff_id=params['staff'])
        if params.get('role'):
            qs = qs.filter(role=params['role'])
        if params.get('status'):
            qs = qs.filter(status=params['status'])
        if params.get('visit'):
            qs = qs.filter(visit_id=params['visit'])
        return _apply_date_range(qs, self.request)

    @extend_schema(
        parameters=PAYOUT_SUMMARY_PARAMS,
        responses=inline_serializer(
            name='StaffPayoutSummary',
            fields={
                'period': inline_serializer('Period', fields={'start': OpenApiTypes.DATETIME, 'end': OpenApiTypes.DATETIME}),
                'total_cash_usd': serializers.CharField(),
                'total_cash_toman': serializers.CharField(),
                'total_product_value_usd': serializers.CharField(),
                'total_product_value_toman': serializers.CharField(),
                'total_payout_usd': serializers.CharField(),
                'total_payout_toman': serializers.CharField(),
                'payout_count': serializers.IntegerField(),
            },
        ),
    )
    @action(detail=False, methods=['get'])
    def summary(self, request):
        return Response(_staff_payout_summary_payload(request))

    @extend_schema(parameters=PAYOUT_DETAIL_PARAMS)
    @action(detail=False, methods=['get'])
    def detail_report(self, request):
        start, end = _resolve_range(request)
        params = request.query_params
        data = staff_compensation.staff_payout_detail(
            start, end,
            staff_id=_query_int(params, 'staff'),
            status=params.get('status'),
        )
        return Response(_stringify(data))


@extend_schema(tags=['Reports'])
class StaffPayoutSummaryView(APIView):
    """Reports-tagged door onto the same payout summary.

    Kept because clients already call it; the numbers come from
    :func:`_staff_payout_summary_payload`, shared with
    ``/api/finance/staff-payouts/summary/``.
    """

    permission_classes = [IsEmployeeOrAdmin]

    @extend_schema(parameters=PAYOUT_SUMMARY_PARAMS)
    def get(self, request):
        return Response(_staff_payout_summary_payload(request))


@extend_schema(tags=['Reports'])
class ProfitByStaffView(APIView):
    """Clinic profitability per staff member -- not a payslip.

    Reads completed visits in the window and answers "what did this person's
    work earn the clinic": revenue, material cost, welcome-pack cost and the
    clinic's share. ``operator_compensation_usd`` is the obligation recorded in
    the payout ledger (pending/approved/paid only), so it lines up with
    ``/reports/staff-payout-summary/`` for the same window -- but the two are
    deliberately not forced to match:

    * this report is keyed on ``Visit.start_at`` (when the work happened),
      the payout summary on ``StaffPayout.created_at`` (when the debt was
      recorded), so a payout booked for a visit outside the window will
      differ;
    * this report only sees visits attributable to an operator (a primary staff
      member or per-service operators); the summary counts
      every payout, including monthly salaries that have no visit.

    For what is actually owed, use the payout endpoints in the Staff
    Compensation category. For a whole Shamsi year, month by month, with the
    P&L and the operator pay side by side, use ``/reports/monthly-close/``.
    """

    permission_classes = [IsEmployeeOrAdmin]

    @extend_schema(
        parameters=[
            *SHAMSI_MONTH_PARAMS,
            OpenApiParameter('start_date', OpenApiTypes.STR, OpenApiParameter.QUERY),
            OpenApiParameter('end_date', OpenApiTypes.STR, OpenApiParameter.QUERY),
            OpenApiParameter('period', OpenApiTypes.STR, OpenApiParameter.QUERY),
        ],
    )
    def get(self, request):
        from customers.models import Visit, VisitService
        start, end = _resolve_range(request)

        visits = Visit.objects.filter(
            start_at__gte=start, start_at__lte=end, status=Visit.Status.COMPLETED,
        ).select_related('staff').prefetch_related('services__items__product')

        # The per-service operator of each visit (explicit or auto-resolved),
        # fetched once for the window instead of per visit.
        operators_by_visit = {}
        for link in VisitService.objects.filter(visit__in=visits).select_related('staff'):
            if link.staff_id:
                operators_by_visit.setdefault(link.visit_id, {})[link.service_id] = link.staff

        def empty_row(staff_obj):
            return {
                'staff_id': staff_obj.id,
                'staff_name': f"{staff_obj.first_name} {staff_obj.last_name}".strip() or staff_obj.username,
                'revenue_usd': Decimal('0'),
                'revenue_toman': Decimal('0'),
                'product_cost_usd': Decimal('0'),
                'product_cost_toman': Decimal('0'),
                'operator_compensation_usd': Decimal('0'),
                'operator_compensation_toman': Decimal('0'),
                'welcome_pack_cost_usd': Decimal('0'),
                'welcome_pack_cost_toman': Decimal('0'),
                'recipe_estimate_cost_usd': Decimal('0'),
                'clinic_share_usd': Decimal('0'),
                'clinic_share_toman': Decimal('0'),
                'profit_usd': Decimal('0'),
                'profit_toman': Decimal('0'),
                'visit_count': 0,
            }

        money_keys = (
            'revenue_usd', 'revenue_toman', 'product_cost_usd', 'product_cost_toman',
            'operator_compensation_usd', 'operator_compensation_toman',
            'welcome_pack_cost_usd', 'welcome_pack_cost_toman',
            'recipe_estimate_cost_usd', 'clinic_share_usd', 'clinic_share_toman',
            'profit_usd', 'profit_toman',
        )

        rate = get_rate()
        staff_data = {}
        basis_by_staff = {}

        for visit in visits:
            if not visit.staff_id and visit.id not in operators_by_visit:
                # No primary staff and no assigned operator: nothing can be
                # attributed. Excluded here and counted by `coverage`.
                continue
            # Same per-service actuals the payout engine uses, so this report
            # and the compensation ledger cannot disagree.
            per_visit = financials.calculate_visit_financials(visit, rate=rate)
            service_operators = operators_by_visit.get(visit.id, {})

            # Every service row goes to the operator who performed THAT
            # service (per-service assignment first, primary staff as the
            # fallback); each involved operator counts the visit once.
            involved = {}
            if visit.staff_id:
                involved[visit.staff_id] = visit.staff
            for service_row in per_visit['services'].values():
                operator = service_operators.get(service_row['service_id']) or visit.staff
                if operator is None:
                    continue
                involved[operator.id] = operator
                row = staff_data.setdefault(operator.id, empty_row(operator))
                for key in money_keys:
                    row[key] += service_row[key]

            for staff_obj in involved.values():
                staff_data.setdefault(staff_obj.id, empty_row(staff_obj))['visit_count'] += 1
                # Only call it list price if *every* visit for this staff member
                # was priced from list price; any collected sale makes it real
                # revenue.
                basis_by_staff.setdefault(staff_obj.id, financials.REVENUE_BASIS_LEDGER)
                if per_visit['revenue_basis'] == financials.REVENUE_BASIS_LIST_PRICE:
                    basis_by_staff[staff_obj.id] = financials.REVENUE_BASIS_LIST_PRICE

        for data in staff_data.values():
            data['revenue_usd'] = str(data['revenue_usd'].quantize(Decimal('0.01')))
            data['revenue_toman'] = str(data['revenue_toman'].quantize(Decimal('0.01')))
            data['product_cost_usd'] = str(data['product_cost_usd'].quantize(Decimal('0.01')))
            data['product_cost_toman'] = str(data['product_cost_toman'].quantize(Decimal('0.01')))
            data['profit_usd'] = str(data['profit_usd'].quantize(Decimal('0.01')))
            data['profit_toman'] = str(data['profit_toman'].quantize(Decimal('0.01')))
            data['operator_compensation_usd'] = str(data['operator_compensation_usd'].quantize(Decimal('0.01')))
            data['operator_compensation_toman'] = str(data['operator_compensation_toman'].quantize(Decimal('0.01')))
            data['welcome_pack_cost_usd'] = str(data['welcome_pack_cost_usd'].quantize(Decimal('0.01')))
            data['welcome_pack_cost_toman'] = str(data['welcome_pack_cost_toman'].quantize(Decimal('0.01')))
            data['recipe_estimate_cost_usd'] = str(data['recipe_estimate_cost_usd'].quantize(Decimal('0.01')))
            data['clinic_share_usd'] = str(data['clinic_share_usd'].quantize(Decimal('0.01')))
            data['clinic_share_toman'] = str(data['clinic_share_toman'].quantize(Decimal('0.01')))
            # Revenue here is list price of services delivered, not collected
            # money. The key is kept for backward compatibility; this label lets
            # the UI present it as potential revenue.
            data['revenue_basis'] = basis_by_staff.get(
                    data['staff_id'], financials.REVENUE_BASIS_LEDGER,
                )
            data['welcome_pack_cost_basis'] = 'allocated_by_revenue_share'

        rows = sorted(staff_data.values(), key=lambda x: x['staff_name'])
        # The response stays a bare list of per-staff rows (backward compatible);
        # assignment coverage lives in ProfitByStaffCoverageView.
        return Response(_stringify(rows))


@extend_schema(tags=['Reports'])
class ProfitByStaffCoverageView(APIView):
    """How many completed visits could be attributed to a staff member.

    Visits with neither a primary staff member nor an assigned per-service
    operator cannot appear in ``profit-by-staff``, so without this the report
    looks healthy while silently dropping them.
    """

    permission_classes = [IsEmployeeOrAdmin]

    @extend_schema(
        parameters=[
            OpenApiParameter('start_date', OpenApiTypes.STR, OpenApiParameter.QUERY),
            OpenApiParameter('end_date', OpenApiTypes.STR, OpenApiParameter.QUERY),
            OpenApiParameter('period', OpenApiTypes.STR, OpenApiParameter.QUERY),
        ],
    )
    def get(self, request):
        from customers.models import Visit, VisitService

        start, end = _resolve_range(request)
        completed = Visit.objects.filter(
            start_at__gte=start, start_at__lte=end, status=Visit.Status.COMPLETED,
        )
        total_visits = completed.count()
        # A visit counts as assigned when it has a primary staff member OR at
        # least one per-service operator assignment.
        assigned_ids = set(
            VisitService.objects.filter(
                visit__in=completed, staff__isnull=False,
            ).values_list('visit_id', flat=True)
        )
        unassigned_visits = sum(
            1
            for visit_id, staff_id in completed.values_list('id', 'staff_id')
            if staff_id is None and visit_id not in assigned_ids
        )
        return Response({
            'period': _stringify({'start': start, 'end': end}),
            'total_visits': total_visits,
            'visits_with_staff': total_visits - unassigned_visits,
            'unassigned_visits': unassigned_visits,
            'revenue_basis': reporting.REVENUE_BASIS_LIST_PRICE,
            'welcome_pack_cost_basis': 'allocated_by_revenue_share',
        })


@extend_schema(tags=['Reports'])
class MonthlyCloseView(APIView):
    """A Shamsi year of monthly P&L, each month next to its operator pay.

    The "close this month, move to the next one" report. For every month of
    the requested Shamsi year it returns:

    * the full P&L for that month -- revenue, product cost, welcome-pack cost,
      gross profit, staff compensation, operating expenses, staff claims,
      clinic share and **net profit** -- all from the same
      ``financials.build_report`` that backs ``/reports/financial-summary/``;
    * **purchases** (both stock-buying ledgers) and **net profit after
      purchases**, the cash view. Purchases are never subtracted from net
      profit, because inventory is charged once, at consumption;
    * one row per operator (doctor / facial / laser) with the revenue and
      material profit they produced, what they are owed, how much of that is
      per-visit earnings versus monthly salary, and paid / pending / approved
      splits;
    * ``role_totals`` (laser, facial, doctor) and ``year_total``.

    Payout figures are anchored on ``StaffPayout.created_at``, the same anchor
    ``build_report`` uses, so a month's operator rows add back up to that
    month's ``staff_compensation.total``.
    """

    permission_classes = [IsEmployeeOrAdmin]

    @extend_schema(
        parameters=[
            OpenApiParameter(
                'year', OpenApiTypes.INT, OpenApiParameter.QUERY,
                description='Shamsi year. Defaults to the current Shamsi year.',
            ),
            OpenApiParameter(
                'month', OpenApiTypes.STR, OpenApiParameter.QUERY,
                description="Return a single Shamsi month: 1-12 or '1405-05'.",
            ),
            OpenApiParameter(
                'status', OpenApiTypes.STR, OpenApiParameter.QUERY,
                description="Payout status filter. Defaults to the payouts still "
                            "owed (pending, approved, paid); 'all' includes cancelled.",
            ),
            OpenApiParameter('staff', OpenApiTypes.INT, OpenApiParameter.QUERY,
                             description='Restrict the operator rows to one staff member.'),
            OpenApiParameter('role', OpenApiTypes.STR, OpenApiParameter.QUERY,
                             description='Restrict the operator rows to one role '
                                         '(doctor | facial | laser).'),
        ],
    )
    def get(self, request):
        params = request.query_params
        return Response(_stringify(reporting.monthly_close(
            year=params.get('year'),
            month=params.get('month'),
            status=params.get('status'),
            staff_id=params.get('staff') or None,
            role=params.get('role') or None,
        )))


@extend_schema(tags=['Reports'])
class MonthlyCloseCloseView(APIView):
    """POST: freeze one past Shamsi month.

    Renders the month's full P&L + outstanding obligations into an immutable
    snapshot and marks the month closed; every write path for that month then
    answers 409 until it is reopened. Idempotent: re-closing an already
    closed month returns the existing snapshot untouched.
    """

    permission_classes = [IsEmployeeOrAdmin]

    @extend_schema(request=MonthlyCloseRequestSerializer,
                   responses={200: MonthlyCloseRequestSerializer})
    def post(self, request):
        serializer = MonthlyCloseRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            row, already = closing.close_month(
                int(serializer.validated_data['year']),
                int(serializer.validated_data['month']),
                user=request.user,
                note=serializer.validated_data.get('note', ''),
            )
        except closing.ClosingError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(_stringify(_close_row_payload(row, already)), status=status.HTTP_200_OK)


@extend_schema(tags=['Reports'])
class MonthlyCloseReopenView(APIView):
    """POST: reopen a closed month. Requires a reason (audited); the closing
    row is kept with status 'reopened', and re-closing refreshes it."""

    permission_classes = [IsEmployeeOrAdmin]

    @extend_schema(request=MonthlyCloseReopenSerializer,
                   responses={200: MonthlyCloseRequestSerializer})
    def post(self, request):
        serializer = MonthlyCloseReopenSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            row = closing.reopen_month(
                int(serializer.validated_data['year']),
                int(serializer.validated_data['month']),
                user=request.user,
                reason=serializer.validated_data['reason'],
            )
        except closing.ClosingError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(_stringify(_close_row_payload(row, False)), status=status.HTTP_200_OK)


def _close_row_payload(row, already_closed):
    """Response body shared by the close/reopen endpoints."""
    return {
        'period': row.period_key,
        'status': row.status,
        'already_closed': already_closed,
        'closed_at': row.closed_at,
        'closed_by': row.closed_by.username if row.closed_by_id else None,
        'close_note': row.close_note,
        'reopened_at': row.reopened_at,
        'reopened_by': row.reopened_by.username if row.reopened_by_id else None,
        'reopen_reason': row.reopen_reason,
        'net_profit_usd': str(row.net_profit_usd),
        'rate_used': str(row.rate_used) if row.rate_used is not None else None,
        'schema_version': row.schema_version,
    }


@extend_schema(tags=['Reports'])
class DashboardView(APIView):
    permission_classes = [IsEmployeeOrAdmin]

    @extend_schema(
        parameters=[
            OpenApiParameter('start_date', OpenApiTypes.STR, OpenApiParameter.QUERY),
            OpenApiParameter('end_date', OpenApiTypes.STR, OpenApiParameter.QUERY),
            OpenApiParameter('period', OpenApiTypes.STR, OpenApiParameter.QUERY),
        ],
    )
    def get(self, request):
        start, end = _resolve_range(request)

        from customers.models import Customer

        # One authoritative calculation, shared with /reports/financial-summary/.
        # The dashboard used to re-derive revenue, cost and profit locally, which
        # is how the two endpoints drifted apart.
        report = financials.build_report(start, end)

        # Wallet rewards and payments come from the same report as everything
        # else here. The dashboard used to re-query them, which put a second
        # definition of "wallet payments" next to the one financial-summary
        # reports. Only the liability is read locally: it is a balance, not a
        # period figure, so build_report has no equivalent.
        wallet_liability = Wallet.objects.aggregate(total=Sum('balance'))['total'] or Decimal('0')

        new_customers = Customer.objects.filter(
            created_at__gte=start, created_at__lte=end,
        ).count()

        return Response(_stringify({
            'period': report['period'],
            'sales_summary': {
                # Existing keys, unchanged names.
                'revenue_usd': str(report['revenue']['usd']),
                'revenue_toman': str(report['revenue']['toman']),
                'product_cost_usd': str(report['product_cost']['usd']),
                'product_cost_toman': str(report['product_cost']['toman']),
                'welcome_pack_cost_usd': str(report['welcome_pack_cost']['usd']),
                'welcome_pack_cost_toman': str(report['welcome_pack_cost']['toman']),
                'gross_profit_usd': str(report['gross_profit']['usd']),
                'gross_profit_toman': str(report['gross_profit']['toman']),
                'expenses_usd': str(report['staff_expense_claims']['usd']),
                'expenses_toman': str(report['staff_expense_claims']['toman']),
                'net_profit_usd': str(report['net_profit']['usd']),
                'net_profit_toman': str(report['net_profit']['toman']),
                'total_payout_usd': str(report['staff_compensation']['total']['usd']),
                'total_payout_toman': str(report['staff_compensation']['total']['toman']),
                'sale_count': report['counts']['paid_sales'],
                'avg_ticket_usd': str(report['counts']['average_transaction_value']),
                'payment_methods': {k: str(v) for k, v in report['payment_methods'].items()},
                'payment_methods_by_method': {
                    k: str(v) for k, v in report['payment_methods_by_method'].items()
                },
                # New: the below-the-line buckets Net Profit actually subtracts.
                'operating_expenses_usd': str(report['operating_expenses']['usd']),
                'operating_expenses_toman': str(report['operating_expenses']['toman']),
                'staff_compensation_usd': str(report['staff_compensation']['total']['usd']),
                'staff_compensation_toman': str(report['staff_compensation']['total']['toman']),
                'clinic_share_usd': str(report['clinic_share']['usd']),
                'clinic_share_toman': str(report['clinic_share']['toman']),
                'below_the_line_total_usd': str(report['below_the_line_total']['usd']),
                'below_the_line_total_toman': str(report['below_the_line_total']['toman']),
                'net_profit_breakdown': {
                    'gross_profit_usd': str(report['gross_profit']['usd']),
                    'minus_staff_compensation_usd': str(report['staff_compensation']['total']['usd']),
                    'minus_operating_expenses_usd': str(report['operating_expenses']['usd']),
                    'minus_staff_claims_usd': str(report['staff_expense_claims']['usd']),
                    'net_profit_usd': str(report['net_profit']['usd']),
                },
            },
            # Cash view: stock bought in the period, and net profit with it
            # deducted. Never replaces net_profit (that would double count).
            'purchases': report['purchases'],
            'net_profit_after_purchases': report['net_profit_after_purchases'],
            'staff_compensation': report['staff_compensation'],
            'operating_expenses': report['operating_expenses'],
            'staff_expense_claims': report['staff_expense_claims'],
            'cost_coverage': report['cost_coverage'],
            'wallet_summary': {
                'total_liability_usd': str(wallet_liability),
                'rewards_issued_usd': str(report['wallet']['rewards_issued']),
                'wallet_payments_usd': str(abs(report['wallet']['wallet_payments'])),
            },
            'operational': {
                'visits_completed': report['counts']['appointments'],
                'new_customers': new_customers,
                'staff_payout_count': report['staff_compensation']['payout_count'],
            },
        }))

@extend_schema(tags=['Operating Expenses'])
class OperatingExpenseCategoryViewSet(viewsets.ModelViewSet):
    """Direct clinic operating-cost categories (هزینه‌های جاری).

    Owner decision: both admin and employee staff have full CRUD access
    (IsEmployeeOrAdmin = any authenticated staff). Distinct from
    ExpenseCategory, which belongs to the employee expense-claim workflow.
    """
    queryset = OperatingExpenseCategory.objects.all()
    serializer_class = OperatingExpenseCategorySerializer
    permission_classes = [IsEmployeeOrAdmin]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['name', 'slug', 'description']
    ordering_fields = ['name', 'slug', 'sort_order', 'is_active']
    ordering = ['sort_order', 'name']

    def destroy(self, request, *args, **kwargs):
        category = self.get_object()
        if category.operating_expenses.exists():
            return Response(
                {'detail': 'Cannot delete category with existing operating expenses. Deactivate it instead.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return super().destroy(request, *args, **kwargs)


@extend_schema(
    tags=['Operating Expenses'],
    parameters=[
        OpenApiParameter('category', OpenApiTypes.INT, OpenApiParameter.QUERY, description='Filter by category id'),
        OpenApiParameter('payment_method', OpenApiTypes.STR, OpenApiParameter.QUERY, description='cash | card | bank_transfer | other'),
        OpenApiParameter('created_by', OpenApiTypes.INT, OpenApiParameter.QUERY, description='Filter by staff user id'),
        OpenApiParameter('date_from', OpenApiTypes.STR, OpenApiParameter.QUERY, description='Jalali (Shamsi) YYYY-MM-DD, inclusive'),
        OpenApiParameter('date_to', OpenApiTypes.STR, OpenApiParameter.QUERY, description='Jalali (Shamsi) YYYY-MM-DD, inclusive'),
    ],
)
class OperatingExpenseViewSet(viewsets.ModelViewSet):
    """Direct clinic operating expenditures paid with clinic money.

    Full CRUD for any authenticated staff (admin and employee alike, per
    owner decision). Never touches Wallet, Sale, or PaymentComponent.
    """
    serializer_class = OperatingExpenseSerializer
    permission_classes = [IsEmployeeOrAdmin]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['title', 'description', 'vendor', 'notes', 'category__name']
    ordering_fields = ['expense_date', 'amount_usd', 'created_at']
    ordering = ['-expense_date', '-created_at']

    def get_queryset(self):
        qs = OperatingExpense.objects.select_related('category', 'created_by')
        params = self.request.query_params
        if params.get('category'):
            qs = qs.filter(category_id=params['category'])
        if params.get('payment_method'):
            qs = qs.filter(payment_method=params['payment_method'])
        if params.get('created_by'):
            qs = qs.filter(created_by_id=params['created_by'])
        date_from = params.get('date_from')
        if date_from:
            qs = qs.filter(expense_date__gte=shamsi_to_greg_date(date_from))
        date_to = params.get('date_to')
        if date_to:
            qs = qs.filter(expense_date__lte=shamsi_to_greg_date(date_to))
        return qs

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            expense = opex_svc.create_operating_expense(
                created_by=request.user,
                category=data['category'],
                title=data['title'],
                amount_usd=data['amount_usd'],
                expense_date=data['expense_date'],
                payment_method=data.get('payment_method', OperatingExpense.PaymentMethod.CASH),
                description=data.get('description', ''),
                vendor=data.get('vendor', ''),
                receipt=data.get('receipt'),
                notes=data.get('notes', ''),
                idempotency_key=data.get('idempotency_key') or None,
            )
        except opex_svc.OperatingExpenseError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(
            OperatingExpenseSerializer(expense, context=self.get_serializer_context()).data,
            status=status.HTTP_201_CREATED,
        )

    def perform_update(self, serializer):
        data = serializer.validated_data
        try:
            expense = opex_svc.update_operating_expense(self.get_object(), **data)
        except opex_svc.OperatingExpenseError as exc:
            raise serializers.ValidationError({'error': str(exc)})
        serializer.instance = expense

    def destroy(self, request, *args, **kwargs):
        # Route through the service so the closed-month guard (and the audit
        # trail) sees the deletion instead of a silent ORM delete.
        expense = self.get_object()
        opex_svc.delete_operating_expense(expense)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(
        parameters=[
            OpenApiParameter('start_date', OpenApiTypes.STR, OpenApiParameter.QUERY),
            OpenApiParameter('end_date', OpenApiTypes.STR, OpenApiParameter.QUERY),
            OpenApiParameter('period', OpenApiTypes.STR, OpenApiParameter.QUERY),
        ],
    )
    @action(detail=False, methods=['get'])
    def summary(self, request):
        """Totals for direct clinic operating costs over a period.

        Reported separately from the employee-expense (Expense) figures so the
        two domains can be combined explicitly upstream:
        total clinic operating expenses = employee expenses + operating expenses.
        """
        start, end = _resolve_range(request)
        return Response(_stringify(reporting.operating_expense_summary(start, end)))


@extend_schema(tags=['Welcome Packs'])
class WelcomePackViewSet(viewsets.ModelViewSet):
    """CRUD for Welcome Pack definitions.

    Both admin and employee have full access (create, read, update, delete).
    Creating a pack definition does NOT create financial transactions.
    Financial impact occurs only when a pack is issued via the issue endpoint.
    """
    queryset = WelcomePack.objects.prefetch_related('items__product').all()
    serializer_class = WelcomePackSerializer
    permission_classes = [IsEmployeeOrAdmin]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['name', 'description']
    ordering_fields = ['name', 'is_active', 'created_at']
    ordering = ['name']

    def get_queryset(self):
        qs = super().get_queryset()
        params = self.request.query_params
        if params.get('is_active') is not None:
            is_active = params['is_active'].lower() == 'true'
            qs = qs.filter(is_active=is_active)
        return qs

    def perform_create(self, serializer):
        items_data = self.request.data.get('items', [])
        try:
            pack = welcome_pack_svc.create_welcome_pack_with_items(
                name=serializer.validated_data['name'],
                description=serializer.validated_data.get('description', ''),
                is_active=serializer.validated_data.get('is_active', True),
                items_data=items_data,
                created_by=self.request.user,
            )
        except welcome_pack_svc.WelcomePackError as exc:
            raise serializers.ValidationError({'error': str(exc)})
        serializer.instance = pack

    def perform_update(self, serializer):
        items_data = self.request.data.get('items')
        try:
            pack = welcome_pack_svc.update_welcome_pack_with_items(
                self.get_object(),
                name=serializer.validated_data.get('name'),
                description=serializer.validated_data.get('description'),
                is_active=serializer.validated_data.get('is_active'),
                items_data=items_data,
                updated_by=self.request.user,
            )
        except welcome_pack_svc.WelcomePackError as exc:
            raise serializers.ValidationError({'error': str(exc)})
        serializer.instance = pack

    @extend_schema(
        request=inline_serializer(
            name='WelcomePackIssueRequest',
            fields={
                'customer': serializers.IntegerField(),
                'quantity': serializers.DecimalField(max_digits=10, decimal_places=3, default='1'),
                'visit': serializers.IntegerField(required=False, allow_null=True),
            },
        ),
        responses=WelcomePackUsageSerializer,
    )
    @action(detail=True, methods=['post'], permission_classes=[IsEmployeeOrAdmin])
    def issue(self, request, pk=None):
        """Issue this welcome pack to a customer (creates financial event)."""
        pack = self.get_object()
        customer_id = request.data.get('customer')
        quantity = request.data.get('quantity', '1')
        visit_id = request.data.get('visit')

        if not customer_id:
            return Response({'error': 'customer is required.'}, status=status.HTTP_400_BAD_REQUEST)

        from customers.models import Customer, Visit

        try:
            customer = Customer.objects.get(id=customer_id)
        except Customer.DoesNotExist:
            return Response({'error': 'Customer not found.'}, status=status.HTTP_404_NOT_FOUND)

        visit = None
        if visit_id:
            visit = Visit.objects.filter(id=visit_id).first()
            if not visit:
                return Response({'error': 'Visit not found.'}, status=status.HTTP_404_NOT_FOUND)

        if visit is not None and visit.customer_id != customer.id:
            return Response(
                {'error': 'Visit does not belong to the specified customer.'},
                status=status.HTTP_400_BAD_REQUEST,
)

        try:
            usage = welcome_pack_svc.issue_welcome_pack(
                welcome_pack=pack,
                customer=customer,
                quantity=quantity,
                visit=visit,
                issued_by=request.user,
                idempotency_key=request.data.get('idempotency_key'),
            )
        except welcome_pack_svc.WelcomePackError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(WelcomePackUsageSerializer(usage).data, status=status.HTTP_201_CREATED)


@extend_schema(tags=['Welcome Packs'])
class WelcomePackItemViewSet(viewsets.ModelViewSet):
    """Manage individual items within welcome packs.

    Typically managed via nested operations on WelcomePackViewSet,
    but exposed separately for granular access if needed.
    """
    queryset = WelcomePackItem.objects.select_related('welcome_pack', 'product').all()
    serializer_class = WelcomePackItemSerializer
    permission_classes = [IsEmployeeOrAdmin]
    filter_backends = [filters.OrderingFilter]
    ordering = ['welcome_pack', 'product']


@extend_schema(tags=['Welcome Packs'])
class WelcomePackUsageViewSet(viewsets.ReadOnlyModelViewSet):
    """Read-only view of Welcome Pack issuance history (financial events).

    Used for reporting and audit. Creating/editing/deleting usages
    is not allowed — they are immutable historical snapshots.
    """
    queryset = WelcomePackUsage.objects.select_related('welcome_pack', 'customer', 'visit', 'issued_by').all()
    serializer_class = WelcomePackUsageSerializer
    permission_classes = [IsEmployeeOrAdmin]
    filter_backends = [filters.OrderingFilter, filters.SearchFilter]
    ordering = ['-issued_at']
    search_fields = ['welcome_pack__name', 'customer__first_name', 'customer__last_name']

    def get_queryset(self):
        qs = super().get_queryset()
        params = self.request.query_params
        if params.get('welcome_pack'):
            qs = qs.filter(welcome_pack_id=params['welcome_pack'])
        if params.get('customer'):
            qs = qs.filter(customer_id=params['customer'])
        if params.get('visit'):
            qs = qs.filter(visit_id=params['visit'])
        if params.get('date_from'):
            qs = qs.filter(issued_at__date__gte=shamsi_to_greg_date(params['date_from']))
        if params.get('date_to'):
            qs = qs.filter(issued_at__date__lte=shamsi_to_greg_date(params['date_to']))
        return qs


@extend_schema(tags=['Reports'])
class WelcomePackReportView(APIView):
    """Welcome Pack usage and cost summary for a period."""
    permission_classes = [IsEmployeeOrAdmin]

    @extend_schema(
        parameters=[
            OpenApiParameter('start_date', OpenApiTypes.STR, OpenApiParameter.QUERY),
            OpenApiParameter('end_date', OpenApiTypes.STR, OpenApiParameter.QUERY),
            OpenApiParameter('period', OpenApiTypes.STR, OpenApiParameter.QUERY),
        ],
        responses=inline_serializer(
            name='WelcomePackReport',
            fields={
                'period': inline_serializer('Period', fields={'start': OpenApiTypes.DATETIME, 'end': OpenApiTypes.DATETIME}),
                'total_usage_count': serializers.IntegerField(),
                'total_packs_issued': serializers.CharField(),
                'total_cost_usd': serializers.CharField(),
                'total_cost_toman': serializers.CharField(),
                'by_pack': serializers.ListField(
                    child=inline_serializer(
                        name='WelcomePackReportItem',
                        fields={
                            'welcome_pack_id': serializers.IntegerField(),
                            'welcome_pack__name': serializers.CharField(),
                            'count': serializers.CharField(),
                            'cost_usd': serializers.CharField(),
                            'cost_toman': serializers.CharField(),
                            'usage_count': serializers.IntegerField(),
                        }
                    )
                ),
            },
        ),
    )
    def get(self, request):
        start, end = _resolve_range(request)
        result = welcome_pack_svc.get_welcome_pack_usage_summary(start, end)
        return Response(_stringify(result))


@extend_schema(tags=['Purchases'])
class PurchaseOrderViewSet(viewsets.ModelViewSet):
    """Buying products (stock purchase orders).

    Lifecycle: `draft → ordered → received` (or `cancelled`). Editing is allowed
    while draft/ordered; **receiving** is the only step that changes inventory
    and cost — it adds stock, refreshes `Product.cost_usd`, rolls
    `ProductCostHistory` and snapshots Toman values at the current exchange
    rate. Read: any staff. Write / actions: admin.
    """

    queryset = PurchaseOrder.objects.all()
    serializer_class = PurchaseOrderSerializer
    permission_classes = [IsAdminOrReadOnly]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['supplier', 'notes', 'items__product__name']
    ordering_fields = ['order_date', 'status', 'total_cost_usd', 'created_at']
    ordering = ['-order_date', '-created_at']

    def get_queryset(self):
        qs = (
            super().get_queryset()
            .select_related('created_by')
            .prefetch_related('items__product')
        )
        params = self.request.query_params
        if params.get('status'):
            qs = qs.filter(status=params['status'])
        if params.get('supplier'):
            qs = qs.filter(supplier__icontains=params['supplier'])
        if params.get('product'):
            qs = qs.filter(items__product_id=params['product'])
        date_from = params.get('date_from')
        if date_from:
            qs = qs.filter(order_date__gte=shamsi_to_greg_date(date_from))
        date_to = params.get('date_to')
        if date_to:
            qs = qs.filter(order_date__lte=shamsi_to_greg_date(date_to))
        return qs.distinct()

    def perform_create(self, serializer):
        data = serializer.validated_data
        try:
            order, _created = purchase_svc.create_purchase_order(
                supplier=data.get('supplier', ''),
                order_date=data.get('order_date'),
                notes=data.get('notes', ''),
                created_by=self.request.user,
                idempotency_key=data.get('idempotency_key') or '',
                items_data=self.request.data.get('items', []),
            )
        except purchase_svc.PurchaseOrderError as exc:
            raise serializers.ValidationError({'error': str(exc)})
        serializer.instance = order

    def perform_update(self, serializer):
        data = serializer.validated_data
        request_data = self.request.data
        try:
            order = purchase_svc.update_purchase_order(
                self.get_object(),
                supplier=data.get('supplier'),
                order_date=data.get('order_date'),
                notes=data.get('notes'),
                items_data=request_data.get('items') if 'items' in request_data else None,
            )
        except purchase_svc.PurchaseOrderError as exc:
            raise serializers.ValidationError({'error': str(exc)})
        serializer.instance = order

    def destroy(self, request, *args, **kwargs):
        order = self.get_object()
        if order.status == PurchaseOrder.Status.RECEIVED:
            return Response(
                {'detail': 'A received purchase order cannot be deleted: it already changed '
                           'stock and cost history. Keep it for the audit trail.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return super().destroy(request, *args, **kwargs)

    def _transition(self, request, service_call, schema_response=None):
        order = self.get_object()
        try:
            order = service_call(order)
        except purchase_svc.PurchaseOrderError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(order).data)

    @extend_schema(request=None, responses=PurchaseOrderSerializer)
    @action(detail=True, methods=['post'], permission_classes=[IsAdmin], url_path='mark-ordered')
    def mark_ordered(self, request, pk=None):
        """draft → ordered (still no inventory or financial effect)."""
        return self._transition(request, purchase_svc.mark_ordered)

    @extend_schema(request=None, responses=PurchaseOrderSerializer)
    @action(detail=True, methods=['post'], permission_classes=[IsAdmin])
    def receive(self, request, pk=None):
        """Add stock, roll cost history, snapshot Toman totals at the current rate."""
        return self._transition(request, purchase_svc.receive_purchase_order)

    @extend_schema(request=None, responses=PurchaseOrderSerializer)
    @action(detail=True, methods=['post'], permission_classes=[IsAdmin])
    def cancel(self, request, pk=None):
        """Any state except received → cancelled."""
        return self._transition(request, purchase_svc.cancel_purchase_order)


@extend_schema(tags=['Reports'])
class ProductPurchaseReportView(APIView):
    """Received purchase orders: totals in USD and Toman per period/product/supplier."""

    permission_classes = [IsEmployeeOrAdmin]

    @extend_schema(
        parameters=[
            OpenApiParameter('start_date', OpenApiTypes.STR, OpenApiParameter.QUERY),
            OpenApiParameter('end_date', OpenApiTypes.STR, OpenApiParameter.QUERY),
            OpenApiParameter('period', OpenApiTypes.STR, OpenApiParameter.QUERY),
            OpenApiParameter('product', OpenApiTypes.INT, OpenApiParameter.QUERY),
            OpenApiParameter('supplier', OpenApiTypes.STR, OpenApiParameter.QUERY),
        ],
    )
    def get(self, request):
        start, end = _resolve_range(request)
        params = request.query_params
        result = purchase_svc.purchase_summary(
            start, end,
            product_id=params.get('product'),
            supplier=params.get('supplier'),
        )
        return Response(_stringify(result))
