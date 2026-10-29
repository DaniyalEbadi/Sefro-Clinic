from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal, localcontext

WHOLE_TOMAN = Decimal('1')
USD_QUANTUM = Decimal('0.000000000001')


def round_toman_up(value: Decimal) -> Decimal:
    """Round a non-negative Toman amount upward to a whole Toman."""
    return Decimal(str(value)).quantize(WHOLE_TOMAN, rounding=ROUND_CEILING)


def toman_price_from_usd(price_usd: Decimal, rate: Decimal) -> Decimal:
    if price_usd is None or rate is None:
        raise ValueError('Both USD price and exchange rate are required.')
    if price_usd < 0 or rate <= 0:
        raise ValueError('USD price must be non-negative and exchange rate must be positive.')
    return round_toman_up(price_usd * rate)


def usd_price_from_toman(price: Decimal, rate: Decimal) -> Decimal:
    """Keep whole-Toman prices stable when converted back at the same rate.

    Round the USD base down: rounding it up followed by Toman's ceiling can
    add an unwanted Toman. Twelve decimal places retain sub-Toman precision
    throughout the exchange-rate field's supported range.
    """
    if price is None or rate is None:
        raise ValueError('Both Toman price and exchange rate are required.')
    if not price.is_finite() or not rate.is_finite() or price < 0 or rate <= 0:
        raise ValueError('Toman price must be non-negative and exchange rate must be positive.')
    with localcontext() as context:
        context.prec = 40
        return (round_toman_up(price) / rate).quantize(USD_QUANTUM, rounding=ROUND_FLOOR)


def get_website_dashboard_rate():
    """Use the last website sync rate, never the financial rate ledger."""
    from website.models import WebsitePriceSyncRun
    from website.services.sync import fetch_website_rate

    rate = WebsitePriceSyncRun.objects.filter(
        status=WebsitePriceSyncRun.Status.SUCCEEDED,
        rate__isnull=False,
        provider__in=('priceto_day', 'nerkhsanj', 'manual'),
    ).order_by('-finished_at', '-pk').values_list('rate', flat=True).first()
    if rate is not None and rate.is_finite() and rate > 0:
        return rate
    rate, _ = fetch_website_rate()
    return rate if rate is not None and rate.is_finite() and rate > 0 else None
