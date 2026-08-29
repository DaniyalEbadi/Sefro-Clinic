from decimal import Decimal
from typing import Optional

from .exchange_rates import get_rate, to_toman


def service_price_toman(service, at: Optional[object] = None, rate: Optional[Decimal] = None) -> Decimal:
    rate = rate if rate is not None else get_rate('USD', 'TOMAN', at=at)
    return to_toman(service.price_usd or Decimal('0'), rate)


def package_price_toman(package, at: Optional[object] = None, rate: Optional[Decimal] = None) -> Decimal:
    rate = rate if rate is not None else get_rate('USD', 'TOMAN', at=at)
    return to_toman(package.price_usd or Decimal('0'), rate)


def service_pricing_payload(service, at: Optional[object] = None) -> dict:
    rate = get_rate('USD', 'TOMAN', at=at)
    usd = service.price_usd or Decimal('0')
    return {
        'price_usd': str(usd),
        'price_toman': str(to_toman(usd, rate)),
        'exchange_rate': str(rate),
    }


def package_pricing_payload(package, at: Optional[object] = None) -> dict:
    rate = get_rate('USD', 'TOMAN', at=at)
    usd = package.price_usd or Decimal('0')
    return {
        'price_usd': str(usd),
        'price_toman': str(to_toman(usd, rate)),
        'exchange_rate': str(rate),
    }
