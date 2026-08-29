from decimal import Decimal
from typing import Optional

from django.conf import settings
from django.utils import timezone

from ..models import ExchangeRate


def get_rate(currency_from: str = 'USD', currency_to: str = 'TOMAN', at: Optional[object] = None) -> Decimal:
    when = at or timezone.now()
    if isinstance(when, str):
        when = timezone.now()
    qs = ExchangeRate.objects.filter(
        currency_from=currency_from,
        currency_to=currency_to,
        is_active=True,
        effective_at__lte=when,
    ).order_by('-effective_at')
    rate = qs.values_list('rate', flat=True).first()
    if rate is not None:
        return rate
    fallback = getattr(settings, 'FINANCE_DEFAULT_USD_TO_TOMAN_RATE', Decimal('100000'))
    if isinstance(fallback, str):
        fallback = Decimal(fallback)
    return fallback


def to_toman(usd: Decimal, rate: Optional[Decimal] = None) -> Decimal:
    rate = rate if rate is not None else get_rate('USD', 'TOMAN')
    quantized = (Decimal(usd) * rate).quantize(Decimal('0.01'))
    return quantized


def to_usd(toman: Decimal, rate: Optional[Decimal] = None) -> Decimal:
    rate = rate if rate is not None else get_rate('USD', 'TOMAN')
    if rate == 0:
        return Decimal('0')
    return (Decimal(toman) / rate).quantize(Decimal('0.01'))


def set_rate(currency_from: str, currency_to: str, rate: Decimal, *, effective_at=None, source='', is_active=True):
    effective_at = effective_at or timezone.now()
    return ExchangeRate.objects.create(
        currency_from=currency_from,
        currency_to=currency_to,
        rate=rate,
        effective_at=effective_at,
        source=source,
        is_active=is_active,
    )
