"""Shamsi (Jalali) calendar period helpers.

One implementation of "which Gregorian instants does this Shamsi period
cover", used by the customers report views *and* by the finance monthly
close report, so the two can never bucket the same day differently.

Two conventions, both provided on purpose:

``shamsi_month_bounds`` / ``shamsi_period_bounds``
    Inclusive range: ``start`` = first day 00:00, ``end`` = last day
    23:59:59.999999. This is what ``finance.services.financials.build_report``
    needs, because it filters both ``field__lte=end`` datetimes *and*
    ``date__lte=end.date()`` date columns.

``shamsi_period_range``
    Half-open range: ``end`` = first instant of the following period. Legacy
    shape used by the customers report views (``created_at__lt=end``).
"""
from datetime import datetime, time, timedelta

import jdatetime
from django.utils import timezone

#: Shamsi month names, January..Esfand order (1-based index = month).
SHAMSI_MONTH_NAMES = [
    '', 'Farvardin', 'Ordibehesht', 'Khordad', 'Tir', 'Mordad', 'Shahrivar',
    'Mehr', 'Aban', 'Azar', 'Dey', 'Bahman', 'Esfand',
]

PERIODS = ('daily', 'weekly', 'monthly', 'quarterly', 'yearly')

#: Accepted Shamsi year window for inbound date strings. A Gregorian string
#: such as "2026-09-28" parses *structurally* as the Jalali date 2026-09-28,
#: so anything outside this window is rejected instead of silently shifted.
SHAMSI_YEAR_MIN = 1300
SHAMSI_YEAR_MAX = 1499


def _to_shamsi(moment):
    """Timezone-aware datetime (or naive) -> jdatetime.datetime in Tehran."""
    return jdatetime.datetime.fromgregorian(datetime=timezone.localtime(moment))


def shamsi_of(moment):
    """A ``datetime`` or ``date`` -> ``(shamsi_year, shamsi_month)``."""
    if isinstance(moment, datetime):
        if timezone.is_aware(moment):
            moment = timezone.localtime(moment)
        moment = moment.date()
    jalali = jdatetime.date.fromgregorian(date=moment)
    return jalali.year, jalali.month


def shamsi_month_name(month):
    return SHAMSI_MONTH_NAMES[month] if 1 <= month <= 12 else ''


def _shamsi_month_bounds(year, month):
    """First day and first day of the next month, as ``jdatetime.date``."""
    first = jdatetime.date(year, month, 1)
    if month == 12:
        next_first = jdatetime.date(year + 1, 1, 1)
    else:
        next_first = jdatetime.date(year, month + 1, 1)
    return first, next_first


def shamsi_month_gregorian_bounds(year, month):
    """First-day and day-after-last-day Gregorian dates of a Shamsi month.

    Returns ``(first_day, next_first_day)`` as ``datetime.date``.
    """
    first, next_first = _shamsi_month_bounds(year, month)
    return first.togregorian(), next_first.togregorian()


def shamsi_month_bounds(year, month):
    """Inclusive ``(start, end)`` aware datetimes covering one Shamsi month."""
    first, next_first = shamsi_month_gregorian_bounds(year, month)
    start = timezone.make_aware(datetime.combine(first, time.min))
    end = timezone.make_aware(datetime.combine(next_first - timedelta(days=1), time.max))
    return start, end


def shamsi_months_of_year(year):
    """All 12 months of a Shamsi year as dicts, oldest first."""
    months = []
    for month in range(1, 13):
        start, end = shamsi_month_bounds(year, month)
        months.append({
            'key': f'{year}-{month:02d}',
            'year': year,
            'month': month,
            'month_name': shamsi_month_name(month),
            'start': start,
            'end': end,
        })
    return months


def shamsi_month_key(date):
    """``jdatetime.date`` -> ``'1405-05'``."""
    return f'{date.year}-{date.month:02d}'


def parse_shamsi_date(value):
    """``'YYYY-MM-DD'`` as a **Shamsi** date -> ``jdatetime.date`` or ``None``.

    Returns ``None`` for anything unparseable; callers decide whether that is
    a hard error or a tolerated fallback.
    """
    try:
        return jdatetime.datetime.strptime(str(value), '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return None


def shamsi_day_bounds(day):
    """One Shamsi day as inclusive aware ``(start, end)`` datetimes."""
    greg = day.togregorian()
    start = timezone.make_aware(datetime.combine(greg, time.min))
    end = timezone.make_aware(datetime.combine(greg, time.max))
    return start, end


def shamsi_prev_month(year, month):
    """The Shamsi month before ``(year, month)``."""
    return (year - 1, 12) if month == 1 else (year, month - 1)


def shamsi_period_gregorian_bounds(period, now=None):
    """First-day and day-after-last-day Gregorian dates of the *current* period."""
    moment = now or timezone.now()
    shamsi_now = _to_shamsi(moment)
    syear, smonth, sday = shamsi_now.year, shamsi_now.month, shamsi_now.day

    if period == 'daily':
        start = jdatetime.date(syear, smonth, sday)
        end = start + timedelta(days=1)
    elif period == 'weekly':
        # Saturday-start weeks. NOTE: jdatetime numbers isoweekday with
        # Shanbeh (Saturday) = 1 .. Jomeh (Friday) = 7, so days since
        # Saturday is simply isoweekday() - 1.
        days_since_saturday = shamsi_now.date().isoweekday() - 1
        start = shamsi_now.date() - timedelta(days=days_since_saturday)
        end = start + timedelta(days=7)
    elif period == 'monthly':
        start, end = _shamsi_month_bounds(syear, smonth)
    elif period == 'quarterly':
        sq = (smonth - 1) // 3
        start = jdatetime.date(syear, sq * 3 + 1, 1)
        if sq == 3:
            end = jdatetime.date(syear + 1, 1, 1)
        else:
            end = jdatetime.date(syear, (sq + 1) * 3 + 1, 1)
    elif period == 'yearly':
        start = jdatetime.date(syear, 1, 1)
        end = jdatetime.date(syear + 1, 1, 1)
    else:
        return None, None
    return start.togregorian(), end.togregorian()


def shamsi_period_range(period, now=None):
    """Half-open ``(start, end)`` aware datetimes for the current period.

    ``end`` is the first instant of the *next* period, for ``__lt`` filters.
    """
    start, end = shamsi_period_gregorian_bounds(period, now)
    if start is None:
        return None, None
    return (
        timezone.make_aware(datetime.combine(start, time.min)),
        timezone.make_aware(datetime.combine(end, time.min)),
    )


def shamsi_period_bounds(period, now=None):
    """Inclusive ``(start, end)`` aware datetimes for the current period."""
    start, end = shamsi_period_gregorian_bounds(period, now)
    if start is None:
        return None, None
    return (
        timezone.make_aware(datetime.combine(start, time.min)),
        timezone.make_aware(datetime.combine(end - timedelta(days=1), time.max)),
    )


def shamsi_period_key(date, period):
    """Bucket a Shamsi date into its period key (``'1405-05'``, ``'1405-W01'``)."""
    if period == 'daily':
        return date.strftime('%Y-%m-%d')
    if period == 'weekly':
        # Saturday-start weeks, the same weeks shamsi_period_bounds slices:
        # every day of one week must share one key. W01 is the week that
        # contains 1 Farvardin (it may start in the previous Shamsi year).
        # jdatetime numbers isoweekday with Saturday = 1, so days since
        # Saturday is isoweekday() - 1.
        year_start = date.replace(day=1, month=1)
        first_week_start = year_start - timedelta(days=year_start.isoweekday() - 1)
        week_start = date - timedelta(days=date.isoweekday() - 1)
        wn = ((week_start - first_week_start).days) // 7 + 1
        return f'{date.year}-W{wn:02d}'
    if period == 'monthly':
        return shamsi_month_key(date)
    if period == 'quarterly':
        q = (date.month - 1) // 3 + 1
        return f'{date.year}-Q{q}'
    if period == 'yearly':
        return str(date.year)
    return ''
