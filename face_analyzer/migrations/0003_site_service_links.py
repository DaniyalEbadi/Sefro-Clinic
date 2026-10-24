import django.db.models.deletion
from django.db import migrations, models


def clear_service_links(apps, schema_editor):
    tips = apps.get_model('face_analyzer', 'SkinCareTip')
    tips.objects.using(schema_editor.connection.alias).filter(
        related_service_id__isnull=False,
    ).update(related_service_id=None)


def link_matching_site_services(apps, schema_editor):
    tips = apps.get_model('face_analyzer', 'SkinCareTip')
    services = apps.get_model('website', 'SiteService')
    alias = schema_editor.connection.alias
    by_slug = dict(services.objects.using(alias).values_list('slug', 'id'))
    for slug, service_id in by_slug.items():
        tips.objects.using(alias).filter(related_service_slug=slug).update(related_service_id=service_id)


class Migration(migrations.Migration):
    dependencies = [
        ('face_analyzer', '0002_skincareplan_skincaretip'),
        ('website', '0005_website_usd_price_precision'),
    ]

    operations = [
        migrations.RunPython(clear_service_links, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='skincaretip',
            name='related_service',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='skin_tips',
                to='website.siteservice',
            ),
        ),
        migrations.RunPython(link_matching_site_services, clear_service_links),
    ]
