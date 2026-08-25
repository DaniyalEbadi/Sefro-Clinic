from django.test import TestCase
from django.utils import timezone

from customers.models import Customer, Payment, Service, Visit
from tests.helpers import admin_client


class PaymentsByServiceTests(TestCase):
    def setUp(self):
        self.client = admin_client()
        self.customer = Customer.objects.create(
            first_name='Ali', last_name='Rezaei',
            mobile_number='09121111111', national_id='001-0000001',
        )
        self.consult = Service.objects.create(name='Consultation', price='100000')
        self.laser = Service.objects.create(name='Laser', price='500000')
        self.visit = Visit.objects.create(
            customer=self.customer,
            start_at=timezone.now(),
            end_at=timezone.now(),
        )
        self.visit.services.add(self.consult, self.laser)

    def test_aggregates_payments_per_service(self):
        Payment.objects.create(
            customer=self.customer, visit=self.visit,
            amount='600000', paid_at=timezone.now(),
        )
        response = self.client.get('/api/payments/by_service/')
        self.assertEqual(response.status_code, 200)
        rows = {row['service_name']: row for row in response.data}
        self.assertEqual(set(rows), {'Consultation', 'Laser'})
        self.assertEqual(rows['Consultation']['total_payments'], 600000.0)
        self.assertEqual(rows['Laser']['total_payments'], 600000.0)
        self.assertEqual(rows['Consultation']['count'], 1)

    def test_payment_without_visit_is_excluded(self):
        Payment.objects.create(
            customer=self.customer, visit=None,
            amount='999999', paid_at=timezone.now(),
        )
        response = self.client.get('/api/payments/by_service/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, [])

    def test_employee_can_read_service_aggregates(self):
        from tests.helpers import employee_client
        Payment.objects.create(
            customer=self.customer, visit=self.visit,
            amount='600000', paid_at=timezone.now(),
        )
        client = employee_client()
        response = client.get('/api/payments/by_service/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 2)
