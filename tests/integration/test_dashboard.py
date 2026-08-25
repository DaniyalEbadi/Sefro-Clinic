from django.test import TestCase
from django.utils import timezone

from customers.models import Customer, Payment, Service, Visit
from tests.helpers import admin_client


class DashboardTests(TestCase):
    def setUp(self):
        self.client = admin_client()

    def test_empty_database_baseline(self):
        response = self.client.get('/api/dashboard/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['customer_count'], 0)
        self.assertEqual(response.data['loyal_customer_count'], 0)
        self.assertEqual(float(response.data['today_sales']), 0)
        self.assertEqual(response.data['today_visits'], 0)
        self.assertEqual(response.data['new_customers'], 0)

    def test_counts_reflect_seeded_data(self):
        customer = Customer.objects.create(
            first_name='Ali', last_name='Rezaei',
            mobile_number='09121111111', national_id='001-0000001',
        )
        Payment.objects.create(customer=customer, amount='300000', paid_at=timezone.now())
        Visit.objects.create(
            customer=customer,
            start_at=timezone.now(),
            end_at=timezone.now(),
        )
        response = self.client.get('/api/dashboard/')
        self.assertEqual(response.data['customer_count'], 1)
        self.assertEqual(float(response.data['today_sales']), 300000.0)
        self.assertGreaterEqual(response.data['today_visits'], 1)
        self.assertGreaterEqual(response.data['new_customers'], 1)

    def test_loyal_customer_requires_five_visits(self):
        customer = Customer.objects.create(
            first_name='Loyal', last_name='Lucy',
            mobile_number='09128888888', national_id='008-0000008',
        )
        for _ in range(5):
            Visit.objects.create(customer=customer, start_at=timezone.now(), end_at=timezone.now())
        Customer.objects.create(
            first_name='Fresh', last_name='Fred',
            mobile_number='09129999999', national_id='009-0000009',
        )
        response = self.client.get('/api/dashboard/')
        self.assertEqual(response.data['loyal_customer_count'], 1)

    def test_service_creation_does_not_break_dashboard(self):
        Service.objects.create(name='Consultation')
        response = self.client.get('/api/dashboard/')
        self.assertEqual(response.status_code, 200)
