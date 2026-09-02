from decimal import Decimal

from rest_framework import serializers

from Sefro_Clinic.fields import ShamsiDateTimeField

from .models import Customer, Payment, Service, ServiceCategory, Visit


class ServiceCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = ServiceCategory
        fields = ['id', 'name', 'slug', 'description', 'is_active', 'sort_order']


class ServiceSerializer(serializers.ModelSerializer):
    price_toman = serializers.SerializerMethodField()
    exchange_rate = serializers.SerializerMethodField()
    category = ServiceCategorySerializer(read_only=True)
    category_id = serializers.PrimaryKeyRelatedField(
        source='category', queryset=ServiceCategory.objects.all(), required=False, allow_null=True, write_only=True
    )
    products = serializers.SerializerMethodField()
    estimated_cost_usd = serializers.SerializerMethodField()
    estimated_cost_toman = serializers.SerializerMethodField()
    estimated_gross_profit_usd = serializers.SerializerMethodField()
    estimated_gross_profit_toman = serializers.SerializerMethodField()
    estimated_margin_percent = serializers.SerializerMethodField()

    class Meta:
        model = Service
        fields = [
            'id', 'name', 'description', 'price', 'price_usd', 'price_toman', 'exchange_rate',
            'time', 'is_active', 'category', 'category_id',
            'products', 'estimated_cost_usd', 'estimated_cost_toman',
            'estimated_gross_profit_usd', 'estimated_gross_profit_toman',
            'estimated_margin_percent',
        ]

    def _get_exchange_rate(self):
        """Resolve the current rate once per request/context to avoid N+1 external calls."""
        # Reuse context cache across list serialization
        ctx = self.context
        # Check if parent serializer sets it
        if isinstance(ctx, dict) and '_exchange_rate_cached' in ctx:
            return ctx['_exchange_rate_cached']
        if not hasattr(self, '_exchange_rate'):
            from finance.services.exchange_rates import get_current_usd_to_toman_rate

            self._exchange_rate = get_current_usd_to_toman_rate()
            # store in context for sibling serializers
            if isinstance(ctx, dict):
                ctx['_exchange_rate_cached'] = self._exchange_rate
        return self._exchange_rate

    def _get_pricing(self, obj):
        if not hasattr(self, '_pricing_cache'):
            self._pricing_cache = {}
        if obj.id not in self._pricing_cache:
            from customers.services.pricing import service_pricing_breakdown

            self._pricing_cache[obj.id] = service_pricing_breakdown(obj, rate=self._get_exchange_rate())
        return self._pricing_cache[obj.id]

    def get_price_toman(self, obj):
        if obj.price_usd is None:
            return None
        pricing = self._get_pricing(obj)
        val = pricing['price_toman']
        return str(val) if val is not None else None

    def get_exchange_rate(self, obj):
        rate = self._get_exchange_rate()
        return str(rate) if rate is not None else None

    def get_products(self, obj):
        items = []
        # Use prefetched items if available
        if hasattr(obj, '_prefetched_objects_cache') and 'items' in obj._prefetched_objects_cache:
            qs = obj._prefetched_objects_cache['items']
        else:
            qs = obj.items.select_related('product').all()
        for item in qs:
            qty = item.quantity
            unit_cost = item.product.cost_usd if item.product else Decimal('0')
            try:
                total = (Decimal(str(qty)) * Decimal(str(unit_cost))).quantize(Decimal('0.01'))
            except Exception:
                total = Decimal('0.00')
            items.append({
                'product': item.product_id,
                'name': str(item.product) if item.product else '',
                'quantity': format(qty, '.3f') if qty is not None else '0.000',
                'unit_cost_usd': format(Decimal(str(unit_cost)).quantize(Decimal('0.01')), '.2f'),
                'total_cost_usd': format(total, '.2f'),
            })
        return items

    def get_estimated_cost_usd(self, obj):
        return format(self._get_pricing(obj)['estimated_cost_usd'], '.2f')

    def get_estimated_cost_toman(self, obj):
        val = self._get_pricing(obj)['estimated_cost_toman']
        return format(val, '.2f') if val is not None else None

    def get_estimated_gross_profit_usd(self, obj):
        return format(self._get_pricing(obj)['estimated_gross_profit_usd'], '.2f')

    def get_estimated_gross_profit_toman(self, obj):
        val = self._get_pricing(obj)['estimated_gross_profit_toman']
        return format(val, '.2f') if val is not None else None

    def get_estimated_margin_percent(self, obj):
        return format(self._get_pricing(obj)['estimated_margin_percent'], '.2f')


# Reuse authoritative ServiceItem serializer from finance to avoid duplicate concept
from finance.serializers import ServiceItemSerializer  # noqa: E402, F401


class VisitSerializer(serializers.ModelSerializer):
    service_names = serializers.StringRelatedField(source='services', many=True, read_only=True)
    start_at = ShamsiDateTimeField()
    end_at = ShamsiDateTimeField()
    staff = serializers.PrimaryKeyRelatedField(read_only=True)

    class Meta:
        model = Visit
        fields = ['id', 'customer', 'staff', 'services', 'service_names', 'start_at', 'end_at',
                  'status', 'notes']

    def validate(self, attrs):
        start_at = attrs.get('start_at')
        end_at = attrs.get('end_at')
        if start_at and end_at and end_at < start_at:
            raise serializers.ValidationError({'end_at': 'پایان ویزیت باید بعد از شروع آن باشد.'})

        customer = attrs.get('customer') or getattr(self.instance, 'customer', None)
        start_at = start_at or getattr(self.instance, 'start_at', None)
        end_at = end_at or getattr(self.instance, 'end_at', None)
        if customer and start_at and end_at:
            queryset = Visit.objects.filter(
                customer=customer,
                status__in=[Visit.Status.PENDING, Visit.Status.CONFIRMED, Visit.Status.COMPLETED],
            )
            if self.instance is not None:
                queryset = queryset.exclude(pk=self.instance.pk)
            overlapping = queryset.filter(start_at__lt=end_at, end_at__gt=start_at).exists()
            if overlapping:
                raise serializers.ValidationError(
                    {'start_at': 'این بازه زمانی با ویزیت دیگری از همین مشتری تداخل دارد.'}
                )
        return attrs


class PaymentSerializer(serializers.ModelSerializer):
    paid_at = ShamsiDateTimeField(required=False)
    customer_name = serializers.SerializerMethodField()

    class Meta:
        model = Payment
        fields = ['id', 'customer', 'customer_name', 'visit', 'amount', 'amount_usd', 'exchange_rate',
                  'payment_method', 'paid_at', 'notes']

    def get_customer_name(self, obj):
        return str(obj.customer)


class CustomerSerializer(serializers.ModelSerializer):
    visit_number = serializers.SerializerMethodField()
    is_new_customer = serializers.SerializerMethodField()
    is_loyal_customer = serializers.SerializerMethodField()
    total_payments = serializers.SerializerMethodField()
    created_at = ShamsiDateTimeField(read_only=True)
    last_visit_date = serializers.SerializerMethodField()
    bitmoji_code = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    satisfaction = serializers.IntegerField(required=False, allow_null=True, min_value=1, max_value=5)

    class Meta:
        model = Customer
        fields = [
            'id',
            'first_name',
            'last_name',
            'mobile_number',
            'national_id',
            'bitmoji_code',
            'satisfaction',
            'notes',
            'created_at',
            'visit_number',
            'is_new_customer',
            'is_loyal_customer',
            'total_payments',
            'last_visit_date',
        ]

    def get_is_new_customer(self, obj):
        vc = getattr(obj, 'num_visits', None) or 0
        return vc == 0

    def get_visit_number(self, obj):
        # Detail/create responses are not annotated. Preserve the API
        # contract without triggering an extra query per row.
        return getattr(obj, 'num_visits', 0) or 0

    def get_is_loyal_customer(self, obj):
        vc = getattr(obj, 'num_visits', None) or 0
        return vc >= 5

    def get_total_payments(self, obj):
        return getattr(obj, 'sum_payments', Decimal('0')) or Decimal('0')

    def get_last_visit_date(self, obj):
        from Sefro_Clinic.fields import greg_to_shamsi_date
        dt = getattr(obj, 'last_visit_at', None)
        return greg_to_shamsi_date(dt)
