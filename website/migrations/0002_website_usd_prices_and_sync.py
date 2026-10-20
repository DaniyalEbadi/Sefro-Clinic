from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings
from django.db import migrations, models
from django.core.validators import MinValueValidator


def initialize_usd_prices(apps, schema_editor):
    SiteService = apps.get_model('website', 'SiteService')
    SiteProduct = apps.get_model('website', 'SiteProduct')
    SitePackage = apps.get_model('website', 'SitePackage')
    ExchangeRate = apps.get_model('finance', 'ExchangeRate')

    rate = ExchangeRate.objects.filter(
        currency_from='USD', currency_to='TOMAN', is_active=True,
        rate__gt=0,
    ).order_by('-effective_at').values_list('rate', flat=True).first()
    rate = Decimal(str(rate or getattr(settings, 'FINANCE_DEFAULT_USD_TO_TOMAN_RATE', '100000')))
    if rate <= 0:
        raise ValueError('A positive USD-to-Toman rate is required to initialize website prices.')

    def to_usd(price):
        return (Decimal(str(price)) / rate).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    for model in (SiteService, SiteProduct):
        for obj in model.objects.all().iterator():
            obj.price_usd = to_usd(obj.price)
            obj.save(update_fields=['price_usd'])

    for obj in SitePackage.objects.all().iterator():
        obj.price_usd = to_usd(obj.price)
        obj.original_price_usd = to_usd(obj.original_price) if obj.original_price is not None else None
        obj.save(update_fields=['price_usd', 'original_price_usd'])


class Migration(migrations.Migration):
    dependencies = [
        ('finance', '0021_productusage_zero_reason'),
        ('website', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='siteservice', name='price_usd',
            field=models.DecimalField(
                decimal_places=2, default=Decimal('0.00'), max_digits=14,
                validators=[MinValueValidator(Decimal('0'))],
                help_text='Editable USD base price. The public Toman price is derived from this value.',
            ),
        ),
        migrations.AddField(
            model_name='siteproduct', name='price_usd',
            field=models.DecimalField(
                decimal_places=2, default=Decimal('0.00'), max_digits=14,
                validators=[MinValueValidator(Decimal('0'))],
                help_text='Editable USD base price. The public Toman price is derived from this value.',
            ),
        ),
        migrations.AddField(
            model_name='sitepackage', name='price_usd',
            field=models.DecimalField(
                decimal_places=2, default=Decimal('0.00'), max_digits=14,
                validators=[MinValueValidator(Decimal('0'))],
                help_text='Editable USD base price. The public Toman price is derived from this value.',
            ),
        ),
        migrations.AddField(
            model_name='sitepackage', name='original_price_usd',
            field=models.DecimalField(
                blank=True, decimal_places=2, max_digits=14, null=True,
                validators=[MinValueValidator(Decimal('0'))],
                help_text='Editable USD list price used to derive original_price.',
            ),
        ),
        migrations.CreateModel(
            name='WebsitePriceSyncRun',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('status', models.CharField(choices=[('running', 'Running'), ('succeeded', 'Succeeded'), ('failed', 'Failed')], default='running', max_length=20)),
                ('provider', models.CharField(blank=True, max_length=40)),
                ('rate', models.DecimalField(blank=True, decimal_places=6, max_digits=18, null=True)),
                ('started_at', models.DateTimeField(auto_now_add=True)),
                ('finished_at', models.DateTimeField(blank=True, null=True)),
                ('updated_services', models.PositiveIntegerField(default=0)),
                ('updated_packages', models.PositiveIntegerField(default=0)),
                ('updated_products', models.PositiveIntegerField(default=0)),
                ('error', models.TextField(blank=True)),
            ],
            options={'ordering': ['-started_at']},
        ),
        migrations.RunPython(initialize_usd_prices, migrations.RunPython.noop),
    ]
