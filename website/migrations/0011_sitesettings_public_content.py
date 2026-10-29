import django.core.validators
from django.db import migrations, models

import Sefro_Clinic.validators


class Migration(migrations.Migration):
    dependencies = [
        ('website', '0010_alter_websitemanagercredential_user'),
    ]

    operations = [
        migrations.AddField(
            model_name='sitesettings',
            name='clinic_name',
            field=models.CharField(
                blank=True, max_length=180,
                validators=[django.core.validators.ProhibitNullCharactersValidator(), Sefro_Clinic.validators._reject_surrogates],
            ),
        ),
        migrations.AddField(
            model_name='sitesettings',
            name='logo_url',
            field=models.URLField(blank=True),
        ),
        migrations.AddField(
            model_name='sitesettings',
            name='contact_email',
            field=models.EmailField(blank=True, max_length=254),
        ),
        migrations.AddField(
            model_name='sitesettings',
            name='social_links',
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
