from datetime import timedelta
from decimal import Decimal

import jdatetime
from django.test import TestCase
from django.utils import timezone

from accounts.models import ClinicUser
from customers.models import Customer, Service, Visit
from customers.serializers import CustomerSerializer, ServiceSerializer, VisitSerializer
from finance.models import PaymentComponent, Sale
from tests.helpers import make_employee


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

    def test_visit_serializer_exposes_sales_and_total(self):
        visit = VisitSerializer(data={
            'customer': self.customer.id, 'services': [self.service.id],
            'start_at': _START, 'end_at': _END,
        })
        self.assertTrue(visit.is_valid(), visit.errors)
        visit = visit.save()

        sale = Sale.objects.create(
            customer=self.customer, visit=visit, amount_usd=Decimal('0.75'),
            amount_toman=Decimal('75000'), status=Sale.Status.PAID,
        )
        PaymentComponent.objects.create(
            sale=sale, method=PaymentComponent.Method.CASH_TOMAN,
            amount_usd=Decimal('0.75'),
        )

        data = VisitSerializer(visit).data
        self.assertIn('sales', data)
        self.assertIn('total_paid', data)
        self.assertEqual(len(data['sales']), 1)
        self.assertEqual(data['sales'][0]['customer'], self.customer.id)
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
        self.assertEqual(data['sales'], [])
        self.assertEqual(Decimal(str(data['total_paid'])), Decimal('0'))

    def test_visit_serializer_accepts_active_staff(self):
        employee = make_employee(username='serializer_staff')
        serializer = VisitSerializer(data={
            'customer': self.customer.id, 'services': [self.service.id],
            'start_at': _START, 'end_at': _END, 'staff': employee.id,
        })
        self.assertTrue(serializer.is_valid(), serializer.errors)
        visit = serializer.save()
        self.assertEqual(visit.staff, employee)

    def test_visit_serializer_rejects_unknown_staff(self):
        serializer = VisitSerializer(data={
            'customer': self.customer.id, 'services': [self.service.id],
            'start_at': _START, 'end_at': _END, 'staff': 999999,
        })
        self.assertFalse(serializer.is_valid())
        self.assertIn('staff', serializer.errors)

    def test_visit_serializer_rejects_inactive_staff(self):
        inactive = ClinicUser.objects.create_user(
            username='inactive_staff', password='x',
            role=ClinicUser.Role.EMPLOYEE, is_active=False,
        )
        serializer = VisitSerializer(data={
            'customer': self.customer.id, 'services': [self.service.id],
            'start_at': _START, 'end_at': _END, 'staff': inactive.id,
        })
        self.assertFalse(serializer.is_valid())
        self.assertIn('staff', serializer.errors)

    def _completed_visit(self, staff):
        return Visit.objects.create(
            customer=self.customer, staff=staff,
            start_at=timezone.now(), end_at=timezone.now() + timedelta(minutes=30),
            status=Visit.Status.COMPLETED,
        )

    def test_visit_serializer_rejects_staff_change_on_completed_visit(self):
        original = make_employee(username='original_staff')
        replacement = make_employee(username='replacement_staff')
        visit = self._completed_visit(original)

        serializer = VisitSerializer(instance=visit, data={'staff': replacement.id}, partial=True)
        self.assertFalse(serializer.is_valid())
        self.assertIn('staff', serializer.errors)

    def test_visit_serializer_allows_same_staff_on_completed_visit(self):
        employee = make_employee(username='unchanged_staff')
        visit = self._completed_visit(employee)

        serializer = VisitSerializer(instance=visit, data={'staff': employee.id}, partial=True)
        self.assertTrue(serializer.is_valid(), serializer.errors)

    def test_visit_serializer_allows_staff_backfill_on_staffless_completed_visit(self):
        employee = make_employee(username='backfill_staff')
        visit = self._completed_visit(None)

        serializer = VisitSerializer(instance=visit, data={'staff': employee.id}, partial=True)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        updated = serializer.save()
        self.assertEqual(updated.staff, employee)


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
