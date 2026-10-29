import json
import logging
import urllib.error
import urllib.request
from decimal import Decimal, InvalidOperation
from typing import Optional, Protocol

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from ..models import ExchangeRate

logger = logging.getLogger(__name__)
_FAILED_REFRESH_CACHE_KEY = 'finance:usd_toman:provider_failure'


class ExchangeRateProvider(Protocol):
    """Abstraction for USD→TOMAN rate retrieval."""

    def get_usd_to_toman_rate(self) -> Optional[Decimal]:
        ...


def _validate_rate(value) -> Optional[Decimal]:
    """Validate rate is positive numeric Decimal."""
    try:
        rate = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError, AttributeError):
        return None
    if not rate.is_finite() or rate <= 0:
        return None
    return rate


def _get_cached_rate(currency_from: str = 'USD', currency_to: str = 'TOMAN', at=None) -> Optional[Decimal]:
    when = at or timezone.now()
    if isinstance(when, str):
        when = timezone.now()
    qs = ExchangeRate.objects.filter(
        currency_from=currency_from,
        currency_to=currency_to,
        is_active=True,
        effective_at__lte=when,
    ).order_by('-effective_at')
    return qs.values_list('rate', flat=True).first()


def get_rate(currency_from: str = 'USD', currency_to: str = 'TOMAN', at: Optional[object] = None) -> Decimal:
    """Legacy helper: returns DB rate or configured fallback."""
    rate = _get_cached_rate(currency_from, currency_to, at=at)
    if rate is not None:
        validated = _validate_rate(rate)
        if validated is not None:
            return validated
    fallback = getattr(settings, 'FINANCE_DEFAULT_USD_TO_TOMAN_RATE', Decimal('100000'))
    if isinstance(fallback, str):
        fallback = Decimal(fallback)
    # fallback is explicit documented policy; validate but still return if positive
    validated = _validate_rate(fallback)
    if validated is not None:
        return validated
    return Decimal('100000')


def get_current_usd_to_toman_rate() -> Optional[Decimal]:
    """
    Return latest valid cached rate for USD→TOMAN.
    Uses DB cache; attempts external refresh if configured and cache stale.
    PriceToDay is primary; Nerkhsanj is backup. On failure, preserve the cached rate.
    Returns None if no valid rate available (caller should expose null).
    """
    # Try external provider if configured and cache stale
    provider = getattr(settings, 'EXCHANGE_RATE_PROVIDER', 'database')
    if provider == 'external':
        ttl = int(getattr(settings, 'EXCHANGE_RATE_CACHE_TTL', 3600))
        latest = ExchangeRate.objects.filter(
            currency_from='USD', currency_to='TOMAN', is_active=True,
            effective_at__lte=timezone.now(),
        ).order_by('-effective_at').first()
        is_stale = latest is None or latest.source not in ('priceto_day', 'nerkhsanj')
        if latest and not is_stale:
            age = (timezone.now() - latest.effective_at).total_seconds()
            is_stale = age >= ttl or _validate_rate(latest.rate) is None
        # Avoid calling both upstreams on every dashboard request during an outage.
        if is_stale and (settings.TESTING or not cache.get(_FAILED_REFRESH_CACHE_KEY)):
            fetched = ExternalExchangeRateProvider().get_usd_to_toman_rate()
            source = 'priceto_day'
            if fetched is None:
                fetched = NerkhsanjExchangeRateProvider().get_usd_to_toman_rate()
                source = 'nerkhsanj'
            if fetched is not None:
                if not settings.TESTING:
                    cache.delete(_FAILED_REFRESH_CACHE_KEY)
                try:
                    ExchangeRate.objects.create(
                        currency_from='USD',
                        currency_to='TOMAN',
                        rate=fetched,
                        effective_at=timezone.now(),
                        source=source,
                        is_active=True,
                    )
                except Exception:  # pragma: no cover
                    logger.exception('Failed to cache exchange rate')
                return fetched
            if not settings.TESTING:
                cache.set(_FAILED_REFRESH_CACHE_KEY, True, timeout=60)
        elif latest is not None and not is_stale:
            return _validate_rate(latest.rate)
    rate = _get_cached_rate('USD', 'TOMAN')
    validated = _validate_rate(rate) if rate is not None else None
    if validated is not None:
        return validated
    # Explicit fallback policy: use configured default if no DB rate
    fallback = getattr(settings, 'FINANCE_DEFAULT_USD_TO_TOMAN_RATE', None)
    if fallback is not None:
        validated = _validate_rate(fallback)
        if validated is not None:
            return validated
    return None


class DatabaseExchangeRateProvider:
    """Provider backed by DB cached rate (and documented fallback)."""

    def get_usd_to_toman_rate(self) -> Optional[Decimal]:
        return get_current_usd_to_toman_rate()


class ExternalExchangeRateProvider:
    """PriceToDay USD/IRR quote, converted to Toman per USD."""

    DEFAULT_URL = 'https://api.priceto.day/v1/latest/irr/usd'

    def __init__(self, api_url: str = '', timeout: Optional[int] = None):
        self.api_url = api_url
        self.timeout = timeout

    def get_usd_to_toman_rate(self) -> Optional[Decimal]:
        api_url = self.api_url or getattr(settings, 'PRICE_TO_DAY_API_URL', '') or self.DEFAULT_URL
        if not api_url:
            return None
        timeout = self.timeout if self.timeout is not None else int(getattr(settings, 'EXCHANGE_RATE_TIMEOUT', 5))
        headers = {
            'Accept': 'application/json',
            'User-Agent': 'Mozilla/5.0 (SefroClinic/1.0)',
        }
        if not api_url.lower().startswith(('http://', 'https://')):
            logger.warning('Exchange rate API URL must be http(s)')
            return None
        req = urllib.request.Request(api_url, headers=headers, method='GET')
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec B310
                if resp.status != 200:
                    # Respect Retry-After on 429 without leaking key
                    if resp.status == 429:
                        retry = resp.headers.get('Retry-After')
                        logger.warning('Exchange rate rate-limited; retry_after=%s', retry)
                    else:
                        logger.warning('Exchange rate API HTTP %s', resp.status)
                    return None
                body = resp.read().decode('utf-8')
                data = json.loads(body)
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                try:
                    retry = exc.headers.get('Retry-After')
                except Exception:
                    retry = None
                logger.warning('Exchange rate rate-limited; retry_after=%s', retry)
            else:
                logger.warning('Exchange rate fetch failed: HTTPError %s', exc.code)
            return None
        except urllib.error.URLError as exc:
            logger.warning('Exchange rate fetch failed: %s', exc.__class__.__name__)
            return None
        except TimeoutError:
            logger.warning('Exchange rate fetch timeout')
            return None
        except json.JSONDecodeError:
            logger.warning('Exchange rate malformed JSON')
            return None
        except Exception as exc:  # pragma: no cover
            logger.warning('Exchange rate fetch error: %s', exc.__class__.__name__)
            return None

        if not isinstance(data, dict) or data.get('success') is not True:
            logger.warning('PriceToDay response was unsuccessful')
            return None
        rial_price = _validate_rate(data.get('price'))
        if rial_price is None:
            logger.warning('PriceToDay response had no valid rial price')
            return None
        return rial_price / Decimal('10')


class NerkhsanjExchangeRateProvider:
    """Read Nerkhsanj's public USD price, which is already in Toman."""

    DEFAULT_URL = 'https://nerkh.jahankhahan.shop/data/live.json'

    def __init__(self, api_url: str = '', timeout: Optional[int] = None):
        self.api_url = api_url
        self.timeout = timeout

    def get_usd_to_toman_rate(self) -> Optional[Decimal]:
        api_url = self.api_url or getattr(settings, 'NERKHSANJ_API_URL', '') or self.DEFAULT_URL
        if not api_url.lower().startswith(('http://', 'https://')):
            logger.warning('Nerkhsanj API URL must be http(s)')
            return None
        timeout = self.timeout if self.timeout is not None else int(getattr(settings, 'EXCHANGE_RATE_TIMEOUT', 5))
        req = urllib.request.Request(
            api_url,
            headers={'Accept': 'application/json', 'User-Agent': 'SefroClinic/1.0'},
            method='GET',
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec B310
                if resp.status != 200:
                    logger.warning('Nerkhsanj API HTTP %s', resp.status)
                    return None
                data = json.loads(resp.read().decode('utf-8'))
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            logger.warning('Nerkhsanj fetch failed: %s', exc.__class__.__name__)
            return None
        except Exception as exc:  # pragma: no cover
            logger.warning('Nerkhsanj fetch error: %s', exc.__class__.__name__)
            return None

        rates = data.get('rates') if isinstance(data, dict) else None
        rate = _validate_rate(rates.get('dollar')) if isinstance(rates, dict) else None
        if rate is None:
            logger.warning('Nerkhsanj response had no valid Toman dollar rate')
        return rate


def convert_usd_to_toman(amount_usd: Decimal, rate: Decimal) -> Decimal:
    """Convert USD amount using explicit rate. Validates inputs."""
    try:
        amt = Decimal(str(amount_usd))
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError('amount must be Decimal-compatible')
    r = _validate_rate(rate)
    if r is None:
        raise ValueError('rate must be positive')
    return (amt * r).quantize(Decimal('0.01'))


def usd_to_toman(amount_usd: Decimal) -> Optional[Decimal]:
    """High-level helper: obtains current valid rate and converts."""
    rate = get_current_usd_to_toman_rate()
    if rate is None:
        return None
    return convert_usd_to_toman(amount_usd, rate)


def to_toman(usd: Decimal, rate: Optional[Decimal] = None) -> Decimal:
    if rate is not None:
        validated = _validate_rate(rate)
        if validated is None:
            raise ValueError('rate must be positive')
        return convert_usd_to_toman(usd, validated)
    # legacy path: use get_rate fallback
    rate = get_rate('USD', 'TOMAN')
    return (Decimal(str(usd)) * rate).quantize(Decimal('0.01'))


def to_usd(toman: Decimal, rate: Optional[Decimal] = None) -> Decimal:
    r = rate if rate is not None else get_rate('USD', 'TOMAN')
    validated = _validate_rate(r)
    if validated is None or validated == 0:
        return Decimal('0')
    return (Decimal(str(toman)) / validated).quantize(Decimal('0.01'))


def set_rate(currency_from: str, currency_to: str, rate: Decimal, *, effective_at=None, source='', is_active=True):
    effective_at = effective_at or timezone.now()
    validated = _validate_rate(rate)
    if validated is None:
        raise ValueError('rate must be positive')
    return ExchangeRate.objects.create(
        currency_from=currency_from,
        currency_to=currency_to,
        rate=validated,
        effective_at=effective_at,
        source=source,
        is_active=is_active,
    )
