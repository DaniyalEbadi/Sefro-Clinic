from django.conf import settings
from django.db.models.signals import post_migrate
from django.dispatch import receiver


@receiver(post_migrate)
def ensure_default_exchange_rate(sender, **kwargs):
    if kwargs.get('app_config') is None or kwargs['app_config'].name != 'finance':
        return
    from .models import ExchangeRate

    if ExchangeRate.objects.filter(currency_from='USD', currency_to='TOMAN').exists():
        return
    fallback = getattr(settings, 'FINANCE_DEFAULT_USD_TO_TOMAN_RATE', None)
    if fallback is None:
        return
    from django.utils import timezone
    ExchangeRate.objects.create(
        currency_from='USD',
        currency_to='TOMAN',
        rate=fallback,
        effective_at=timezone.now(),
        source='default-seed',
        is_active=True,
    )
