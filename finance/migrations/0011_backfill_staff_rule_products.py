from decimal import Decimal

from django.db import migrations


def backfill_rule_products(apps, schema_editor):
    StaffCompensationRule = apps.get_model('finance', 'StaffCompensationRule')
    StaffCompensationRuleProduct = apps.get_model('finance', 'StaffCompensationRuleProduct')

    for rule in StaffCompensationRule.objects.exclude(product__isnull=True).iterator():
        StaffCompensationRuleProduct.objects.get_or_create(
            rule=rule,
            product=rule.product,
            defaults={'quantity': rule.product_qty or Decimal('1')},
        )


def unbackfill_rule_products(apps, schema_editor):
    apps.get_model('finance', 'StaffCompensationRuleProduct').objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [
        ('finance', '0010_staffcompensationruleproduct_staffpayoutproduct_and_more'),
        ('inventory', '0005_alter_product_unit_price'),
    ]

    operations = [
        migrations.RunPython(backfill_rule_products, unbackfill_rule_products),
    ]
