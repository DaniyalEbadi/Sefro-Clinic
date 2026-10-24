"""Stored Jalali mirrors for native date columns.

The native fields remain authoritative for indexing, timezone arithmetic and
finance calculations. Mirrors are read-only text representations in Tehran
local time; they are never accepted as user input.
"""

from datetime import datetime
from functools import wraps

import jdatetime
from django.db import models
from django.utils import timezone


def shamsi_storage_value(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        if timezone.is_aware(value):
            value = timezone.localtime(value, timezone.get_default_timezone())
        return jdatetime.datetime.fromgregorian(datetime=value).strftime('%Y-%m-%d %H:%M:%S.%f')
    return jdatetime.date.fromgregorian(date=value).strftime('%Y-%m-%d')


class ShamsiMirrorField(models.CharField):
    """Set from a native date field during ordinary and bulk inserts."""

    def __init__(self, source_field, **kwargs):
        self.source_field = source_field
        kwargs.setdefault('max_length', 26)
        kwargs.setdefault('null', True)
        kwargs.setdefault('blank', True)
        kwargs.setdefault('editable', False)
        super().__init__(**kwargs)

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()
        kwargs['source_field'] = self.source_field
        return name, path, args, kwargs

    def pre_save(self, model_instance, add):
        value = shamsi_storage_value(getattr(model_instance, self.source_field))
        setattr(model_instance, self.attname, value)
        return value


def install_shamsi_mirrors(namespace):
    """Attach a paired column to every native date field in an app's models."""
    module_name = namespace['__name__']
    for model in tuple(namespace.values()):
        if not isinstance(model, type) or not issubclass(model, models.Model):
            continue
        if model.__module__ != module_name or model._meta.abstract:
            continue
        native_fields = tuple(
            field for field in model._meta.local_concrete_fields
            if isinstance(field, models.DateField)
        )
        if not native_fields:
            continue
        for field in native_fields:
            model.add_to_class(f'{field.name}_shamsi', ShamsiMirrorField(field.name))

        original_save = model.save
        native_names = frozenset(field.name for field in native_fields)

        @wraps(original_save)
        def save_with_shamsi(self, *args, __save=original_save, __names=native_names, **kwargs):
            update_fields = kwargs.get('update_fields')
            if update_fields is not None:
                updates = set(update_fields)
                updates.update(f'{name}_shamsi' for name in __names & updates)
                kwargs['update_fields'] = updates
            return __save(self, *args, **kwargs)

        model.save = save_with_shamsi
