from decimal import Decimal

from rest_framework import serializers

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
    WelcomePack,
    WelcomePackItem,
    WelcomePackUsage,
)


class ExchangeRateSerializer(serializers.ModelSerializer):
    class Meta:
        model = ExchangeRate
        fields = ['id', 'currency_from', 'currency_to', 'rate', 'effective_at', 'source', 'is_active', 'created_at']


class WalletRewardRuleSerializer(serializers.ModelSerializer):
    class Meta:
        model = WalletRewardRule
        fields = [
            'id', 'name', 'rule_type', 'value', 'min_base_amount_usd',
            'applies_to', 'is_active', 'start_date', 'end_date', 'created_at',
        ]


class WalletSerializer(serializers.ModelSerializer):
    customer_name = serializers.SerializerMethodField()

    class Meta:
        model = Wallet
        fields = ['id', 'customer', 'customer_name', 'currency', 'balance', 'created_at', 'updated_at']

    def get_customer_name(self, obj):
        return str(obj.customer)


class WalletTransactionSerializer(serializers.ModelSerializer):
    class Meta:
        model = WalletTransaction
        fields = [
            'id', 'wallet', 'transaction_type', 'amount', 'balance_after',
            'reference_type', 'reference_id', 'description', 'exchange_rate_snapshot', 'created_at',
        ]


class PackageSerializer(serializers.ModelSerializer):
    price_toman = serializers.SerializerMethodField()
    exchange_rate = serializers.SerializerMethodField()
    services = serializers.SerializerMethodField()
    items = serializers.SerializerMethodField()

    class Meta:
        model = Package
        fields = [
            'id', 'name', 'description', 'price_usd', 'is_active', 'created_at',
            'price_toman', 'exchange_rate', 'services', 'items',
        ]

    def _get_exchange_rate(self):
        if not hasattr(self, '_exchange_rate'):
            from .services.exchange_rates import get_rate
            self._exchange_rate = get_rate('USD', 'TOMAN')
        return self._exchange_rate

    def get_price_toman(self, obj):
        from .services.pricing import package_price_toman
        return str(package_price_toman(obj, rate=self._get_exchange_rate()))

    def get_exchange_rate(self, obj):
        return str(self._get_exchange_rate())

    def get_services(self, obj):
        return list(obj.package_services.values_list('service_id', flat=True))

    def get_items(self, obj):
        return [
            {'product': i.product_id, 'quantity': str(i.quantity)}
            for i in obj.items.all()
        ]


class ServiceItemSerializer(serializers.ModelSerializer):
    product_name = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = ServiceItem
        fields = ['id', 'service', 'product', 'product_name', 'quantity', 'selection_group']

    def get_product_name(self, obj):
        return str(obj.product) if obj.product else ''

    def validate_quantity(self, value):
        if value is not None and value <= 0:
            raise serializers.ValidationError('Quantity must be greater than zero.')
        return value

    def validate(self, attrs):
        product = attrs.get('product') or getattr(self.instance, 'product', None)
        if product is not None and hasattr(product, 'status'):
            if product.status == product.StatusChoices.FINISHED:
                raise serializers.ValidationError({'product': 'Cannot assign a finished/inactive product.'})
        return attrs

    def validate_selection_group(self, value):
        if value is None:
            return None
        value = value.strip()
        return value or None


class PackageItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = PackageItem
        fields = ['id', 'package', 'product', 'quantity']


class PackageServiceSerializer(serializers.ModelSerializer):
    class Meta:
        model = PackageService
        fields = ['id', 'package', 'service']


class WelcomePackItemSerializer(serializers.ModelSerializer):
    product_name = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = WelcomePackItem
        fields = ['id', 'welcome_pack', 'product', 'product_name', 'quantity', 'created_at', 'updated_at']
        read_only_fields = ['created_at', 'updated_at']

    def get_product_name(self, obj):
        return str(obj.product) if obj.product else ''

    def validate_quantity(self, value):
        if value is not None and value <= 0:
            raise serializers.ValidationError('Quantity must be greater than zero.')
        return value

    def validate(self, attrs):
        product = attrs.get('product') or getattr(self.instance, 'product', None)
        if product is not None and hasattr(product, 'status'):
            if product.status == product.StatusChoices.FINISHED:
                raise serializers.ValidationError({'product': 'Cannot assign a finished/inactive product.'})
        return attrs


class WelcomePackSerializer(serializers.ModelSerializer):
    total_cost_usd = serializers.SerializerMethodField()
    total_cost_toman = serializers.SerializerMethodField()
    exchange_rate = serializers.SerializerMethodField()
    items = WelcomePackItemSerializer(many=True, read_only=True)
    created_by_name = serializers.SerializerMethodField()

    class Meta:
        model = WelcomePack
        fields = [
            'id', 'name', 'description', 'is_active', 'created_at', 'updated_at',
            'created_by', 'created_by_name',
            'total_cost_usd', 'total_cost_toman', 'exchange_rate',
            'items',
        ]
        read_only_fields = ['created_by', 'created_at', 'updated_at']

    def _get_exchange_rate(self):
        if not hasattr(self, '_exchange_rate'):
            from .services.exchange_rates import get_current_usd_to_toman_rate
            self._exchange_rate = get_current_usd_to_toman_rate()
        return self._exchange_rate

    def get_exchange_rate(self, obj):
        rate = self._get_exchange_rate()
        return str(rate) if rate is not None else None

    def get_total_cost_usd(self, obj):
        from .services.welcome_pack import calculate_welcome_pack_cost_usd
        cost = calculate_welcome_pack_cost_usd(obj)
        return str(cost)

    def get_total_cost_toman(self, obj):
        from .services.welcome_pack import calculate_welcome_pack_cost_toman
        cost = calculate_welcome_pack_cost_toman(obj)
        return str(cost) if cost is not None else None

    def get_created_by_name(self, obj):
        return str(obj.created_by) if obj.created_by else None

    def create(self, validated_data):
        validated_data['created_by'] = self.context['request'].user
        return super().create(validated_data)


class WelcomePackUsageSerializer(serializers.ModelSerializer):
    welcome_pack_name = serializers.SerializerMethodField()
    customer_name = serializers.SerializerMethodField()
    issued_by_name = serializers.SerializerMethodField()

    class Meta:
        model = WelcomePackUsage
        fields = [
            'id', 'welcome_pack', 'welcome_pack_name', 'customer', 'customer_name',
            'visit', 'issued_by', 'issued_by_name', 'quantity',
            'total_cost_usd_snapshot', 'exchange_rate_snapshot', 'total_cost_toman_snapshot',
            'issued_at', 'created_at',
        ]
        read_only_fields = fields

    def get_welcome_pack_name(self, obj):
        return str(obj.welcome_pack)

    def get_customer_name(self, obj):
        return str(obj.customer) if obj.customer else None

    def get_issued_by_name(self, obj):
        return str(obj.issued_by) if obj.issued_by else None


class ProductCostHistorySerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductCostHistory
        fields = ['id', 'product', 'cost_usd', 'effective_from', 'effective_to', 'created_at']


class ProductUsageSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductUsage
        fields = [
            'id', 'product', 'visit', 'service', 'package_sale',
            'quantity', 'unit_cost_usd_snapshot', 'total_cost_usd_snapshot',
            'exchange_rate_snapshot', 'is_commission', 'created_at',
        ]


class SaleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Sale
        fields = [
            'id', 'customer', 'visit', 'package', 'payment', 'amount_usd',
            'discount_usd', 'exchange_rate', 'amount_toman', 'status',
            'idempotency_key', 'created_at',
        ]


class PaymentComponentSerializer(serializers.ModelSerializer):
    class Meta:
        model = PaymentComponent
        fields = ['id', 'sale', 'method', 'amount_usd', 'wallet_transaction', 'created_at']


class ExpenseCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = ExpenseCategory
        fields = ['id', 'name', 'is_active']


class ExpenseSerializer(serializers.ModelSerializer):
    created_by_name = serializers.SerializerMethodField()
    approved_by_name = serializers.SerializerMethodField()

    class Meta:
        model = Expense
        fields = [
            'id', 'created_by', 'created_by_name', 'category', 'amount_usd',
            'exchange_rate_snapshot', 'amount_toman', 'description', 'vendor',
            'expense_date', 'status', 'approved_by', 'approved_by_name',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['created_by', 'approved_by', 'exchange_rate_snapshot', 'amount_toman']

    def get_created_by_name(self, obj):
        return str(obj.created_by) if obj.created_by else None

    def get_approved_by_name(self, obj):
        return str(obj.approved_by) if obj.approved_by else None


class ProductPurchaseSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductPurchase
        fields = [
            'id', 'product', 'quantity', 'unit_cost_usd', 'total_cost_usd',
            'supplier', 'purchase_date', 'exchange_rate_snapshot', 'created_at',
        ]


class CheckoutSerializer(serializers.Serializer):
    customer = serializers.IntegerField()
    amount_usd = serializers.DecimalField(max_digits=14, decimal_places=2)
    components = serializers.ListField(
        child=serializers.DictField(child=serializers.CharField()),
        allow_empty=False,
    )
    discount_usd = serializers.DecimalField(max_digits=14, decimal_places=2, required=False, default=Decimal('0'))
    visit = serializers.IntegerField(required=False, allow_null=True)
    package = serializers.IntegerField(required=False, allow_null=True)
    idempotency_key = serializers.CharField(required=False, allow_blank=True, max_length=64)
    description = serializers.CharField(required=False, allow_blank=True, max_length=500)

    def validate_components(self, value):
        valid_methods = {'cash', 'cash_usd', 'cash_toman', 'card', 'wallet'}
        for comp in value:
            method = comp.get('method')
            amt = comp.get('amount_usd')
            if method not in valid_methods:
                raise serializers.ValidationError(f'Invalid payment method: {method}. Valid methods: {", ".join(valid_methods)}')
            try:
                amt = Decimal(str(amt))
            except Exception:
                raise serializers.ValidationError('amount_usd must be a decimal.')
            if amt < 0:
                raise serializers.ValidationError('Component amount cannot be negative.')
            comp['amount_usd'] = amt
        return value


class RefundSerializer(serializers.Serializer):
    refund_amount_usd = serializers.DecimalField(max_digits=14, decimal_places=2, required=False, allow_null=True)
    reason = serializers.CharField(required=False, allow_blank=True, max_length=500)


class StaffCompensationRuleSerializer(serializers.ModelSerializer):
    class Meta:
        model = StaffCompensationRule
        fields = [
            'id', 'role', 'payout_type', 'calculation_type',
            'percent_profit', 'fixed_amount_usd', 'fixed_amount_toman',
            'transport_usd', 'transport_toman',
            'product', 'product_qty',
            'is_active', 'created_at', 'updated_at',
        ]
        read_only_fields = ['created_at', 'updated_at']


class StaffPayoutSerializer(serializers.ModelSerializer):
    staff_name = serializers.SerializerMethodField()
    service_name = serializers.SerializerMethodField()
    product_name = serializers.SerializerMethodField()
    total_payout_usd = serializers.SerializerMethodField()
    total_payout_toman = serializers.SerializerMethodField()

    class Meta:
        model = StaffPayout
        fields = [
            'id', 'staff', 'staff_name', 'visit', 'service', 'service_name', 'role',
            'revenue_usd', 'revenue_toman',
            'product_cost_usd', 'product_cost_toman',
            'profit_usd', 'profit_toman',
            'payout_cash_usd', 'payout_cash_toman',
            'payout_product', 'product_name', 'payout_product_qty',
            'payout_product_value_usd', 'payout_product_value_toman',
            'total_payout_usd', 'total_payout_toman',
            'exchange_rate', 'status', 'payout_mode', 'notes',
            'approved_by', 'approved_at', 'paid_at',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['created_at', 'updated_at']

    def get_staff_name(self, obj):
        return f"{obj.staff.first_name} {obj.staff.last_name}".strip() or obj.staff.username

    def get_service_name(self, obj):
        return obj.service.name if obj.service else None

    def get_product_name(self, obj):
        return obj.payout_product.name if obj.payout_product else None

    def get_total_payout_usd(self, obj):
        return str((obj.payout_cash_usd or Decimal('0')) + (obj.payout_product_value_usd or Decimal('0')))

    def get_total_payout_toman(self, obj):
        return str((obj.payout_cash_toman or Decimal('0')) + (obj.payout_product_value_toman or Decimal('0')))


class OperatingExpenseCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = OperatingExpenseCategory
        fields = ['id', 'name', 'slug', 'description', 'is_active', 'sort_order', 'created_at', 'updated_at']
        read_only_fields = ['created_at', 'updated_at']


class OperatingExpenseSerializer(serializers.ModelSerializer):
    category_name = serializers.SerializerMethodField()
    created_by_name = serializers.SerializerMethodField()
    # Declared explicitly (no UniqueValidator) so a retried create reaches the
    # service layer, which returns the original record for the same key —
    # mirroring the checkout/Sale idempotency pattern.
    idempotency_key = serializers.CharField(required=False, allow_blank=True, max_length=64)

    class Meta:
        model = OperatingExpense
        fields = [
            'id', 'category', 'category_name', 'title', 'description',
            'amount_usd', 'exchange_rate', 'amount_toman', 'expense_date',
            'payment_method', 'vendor', 'receipt', 'notes',
            'created_by', 'created_by_name', 'idempotency_key',
            'created_at', 'updated_at',
        ]
        # Server-owned fields: the rate/Toman snapshots are taken at write time
        # by the service layer, and the creator always comes from the request.
        read_only_fields = ['exchange_rate', 'amount_toman', 'created_by', 'created_at', 'updated_at']

    def get_category_name(self, obj):
        return obj.category.name if obj.category else None

    def get_created_by_name(self, obj):
        user = obj.created_by
        if user is None:
            return None
        full = f'{user.first_name} {user.last_name}'.strip()
        return full or user.username

    def validate_category(self, value):
        if value is not None and not value.is_active:
            raise serializers.ValidationError('Category is inactive.')
        return value

    def validate_amount_usd(self, value):
        if value is not None and value < Decimal('0'):
            raise serializers.ValidationError('Amount must be non-negative.')
        return value
