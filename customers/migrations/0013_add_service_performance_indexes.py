# Generated for Sefro Clinic performance tuning

import django.db.models
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('customers', '0012_add_service_category_and_service_product'),
    ]

    operations = [
        # Service filtering by ?category= & ?is_active= (customers/views.py:464)
        # Partial index keeps size small — only active services are filtered in UI
        migrations.AddIndex(
            model_name='service',
            index=models.Index(
                fields=['category', 'is_active'],
                name='svc_category_active_idx',
                condition=models.Q(is_active=True),
            ),
        ),
        # Service ordering ['name'] and search ['name','category__name'] — btree on name helps ORDER BY and prefix search
        migrations.AddIndex(
            model_name='service',
            index=models.Index(fields=['name'], name='svc_name_idx'),
        ),
        # ServiceCategory ordering ['sort_order','name'] (Meta ordering)
        migrations.AddIndex(
            model_name='servicecategory',
            index=models.Index(fields=['sort_order', 'name'], name='svc_cat_sort_idx'),
        ),
        # Payment range queries for reports: _filtered_payments (paid_at__gte/lt) + customer breakdown
        # Composite covers both date-range and customer-filtered reports
        migrations.AddIndex(
            model_name='payment',
            index=models.Index(fields=['paid_at', 'customer'], name='payments_paid_at_customer_idx'),
        ),
    ]
