from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('finance', '0020_remove_sale_payment'),
    ]

    operations = [
        migrations.AddField(
            model_name='productusage',
            name='zero_reason',
            field=models.TextField(
                blank=True,
                help_text='Required explanation when a recipe product was explicitly not used.',
                null=True,
            ),
        ),
    ]
