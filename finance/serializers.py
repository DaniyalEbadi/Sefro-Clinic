from decimal import Decimal

from rest_framework import serializers

from .models import (
    ExchangeRate,
    Expense,
    ExpenseCategory,
    Package,
    PackageItem,
    PackageService,
    PaymentComponent,
    ProductCostHistory,
    ProductPurchase,
    ProductUsage,
    Sale,
    ServiceItem,
    Wallet,
    WalletRewardRule,
    WalletTransaction,
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
    class Meta:
        model = ServiceItem
        fields = ['id', 'service', 'product', 'quantity']


class PackageItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = PackageItem
        fields = ['id', 'package', 'product', 'quantity']


class PackageServiceSerializer(serializers.ModelSerializer):
    class Meta:
        model = PackageService
        fields = ['id', 'package', 'service']


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
            'exchange_rate_snapshot', 'created_at',
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
        valid = {'cash', 'card', 'wallet'}
        total = Decimal('0')
        for comp in value:
            method = comp.get('method')
            amt = comp.get('amount_usd')
            if method not in valid:
                raise serializers.ValidationError(f'Invalid payment method: {method}')
            try:
                amt = Decimal(str(amt))
            except Exception:
                raise serializers.ValidationError('amount_usd must be a decimal.')
            if amt < 0:
                raise serializers.ValidationError('Component amount cannot be negative.')
            comp['amount_usd'] = amt
            total += amt
        return value


class RefundSerializer(serializers.Serializer):
    refund_amount_usd = serializers.DecimalField(max_digits=14, decimal_places=2, required=False, allow_null=True)
    reason = serializers.CharField(required=False, allow_blank=True, max_length=500)
