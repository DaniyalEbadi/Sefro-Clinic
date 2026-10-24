"""Populate stored Shamsi mirrors for rows that predate the new columns."""

from django.db import migrations, models

from Sefro_Clinic.shamsi_storage import shamsi_storage_value

APP_LABELS = ('accounts', 'customers', 'face_analyzer', 'finance', 'logs', 'website')


def backfill_shamsi_dates(apps, schema_editor):
    alias = schema_editor.connection.alias
    for app_label in APP_LABELS:
        for model in apps.get_app_config(app_label).get_models():
            native_names = [
                field.name for field in model._meta.local_concrete_fields
                if isinstance(field, models.DateField)
                and f'{field.name}_shamsi' in {f.name for f in model._meta.local_concrete_fields}
            ]
            if not native_names:
                continue
            mirror_names = [f'{name}_shamsi' for name in native_names]
            batch = []
            queryset = model.objects.using(alias).only('pk', *native_names)
            for instance in queryset.iterator(chunk_size=500):
                for name in native_names:
                    setattr(instance, f'{name}_shamsi', shamsi_storage_value(getattr(instance, name)))
                batch.append(instance)
                if len(batch) == 500:
                    model.objects.using(alias).bulk_update(batch, mirror_names, batch_size=500)
                    batch.clear()
            if batch:
                model.objects.using(alias).bulk_update(batch, mirror_names, batch_size=500)


class Migration(migrations.Migration):
    atomic = False  # Batch updates should not hold locks on every table at once.

    dependencies = [
        ('accounts', '0005_clinicuser_date_joined_shamsi_and_more'),
        ('customers', '0019_customer_birthday_shamsi_customer_created_at_shamsi_and_more'),
        ('face_analyzer', '0004_faceanalysis_created_at_shamsi_and_more'),
        ('finance', '0023_exchangerate_created_at_shamsi_and_more'),
        ('logs', '0003_auditlog_timestamp_shamsi'),
        ('website', '0008_contactmessage_created_at_shamsi_and_more'),
    ]

    operations = [migrations.RunPython(backfill_shamsi_dates, migrations.RunPython.noop)]
