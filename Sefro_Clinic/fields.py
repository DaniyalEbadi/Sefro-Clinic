from datetime import date, datetime

import jdatetime
from django.utils import timezone
from rest_framework import serializers

from Sefro_Clinic.periods import SHAMSI_YEAR_MAX, SHAMSI_YEAR_MIN  # noqa: F401  (re-exported)

SHAMSI_DATETIME_FORMAT = '%Y-%m-%d %H:%M'
SHAMSI_DATE_FORMAT = '%Y-%m-%d'


def greg_to_shamsi_dt(value):
    if not value:
        return None
    if isinstance(value, str):
        return value
    if timezone.is_aware(value):
        value = timezone.localtime(value)
    return jdatetime.datetime.fromgregorian(datetime=value).strftime(SHAMSI_DATETIME_FORMAT)


def greg_to_shamsi_date(value):
    if not value:
        return None
    if isinstance(value, str):
        return value
    return jdatetime.date.fromgregorian(date=value).strftime(SHAMSI_DATE_FORMAT)


def shamsi_to_greg_dt(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    for fmt in (SHAMSI_DATETIME_FORMAT, '%Y-%m-%d %H:%M:%S', '%Y-%m-%d'):
        try:
            dt = jdatetime.datetime.strptime(str(value), fmt)
            return dt.togregorian()
        except ValueError:
            continue
    raise serializers.ValidationError(f'Invalid Shamsi datetime format. Use {SHAMSI_DATETIME_FORMAT}')


def shamsi_to_greg_date(value):
    if not value:
        return None
    if isinstance(value, date):
        # Programmatic callers may already hold a Gregorian date (e.g. the
        # service layer); only strings are interpreted as Shamsi.
        return value
    try:
        d = jdatetime.datetime.strptime(str(value), SHAMSI_DATE_FORMAT).date()
    except ValueError:
        raise serializers.ValidationError(f'Invalid Shamsi date format. Use {SHAMSI_DATE_FORMAT}')
    if not SHAMSI_YEAR_MIN <= d.year <= SHAMSI_YEAR_MAX:
        # Structurally valid, semantically impossible: reject instead of
        # silently reinterpreting a Gregorian date as a Jalali one.
        raise serializers.ValidationError(
            f'Invalid Shamsi (Jalali) date: "{value}". '
            f'Shamsi year must be between {SHAMSI_YEAR_MIN} and {SHAMSI_YEAR_MAX}; '
            f'{d.year} looks like a Gregorian year. Send a Jalali date '
            f'(e.g. 1405-07-08).'
        )
    return d.togregorian()


class ShamsiDateTimeField(serializers.DateTimeField):
    def to_representation(self, value):
        return greg_to_shamsi_dt(value)

    def to_internal_value(self, value):
        dt = shamsi_to_greg_dt(value)
        if dt and timezone.is_naive(dt):
            return timezone.make_aware(dt)
        return dt


class ShamsiDateField(serializers.DateField):
    def to_representation(self, value):
        return greg_to_shamsi_date(value)

    def to_internal_value(self, value):
        return shamsi_to_greg_date(value)
