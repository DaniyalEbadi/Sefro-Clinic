"""Seed default employee-expense claim categories.

``finance_expensecategory`` shipped empty, so every claim had to invent a
category inline. Mirrors the operating-expense seed (0005) with a
conservative default set for employee claims.
"""
from django.db import migrations

SEED_CATEGORIES = [
    'Transport',
    'Meals',
    'Supplies',
    'Printing',
    'Other',
]


def seed_categories(apps, schema_editor):
    ExpenseCategory = apps.get_model('finance', 'ExpenseCategory')
    for name in SEED_CATEGORIES:
        ExpenseCategory.objects.get_or_create(
            name=name,
            defaults={'is_active': True},
        )


def unseed_categories(apps, schema_editor):
    """No-op on reverse: seeded rows may already be referenced by real claims,
    and deleting financial reference data on a down migration would be unsafe.
    Deactivate manually instead."""
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('finance', '0012_productusage_welcome_pack_usage'),
    ]

    operations = [
        migrations.RunPython(seed_categories, unseed_categories),
    ]
