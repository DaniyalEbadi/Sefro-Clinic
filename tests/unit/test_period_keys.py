
import jdatetime
from django.test import SimpleTestCase
from django.utils import timezone

from customers.views import _shamsi_period_key, _shamsi_period_range, _shamsi_today_range


def shamsi(y, m, d):
    return jdatetime.date(y, m, d)


class PeriodKeyTests(SimpleTestCase):
    def test_daily_key_format(self):
        self.assertEqual(_shamsi_period_key(shamsi(1404, 1, 1), 'daily'), '1404-01-01')

    def test_weekly_key_is_seven_day_blocks(self):
        self.assertEqual(_shamsi_period_key(shamsi(1404, 1, 1), 'weekly'), '1404-W01')
        self.assertEqual(_shamsi_period_key(shamsi(1404, 1, 7), 'weekly'), '1404-W01')
        self.assertEqual(_shamsi_period_key(shamsi(1404, 1, 8), 'weekly'), '1404-W02')

    def test_monthly_key_format(self):
        self.assertEqual(_shamsi_period_key(shamsi(1404, 5, 17), 'monthly'), '1404-05')

    def test_quarterly_key_boundaries(self):
        self.assertEqual(_shamsi_period_key(shamsi(1404, 1, 1), 'quarterly'), '1404-Q1')
        self.assertEqual(_shamsi_period_key(shamsi(1404, 3, 29), 'quarterly'), '1404-Q1')
        self.assertEqual(_shamsi_period_key(shamsi(1404, 4, 1), 'quarterly'), '1404-Q2')
        self.assertEqual(_shamsi_period_key(shamsi(1404, 12, 29), 'quarterly'), '1404-Q4')

    def test_yearly_key_format(self):
        self.assertEqual(_shamsi_period_key(shamsi(1404, 7, 7), 'yearly'), '1404')

    def test_unknown_period_returns_empty(self):
        self.assertEqual(_shamsi_period_key(shamsi(1404, 1, 1), 'decade'), '')


class PeriodRangeTests(SimpleTestCase):
    def test_daily_range_is_one_day_containing_now(self):
        start, end = _shamsi_period_range('daily')
        self.assertLess(start, end)
        self.assertEqual((end - start).total_seconds(), 86400)

    def test_monthly_range_spans_whole_shamsi_month(self):
        start, end = _shamsi_period_range('monthly')
        days = (end - start).days
        self.assertIn(days, [29, 30, 31])

    def test_yearly_range_spans_whole_shamsi_year(self):
        start, end = _shamsi_period_range('yearly')
        days = (end - start).days
        self.assertIn(days, [365, 366])

    def test_quarterly_range_about_three_months(self):
        start, end = _shamsi_period_range('quarterly')
        days = (end - start).days
        self.assertTrue(88 <= days <= 93)

    def test_weekly_range_is_seven_days_aligned_to_saturday(self):
        start, _ = _shamsi_period_range('weekly')
        start_shamsi = jdatetime.datetime.fromgregorian(datetime=start).date()
        self.assertEqual(start_shamsi.weekday(), 5)

    def test_unknown_period_returns_none_pair(self):
        self.assertEqual(_shamsi_period_range('decade'), (None, None))


class TodayRangeTests(SimpleTestCase):
    def test_today_range_covers_now(self):
        start, end = _shamsi_today_range()
        self.assertLessEqual(start, timezone.now())
        self.assertLess(timezone.now(), end)
