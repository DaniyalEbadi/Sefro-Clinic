"""Edge-case tests for the Shamsi calendar standardisation.

Covers leap-Esfand handling, month/year boundaries, Saturday-start weeks,
year-window bounds (1300 / 1499), and the monthly-close / reopen edges that
the finance API exposes.
"""
from datetime import timedelta

import jdatetime
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from Sefro_Clinic.fields import (
    greg_to_shamsi_date,
    greg_to_shamsi_dt,
    shamsi_to_greg_date,
    shamsi_to_greg_dt,
)
from Sefro_Clinic.periods import (
    parse_shamsi_date,
    shamsi_month_bounds,
    shamsi_month_key,
    shamsi_period_key,
)


def sj(y, m, d):
    """Convenience: jdatetime.date."""
    return jdatetime.date(y, m, d)


class LeapEsfandTests(SimpleTestCase):
    """Esfand 30 exists only in leap years (years where the next Farvardin
    starts one Gregorian day later than usual)."""

    def test_leap_esfand_30_valid(self):
        # 1403 is a leap year; Esfand 30 exists.
        d = sj(1403, 12, 30)
        self.assertEqual(d.month, 12)
        self.assertEqual(d.day, 30)

    def test_non_leap_esfand_30_raises(self):
        # 1404 is not a leap year; Esfand 30 does not exist.
        with self.assertRaises(ValueError):
            sj(1404, 12, 30)

    def test_esfand_29_is_last_day_of_non_leap_year(self):
        d = sj(1404, 12, 29)
        self.assertEqual(d + timedelta(days=1), sj(1405, 1, 1))

    def test_month_bounds_leap_esfand(self):
        start, end = shamsi_month_bounds(1403, 12)
        # 1403 Esfand has 30 days → inclusive range covers 30 × 86 400 s.
        self.assertEqual((end.date() - start.date()).days + 1, 30)

    def test_month_bounds_non_leap_esfand(self):
        start, end = shamsi_month_bounds(1404, 12)
        self.assertEqual((end.date() - start.date()).days + 1, 29)


class MonthYearBoundaryTests(SimpleTestCase):
    def test_esfand_to_farvardin_transition(self):
        # 1404-12-29 + 1 day = 1405-01-01
        self.assertEqual(sj(1404, 12, 29) + timedelta(days=1), sj(1405, 1, 1))

    def test_farvardin_1_is_day_one(self):
        d = sj(1405, 1, 1)
        self.assertEqual(d.day, 1)
        self.assertEqual(d.month, 1)

    def test_month_key_farvardin(self):
        self.assertEqual(shamsi_month_key(sj(1405, 1, 1)), '1405-01')

    def test_month_key_esfand(self):
        self.assertEqual(shamsi_month_key(sj(1405, 12, 29)), '1405-12')


class SaturdayWeekTests(SimpleTestCase):
    """Weeks start Saturday (Shanbeh).  jdatetime.isoweekday(): Shanbeh=1 … Jomeh=7."""

    def test_saturday_is_week_start(self):
        # 1404-01-01 was a Friday, so 1404-01-02 is the first Saturday.
        d = sj(1404, 1, 2)
        self.assertEqual(d.isoweekday(), 1)

    def test_friday_is_week_end(self):
        # 1404-01-08 is the Friday that ends the first full week.
        d = sj(1404, 1, 8)
        self.assertEqual(d.isoweekday(), 7)

    def test_same_week_same_key(self):
        # Saturday 1404-01-02 through Friday 1404-01-08 share one key.
        keys = {shamsi_period_key(sj(1404, 1, day), 'weekly') for day in range(2, 9)}
        self.assertEqual(len(keys), 1)

    def test_w01_contains_1_farvardin(self):
        # 1404-01-01 was a Friday; W01 runs 1403-12-26 (Sat) .. 1404-01-01 (Fri).
        self.assertEqual(shamsi_period_key(sj(1404, 1, 1), 'weekly'), '1404-W01')

    def test_w02_starts_next_saturday(self):
        self.assertEqual(shamsi_period_key(sj(1404, 1, 2), 'weekly'), '1404-W02')


class YearWindowBoundTests(SimpleTestCase):
    """SHAMSI_YEAR_MIN=1300, SHAMSI_YEAR_MAX=1499 — Gregorian-looking years are rejected."""

    def test_year_min_accepted(self):
        g = shamsi_to_greg_date('1300-01-01')
        self.assertIsNotNone(g)

    def test_year_max_accepted(self):
        g = shamsi_to_greg_date('1499-12-29')
        self.assertIsNotNone(g)

    def test_year_below_min_rejected(self):
        from rest_framework.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            shamsi_to_greg_date('1299-12-29')

    def test_year_above_max_rejected(self):
        from rest_framework.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            shamsi_to_greg_date('1500-01-01')

    def test_gregorian_looking_string_rejected(self):
        from rest_framework.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            shamsi_to_greg_date('2026-10-15')


class FieldRoundTripTests(SimpleTestCase):
    def test_date_round_trip(self):
        original = sj(1405, 7, 23)
        g = shamsi_to_greg_date(original.strftime('%Y-%m-%d'))
        back = greg_to_shamsi_date(g)
        self.assertEqual(back, '1405-07-23')

    def test_datetime_round_trip(self):
        g = timezone.make_aware(
            __import__('datetime').datetime(2026, 10, 15, 14, 30)
        )
        s = greg_to_shamsi_dt(g)
        # s is 'YYYY-MM-DD HH:MM' Shamsi; parse it back.
        back = shamsi_to_greg_dt(s)
        self.assertEqual(back.year, g.year)
        self.assertEqual(back.month, g.month)
        self.assertEqual(back.day, g.day)

    def test_parse_shamsi_date_valid(self):
        self.assertEqual(parse_shamsi_date('1405-07-23'), sj(1405, 7, 23))

    def test_parse_shamsi_date_invalid_returns_none(self):
        self.assertIsNone(parse_shamsi_date('not-a-date'))

    def test_parse_shamsi_date_empty_returns_none(self):
        self.assertIsNone(parse_shamsi_date(''))


class MonthlyCloseEdgeTests(TestCase):
    """Close / reopen API edges: past-month-only, idempotent re-close,
    reopen requires reason, re-close after reopen refreshes."""

    @classmethod
    def setUpTestData(cls):
        from tests.helpers import make_admin
        cls.admin = make_admin()

    def _client(self):
        from rest_framework.test import APIClient
        c = APIClient()
        c.force_authenticate(self.admin)
        return c

    def _close(self, year, month, **extra):
        return self._client().post(
            '/api/finance/reports/monthly-close/close/',
            {'year': year, 'month': month, **extra},
            format='json',
        )

    def _reopen(self, year, month, reason):
        return self._client().post(
            '/api/finance/reports/monthly-close/reopen/',
            {'year': year, 'month': month, 'reason': reason},
            format='json',
        )

    def test_past_month_close_succeeds(self):
        resp = self._close(1404, 1)
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data['status'], 'closed')
        self.assertFalse(resp.data['already_closed'])

    def test_idempotent_reclose(self):
        self._close(1404, 1)
        resp = self._close(1404, 1)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.data['already_closed'])

    def test_current_month_rejected(self):
        now = timezone.localtime(timezone.now())
        import jdatetime as jd
        s = jd.datetime.fromgregorian(datetime=now)
        resp = self._close(s.year, s.month)
        self.assertEqual(resp.status_code, 400)
        self.assertIn('past', resp.data['error'].lower())

    def test_future_month_rejected(self):
        # 1405 Farvardin is in the past relative to today (1405-07).
        resp = self._close(1406, 1)
        self.assertEqual(resp.status_code, 400)

    def test_month_out_of_range_rejected(self):
        resp = self._close(1404, 13)
        self.assertEqual(resp.status_code, 400)

    def test_reopen_requires_reason(self):
        self._close(1404, 1)
        resp = self._reopen(1404, 1, '')
        self.assertEqual(resp.status_code, 400)

    def test_reopen_closed_month(self):
        self._close(1404, 1)
        resp = self._reopen(1404, 1, 'correction needed')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['status'], 'reopened')

    def test_reclose_after_reopen(self):
        self._close(1404, 1)
        self._reopen(1404, 1, 'fix')
        resp = self._close(1404, 1, note='re-closed')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['status'], 'closed')

    def test_reopen_never_closed_month_rejected(self):
        resp = self._reopen(1403, 6, 'why?')
        self.assertEqual(resp.status_code, 400)
