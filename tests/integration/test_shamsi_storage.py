from datetime import date, datetime
from importlib import import_module
from types import SimpleNamespace

from django.apps import apps
from django.db import connection, models
from django.test import TestCase
from django.utils import timezone

from customers.models import Customer
from Sefro_Clinic.shamsi_storage import shamsi_storage_value
from website.models import SiteSettings, WebsitePriceSyncRun
from website.serializers import SiteSettingsSerializer, WebsitePriceSyncRunSerializer


class ShamsiStorageTests(TestCase):
    def test_all_business_date_columns_have_shamsi_mirrors(self):
        for model in apps.get_models():
            if model._meta.app_label not in (
                'accounts', 'customers', 'face_analyzer', 'finance', 'logs', 'website',
            ):
                continue
            field_names = {field.name for field in model._meta.local_concrete_fields}
            for field in model._meta.local_concrete_fields:
                if isinstance(field, models.DateField) and not field.name.endswith('_shamsi'):
                    self.assertIn(f'{field.name}_shamsi', field_names, model._meta.label)

    def test_native_and_shamsi_columns_are_saved_together(self):
        settings = SiteSettings.objects.create()
        settings.refresh_from_db()
        self.assertIsInstance(settings.updated_at, datetime)
        self.assertEqual(settings.updated_at_shamsi, shamsi_storage_value(settings.updated_at))
        self.assertEqual(
            SiteSettingsSerializer(settings).data['updated_at'],
            settings.updated_at_shamsi[:16],
        )

        run = WebsitePriceSyncRun.objects.create()
        run.finished_at = timezone.make_aware(datetime(2025, 3, 21, 12, 30))
        run.save(update_fields=['finished_at'])
        run.refresh_from_db()
        self.assertEqual(run.finished_at_shamsi, shamsi_storage_value(run.finished_at))
        self.assertIsNone(WebsitePriceSyncRunSerializer(WebsitePriceSyncRun()).data['finished_at'])
        self.assertEqual(
            WebsitePriceSyncRunSerializer(run).data['finished_at'], '1404-01-01 12:30',
        )

    def test_backfill_repairs_preexisting_rows(self):
        settings = SiteSettings.objects.create()
        SiteSettings.objects.filter(pk=settings.pk).update(updated_at_shamsi=None)
        backfill = import_module('finance.migrations.0024_backfill_shamsi_dates').backfill_shamsi_dates
        backfill(apps, SimpleNamespace(connection=connection))
        settings.refresh_from_db()
        self.assertEqual(settings.updated_at_shamsi, shamsi_storage_value(settings.updated_at))

    def test_storage_date_uses_jalali_calendar(self):
        self.assertEqual(shamsi_storage_value(date(2025, 3, 21)), '1404-01-01')

    def test_customer_birthday_keeps_native_date_and_shamsi_text(self):
        customer = Customer.objects.create(
            first_name='Test', last_name='Date', mobile_number='09120000009',
            national_id='0090000009', birthday=date(2025, 3, 21),
        )
        customer.refresh_from_db()
        self.assertEqual(customer.birthday, date(2025, 3, 21))
        self.assertEqual(customer.birthday_shamsi, '1404-01-01')

    def test_bulk_create_populates_timestamp_mirror(self):
        run = WebsitePriceSyncRun.objects.bulk_create([WebsitePriceSyncRun()])[0]
        run.refresh_from_db()
        self.assertEqual(run.started_at_shamsi, shamsi_storage_value(run.started_at))
