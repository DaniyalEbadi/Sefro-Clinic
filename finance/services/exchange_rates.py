import json
import logging
import urllib.error
import urllib.request
from decimal import Decimal, InvalidOperation
from typing import Optional, Protocol

from django.conf import settings
from django.utils import timezone

from ..models import ExchangeRate

logger = logging.getLogger(__name__)


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
    if rate <= 0:
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
    Falls back to BrsApi backup if primary provider fails.
    Returns None if no valid rate available (caller should expose null).
    """
    # Try external provider if configured and cache stale
    provider = getattr(settings, 'EXCHANGE_RATE_PROVIDER', 'database')
    if provider == 'external':
        ttl = int(getattr(settings, 'EXCHANGE_RATE_CACHE_TTL', 3600))
        api_url = getattr(settings, 'EXCHANGE_RATE_API_URL', '')
        if api_url:
            latest = ExchangeRate.objects.filter(
                currency_from='USD', currency_to='TOMAN', is_active=True
            ).order_by('-effective_at').first()
            is_stale = True
            if latest:
                age = (timezone.now() - latest.effective_at).total_seconds()
                if age < ttl:
                    is_stale = False
            if is_stale:
                # Try primary provider first
                ext = ExternalExchangeRateProvider()
                fetched = ext.get_usd_to_toman_rate()
                # If primary fails, try BrsApi backup
                if fetched is None:
                    logger.info('Primary exchange rate provider failed, trying BrsApi backup')
                    backup = BrsApiExchangeRateProvider()
                    fetched = backup.get_usd_to_toman_rate()
                if fetched is not None:
                    # Cache fetched rate to DB so other workers reuse it
                    try:
                        ExchangeRate.objects.create(
                            currency_from='USD',
                            currency_to='TOMAN',
                            rate=fetched,
                            effective_at=timezone.now(),
                            source='external',
                            is_active=True,
                        )
                    except Exception:  # pragma: no cover
                        logger.exception('Failed to cache external rate')
                    return fetched
                # on fetch failure, fall through to cached
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
    """Adapter for external exchange-rate HTTP API. Defaults to Tindex (tindex.app)."""

    DEFAULT_URL = 'https://tindex.app/api/public/indicators/Foreign-Currency/USD-EXCHANGE-RATE'

    def __init__(self, api_url: str = '', api_key: str = '', timeout: int = 5):
        self.api_url = api_url
        self.api_key = api_key
        self.timeout = timeout

    def get_usd_to_toman_rate(self) -> Optional[Decimal]:
        api_url = self.api_url
        if not api_url:
            # Only use default if setting doesn't exist at all (not just empty string)
            if hasattr(settings, 'EXCHANGE_RATE_API_URL'):
                api_url = getattr(settings, 'EXCHANGE_RATE_API_URL', '')
            else:
                api_url = self.DEFAULT_URL
        if not api_url:
            return None
        api_key = self.api_key or getattr(settings, 'EXCHANGE_RATE_API_KEY', '')
        timeout = self.timeout or int(getattr(settings, 'EXCHANGE_RATE_TIMEOUT', 5))
        headers = {
            'Accept': 'application/json',
            'User-Agent': 'Mozilla/5.0 (SefroClinic/1.0)',
        }
        if api_key:
            headers['Authorization'] = f'Bearer {api_key}'
            headers['X-API-Key'] = api_key
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

        # Tindex shape: {"success":true,"data":[{"key":"USD-EXCHANGE-RATE","rate":92570,...}, ...]}
        # Also supports {"success":true,"data":{"price":92570}} for single indicator
        candidates = []
        try:
            if isinstance(data, dict) and 'data' in data:
                payload = data['data']
                if isinstance(payload, list):
                    # currency-rates list
                    for item in payload:
                        if isinstance(item, dict):
                            key = str(item.get('key') or '').lower()
                            slug = str(item.get('slug') or '').lower()
                            if key == 'usd-exchange-rate' or slug == 'usd-exchange-rate':
                                candidates.append(item.get('rate'))
                                candidates.append(item.get('price'))
                    # fallback: boards style data[0].rows
                    if not candidates and payload and isinstance(payload[0], dict) and 'rows' in payload[0]:
                        for board in payload:
                            for row in board.get('rows', []):
                                slug = str(row.get('slug') or '').lower()
                                if slug == 'usd-exchange-rate':
                                    candidates.append(row.get('price'))
                                    candidates.append(row.get('rate'))
                elif isinstance(payload, dict):
                    # single indicator: {"price": 92570} or {"rate":...} (Tindex /api/public/indicators/Foreign-Currency/USD-EXCHANGE-RATE)
                    for k in ('price', 'rate', 'value', 'result'):
                        if k in payload:
                            candidates.append(payload[k])
                    # nested current.price
                    if 'current' in payload and isinstance(payload['current'], dict):
                        for k in ('price', 'rate'):
                            if k in payload['current']:
                                candidates.append(payload['current'][k])
            # Generic fallback patterns (other providers)
            if not candidates:
                if isinstance(data, dict):
                    for key in ('rate', 'Rate', 'RATE', 'USD_TOMAN', 'usd_toman', 'result', 'value', 'price'):
                        if key in data:
                            candidates.append(data[key])
                    for nested_key in ('data', 'rates', 'payload'):
                        nested = data.get(nested_key)
                        if isinstance(nested, dict):
                            for k2 in ('rate', 'TOMAN', 'toman', 'IRR', 'result', 'price'):
                                if k2 in nested:
                                    candidates.append(nested[k2])
                elif isinstance(data, (int, float, str)):
                    candidates.append(data)
        except Exception:  # pragma: no cover
            pass

        for cand in candidates:
            validated = _validate_rate(cand)
            if validated is not None:
                return validated
        logger.warning('Exchange rate missing or invalid rate field')
        return None


class BrsApiExchangeRateProvider:
    """Backup exchange-rate provider using BrsApi.ir Gold/Currency API."""

    DEFAULT_URL = 'https://Api.BrsApi.ir/Market/Gold_Currency.php'

    def get_usd_to_toman_rate(self) -> Optional[Decimal]:
        api_url = getattr(settings, 'EXCHANGE_RATE_BACKUP_API_URL', '') or self.DEFAULT_URL
        api_key = getattr(settings, 'EXCHANGE_RATE_BACKUP_API_KEY', '')
        timeout = int(getattr(settings, 'EXCHANGE_RATE_TIMEOUT', 5))

        if not api_key:
            logger.warning('BrsApi backup: no API key configured')
            return None

        if not api_url.lower().startswith(('http://', 'https://')):
            logger.warning('BrsApi backup: invalid API URL')
            return None

        url = f'{api_url}?key={api_key}'
        headers = {
            'Accept': 'application/json',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer': 'https://brsapi.ir/',
        }
        req = urllib.request.Request(url, headers=headers, method='GET')
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if resp.status != 200:
                    logger.warning('BrsApi backup: HTTP %s', resp.status)
                    return None
                body = resp.read().decode('utf-8')
                data = json.loads(body)
        except urllib.error.HTTPError as exc:
            logger.warning('BrsApi backup: HTTPError %s', exc.code)
            return None
        except urllib.error.URLError:
            logger.warning('BrsApi backup: URLError')
            return None
        except TimeoutError:
            logger.warning('BrsApi backup: timeout')
            return None
        except json.JSONDecodeError:
            logger.warning('BrsApi backup: malformed JSON')
            return None
        except Exception as exc:
            logger.warning('BrsApi backup: %s', exc.__class__.__name__)
            return None

        # BrsApi response: {"currency": [{"name":"دلار","name_en":"US Dollar","symbol":"USD","price":"220300",...},...]}
        candidates = []
        try:
            if isinstance(data, dict):
                for key in ('currency', 'Currency', 'gold', 'Gold', 'data', 'result'):
                    items = data.get(key, [])
                    if isinstance(items, list):
                        for item in items:
                            if isinstance(item, dict):
                                name_en = str(item.get('name_en', '')).upper()
                                symbol = str(item.get('symbol', '')).upper()
                                if 'USD' in symbol or 'USD' in name_en or 'DOLLAR' in name_en:
                                    for price_key in ('price', 'rate', 'value', 'best_buy', 'best_sell'):
                                        candidates.append(item.get(price_key))
                    elif isinstance(items, dict):
                        for k in ('price', 'rate', 'value', 'USD', 'usd'):
                            candidates.append(items.get(k))
        except Exception:
            pass

        for cand in candidates:
            validated = _validate_rate(cand)
            if validated is not None:
                return validated
        logger.warning('BrsApi backup: no valid rate found')
        return None


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
