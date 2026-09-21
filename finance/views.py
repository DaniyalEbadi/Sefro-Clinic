from datetime import date, datetime, time
from decimal import Decimal

from django.db.models import Sum
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, OpenApiTypes, extend_schema, inline_serializer
from rest_framework import filters, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import IsAdmin, IsAdminOrReadOnly

from .models import (
    ExchangeRate,
    Expense,
    ExpenseCategory,
    OperatingExpense,
    OperatingExpenseCategory,
    Package,
    PackageItem,
    PackageService,
    PaymentComponent,
    ProductCostHistory,
    ProductPurchase,
    ProductUsage,
    Sale,
    ServiceItem,
    StaffCompensationRule,
    StaffPayout,
    Wallet,
    WalletRewardRule,
    WalletTransaction,
)
from .permissions import IsEmployeeOrAdmin
from .serializers import (
    CheckoutSerializer,
    ExchangeRateSerializer,
    ExpenseCategorySerializer,
    ExpenseSerializer,
    OperatingExpenseCategorySerializer,
    OperatingExpenseSerializer,
    PackageItemSerializer,
    PackageSerializer,
    PackageServiceSerializer,
    ProductCostHistorySerializer,
    ProductPurchaseSerializer,
    ProductUsageSerializer,
    RefundSerializer,
    SaleSerializer,
    ServiceItemSerializer,
    StaffCompensationRuleSerializer,
    StaffPayoutSerializer,
    WalletRewardRuleSerializer,
    WalletSerializer,
    WalletTransactionSerializer,
)
from .services import accounting, payments, reporting, staff_compensation
from .services import expenses as expense_svc
from .services import operating_expenses as opex_svc
from .services.exchange_rates import get_rate
from .services.wallet import InsufficientFunds


def _stringify(obj):
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, dict):
        return {k: _stringify(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_stringify(v) for v in obj]
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    return obj


def _resolve_range(request):
    start = request.query_params.get('start_date')
    end = request.query_params.get('end_date')
    period = request.query_params.get('period')

    def _parse(value):
        try:
            return timezone.make_aware(datetime.combine(datetime.strptime(value, '%Y-%m-%d').date(), time.min))
        except (ValueError, TypeError):
            return None

    if period:
        now = timezone.localtime(timezone.now())
        today = now.date()
        if period == 'today':
            start_dt = timezone.make_aware(datetime.combine(today, time.min))
            end_dt = timezone.make_aware(datetime.combine(today, time.max))
        elif period == 'this_week':
            start_dt = timezone.make_aware(datetime.combine(today - timezone.timedelta(days=today.weekday()), time.min))
            end_dt = timezone.make_aware(datetime.combine(start_dt.date() + timezone.timedelta(days=7), time.max))
        elif period == 'this_month':
            start_dt = timezone.make_aware(datetime.combine(today.replace(day=1), time.min))
            end_dt = timezone.make_aware(datetime.combine((start_dt.date().replace(month=start_dt.month % 12 + 1, day=1) if start_dt.month != 12 else start_dt.replace(year=start_dt.year + 1, month=1, day=1)), time.max))
        elif period == 'prev_month':
            first_this = today.replace(day=1)
            last_prev = first_this - timezone.timedelta(days=1)
            start_dt = timezone.make_aware(datetime.combine(last_prev.replace(day=1), time.min))
            end_dt = timezone.make_aware(datetime.combine(last_prev, time.max))
        elif period == 'this_year':
            start_dt = timezone.make_aware(datetime.combine(today.replace(month=1, day=1), time.min))
            end_dt = timezone.make_aware(datetime.combine(today.replace(month=12, day=31), time.max))
        else:
            start_dt = end_dt = None
        if start_dt and end_dt:
            return start_dt, end_dt

    start_dt = _parse(start)
    end_dt = _parse(end)
    if end_dt:
        end_dt = timezone.make_aware(datetime.combine(end_dt.date(), time.max))

    # Fall back to today when no usable range was supplied. This mirrors the
    # service-layer convention (services/reporting.py::_range and
    # services/staff_compensation.py::staff_payout_summary). Returning None here
    # made the views that filter inline raise "Cannot use None as a query value".
    if not start_dt or not end_dt:
        today = timezone.localtime(timezone.now()).date()
        start_dt = start_dt or timezone.make_aware(datetime.combine(today, time.min))
        end_dt = end_dt or timezone.make_aware(datetime.combine(today, time.max))

    return start_dt, end_dt


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


@extend_schema(tags=['Finance'])
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
        return qs.select_related('product', 'visit', 'service', 'package_sale')


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
        return qs.select_related('customer', 'visit', 'package', 'payment')

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
            )
        except payments.PaymentError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
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
        responses=ProductUsageSerializer(many=True),
    )
    def post(self, request, pk):
        from customers.models import Visit
        visit = Visit.objects.filter(id=pk).first()
        if not visit:
            return Response({'error': 'Visit not found.'}, status=status.HTTP_404_NOT_FOUND)
        selected = request.data.get('selected_products')
        try:
            usages = accounting.record_visit_consumption(visit, selected_products=selected)
        except Exception as exc:
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(ProductUsageSerializer(usages, many=True).data, status=status.HTTP_201_CREATED)


@extend_schema(tags=['Reports'])
class FinancialSummaryView(APIView):
    permission_classes = [IsEmployeeOrAdmin]

    @extend_schema(
        parameters=[
            OpenApiParameter('start_date', OpenApiTypes.DATE, OpenApiParameter.QUERY),
            OpenApiParameter('end_date', OpenApiTypes.DATE, OpenApiParameter.QUERY),
            OpenApiParameter('period', OpenApiTypes.STR, OpenApiParameter.QUERY),
            OpenApiParameter('service', OpenApiTypes.INT, OpenApiParameter.QUERY),
            OpenApiParameter('package', OpenApiTypes.INT, OpenApiParameter.QUERY),
            OpenApiParameter('product', OpenApiTypes.INT, OpenApiParameter.QUERY),
        ],
    )
    def get(self, request):
        start, end = _resolve_range(request)
        params = request.query_params
        result = reporting.financial_summary(
            start, end,
            service_id=params.get('service'),
            package_id=params.get('package'),
            product_id=params.get('product'),
            personnel_id=params.get('personnel'),
        )
        return Response(_stringify(result))


@extend_schema(tags=['Reports'])
class ProfitByServiceView(APIView):
    permission_classes = [IsEmployeeOrAdmin]

    @extend_schema(
        parameters=[
            OpenApiParameter('start_date', OpenApiTypes.DATE, OpenApiParameter.QUERY),
            OpenApiParameter('end_date', OpenApiTypes.DATE, OpenApiParameter.QUERY),
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
            OpenApiParameter('start_date', OpenApiTypes.DATE, OpenApiParameter.QUERY),
            OpenApiParameter('end_date', OpenApiTypes.DATE, OpenApiParameter.QUERY),
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
            'effective_at': latest.effective_at.isoformat() if latest else None,
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
            'effective_at': timezone.now().isoformat(),
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


def calculate_service_profit(service, rate):
    revenue_usd = service.price_usd or Decimal('0')
    cost_usd = Decimal('0')
    for item in service.items.select_related('product').all():
        qty = item.quantity
        cost = item.product.cost_usd if item.product else Decimal('0')
        cost_usd += (Decimal(str(qty)) * Decimal(str(cost))).quantize(Decimal('0.01'))
    revenue_toman = (revenue_usd * rate).quantize(Decimal('0.01'))
    cost_toman = (cost_usd * rate).quantize(Decimal('0.01'))
    return {
        'revenue_usd': revenue_usd,
        'revenue_toman': revenue_toman,
        'product_cost_usd': cost_usd,
        'product_cost_toman': cost_toman,
        'profit_usd': (revenue_usd - cost_usd).quantize(Decimal('0.01')),
        'profit_toman': (revenue_toman - cost_toman).quantize(Decimal('0.01')),
    }


@extend_schema(tags=['Staff Compensation'])
class StaffCompensationRuleViewSet(viewsets.ModelViewSet):
    queryset = StaffCompensationRule.objects.all()
    serializer_class = StaffCompensationRuleSerializer
    permission_classes = [IsAdmin]
    filter_backends = [filters.OrderingFilter]
    ordering = ['role']


@extend_schema(tags=['Staff Compensation'])
class StaffPayoutViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = StaffPayout.objects.select_related('staff', 'visit', 'service', 'payout_product')
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
        return qs

    @extend_schema(
        parameters=[
            OpenApiParameter('staff', OpenApiTypes.INT, OpenApiParameter.QUERY),
            OpenApiParameter('role', OpenApiTypes.STR, OpenApiParameter.QUERY),
            OpenApiParameter('start_date', OpenApiTypes.DATE, OpenApiParameter.QUERY),
            OpenApiParameter('end_date', OpenApiTypes.DATE, OpenApiParameter.QUERY),
            OpenApiParameter('period', OpenApiTypes.STR, OpenApiParameter.QUERY),
        ],
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
        start, end = _resolve_range(request)
        params = request.query_params
        result = staff_compensation.staff_payout_summary(
            start, end,
            staff_id=params.get('staff'),
            role=params.get('role'),
        )
        return Response(_stringify(result))

    @extend_schema(
        parameters=[
            OpenApiParameter('staff', OpenApiTypes.INT, OpenApiParameter.QUERY),
            OpenApiParameter('start_date', OpenApiTypes.DATE, OpenApiParameter.QUERY),
            OpenApiParameter('end_date', OpenApiTypes.DATE, OpenApiParameter.QUERY),
            OpenApiParameter('period', OpenApiTypes.STR, OpenApiParameter.QUERY),
        ],
    )
    @action(detail=False, methods=['get'])
    def detail_report(self, request):
        start, end = _resolve_range(request)
        params = request.query_params
        data = staff_compensation.staff_payout_detail(
            start, end,
            staff_id=params.get('staff'),
        )
        return Response(_stringify(data))


@extend_schema(tags=['Reports'])
class StaffPayoutSummaryView(APIView):
    permission_classes = [IsEmployeeOrAdmin]

    @extend_schema(
        parameters=[
            OpenApiParameter('start_date', OpenApiTypes.DATE, OpenApiParameter.QUERY),
            OpenApiParameter('end_date', OpenApiTypes.DATE, OpenApiParameter.QUERY),
            OpenApiParameter('period', OpenApiTypes.STR, OpenApiParameter.QUERY),
            OpenApiParameter('staff', OpenApiTypes.INT, OpenApiParameter.QUERY),
            OpenApiParameter('role', OpenApiTypes.STR, OpenApiParameter.QUERY),
        ],
    )
    def get(self, request):
        start, end = _resolve_range(request)
        params = request.query_params
        result = staff_compensation.staff_payout_summary(
            start, end,
            staff_id=params.get('staff'),
            role=params.get('role'),
        )
        return Response(_stringify(result))


@extend_schema(tags=['Reports'])
class ProfitByStaffView(APIView):
    permission_classes = [IsEmployeeOrAdmin]

    @extend_schema(
        parameters=[
            OpenApiParameter('start_date', OpenApiTypes.DATE, OpenApiParameter.QUERY),
            OpenApiParameter('end_date', OpenApiTypes.DATE, OpenApiParameter.QUERY),
            OpenApiParameter('period', OpenApiTypes.STR, OpenApiParameter.QUERY),
        ],
    )
    def get(self, request):
        from customers.models import Visit
        start, end = _resolve_range(request)

        visits = Visit.objects.filter(
            start_at__gte=start, start_at__lte=end, status=Visit.Status.COMPLETED,
        ).select_related('staff').prefetch_related('services__items__product')

        rate = get_rate()
        staff_data = {}

        for visit in visits:
            if not visit.staff:
                continue
            staff_id = visit.staff.id
            staff_name = f"{visit.staff.first_name} {visit.staff.last_name}".strip() or visit.staff.username

            for svc in visit.services.all():
                profit = calculate_service_profit(svc, rate)
                if staff_id not in staff_data:
                    staff_data[staff_id] = {
                        'staff_id': staff_id,
                        'staff_name': staff_name,
                        'revenue_usd': Decimal('0'),
                        'revenue_toman': Decimal('0'),
                        'product_cost_usd': Decimal('0'),
                        'product_cost_toman': Decimal('0'),
                        'profit_usd': Decimal('0'),
                        'profit_toman': Decimal('0'),
                        'visit_count': 0,
                    }
                staff_data[staff_id]['revenue_usd'] += profit['revenue_usd']
                staff_data[staff_id]['revenue_toman'] += profit['revenue_toman']
                staff_data[staff_id]['product_cost_usd'] += profit['product_cost_usd']
                staff_data[staff_id]['product_cost_toman'] += profit['product_cost_toman']
                staff_data[staff_id]['profit_usd'] += profit['profit_usd']
                staff_data[staff_id]['profit_toman'] += profit['profit_toman']
                staff_data[staff_id]['visit_count'] += 1

        for data in staff_data.values():
            data['revenue_usd'] = str(data['revenue_usd'].quantize(Decimal('0.01')))
            data['revenue_toman'] = str(data['revenue_toman'].quantize(Decimal('0.01')))
            data['product_cost_usd'] = str(data['product_cost_usd'].quantize(Decimal('0.01')))
            data['product_cost_toman'] = str(data['product_cost_toman'].quantize(Decimal('0.01')))
            data['profit_usd'] = str(data['profit_usd'].quantize(Decimal('0.01')))
            data['profit_toman'] = str(data['profit_toman'].quantize(Decimal('0.01')))

        return Response(_stringify(sorted(staff_data.values(), key=lambda x: x['staff_name'])))


@extend_schema(tags=['Reports'])
class DashboardView(APIView):
    permission_classes = [IsEmployeeOrAdmin]

    @extend_schema(
        parameters=[
            OpenApiParameter('start_date', OpenApiTypes.DATE, OpenApiParameter.QUERY),
            OpenApiParameter('end_date', OpenApiTypes.DATE, OpenApiParameter.QUERY),
            OpenApiParameter('period', OpenApiTypes.STR, OpenApiParameter.QUERY),
        ],
    )
    def get(self, request):
        start, end = _resolve_range(request)

        from customers.models import Customer, Visit
        from finance.models import Expense, Wallet

        # Sales Summary
        sales = Sale.objects.filter(created_at__gte=start, created_at__lte=end)
        revenue_usd = sales.aggregate(total=Sum('amount_usd'))['total'] or Decimal('0')
        revenue_toman = sales.aggregate(total=Sum('amount_toman'))['total'] or Decimal('0')
        paid_sales = sales.filter(status=Sale.Status.PAID)
        sale_count = paid_sales.count()

        # Product Costs
        usages = ProductUsage.objects.filter(created_at__gte=start, created_at__lte=end)
        product_cost_usd = usages.aggregate(total=Sum('total_cost_usd_snapshot'))['total'] or Decimal('0')
        product_cost_toman = Decimal('0')
        for u in usages.only('total_cost_usd_snapshot', 'exchange_rate_snapshot'):
            product_cost_toman += (u.total_cost_usd_snapshot or Decimal('0')) * (u.exchange_rate_snapshot or get_rate())
        product_cost_toman = product_cost_toman.quantize(Decimal('0.01'))

        # Gross Profit
        gross_profit_usd = (revenue_usd - product_cost_usd).quantize(Decimal('0.01'))
        gross_profit_toman = (revenue_toman - product_cost_toman).quantize(Decimal('0.01'))

        # Expenses
        expenses = Expense.objects.filter(
            expense_date__gte=start.date(), expense_date__lte=end.date(),
            status__in=[Expense.Status.APPROVED, Expense.Status.PAID],
        )
        expenses_usd = expenses.aggregate(total=Sum('amount_usd'))['total'] or Decimal('0')
        expenses_toman = expenses.aggregate(total=Sum('amount_toman'))['total'] or Decimal('0')

        # Net Profit
        net_profit_usd = (gross_profit_usd - expenses_usd).quantize(Decimal('0.01'))
        net_profit_toman = (gross_profit_toman - expenses_toman).quantize(Decimal('0.01'))

        # Staff Payouts
        payouts = StaffPayout.objects.filter(created_at__gte=start, created_at__lte=end)
        payout_cash_usd = payouts.aggregate(total=Sum('payout_cash_usd'))['total'] or Decimal('0')
        payout_cash_toman = payouts.aggregate(total=Sum('payout_cash_toman'))['total'] or Decimal('0')
        payout_product_usd = payouts.aggregate(total=Sum('payout_product_value_usd'))['total'] or Decimal('0')
        payout_product_toman = payouts.aggregate(total=Sum('payout_product_value_toman'))['total'] or Decimal('0')
        total_payout_usd = (payout_cash_usd + payout_product_usd).quantize(Decimal('0.01'))
        total_payout_toman = (payout_cash_toman + payout_product_toman).quantize(Decimal('0.01'))

        # Wallet Summary
        wallet_liability = Wallet.objects.aggregate(total=Sum('balance'))['total'] or Decimal('0')
        wallet_rewards = WalletTransaction.objects.filter(
            transaction_type=WalletTransaction.Type.REWARD,
            created_at__gte=start, created_at__lte=end,
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0')
        wallet_payments = WalletTransaction.objects.filter(
            transaction_type=WalletTransaction.Type.PAYMENT,
            created_at__gte=start, created_at__lte=end,
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0')

        # Operational Metrics
        visits_completed = Visit.objects.filter(
            start_at__gte=start, start_at__lte=end, status=Visit.Status.COMPLETED,
        ).count()
        new_customers = Customer.objects.filter(
            created_at__gte=start, created_at__lte=end,
        ).count()
        avg_ticket = (revenue_usd / sale_count).quantize(Decimal('0.01')) if sale_count else Decimal('0')

        # Payment Method Breakdown
        comps = PaymentComponent.objects.filter(sale__in=sales)
        method_breakdown = {}
        for method in (PaymentComponent.Method.CASH, PaymentComponent.Method.CARD, PaymentComponent.Method.WALLET):
            method_breakdown[method] = comps.filter(method=method).aggregate(total=Sum('amount_usd'))['total'] or Decimal('0')

        return Response(_stringify({
            'period': {'start': start, 'end': end},
            'sales_summary': {
                'revenue_usd': str(revenue_usd),
                'revenue_toman': str(revenue_toman),
                'gross_profit_usd': str(gross_profit_usd),
                'gross_profit_toman': str(gross_profit_toman),
                'expenses_usd': str(expenses_usd),
                'expenses_toman': str(expenses_toman),
                'net_profit_usd': str(net_profit_usd),
                'net_profit_toman': str(net_profit_toman),
                'total_payout_usd': str(total_payout_usd),
                'total_payout_toman': str(total_payout_toman),
                'sale_count': sale_count,
                'avg_ticket_usd': str(avg_ticket),
                'payment_methods': {k: str(v) for k, v in method_breakdown.items()},
            },
            'wallet_summary': {
                'total_liability_usd': str(wallet_liability),
                'rewards_issued_usd': str(wallet_rewards),
                'wallet_payments_usd': str(abs(wallet_payments)),
            },
            'operational': {
                'visits_completed': visits_completed,
                'new_customers': new_customers,
                'staff_payout_count': payouts.count(),
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
        OpenApiParameter('date_from', OpenApiTypes.DATE, OpenApiParameter.QUERY, description='Gregorian YYYY-MM-DD (finance convention)'),
        OpenApiParameter('date_to', OpenApiTypes.DATE, OpenApiParameter.QUERY, description='Gregorian YYYY-MM-DD (finance convention)'),
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
            try:
                qs = qs.filter(expense_date__gte=datetime.strptime(date_from, '%Y-%m-%d').date())
            except (ValueError, TypeError):
                pass
        date_to = params.get('date_to')
        if date_to:
            try:
                qs = qs.filter(expense_date__lte=datetime.strptime(date_to, '%Y-%m-%d').date())
            except (ValueError, TypeError):
                pass
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

    @extend_schema(
        parameters=[
            OpenApiParameter('start_date', OpenApiTypes.DATE, OpenApiParameter.QUERY),
            OpenApiParameter('end_date', OpenApiTypes.DATE, OpenApiParameter.QUERY),
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