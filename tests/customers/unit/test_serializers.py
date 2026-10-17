from decimal import Decimal

from datetime import timedelta

import jdatetime
from django.test import TestCase
from django.utils import timezone

from customers.models import Customer, Payment, Service, Visit
from customers.serializers import CustomerSerializer, PaymentSerializer, ServiceSerializer, VisitSerializer


def shamsi_str(greg_dt):
    """A Gregorian datetime as its Jalali ``YYYY-MM-DD HH:MM``."""
    if timezone.is_aware(greg_dt):
        greg_dt = timezone.localtime(greg_dt)
    return jdatetime.datetime.fromgregorian(datetime=greg_dt).strftime('%Y-%m-%d %H:%M')


_NOW = timezone.now()
_START = shamsi_str(_NOW)
_END = shamsi_str(_NOW + timedelta(minutes=30))


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
            'start_at': _START, 'end_at': _END,
        })
        self.assertTrue(serializer.is_valid(), serializer.errors)
        visit = serializer.save()
        self.assertEqual(visit.customer, self.customer)

    def test_visit_serializer_invalid_missing_customer(self):
        serializer = VisitSerializer(data={
            'services': [self.service.id],
            'start_at': _START, 'end_at': _END,
        })
        self.assertFalse(serializer.is_valid())
        self.assertIn('customer', serializer.errors)

    def test_visit_serializer_exposes_payments_and_total(self):
        visit = VisitSerializer(data={
            'customer': self.customer.id, 'services': [self.service.id],
            'start_at': _START, 'end_at': _END,
        })
        self.assertTrue(visit.is_valid(), visit.errors)
        visit = visit.save()

        Payment.objects.create(
            customer=self.customer, visit=visit, amount=Decimal('75000'),
            payment_method='cash', paid_at=timezone.now(),
        )

        data = VisitSerializer(visit).data
        self.assertIn('payments', data)
        self.assertIn('total_paid', data)
        self.assertEqual(len(data['payments']), 1)
        self.assertEqual(data['payments'][0]['customer'], self.customer.id)
        self.assertEqual(Decimal(str(data['total_paid'])), Decimal('75000'))
        self.assertEqual(data['customer_name'], 'Test Customer')

    def test_visit_serializer_total_paid_zero_without_payments(self):
        visit = VisitSerializer(data={
            'customer': self.customer.id, 'services': [self.service.id],
            'start_at': _START, 'end_at': _END,
        })
        self.assertTrue(visit.is_valid(), visit.errors)
        visit = visit.save()

        data = VisitSerializer(visit).data
        self.assertEqual(data['payments'], [])
        self.assertEqual(Decimal(str(data['total_paid'])), Decimal('0'))


class PaymentSerializerTest(TestCase):
    def setUp(self):
        self.customer = Customer.objects.create(
            first_name='Test', last_name='Customer',
            mobile_number='09120000002', national_id='002-0000002',
        )

    def test_payment_serializer_valid_data(self):
        serializer = PaymentSerializer(data={
            'customer': self.customer.id, 'amount': '50000', 'payment_method': 'cash',
            'paid_at': _START,
        })
        self.assertTrue(serializer.is_valid(), serializer.errors)
        payment = serializer.save()
        self.assertEqual(payment.customer, self.customer)

    def test_payment_serializer_invalid_missing_customer(self):
        serializer = PaymentSerializer(data={
            'amount': '50000', 'payment_method': 'cash',
            'paid_at': _START,
        })
        self.assertFalse(serializer.is_valid())
        self.assertIn('customer', serializer.errors)

    def test_payment_serializer_inherits_customer_from_visit(self):
        visit = Visit.objects.create(
            customer=self.customer,
            start_at=timezone.now(), end_at=timezone.now(),
        )
        serializer = PaymentSerializer(data={
            'visit': visit.id, 'amount': '50000', 'payment_method': 'cash',
            'paid_at': _START,
        })
        self.assertTrue(serializer.is_valid(), serializer.errors)
        payment = serializer.save()
        self.assertEqual(payment.customer, self.customer)
        self.assertEqual(payment.visit, visit)

    def test_payment_serializer_rejects_foreign_customer_on_visit(self):
        visit = Visit.objects.create(
            customer=self.customer,
            start_at=timezone.now(), end_at=timezone.now(),
        )
        other = Customer.objects.create(
            first_name='Other', last_name='Client',
            mobile_number='09120000009', national_id='009-0000009',
        )
        serializer = PaymentSerializer(data={
            'customer': other.id,
            'visit': visit.id, 'amount': '50000', 'payment_method': 'cash',
            'paid_at': _START,
        })
        self.assertFalse(serializer.is_valid())
        self.assertIn('customer', serializer.errors)

    def test_payment_serializer_allows_payment_without_visit(self):
        serializer = PaymentSerializer(data={
            'customer': self.customer.id, 'amount': '50000',
            'payment_method': 'cash', 'paid_at': _START,
        })
        self.assertTrue(serializer.is_valid(), serializer.errors)
        payment = serializer.save()
        self.assertIsNone(payment.visit)


class CustomerSerializerTest(TestCase):
    def test_customer_serializer_valid_data(self):
        serializer = CustomerSerializer(data={
            'first_name': 'Test', 'last_name': 'Customer',
            'mobile_number': '09120000003', 'national_id': '003-0000003',
            'file_sys_id': 'FS00123456789012345678901234567890',
        })
        self.assertTrue(serializer.is_valid(), serializer.errors)
        customer = serializer.save()
        self.assertEqual(customer.first_name, 'Test')
        self.assertEqual(customer.file_sys_id, 'FS00123456789012345678901234567890')

    def test_customer_serializer_invalid_missing_first_name(self):
        serializer = CustomerSerializer(data={
            'last_name': 'Customer', 'mobile_number': '09120000003', 'national_id': '003-0000003',
        })
        self.assertFalse(serializer.is_valid())
        self.assertIn('first_name', serializer.errors)

    def test_customer_serializer_file_sys_id_optional(self):
        serializer = CustomerSerializer(data={
            'first_name': 'Test', 'last_name': 'Customer',
            'mobile_number': '09120000004', 'national_id': '004-0000004',
        })
        self.assertTrue(serializer.is_valid(), serializer.errors)
        customer = serializer.save()
        self.assertIsNone(customer.file_sys_id)
