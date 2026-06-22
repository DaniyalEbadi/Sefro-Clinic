import sys
from django.db import transaction
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from .middleware import get_current_user
from .models import AuditLog

SKIP_MODELS = {AuditLog}


def _safe_write(msg):
    try:
        sys.stderr.write(msg + '\n')
        sys.stderr.flush()
    except Exception:
        pass


def _collect_fields(instance):
    changes = {}
    for f in instance._meta.concrete_fields:
        if f.column == instance._meta.pk.column:
            continue
        val = f.value_from_object(instance)
        if val is not None:
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
                user=get_current_user(),
                action=action,
                model_name=f'{sender._meta.app_label}.{sender._meta.model_name}',
                object_id=instance.pk,
                object_repr=str(instance)[:255],
                changes=_collect_fields(instance),
            )
    except Exception as e:
        _safe_write(f'[audit_log] post_save error: {e}')


@receiver(post_delete)
def _log_post_delete(sender, instance, **kwargs):
    if sender in SKIP_MODELS:
        return
    try:
        with transaction.atomic():
            AuditLog.objects.create(
                user=get_current_user(),
                action=AuditLog.Action.DELETE,
                model_name=f'{sender._meta.app_label}.{sender._meta.model_name}',
                object_id=instance.pk,
                object_repr=str(instance)[:255],
                changes=_collect_fields(instance),
            )
    except Exception as e:
        _safe_write(f'[audit_log] post_delete error: {e}')
