from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ('finance', '0020_remove_sale_payment'),
        ('customers', '0017_visitservice_alter_visit_services_and_more'),
    ]

    operations = [
        migrations.DeleteModel(
            name='Payment',
        ),
    ]
