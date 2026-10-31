from django.db import migrations


SERVICE_CATEGORIES = (
    ('filler-botox', 'فیلر و بوتاکس'),
    ('laser-women', 'لیزر بانوان'),
    ('laser-men', 'لیزر آقایان'),
    ('facial', 'فیشیال'),
)
PACKAGE_CATEGORIES = (
    ('carbon-therapy', 'کربن تراپی'),
    ('laser-women', 'لیزر بانوان'),
    ('laser-men', 'لیزر آقایان'),
)


def seed_categories(apps, schema_editor):
    db = schema_editor.connection.alias
    Category = apps.get_model('website', 'SiteCategory')
    Service = apps.get_model('website', 'SiteService')
    Package = apps.get_model('website', 'SitePackage')
    Product = apps.get_model('website', 'SiteProduct')

    for order, (slug, name) in enumerate(SERVICE_CATEGORIES):
        category, _ = Category.objects.using(db).get_or_create(
            kind='service', slug=slug, defaults={'name': name, 'sort_order': order},
        )
        Service.objects.using(db).filter(source_category=name, site_category__isnull=True).update(
            site_category_id=category.pk,
        )

    for order, (slug, name) in enumerate(PACKAGE_CATEGORIES):
        category, _ = Category.objects.using(db).get_or_create(
            kind='package', slug=slug, defaults={'name': name, 'sort_order': order},
        )
        start, end = ((0, 12), (12, 15), (15, 16))[order]
        Package.objects.using(db).filter(
            source_url='https://barancliniccenter.com/packages',
            is_manually_managed=False, site_category__isnull=True,
            sort_order__gte=start, sort_order__lt=end,
        ).update(site_category_id=category.pk)

    product_category, _ = Category.objects.using(db).get_or_create(
        kind='product', slug='skin-care', defaults={'name': 'مراقبت پوست', 'sort_order': 0},
    )
    Product.objects.using(db).filter(site_category__isnull=True).update(site_category_id=product_category.pk)


class Migration(migrations.Migration):
    dependencies = [('website', '0015_sitecategory_sitepackage_site_category_and_more')]

    operations = [migrations.RunPython(seed_categories, migrations.RunPython.noop)]
