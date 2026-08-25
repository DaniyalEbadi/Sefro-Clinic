from rest_framework import serializers

from Sefro_Clinic.fields import ShamsiDateField, ShamsiDateTimeField

from .models import Customer, Payment, Service, Visit


class ServiceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Service
        fields = ['id', 'name', 'description', 'price', 'time', 'is_active']


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
        fields = ['id', 'customer', 'customer_name', 'visit', 'amount', 'payment_method', 'paid_at', 'notes']

    def get_customer_name(self, obj):
        return str(obj.customer)


class CustomerSerializer(serializers.ModelSerializer):
    visit_number = serializers.IntegerField(source='visit_count', read_only=True)
    is_new_customer = serializers.BooleanField(read_only=True)
    is_loyal_customer = serializers.BooleanField(read_only=True)
    total_payments = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    created_at = ShamsiDateTimeField(read_only=True)
    last_visit_date = ShamsiDateField(read_only=True)
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
