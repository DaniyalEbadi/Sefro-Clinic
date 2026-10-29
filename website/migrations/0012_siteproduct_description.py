import django.core.validators
from django.db import migrations, models

import Sefro_Clinic.validators


class Migration(migrations.Migration):
    dependencies = [
        ('website', '0011_sitesettings_public_content'),
    ]

    operations = [
        migrations.AddField(
            model_name='siteproduct',
            name='description',
            field=models.TextField(
                blank=True,
                validators=[
                    django.core.validators.ProhibitNullCharactersValidator(),
                    Sefro_Clinic.validators._reject_surrogates,
                ],
            ),
        ),
    ]
