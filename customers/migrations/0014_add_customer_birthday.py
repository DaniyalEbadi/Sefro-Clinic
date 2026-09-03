# Generated for Sefro Clinic — Customer birthday (Shamsi YYYY-MM-DD via API)

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('customers', '0013_add_service_performance_indexes'),
    ]

    operations = [
        migrations.AddField(
            model_name='customer',
            name='birthday',
            field=models.DateField(blank=True, help_text='Customer birthday (Shamsi YYYY-MM-DD via API)', null=True),
        ),
    ]
