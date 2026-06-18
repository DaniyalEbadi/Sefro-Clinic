import jdatetime
from rest_framework import serializers
from django.utils import timezone


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
    try:
        dt = jdatetime.datetime.strptime(str(value), SHAMSI_DATETIME_FORMAT)
        return dt.togregorian()
    except (ValueError, jdatetime.InvalidDate):
        raise serializers.ValidationError(f'Invalid Shamsi datetime format. Use {SHAMSI_DATETIME_FORMAT}')


def shamsi_to_greg_date(value):
    if not value:
        return None
    try:
        d = jdatetime.datetime.strptime(str(value), SHAMSI_DATE_FORMAT).date()
        return d.togregorian()
    except ValueError:
        raise serializers.ValidationError(f'Invalid Shamsi date format. Use {SHAMSI_DATE_FORMAT}')


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
