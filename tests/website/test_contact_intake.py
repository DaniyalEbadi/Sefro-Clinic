from django.core.cache import cache
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from tests.helpers import admin_client

CONTACT_URL = '/api/v2/contact/'


class ContactIntakeTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()

    def _valid_payload(self, **overrides):
        payload = {
            'full_name': 'سارا احمدی',
            'phone': '09121234567',
            'message': 'برای مشاوره بوتاکس تماس می‌گیرم.',
        }
        payload.update(overrides)
        return payload

    def test_valid_message_is_accepted_and_stored(self):
        from website.models import ContactMessage

        response = self.client.post(CONTACT_URL, self._valid_payload(), format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(ContactMessage.objects.count(), 1)
        stored = ContactMessage.objects.first()
        self.assertEqual(stored.phone, '09121234567')
        self.assertFalse(stored.is_handled)

    def test_invalid_phone_rejected(self):
        for bad in ['12345', '0912123', '09121234567890', 'notaphone']:
            response = self.client.post(CONTACT_URL, self._valid_payload(phone=bad), format='json')
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, bad)

    def test_missing_name_rejected(self):
        response = self.client.post(
            CONTACT_URL,
            {'phone': '09121234567'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('full_name', response.data)

    def test_nul_byte_in_message_rejected_cleanly(self):
        response = self.client.post(
            CONTACT_URL,
            self._valid_payload(message='hello\x00world'),
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_oversized_fields_rejected(self):
        response = self.client.post(
            CONTACT_URL,
            self._valid_payload(full_name='x' * 500),
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_no_authentication_required_but_throttled(self):
        from rest_framework.throttling import ScopedRateThrottle

        original_rates = ScopedRateThrottle.THROTTLE_RATES
        ScopedRateThrottle.THROTTLE_RATES = {**original_rates, 'contact': '2/min'}
        try:
            statuses = []
            for index in range(4):
                response = self.client.post(
                    CONTACT_URL,
                    self._valid_payload(phone=f'09120000{index:03d}'),
                    format='json',
                )
                statuses.append(response.status_code)
        finally:
            ScopedRateThrottle.THROTTLE_RATES = original_rates
            cache.clear()
        self.assertEqual(statuses[0], status.HTTP_201_CREATED)
        self.assertEqual(statuses[1], status.HTTP_201_CREATED)
        self.assertEqual(statuses[2], status.HTTP_429_TOO_MANY_REQUESTS)
        self.assertEqual(statuses[3], status.HTTP_429_TOO_MANY_REQUESTS)

    def test_staff_can_read_submitted_messages_via_orm_only_not_api(self):
        admin_client().post(CONTACT_URL, self._valid_payload(), format='json')
        from website.models import ContactMessage

        self.assertEqual(ContactMessage.objects.count(), 1)
        response = admin_client().get(CONTACT_URL)
        self.assertIn(response.status_code, [403, 405])
