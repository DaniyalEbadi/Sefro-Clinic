"""Website catalog suggestions derived from an analysis, never from financial data."""

from urllib.parse import quote

from website.models import SitePackage, SiteProduct, SiteService
from website.services.pricing import round_toman_up

CONCERN_LABELS = {
    'hyperpigmentation': 'لک و تیرگی',
    'acne': 'جوش و آکنه',
    'fine_lines': 'خطوط ظریف',
    'dullness': 'کدری پوست',
    'enlarged_pores': 'منافذ قابل مشاهده',
    'redness': 'قرمزی',
    'dark_circles': 'تیرگی دور چشم',
    'dryness': 'خشکی پوست',
    'oiliness': 'چربی پوست',
}

# Ordered, deliberately conservative matches to the imported public catalog.
SERVICE_MATCHES = {
    'hyperpigmentation': ('acid-therapy',),
    'acne': ('skin-cleansing',),
    'fine_lines': ('peptide-therapy', 'mesonidling-face'),
    'dullness': ('skin-cleansing', 'plagen-therapy', 'acid-therapy'),
    'enlarged_pores': ('skin-cleansing',),
    'dark_circles': ('carboxy-eye-therapy',),
    'oiliness': ('skin-cleansing',),
}
PRODUCT_MATCHES = {
    'hyperpigmentation': ('vitamin-c-serum', 'sunscreen-spf50'),
    'acne': ('sunscreen-spf50',),
    'fine_lines': ('hyaluronic-acid-cream', 'sunscreen-spf50'),
    'dullness': ('vitamin-c-serum', 'sunscreen-spf50'),
    'enlarged_pores': ('sunscreen-spf50',),
    'redness': ('hyaluronic-acid-cream', 'sunscreen-spf50'),
    'dark_circles': ('sunscreen-spf50',),
    'dryness': ('hyaluronic-acid-cream', 'sunscreen-spf50'),
    'oiliness': ('sunscreen-spf50',),
}
NEXT_STEPS = {
    'hyperpigmentation': 'برای لک‌ها، محافظت روزانه در برابر آفتاب را در اولویت بگذارید.',
    'acne': 'برای جوش، از دستکاری پوست خودداری کنید و روتین ملایم را با متخصص بررسی کنید.',
    'fine_lines': 'برای خطوط ظریف، درباره روش مناسب با پزشک کلینیک مشورت کنید.',
    'dullness': 'برای کدری، روتین پاکسازی و محافظت در برابر آفتاب را بررسی کنید.',
    'enlarged_pores': 'برای منافذ، درباره پاکسازی ملایم با متخصص مشورت کنید.',
    'redness': 'اگر قرمزی ماندگار است، پیش از هر درمان کلینیکی با متخصص مشورت کنید.',
    'dark_circles': 'برای تیرگی دور چشم، ابتدا علت احتمالی را با پزشک بررسی کنید.',
    'dryness': 'برای خشکی، از مرطوب‌کننده مناسب استفاده کنید و از تحریک پوست پرهیز کنید.',
    'oiliness': 'برای چربی پوست، پاکسازی ملایم و ضدآفتاب مناسب را بررسی کنید.',
}
CLARITY_CONCERNS = frozenset({
    'hyperpigmentation', 'acne', 'dullness', 'enlarged_pores', 'redness', 'dryness', 'oiliness',
})


def _catalog_item(item, kind: str, concern: str) -> dict:
    label = CONCERN_LABELS.get(concern, 'مراقبت عمومی')
    action = 'درباره مناسب بودن این خدمت با متخصص کلینیک مشورت کنید.' if kind != 'product' else (
        'در صورت مناسب بودن برای پوست شما، آن را در روتین مراقبت بررسی کنید.'
    )
    result = {
        'id': item.pk,
        'slug': item.slug,
        'name': item.name,
        'price_toman': str(round_toman_up(item.price)),
        'source_url': item.source_url,
        'api_url': f'/api/v2/{kind}s/{quote(item.slug)}/',
        'image_url': getattr(item, 'image_url', ''),
        'matched_concern': concern,
        'reason': f'برای بررسی {label}: {action}',
    }
    if kind == 'service':
        result['is_from_price'] = item.is_from_price
    if kind == 'package':
        result['price_options'] = [
            {
                'label': option.label,
                'session_count': option.session_count,
                'gift_session_count': option.gift_session_count,
                'price_toman': str(round_toman_up(option.price)),
            }
            for option in item.price_options.all() if option.is_active
        ]
    return result


def _matched_items(concerns: list[str], rules: dict, catalog: dict, kind: str, limit: int) -> list[dict]:
    results = []
    seen = set()
    for concern in concerns:
        for slug in rules.get(concern, ()):
            if slug in seen or slug not in catalog:
                continue
            seen.add(slug)
            results.append(_catalog_item(catalog[slug], kind, concern))
            if len(results) >= limit:
                return results
    return results


def build_catalog_recommendations(analysis) -> dict:
    """Return current, active website matches; no treatment is inferred from a score alone."""
    attributes = analysis.detected_attributes if isinstance(analysis.detected_attributes, dict) else {}
    raw_concerns = attributes.get('concerns')
    concerns = list(dict.fromkeys(
        concern for concern in (raw_concerns if isinstance(raw_concerns, list) else [])
        if isinstance(concern, str) and concern in CONCERN_LABELS
    ))
    # Scores only reorder concerns already flagged by the analyzer. They never
    # create a concern or select a procedure on their own.
    clarity_deficit = max(0.0, 6.0 - float(analysis.skin_clarity_score))
    youth_deficit = max(0.0, 6.0 - float(analysis.youthfulness_score))
    concerns = [concern for _index, concern in sorted(
        enumerate(concerns),
        key=lambda pair: (
            -(
                clarity_deficit if pair[1] in CLARITY_CONCERNS else
                youth_deficit if pair[1] == 'fine_lines' else 0.0
            ),
            pair[0],
        ),
    )]
    service_slugs = {slug for concern in concerns for slug in SERVICE_MATCHES.get(concern, ())}
    product_slugs = {slug for concern in concerns for slug in PRODUCT_MATCHES.get(concern, ())}
    product_slugs.add('sunscreen-spf50')
    services_by_slug = {
        item.slug: item for item in SiteService.objects.filter(is_active=True, slug__in=service_slugs)
    }
    products_by_slug = {
        item.slug: item for item in SiteProduct.objects.filter(is_active=True, slug__in=product_slugs)
    }
    services = _matched_items(concerns, SERVICE_MATCHES, services_by_slug, 'service', 3)
    products = _matched_items(concerns, PRODUCT_MATCHES, products_by_slug, 'product', 3)
    if len(products) < 3 and 'sunscreen-spf50' in products_by_slug and not any(
        product['slug'] == 'sunscreen-spf50' for product in products
    ):
        products.append(_catalog_item(products_by_slug['sunscreen-spf50'], 'product', 'general'))

    selected_service_concerns = {service['slug']: service['matched_concern'] for service in services}
    packages = []
    if selected_service_concerns:
        package_qs = (
            SitePackage.objects.filter(
                is_active=True, services__is_active=True,
                services__slug__in=selected_service_concerns,
            )
            .distinct()
            .prefetch_related('services', 'price_options')
        )
        for package in package_qs:
            concern = next((
                selected_service_concerns[service.slug]
                for service in package.services.all()
                if service.slug in selected_service_concerns and service.is_active
            ), None)
            if concern:
                packages.append(_catalog_item(package, 'package', concern))
            if len(packages) >= 2:
                break

    next_steps = [NEXT_STEPS[concern] for concern in concerns[:3]]
    if float(analysis.skin_clarity_score) < 6:
        next_steps.append('امتیاز شفافیت پوست پایین‌تر است؛ کیفیت نور عکس و وضعیت پوست را با متخصص بررسی کنید.')
    if float(analysis.youthfulness_score) < 6:
        next_steps.append('امتیاز جوانی چهره یک برآورد تصویری است؛ درباره نگرانی‌های واقعی خود مشورت کنید.')
    if not next_steps:
        next_steps.append('برای مراقبت روزانه، ضدآفتاب و روتین ملایم متناسب با پوست خود را بررسی کنید.')
    summary = (
        'بر اساس تصویر، این موارد برای بررسی بیشتر پیشنهاد می‌شوند: '
        + '، '.join(CONCERN_LABELS[concern] for concern in concerns[:3]) + '.'
        if concerns else 'در این تصویر مشکل مشخصی ثبت نشده است؛ مراقبت روزانه را ادامه دهید.'
    )
    return {
        'summary': summary,
        'next_steps': next_steps,
        'services': services,
        'products': products,
        'packages': packages,
        'disclaimer': 'این نتیجه برآورد تصویری است و تشخیص پزشکی نیست. پیش از درمان کلینیکی با پزشک مشورت کنید.',
    }
