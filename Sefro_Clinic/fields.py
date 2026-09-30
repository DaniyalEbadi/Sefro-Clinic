import jdatetime
from django.utils import timezone
from rest_framework import serializers

SHAMSI_DATETIME_FORMAT = '%Y-%m-%d %H:%M'
SHAMSI_DATE_FORMAT = '%Y-%m-%d'

# Accepted Jalali (Shamsi) year window for date-only inputs.
#
# The API contract says inbound date strings are Shamsi, but a Gregorian
# string such as "2026-09-28" parses *structurally* as the Jalali date
# 2026-09-28 and silently converts to Gregorian 2647-12-19 — the exact
# corruption behind the legacy year-2647 visits. A real clinic date can never
# fall outside this window:
#   1300 -> Gregorian 1921 (adoption of the Iranian calendar), inclusive so
#           existing far-past report filters keep working;
#   1499 -> Gregorian 2120.
SHAMSI_YEAR_MIN = 1300
SHAMSI_YEAR_MAX = 1499


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
    try:
        dt = jdatetime.datetime.strptime(str(value), SHAMSI_DATETIME_FORMAT)
        return dt.togregorian()
    except ValueError:
        raise serializers.ValidationError(f'Invalid Shamsi datetime format. Use {SHAMSI_DATETIME_FORMAT}')


def shamsi_to_greg_date(value):
    if not value:
        return None
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
