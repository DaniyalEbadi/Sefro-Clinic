from datetime import datetime

import jdatetime
from django.test import SimpleTestCase
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from Sefro_Clinic.fields import (
    ShamsiDateField,
    ShamsiDateTimeField,
    greg_to_shamsi_date,
    greg_to_shamsi_dt,
    shamsi_to_greg_date,
    shamsi_to_greg_dt,
)

KNOWN_PAIRS = [
    (datetime(2025, 3, 21), (1404, 1, 1)),
    (datetime(2025, 12, 31), (1404, 10, 10)),
    (datetime(2024, 3, 20), (1403, 1, 1)),
    (datetime(2026, 3, 21), (1405, 1, 1)),
]


class GregToShamsiTests(SimpleTestCase):
    def test_none_returns_none(self):
        self.assertIsNone(greg_to_shamsi_dt(None))
        self.assertIsNone(greg_to_shamsi_date(None))

    def test_empty_returns_none(self):
        self.assertIsNone(greg_to_shamsi_dt(''))
        self.assertIsNone(greg_to_shamsi_date(''))

    def test_string_passthrough(self):
        self.assertEqual(greg_to_shamsi_dt('already-a-string'), 'already-a-string')
        self.assertEqual(greg_to_shamsi_date('1404-01-01'), '1404-01-01')

    def test_known_conversions_dt(self):
        aware = timezone.make_aware(datetime(2025, 3, 21, 12, 30))
        self.assertEqual(greg_to_shamsi_dt(aware), '1404-01-01 12:30')

    def test_known_conversions_date(self):
        for gregorian, (sy, sm, sd) in KNOWN_PAIRS:
            self.assertEqual(
                greg_to_shamsi_date(gregorian.date()),
                f'{sy}-{sm:02d}-{sd:02d}',
            )

    def test_naive_dt_converted_without_error(self):
        naive = datetime(2025, 3, 21, 8, 0)
        result = greg_to_shamsi_dt(naive)
        self.assertTrue(result.startswith('1404-01-01'))


class ShamsiToGregTests(SimpleTestCase):
    def test_none_returns_none(self):
        self.assertIsNone(shamsi_to_greg_dt(None))
        self.assertIsNone(shamsi_to_greg_date(None))

    def test_valid_date_roundtrip(self):
        gregorian = shamsi_to_greg_date('1404-01-01')
        self.assertEqual(jdatetime.date.fromgregorian(date=gregorian).strftime('%Y-%m-%d'), '1404-01-01')

    def test_invalid_date_raises_validation_error(self):
        for bad in ['2025-01-01x', 'not-a-date', '1404-13-01', '1404-00-10']:
            with self.assertRaises(ValidationError):
                shamsi_to_greg_date(bad)

    def test_invalid_datetime_raises_validation_error(self):
        for bad in ['1404-01-01 99:99', 'garbage', '1404-01-01T10:00']:
            with self.assertRaises(ValidationError):
                shamsi_to_greg_dt(bad)

    def test_leap_year_esfand_30_valid(self):
        gregorian = shamsi_to_greg_date('1403-12-30')
        self.assertIsNotNone(gregorian)


class ShamsiSerializerFieldTests(SimpleTestCase):
    def test_datetime_field_roundtrip(self):
        field = ShamsiDateTimeField()
        aware = timezone.make_aware(datetime(2025, 3, 21, 15, 45))
        represented = field.to_representation(aware)
        self.assertEqual(represented, '1404-01-01 15:45')
        parsed = field.to_internal_value(represented)
        self.assertTrue(timezone.is_aware(parsed))
        self.assertEqual(field.to_representation(parsed), represented)

    def test_date_field_roundtrip(self):
        field = ShamsiDateField()
        represented = field.to_representation(datetime(2025, 3, 21).date())
        self.assertEqual(represented, '1404-01-01')
        parsed = field.to_internal_value(represented)
        self.assertEqual(field.to_representation(parsed), represented)

    def test_datetime_field_rejects_garbage(self):
        with self.assertRaises(ValidationError):
            ShamsiDateTimeField().to_internal_value('whenever')
