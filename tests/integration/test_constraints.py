from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from customers.models import Customer, Payment, Service
from tests.helpers import admin_client


def make_customer(**overrides):
    data = {
        'first_name': 'Ali', 'last_name': 'Rezaei',
        'mobile_number': '09121111111', 'national_id': '001-0000001',
        'bitmoji_code': 'B001',
    }
    data.update(overrides)
    return Customer.objects.create(**data)


class UniqueConstraintTests(TestCase):
    def test_duplicate_mobile_rejected_at_db_level(self):
        make_customer()
        with transaction.atomic():
            with self.assertRaises(IntegrityError):
                make_customer(mobile_number='09121111111')

    def test_duplicate_national_id_rejected_at_db_level(self):
        make_customer()
        with transaction.atomic():
            with self.assertRaises(IntegrityError):
                make_customer(national_id='001-0000001')

    def test_duplicate_bitmoji_code_rejected_at_db_level(self):
        make_customer()
        with transaction.atomic():
            with self.assertRaises(IntegrityError):
                make_customer(
                    mobile_number='09122222222',
                    national_id='002-0000002',
                    bitmoji_code='B001',
                )

    def test_duplicate_service_name_rejected_at_db_level(self):
        Service.objects.create(name='Consultation')
        with transaction.atomic():
            with self.assertRaises(IntegrityError):
                Service.objects.create(name='Consultation')

    def test_nullable_bitmoji_allows_multiple_blanks(self):
        make_customer(bitmoji_code=None)
        second = make_customer(mobile_number='09122222222', national_id='002-0000002', bitmoji_code=None)
        self.assertIsNone(second.bitmoji_code)


class ApiDuplicateTests(TestCase):
    def test_api_duplicate_mobile_returns_400(self):
        client = admin_client()
        make_customer()
        response = client.post('/api/customers/', {
            'first_name': 'Sara', 'last_name': 'Mohammadi',
            'mobile_number': '09121111111', 'national_id': '009-0000009',
        }, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertIn('mobile_number', response.data)

    def test_api_duplicate_national_id_returns_400(self):
        client = admin_client()
        make_customer()
        response = client.post('/api/customers/', {
            'first_name': 'Sara', 'last_name': 'Mohammadi',
            'mobile_number': '09122222222', 'national_id': '001-0000001',
        }, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertIn('national_id', response.data)


class CascadeTests(TestCase):
    def test_deleting_customer_cascades_visits_and_payments(self):
        from customers.models import Visit
        customer = make_customer()
        visit = Visit.objects.create(customer=customer, start_at=timezone.now(), end_at=timezone.now())
        Payment.objects.create(customer=customer, visit=visit, amount='1000', paid_at=timezone.now())

        customer.delete()

        self.assertFalse(Visit.objects.filter(id=visit.id).exists())
        self.assertFalse(Payment.objects.filter(customer_id=customer.id).exists())

    def test_deleting_visit_nulls_payment_visit_reference(self):
        from customers.models import Visit
        customer = make_customer()
        visit = Visit.objects.create(customer=customer, start_at=timezone.now(), end_at=timezone.now())
        payment = Payment.objects.create(
            customer=customer, visit=visit, amount='1000', paid_at=timezone.now(),
        )

        visit.delete()

        payment.refresh_from_db()
        self.assertIsNone(payment.visit)
        self.assertEqual(payment.customer_id, customer.id)
