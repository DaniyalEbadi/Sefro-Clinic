"""Date-contract regression tests for POST /api/visits/reserve/.

The endpoint's ``date`` field is Shamsi (Jalali) by contract, but it used to
feed the raw string straight into ``jdatetime.strptime`` with no range check,
so a Gregorian value such as ``"2026-09-28"`` was silently reinterpreted as
the Jalali date 2026-09-28 and stored as ``start_at = 2647-12-19`` — the
corrupted production rows.

The contract is now explicit: a Jalali date inside the supported window is
converted to the correct Gregorian instant, and every other value returns
HTTP 400 with an understandable message while leaving no Visit behind.
"""
from datetime import datetime, time, timedelta
from decimal import Decimal

import jdatetime
from django.test import TestCase
from django.utils import timezone

from customers.models import Service, Visit
from tests.helpers import admin_client, make_customer

GREGORIAN_LOOKING_DATES = ['2026-09-28', '2025-06-01', '1990-05-15', '1500-01-01', '1299-01-01']
MALFORMED_DATES = ['1405-13-01', '1405-99-99', '2026-02-30', '1405/07/08', 'abc', '2026']


class ReserveDateContractTests(TestCase):
    def setUp(self):
        self.client = admin_client()
        self.customer = make_customer(mobile_number='09123334455', national_id='333-0000333')
        self.service = Service.objects.create(
            name='Laser Reserve Contract',
            price=Decimal('500000.00'),
            time=45,
        )

    def _reserve(self, **overrides):
        payload = {
            'customer': self.customer.id,
            'services': [self.service.id],
            'date': '1405-07-08',
            'time': '10:30',
        }
        payload.update(overrides)
        return self.client.post('/api/visits/reserve/', payload, format='json')

    # --- accepted input ---------------------------------------------------

    def test_shamsi_date_converts_to_the_expected_gregorian_instant(self):
        resp = self._reserve()
        self.assertEqual(resp.status_code, 201)

        visit = Visit.objects.get(id=resp.data['id'])
        expected_start = timezone.make_aware(
            datetime.combine(jdatetime.date(1405, 7, 8).togregorian(), time(10, 30))
        )
        self.assertEqual(visit.start_at, expected_start)
        self.assertEqual(visit.end_at, expected_start + timedelta(minutes=45))
        self.assertEqual(visit.status, Visit.Status.PENDING)
        self.assertEqual(list(visit.services.all()), [self.service])
        self.assertLess(visit.start_at.year, 2100)

    def test_reserved_visit_serialises_back_as_a_shamsi_datetime(self):
        resp = self._reserve()
        self.assertEqual(resp.status_code, 201)
        self.assertTrue(resp.data['start_at'].startswith('1405-07-08 10:30'), resp.data['start_at'])

    # --- rejected input ---------------------------------------------------

    def test_gregorian_date_is_rejected_with_an_understandable_message(self):
        resp = self._reserve(date='2026-09-28')
        self.assertEqual(resp.status_code, 400)
        error = str(resp.data.get('error', ''))
        self.assertIn('2026-09-28', error)
        self.assertIn('Shamsi', error)
        self.assertIn('Gregorian', error)

    def test_rejected_date_creates_no_visit(self):
        before = Visit.objects.count()
        resp = self._reserve(date='2026-09-28')
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(Visit.objects.count(), before, 'a rejected reservation must not persist a Visit')
        # The exact corrupted values from production must be unreachable.
        self.assertFalse(Visit.objects.filter(start_at__year__gte=2100).exists())
        self.assertFalse(Visit.objects.filter(start_at__year=2647).exists())

    def test_gregorian_looking_dates_are_all_rejected(self):
        for bad in GREGORIAN_LOOKING_DATES:
            with self.subTest(date=bad):
                resp = self._reserve(date=bad)
                self.assertEqual(resp.status_code, 400, f'{bad} must not be accepted as a Shamsi date')
                self.assertEqual(Visit.objects.count(), 0)

    def test_structurally_invalid_dates_are_all_rejected(self):
        for bad in MALFORMED_DATES:
            with self.subTest(date=bad):
                resp = self._reserve(date=bad)
                self.assertEqual(resp.status_code, 400)
                self.assertEqual(Visit.objects.count(), 0)

    def test_missing_date_is_rejected(self):
        resp = self.client.post('/api/visits/reserve/', {
            'customer': self.customer.id,
            'services': [self.service.id],
            'time': '10:30',
        }, format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('date', str(resp.data.get('error', '')).lower())
        self.assertEqual(Visit.objects.count(), 0)

    def test_a_valid_reservation_still_succeeds_after_rejected_attempts(self):
        for bad in ['2026-09-28', '1405-13-01', '']:
            self.assertEqual(self._reserve(date=bad).status_code, 400)
        resp = self._reserve()
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(Visit.objects.count(), 1)
        self.assertLess(Visit.objects.get().start_at.year, 2100)
