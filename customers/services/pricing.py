"""Service pricing: estimated cost / gross / margin in USD and derived Toman.

Current estimate uses current Product.cost_usd (source of truth), not
historical ProductCostHistory/ProductUsage snapshots.
"""

from decimal import Decimal, InvalidOperation

from finance.services.exchange_rates import convert_usd_to_toman, get_current_usd_to_toman_rate


def _get_service_items(service):
    """
    Return already-prefetched items if available to avoid N+1, else query.
    Prefetch should be: prefetch_related('items__product')
    """
    # If prefetched, Django stores in _prefetched_objects_cache
    if hasattr(service, '_prefetched_objects_cache') and 'items' in service._prefetched_objects_cache:
        return service._prefetched_objects_cache['items']
    # Fallback to query with select_related for efficiency
    return service.items.select_related('product').all()


def calculate_service_cost_usd(service) -> Decimal:
    """
    Estimated Service Cost = Σ(Product.cost_usd × ServiceItem.quantity)
    Uses current Product.cost_usd, quantity with 3 decimals, result quantized to 2.
    """
    total = Decimal('0')
    items = _get_service_items(service)
    for item in items:
        try:
            qty = Decimal(str(item.quantity))
        except (InvalidOperation, ValueError, TypeError):
            continue
        cost = item.product.cost_usd if item.product.cost_usd is not None else Decimal('0')
        try:
            cost_dec = Decimal(str(cost))
        except (InvalidOperation, ValueError, TypeError):
            cost_dec = Decimal('0')
        total += qty * cost_dec
    # Quantize at boundary to project USD precision (2 places)
    return total.quantize(Decimal('0.01'))


def calculate_service_gross_profit_usd(service) -> Decimal:
    """
    Estimated Gross Profit = Service.price_usd - Estimated Service Cost
    Negative profit supported, not clamped.
    """
    price = service.price_usd if service.price_usd is not None else Decimal('0')
    try:
        price_dec = Decimal(str(price))
    except (InvalidOperation, ValueError, TypeError):
        price_dec = Decimal('0')
    cost = calculate_service_cost_usd(service)
    return (price_dec - cost).quantize(Decimal('0.01'))


def calculate_service_margin_percent(service) -> Decimal:
    """
    Estimated Margin % = Gross / price * 100, quantized to 2.
    Zero price → 0. Not clamped to 0-100.
    """
    price = service.price_usd if service.price_usd is not None else Decimal('0')
    try:
        price_dec = Decimal(str(price))
    except (InvalidOperation, ValueError, TypeError):
        price_dec = Decimal('0')
    if price_dec == 0:
        return Decimal('0.00')
    gross = calculate_service_gross_profit_usd(service)
    # Retain precision through intermediate, quantize at end
    margin = (gross / price_dec * Decimal('100')).quantize(Decimal('0.01'))
    return margin


def _toman_or_none(usd_value: Decimal, rate: Decimal | None) -> Decimal | None:
    if usd_value is None:
        return None
    if rate is None:
        return None
    try:
        return convert_usd_to_toman(usd_value, rate)
    except (ValueError, InvalidOperation):
        return None


def service_pricing_breakdown(service, rate: Decimal | None = None) -> dict:
    """
    Return full pricing breakdown for serializer use.
    Rate should be resolved once per request/serializer (not per field).
    """
    if rate is None:
        rate = get_current_usd_to_toman_rate()

    price_usd = service.price_usd if service.price_usd is not None else Decimal('0')
    try:
        price_usd = Decimal(str(price_usd)).quantize(Decimal('0.01'))
    except (InvalidOperation, ValueError, TypeError):
        price_usd = Decimal('0.00')

    cost_usd = calculate_service_cost_usd(service)
    gross_usd = calculate_service_gross_profit_usd(service)
    margin = calculate_service_margin_percent(service)

    return {
        'price_usd': price_usd,
        'estimated_cost_usd': cost_usd,
        'estimated_gross_profit_usd': gross_usd,
        'estimated_margin_percent': margin,
        'price_toman': _toman_or_none(price_usd, rate),
        'estimated_cost_toman': _toman_or_none(cost_usd, rate),
        'estimated_gross_profit_toman': _toman_or_none(gross_usd, rate),
        'exchange_rate': rate,
    }
