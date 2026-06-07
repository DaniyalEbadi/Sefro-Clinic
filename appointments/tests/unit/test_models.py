from django.test import TestCase
from django.utils import timezone

from appointments.models import Appointment
from customers.models import Customer, Service


class AppointmentModelTest(TestCase):
    def setUp(self):
        self.customer = Customer.objects.create(
            first_name='Ali', last_name='Rezaei',
            mobile_number='09121111111', national_id='001-0000001',
            bitmoji_code='B001',
        )
        self.service = Service.objects.create(name='Consultation')

    def test_default_status_pending(self):
        apt = Appointment.objects.create(
            customer=self.customer, service=self.service,
            start_at=timezone.now(), end_at=timezone.now() + timezone.timedelta(hours=1),
        )
        self.assertEqual(apt.status, Appointment.Status.PENDING)

    def test_str(self):
        apt = Appointment.objects.create(
            customer=self.customer, service=self.service,
            start_at=timezone.now(), end_at=timezone.now() + timezone.timedelta(hours=1),
        )
        self.assertIn('Ali', str(apt))
