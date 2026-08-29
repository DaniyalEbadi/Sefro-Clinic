from decimal import Decimal

from rest_framework import serializers

from Sefro_Clinic.fields import ShamsiDateTimeField

from .models import Customer, Payment, Service, Visit


class ServiceSerializer(serializers.ModelSerializer):
    price_toman = serializers.SerializerMethodField()
    exchange_rate = serializers.SerializerMethodField()

    class Meta:
        model = Service
        fields = ['id', 'name', 'description', 'price', 'price_usd', 'price_toman', 'exchange_rate', 'time', 'is_active']

    def _get_exchange_rate(self):
        """Resolve the current rate once per serializer instance.

        DRF reuses the child serializer while rendering a list. Keeping the
        value here avoids two identical database queries for every service in
        a paginated response.
        """
        if not hasattr(self, '_exchange_rate'):
            from finance.services.exchange_rates import get_rate
            self._exchange_rate = get_rate('USD', 'TOMAN')
        return self._exchange_rate

    def get_price_toman(self, obj):
        if obj.price_usd is None or obj.price_usd == 0:
            return None
        from finance.services.exchange_rates import to_toman
        return str(to_toman(obj.price_usd, self._get_exchange_rate()))

    def get_exchange_rate(self, obj):
        return str(self._get_exchange_rate())


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
