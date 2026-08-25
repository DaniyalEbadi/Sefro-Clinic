from datetime import datetime, timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework import status

from customers.models import Customer, Service
from tests.helpers import admin_client


def at(year, month, day, hour=10, minute=0):
    return timezone.make_aware(datetime(year, month, day, hour, minute))


def future_slot(days_ahead=7, hour=10):
    start = (timezone.now() + timedelta(days=days_ahead)).replace(
        hour=hour, minute=0, second=0, microsecond=0,
    )
    return start, start + timedelta(hours=1)


class VisitOverlapPreventionTests(TestCase):
    def setUp(self):
        self.client = admin_client()
        self.customer = Customer.objects.create(
            first_name='Ola', last_name='Verlap',
            mobile_number='09129129129', national_id='320-0000320',
        )
        self.other_customer = Customer.objects.create(
            first_name='Free', last_name='Slot',
            mobile_number='09129292929', national_id='321-0000321',
        )
        self.service = Service.objects.create(name='Consultation')

    def _payload(self, customer_id, start, end, visit_id=None):
        data = {
            'customer': customer_id,
            'start_at': start.strftime('%Y-%m-%d %H:%M'),
            'end_at': end.strftime('%Y-%m-%d %H:%M'),
            'services': [self.service.id],
        }
        if visit_id:
            return f'/api/visits/{visit_id}/', data
        return '/api/visits/', data

    def test_overlapping_visit_for_same_customer_rejected(self):
        start, end = future_slot()
        first = self.client.post('/api/visits/', self._payload(self.customer.id, start, end)[1], format='json')
        self.assertEqual(first.status_code, status.HTTP_201_CREATED)

        overlap_start = start + timedelta(minutes=30)
        overlap_end = end + timedelta(minutes=30)
        second = self.client.post('/api/visits/', self._payload(self.customer.id, overlap_start, overlap_end)[1], format='json')
        self.assertEqual(second.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('start_at', second.data)

    def test_adjacent_back_to_back_visits_allowed(self):
        start, end = future_slot()
        ok = self.client.post('/api/visits/', self._payload(self.customer.id, start, end)[1], format='json')
        self.assertEqual(ok.status_code, status.HTTP_201_CREATED)

        next_start, next_end = end, end + timedelta(hours=1)
        adjacent = self.client.post('/api/visits/', self._payload(self.customer.id, next_start, next_end)[1], format='json')
        self.assertEqual(adjacent.status_code, status.HTTP_201_CREATED)

    def test_same_slot_for_different_customer_allowed(self):
        start, end = future_slot()
        ok = self.client.post('/api/visits/', self._payload(self.other_customer.id, start, end)[1], format='json')
        self.assertEqual(ok.status_code, status.HTTP_201_CREATED)

    def test_canceled_visit_does_not_block_new_booking(self):
        start, end = future_slot()
        created = self.client.post('/api/visits/', self._payload(self.customer.id, start, end)[1], format='json')
        visit_id = created.data['id']
        canceled = self.client.post(f'/api/visits/{visit_id}/cancel/')
        self.assertEqual(canceled.status_code, status.HTTP_200_OK)

        rebirth = self.client.post('/api/visits/', self._payload(self.customer.id, start, end)[1], format='json')
        self.assertEqual(rebirth.status_code, status.HTTP_201_CREATED)

    def test_updating_visit_excludes_itself_from_overlap_check(self):
        start, end = future_slot()
        created = self.client.post('/api/visits/', self._payload(self.customer.id, start, end)[1], format='json')
        visit_id = created.data['id']

        url, payload = self._payload(self.customer.id, start + timedelta(minutes=15), end + timedelta(minutes=15), visit_id)
        shifted = self.client.put(url, payload, format='json')
        self.assertEqual(shifted.status_code, status.HTTP_200_OK)

    def test_update_into_conflict_with_other_visit_rejected(self):
        start, end = future_slot()
        first = self.client.post('/api/visits/', self._payload(self.customer.id, start, end)[1], format='json')
        other_start, other_end = start + timedelta(hours=3), end + timedelta(hours=3)
        second = self.client.post('/api/visits/', self._payload(self.customer.id, other_start, other_end)[1], format='json')
        self.assertEqual(first.status_code, status.HTTP_201_CREATED)
        self.assertEqual(second.status_code, status.HTTP_201_CREATED)

        url, payload = self._payload(self.customer.id, other_start, other_end, first.data['id'])
        conflict = self.client.put(url, payload, format='json')
        self.assertEqual(conflict.status_code, status.HTTP_400_BAD_REQUEST)

    def test_staff_field_is_not_writable(self):
        start, end = future_slot(hour=16)
        url, payload = self._payload(self.customer.id, start, end)
        payload['staff'] = 999999
        response = self.client.post(url, payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIsNone(response.data.get('staff'))
