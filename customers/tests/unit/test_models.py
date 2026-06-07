from decimal import Decimal

from django.test import TestCase

from customers.models import Customer, Service, Visit, Payment


class CustomerModelTest(TestCase):
    def setUp(self):
        self.customer = Customer.objects.create(
            first_name='Ali', last_name='Rezaei',
            mobile_number='09121111111', national_id='001-0000001',
            bitmoji_code='B001',
        )

    def test_full_name(self):
        self.assertEqual(self.customer.full_name, 'Ali Rezaei')

    def test_is_new_customer(self):
        self.assertTrue(self.customer.is_new_customer)

    def test_is_loyal_customer_false(self):
        self.assertFalse(self.customer.is_loyal_customer)

    def test_total_payments_default_zero(self):
        self.assertEqual(self.customer.total_payments, Decimal('0'))


class ServiceModelTest(TestCase):
    def test_str(self):
        s = Service.objects.create(name='Massage')
        self.assertEqual(str(s), 'Massage')


class VisitModelTest(TestCase):
    def setUp(self):
        self.customer = Customer.objects.create(
            first_name='Ali', last_name='Rezaei',
            mobile_number='09121111111', national_id='001-0000001',
            bitmoji_code='B001',
        )

    def test_str(self):
        from django.utils import timezone
        v = Visit.objects.create(customer=self.customer, visit_date=timezone.now())
        self.assertIn('Ali', str(v))


class PaymentModelTest(TestCase):
    def setUp(self):
        self.customer = Customer.objects.create(
            first_name='Ali', last_name='Rezaei',
            mobile_number='09121111111', national_id='001-0000001',
            bitmoji_code='B001',
        )

    def test_str(self):
        from django.utils import timezone
        p = Payment.objects.create(
            customer=self.customer, amount=Decimal('50000'),
            paid_at=timezone.now(),
        )
        self.assertIn('Ali', str(p))
