from datetime import timedelta
from zoneinfo import ZoneInfo

from django.db import connection, transaction
from django.utils import timezone

from finance.services.exchange_rates import ExternalExchangeRateProvider, NerkhsanjExchangeRateProvider

from ..models import SitePackage, SitePackagePriceOption, SiteService, WebsitePriceSyncRun
from .pricing import toman_price_from_usd, usd_price_from_toman


class WebsitePriceSyncAlreadyRunning(RuntimeError):
    pass


_SYNC_LOCK_ID = 7742026
_SCHEDULE_LOCK_ID = 7742027
_TEHRAN = ZoneInfo('Asia/Tehran')


def fetch_website_rate():
    rate = ExternalExchangeRateProvider().get_usd_to_toman_rate()
    if rate is not None:
        return rate, 'priceto_day'
    rate = NerkhsanjExchangeRateProvider().get_usd_to_toman_rate()
    if rate is not None:
        return rate, 'nerkhsanj'
    return None, ''


def _update_prices(queryset, usd_field='price_usd', toman_field='price', rate=None):
    objects = list(queryset)
    for obj in objects:
        setattr(obj, toman_field, toman_price_from_usd(getattr(obj, usd_field), rate))
    if objects:
        queryset.model.objects.bulk_update(objects, [toman_field])
    return len(objects)


def _initialize_pending_usd_bases(model, rate):
    """Anchor imported Toman prices at the first available website rate."""
    pending = list(model.objects.filter(price_usd=0, price__gt=0))
    for obj in pending:
        obj.price_usd = usd_price_from_toman(obj.price, rate)
    if pending:
        model.objects.bulk_update(pending, ['price_usd'])


def _sync_website_prices_unlocked(rate_override=None):
    run = WebsitePriceSyncRun.objects.create(status=WebsitePriceSyncRun.Status.RUNNING)
    try:
        rate, provider = (rate_override, 'manual') if rate_override is not None else fetch_website_rate()
        if rate is None or not rate.is_finite() or rate <= 0:
            run.status = WebsitePriceSyncRun.Status.FAILED
            run.error = (
                'Website exchange-rate providers are unavailable. Existing prices were preserved; '
                'configure a working provider or submit a manager-supplied rate.'
                if rate_override is None else 'Invalid manager-supplied website rate.'
            )
            run.finished_at = timezone.now()
            run.save(update_fields=['status', 'error', 'finished_at'])
            return run

        with transaction.atomic():
            for model in (SiteService, SitePackage, SitePackagePriceOption):
                _initialize_pending_usd_bases(model, rate)
            service_count = _update_prices(SiteService.objects.all(), rate=rate)
            package_count = _update_prices(SitePackage.objects.all(), rate=rate)
            option_objects = list(SitePackagePriceOption.objects.all())
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
            run.updated_products = 0
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


def sync_website_prices(*, rate_override=None):
    """Allow only one website sync at a time across API and scheduler workers."""
    if connection.vendor != 'postgresql':
        return _sync_website_prices_unlocked(rate_override=rate_override)
    with connection.cursor() as cursor:
        cursor.execute('SELECT pg_try_advisory_lock(%s)', [_SYNC_LOCK_ID])
        if not cursor.fetchone()[0]:
            raise WebsitePriceSyncAlreadyRunning('A website price sync is already running.')
    try:
        return _sync_website_prices_unlocked(rate_override=rate_override)
    finally:
        with connection.cursor() as cursor:
            cursor.execute('SELECT pg_advisory_unlock(%s)', [_SYNC_LOCK_ID])


def _scheduled_window_start(now):
    local_now = timezone.localtime(now, _TEHRAN)
    hour = (local_now.hour // 6) * 6
    return local_now.replace(hour=hour, minute=0, second=0, microsecond=0)


def _sync_website_prices_if_due_unlocked(now):
    window_start = _scheduled_window_start(now)
    if WebsitePriceSyncRun.objects.filter(
        status=WebsitePriceSyncRun.Status.SUCCEEDED,
        provider__in=('priceto_day', 'nerkhsanj'),
        finished_at__gte=window_start,
    ).exists():
        return None
    recent_failure = WebsitePriceSyncRun.objects.filter(
        status=WebsitePriceSyncRun.Status.FAILED,
        finished_at__gte=max(window_start, now - timedelta(minutes=15)),
    ).exists()
    if recent_failure:
        return None
    return sync_website_prices()


def sync_website_prices_if_due(*, now=None):
    """Run once in each Tehran 00:00/06:00/12:00/18:00 window."""
    now = now or timezone.now()
    if connection.vendor != 'postgresql':
        return _sync_website_prices_if_due_unlocked(now)
    with connection.cursor() as cursor:
        cursor.execute('SELECT pg_try_advisory_lock(%s)', [_SCHEDULE_LOCK_ID])
        if not cursor.fetchone()[0]:
            return None
    try:
        return _sync_website_prices_if_due_unlocked(now)
    finally:
        with connection.cursor() as cursor:
            cursor.execute('SELECT pg_advisory_unlock(%s)', [_SCHEDULE_LOCK_ID])
