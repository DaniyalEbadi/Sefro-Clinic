from django.db import connection, transaction
from django.utils import timezone

from finance.services.exchange_rates import (
    BrsApiExchangeRateProvider,
    ExternalExchangeRateProvider,
)

from ..models import SitePackage, SitePackagePriceOption, SiteProduct, SiteService, WebsitePriceSyncRun
from .pricing import toman_price_from_usd


class WebsitePriceSyncAlreadyRunning(RuntimeError):
    pass


_SYNC_LOCK_ID = 7742026


def fetch_website_rate():
    rate = ExternalExchangeRateProvider().get_usd_to_toman_rate()
    if rate is not None:
        return rate, 'tindex'
    rate = BrsApiExchangeRateProvider().get_usd_to_toman_rate()
    if rate is not None:
        return rate, 'brsapi'
    return None, ''


def _update_prices(queryset, usd_field='price_usd', toman_field='price', rate=None):
    objects = list(queryset)
    for obj in objects:
        setattr(obj, toman_field, toman_price_from_usd(getattr(obj, usd_field), rate))
    if objects:
        queryset.model.objects.bulk_update(objects, [toman_field])
    return len(objects)


def _sync_website_prices_unlocked():
    run = WebsitePriceSyncRun.objects.create(status=WebsitePriceSyncRun.Status.RUNNING)
    try:
        rate, provider = fetch_website_rate()
        if rate is None:
            run.status = WebsitePriceSyncRun.Status.FAILED
            run.error = 'Both configured exchange-rate providers failed.'
            run.finished_at = timezone.now()
            run.save(update_fields=['status', 'error', 'finished_at'])
            return run

        with transaction.atomic():
            service_count = _update_prices(SiteService.objects.all(), rate=rate)
            product_count = _update_prices(SiteProduct.objects.all(), rate=rate)
            package_count = _update_prices(SitePackage.objects.all(), rate=rate)
            option_objects = list(SitePackagePriceOption.objects.filter(is_active=True))
            for option in option_objects:
                option.price = toman_price_from_usd(option.price_usd, rate)
            if option_objects:
                SitePackagePriceOption.objects.bulk_update(option_objects, ['price'])
            packages = list(SitePackage.objects.all())
            for package in packages:
                if package.original_price_usd is None:
                    package.original_price = None
                else:
                    package.original_price = toman_price_from_usd(package.original_price_usd, rate)
            if packages:
                SitePackage.objects.bulk_update(packages, ['original_price'])

            run.status = WebsitePriceSyncRun.Status.SUCCEEDED
            run.provider = provider
            run.rate = rate
            run.updated_services = service_count
            run.updated_products = product_count
            run.updated_packages = package_count
            run.finished_at = timezone.now()
            run.save(update_fields=[
                'status', 'provider', 'rate', 'updated_services', 'updated_products',
                'updated_packages', 'finished_at',
            ])
    except Exception as exc:
        run.status = WebsitePriceSyncRun.Status.FAILED
        run.error = f'{exc.__class__.__name__}: {exc}'
        run.finished_at = timezone.now()
        run.save(update_fields=['status', 'error', 'finished_at'])
        raise
    return run


def sync_website_prices():
    """Allow only one website sync at a time across API and scheduler workers."""
    if connection.vendor != 'postgresql':
        return _sync_website_prices_unlocked()
    with connection.cursor() as cursor:
        cursor.execute('SELECT pg_try_advisory_lock(%s)', [_SYNC_LOCK_ID])
        if not cursor.fetchone()[0]:
            raise WebsitePriceSyncAlreadyRunning('A website price sync is already running.')
    try:
        return _sync_website_prices_unlocked()
    finally:
        with connection.cursor() as cursor:
            cursor.execute('SELECT pg_advisory_unlock(%s)', [_SYNC_LOCK_ID])
