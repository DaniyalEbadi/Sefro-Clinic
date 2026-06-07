from rest_framework import serializers

from .models import Customer, Payment, Service, Visit


class ServiceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Service
        fields = ['id', 'name', 'description', 'is_active']


class VisitSerializer(serializers.ModelSerializer):
    service_names = serializers.StringRelatedField(source='services', many=True, read_only=True)

    class Meta:
        model = Visit
        fields = ['id', 'customer', 'staff', 'visit_date', 'services', 'service_names', 'notes']


class PaymentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Payment
        fields = ['id', 'customer', 'visit', 'amount', 'payment_method', 'paid_at', 'notes']


class CustomerSerializer(serializers.ModelSerializer):
    visit_count = serializers.IntegerField(read_only=True)
    is_new_customer = serializers.BooleanField(read_only=True)
    is_loyal_customer = serializers.BooleanField(read_only=True)
    total_payments = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    visits = VisitSerializer(many=True, read_only=True)
    payments = PaymentSerializer(many=True, read_only=True)

    class Meta:
        model = Customer
        fields = [
            'id',
            'first_name',
            'last_name',
            'mobile_number',
            'national_id',
            'bitmoji_code',
            'notes',
            'created_at',
            'visit_count',
            'is_new_customer',
            'is_loyal_customer',
            'total_payments',
            'visits',
            'payments',
        ]
