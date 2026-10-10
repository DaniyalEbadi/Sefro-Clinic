from django.db import migrations, models


def rename_calculation_type_value(apps, schema_editor):
    StaffCompensationRule = apps.get_model('finance', 'StaffCompensationRule')
    StaffCompensationRule.objects.filter(calculation_type='percent_profit').update(
        calculation_type='percent_revenue',
    )


def revert_calculation_type_value(apps, schema_editor):
    StaffCompensationRule = apps.get_model('finance', 'StaffCompensationRule')
    StaffCompensationRule.objects.filter(calculation_type='percent_revenue').update(
        calculation_type='percent_profit',
    )


class Migration(migrations.Migration):

    dependencies = [
        ('finance', '0015_seed_staff_compensation_rules'),
    ]

    operations = [
        migrations.RenameField(
            model_name='staffcompensationrule',
            old_name='percent_profit',
            new_name='percent_revenue',
        ),
        migrations.AlterField(
            model_name='staffcompensationrule',
            name='percent_revenue',
            field=models.DecimalField(
                blank=True, decimal_places=2, max_digits=5, null=True,
                help_text='Percentage of the collected service revenue (e.g., 50.00 for 50%)',
            ),
        ),
        migrations.AlterField(
            model_name='staffcompensationrule',
            name='calculation_type',
            field=models.CharField(
                choices=[
                    ('percent_revenue', '% of Revenue'),
                    ('fixed_per_session', 'Fixed per Session'),
                    ('monthly_salary', 'Monthly Salary'),
                ],
                default='percent_revenue',
                max_length=20,
            ),
        ),
        migrations.RunPython(rename_calculation_type_value, revert_calculation_type_value),
    ]
