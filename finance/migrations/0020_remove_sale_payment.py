from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ('customers', '0017_visitservice_alter_visit_services_and_more'),
        ('finance', '0019_alter_staffcompensationrule_percent_revenue'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='sale',
            name='payment',
        ),
    ]
