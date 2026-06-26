from rest_framework import serializers

from Sefro_Clinic.fields import ShamsiDateField, ShamsiDateTimeField

from .models import Customer, Payment, Service, Visit, WorkTime


class ShortTimeField(serializers.CharField):
    def to_representation(self, value):
        if isinstance(value, str):
            return value
        return value.strftime('%H:%M')

    def to_internal_value(self, value):
        from datetime import datetime
        try:
            return datetime.strptime(value, '%H:%M').time()
        except (ValueError, TypeError):
            raise serializers.ValidationError('فرمت زمان باید HH:MM باشد')


class ServiceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Service
        fields = ['id', 'name', 'description', 'price', 'time', 'is_active']


class VisitSerializer(serializers.ModelSerializer):
    service_names = serializers.StringRelatedField(source='services', many=True, read_only=True)
    start_at = ShamsiDateTimeField()
    end_at = ShamsiDateTimeField()

    class Meta:
        model = Visit
        fields = ['id', 'customer', 'staff', 'services', 'service_names', 'start_at', 'end_at',
                  'status', 'notes']


class PaymentSerializer(serializers.ModelSerializer):
    paid_at = ShamsiDateTimeField(required=False)
    customer_name = serializers.SerializerMethodField()

    class Meta:
        model = Payment
        fields = ['id', 'customer', 'customer_name', 'visit', 'amount', 'payment_method', 'paid_at', 'notes']

    def get_customer_name(self, obj):
        return str(obj.customer)


class WorkTimeSerializer(serializers.ModelSerializer):
    start_time = ShortTimeField()
    end_time = ShortTimeField()

    class Meta:
        model = WorkTime
        fields = ['id', 'start_time', 'end_time']


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
