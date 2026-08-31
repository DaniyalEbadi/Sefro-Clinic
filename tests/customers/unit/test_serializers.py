from django.test import TestCase

from customers.models import Customer, Service, Visit, Payment
from customers.serializers import ServiceSerializer, VisitSerializer, PaymentSerializer, CustomerSerializer


class ServiceSerializerTest(TestCase):
    def test_service_serializer_valid_data(self):
        serializer = ServiceSerializer(data={'name': 'Facial', 'price': '800000', 'price_usd': '100', 'time': 30})
        self.assertTrue(serializer.is_valid(), serializer.errors)
        service = serializer.save()
        self.assertEqual(service.name, 'Facial')

    def test_service_serializer_invalid_missing_name(self):
        serializer = ServiceSerializer(data={'price': '800000', 'price_usd': '100', 'time': 30})
        self.assertFalse(serializer.is_valid())
        self.assertIn('name', serializer.errors)

    def test_service_serializer_invalid_negative_price(self):
        serializer = ServiceSerializer(data={'name': 'Facial', 'price': '-100', 'price_usd': '100', 'time': 30})
        self.assertFalse(serializer.is_valid())


class VisitSerializerTest(TestCase):
    def setUp(self):
        self.customer = Customer.objects.create(
            first_name='Test', last_name='Customer',
            mobile_number='09120000001', national_id='001-0000001',
        )
        self.service = Service.objects.create(name='Facial', price=800000, price_usd=100, time=30)

    def test_visit_serializer_valid_data(self):
        serializer = VisitSerializer(data={
            'customer': self.customer.id, 'services': [self.service.id],
            'start_at': '2024-01-01 10:00', 'end_at': '2024-01-01 10:30',
        })
        self.assertTrue(serializer.is_valid(), serializer.errors)
        visit = serializer.save()
        self.assertEqual(visit.customer, self.customer)

    def test_visit_serializer_invalid_missing_customer(self):
        serializer = VisitSerializer(data={
            'services': [self.service.id],
            'start_at': '2024-01-01 10:00', 'end_at': '2024-01-01 10:30',
        })
        self.assertFalse(serializer.is_valid())
        self.assertIn('customer', serializer.errors)


class PaymentSerializerTest(TestCase):
    def setUp(self):
        self.customer = Customer.objects.create(
            first_name='Test', last_name='Customer',
            mobile_number='09120000002', national_id='002-0000002',
        )

    def test_payment_serializer_valid_data(self):
        serializer = PaymentSerializer(data={
            'customer': self.customer.id, 'amount': '50000', 'payment_method': 'cash',
            'paid_at': '2024-01-01 10:00',
        })
        self.assertTrue(serializer.is_valid(), serializer.errors)
        payment = serializer.save()
        self.assertEqual(payment.customer, self.customer)

    def test_payment_serializer_invalid_missing_customer(self):
        serializer = PaymentSerializer(data={
            'amount': '50000', 'payment_method': 'cash',
            'paid_at': '2024-01-01 10:00',
        })
        self.assertFalse(serializer.is_valid())
        self.assertIn('customer', serializer.errors)


class CustomerSerializerTest(TestCase):
    def test_customer_serializer_valid_data(self):
        serializer = CustomerSerializer(data={
            'first_name': 'Test', 'last_name': 'Customer',
            'mobile_number': '09120000003', 'national_id': '003-0000003',
        })
        self.assertTrue(serializer.is_valid(), serializer.errors)
        customer = serializer.save()
        self.assertEqual(customer.first_name, 'Test')

    def test_customer_serializer_invalid_missing_first_name(self):
        serializer = CustomerSerializer(data={
            'last_name': 'Customer', 'mobile_number': '09120000003', 'national_id': '003-0000003',
        })
        self.assertFalse(serializer.is_valid())
        self.assertIn('first_name', serializer.errors)