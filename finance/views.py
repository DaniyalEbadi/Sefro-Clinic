from datetime import date, datetime, time
from decimal import Decimal

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
    Package,
    PackageItem,
    PackageService,
    ProductCostHistory,
    ProductPurchase,
    ProductUsage,
    Sale,
    ServiceItem,
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
    PackageItemSerializer,
    PackageSerializer,
    PackageServiceSerializer,
    ProductCostHistorySerializer,
    ProductPurchaseSerializer,
    ProductUsageSerializer,
    RefundSerializer,
    SaleSerializer,
    ServiceItemSerializer,
    WalletRewardRuleSerializer,
    WalletSerializer,
    WalletTransactionSerializer,
)
from .services import accounting, payments, reporting
from .services import expenses as expense_svc
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
    return start_dt, end_dt


class ExchangeRateViewSet(viewsets.ModelViewSet):
    queryset = ExchangeRate.objects.all()
    serializer_class = ExchangeRateSerializer
    permission_classes = [IsAdminOrReadOnly]
    filter_backends = [filters.OrderingFilter]
    ordering = ['-effective_at']


class WalletRewardRuleViewSet(viewsets.ModelViewSet):
    queryset = WalletRewardRule.objects.all()
    serializer_class = WalletRewardRuleSerializer
    permission_classes = [IsAdminOrReadOnly]


class PackageViewSet(viewsets.ModelViewSet):
    queryset = Package.objects.all()
    serializer_class = PackageSerializer
    permission_classes = [IsAdminOrReadOnly]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['name']
    ordering_fields = ['name', 'price_usd', 'created_at']


class ServiceItemViewSet(viewsets.ModelViewSet):
    queryset = ServiceItem.objects.all()
    serializer_class = ServiceItemSerializer
    permission_classes = [IsAdminOrReadOnly]


class PackageItemViewSet(viewsets.ModelViewSet):
    queryset = PackageItem.objects.all()
    serializer_class = PackageItemSerializer
    permission_classes = [IsAdminOrReadOnly]


class PackageServiceViewSet(viewsets.ModelViewSet):
    queryset = PackageService.objects.all()
    serializer_class = PackageServiceSerializer
    permission_classes = [IsAdminOrReadOnly]


class ProductCostHistoryViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = ProductCostHistory.objects.all()
    serializer_class = ProductCostHistorySerializer
    permission_classes = [IsEmployeeOrAdmin]


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


class ExpenseCategoryViewSet(viewsets.ModelViewSet):
    queryset = ExpenseCategory.objects.all()
    serializer_class = ExpenseCategorySerializer
    permission_classes = [IsAdminOrReadOnly]


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


class WalletSummaryView(APIView):
    permission_classes = [IsEmployeeOrAdmin]

    def get(self, request):
        return Response(_stringify(reporting.wallet_summary()))
