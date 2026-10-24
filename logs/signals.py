import sys
from datetime import date, datetime

from django.contrib.auth import get_user_model
from django.db import OperationalError, ProgrammingError, transaction
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken

from Sefro_Clinic.fields import greg_to_shamsi_date, greg_to_shamsi_dt

from .middleware import get_current_user
from .models import AuditLog

# Internal/token-bookkeeping models must stay out of the audit trail.
SKIP_MODELS = {AuditLog, OutstandingToken, BlacklistedToken}

# Credential material must never be copied into the audit trail.
SKIP_COLUMNS = frozenset({'password'})

UserModel = get_user_model()


def _safe_write(msg):
    try:
        sys.stderr.write(msg + '\n')
        sys.stderr.flush()
    except Exception:
        pass


def _audit_table_not_ready(error):
    """Migrations can save models before the audit table/mirror exists."""
    cause = getattr(error, '__cause__', None)
    code = getattr(cause, 'pgcode', None)
    return isinstance(error, (OperationalError, ProgrammingError)) and (
        code == '42P01' or (code == '42703' and 'timestamp_shamsi' in str(error))
    )


def _current_user():
    user = get_current_user()
    if user is None:
        return None
    if isinstance(user, UserModel):
        return user
    if getattr(user, 'is_authenticated', False) is True:
        return user
    return None


def _collect_fields(instance):
    """Field snapshot for the audit trail.

    Dates render as Shamsi strings — the same calendar the API uses — so an
    auditor reading ``changes`` never has to translate Gregorian columns.
    """
    changes = {}
    for f in instance._meta.concrete_fields:
        if f.column == instance._meta.pk.column:
            continue
        if f.column in SKIP_COLUMNS:
            continue
        if f.column.endswith('_shamsi'):
            continue  # The native date is already rendered as Shamsi below.
        val = f.value_from_object(instance)
        if val is None:
            continue
        if isinstance(val, datetime):
            changes[f.column] = greg_to_shamsi_dt(val)
        elif isinstance(val, date):
            changes[f.column] = greg_to_shamsi_date(val)
        else:
            changes[f.column] = str(val)
    return changes


@receiver(post_save)
def _log_post_save(sender, instance, created, **kwargs):
    if sender in SKIP_MODELS:
        return
    try:
        with transaction.atomic():
            action = AuditLog.Action.CREATE if created else AuditLog.Action.UPDATE
            AuditLog.objects.create(
                user=_current_user(),
                action=action,
                model_name=f'{sender._meta.app_label}.{sender._meta.model_name}',
                object_id=instance.pk,
                object_repr=str(instance)[:255],
                changes=_collect_fields(instance),
            )
    except Exception as e:
        if _audit_table_not_ready(e):
            return
        _safe_write(f'[audit_log] post_save error: {e}')


@receiver(post_delete)
def _log_post_delete(sender, instance, **kwargs):
    if sender in SKIP_MODELS:
        return
    try:
        with transaction.atomic():
            AuditLog.objects.create(
                user=_current_user(),
                action=AuditLog.Action.DELETE,
                model_name=f'{sender._meta.app_label}.{sender._meta.model_name}',
                object_id=instance.pk,
                object_repr=str(instance)[:255],
                changes=_collect_fields(instance),
            )
    except Exception as e:
        if _audit_table_not_ready(e):
            return
        _safe_write(f'[audit_log] post_delete error: {e}')
