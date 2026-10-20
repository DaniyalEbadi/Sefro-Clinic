from decimal import ROUND_CEILING, Decimal

WHOLE_TOMAN = Decimal('1')


def round_toman_up(value: Decimal) -> Decimal:
    """Round a non-negative Toman amount upward to a whole Toman."""
    return Decimal(str(value)).quantize(WHOLE_TOMAN, rounding=ROUND_CEILING)


def toman_price_from_usd(price_usd: Decimal, rate: Decimal) -> Decimal:
    if price_usd is None or rate is None:
        raise ValueError('Both USD price and exchange rate are required.')
    if price_usd < 0 or rate <= 0:
        raise ValueError('USD price must be non-negative and exchange rate must be positive.')
    return round_toman_up(price_usd * rate)
