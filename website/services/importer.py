import html
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Iterable

from django.db import transaction
from django.utils.text import slugify

from ..models import (
    SitePackage,
    SitePackagePriceOption,
    SiteProduct,
    SiteService,
    SiteSettings,
    TeamMember,
    Testimonial,
)
from .pricing import get_website_dashboard_rate, usd_price_from_toman
from .sync import fetch_website_rate

BASE_URL = 'https://barancliniccenter.com'
PERSIAN_DIGITS = str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩', '01234567890123456789')
MONEY_RE = re.compile(r'[۰-۹٠-٩0-9][۰-۹٠-٩0-9٬,\. ]{2,}')


@dataclass
class WebsiteImportResult:
    services: int = 0
    packages: int = 0
    package_options: int = 0
    products: int = 0
    team_members: int = 0
    testimonials: int = 0


def _text(value: str) -> str:
    value = re.sub(r'<script[\s\S]*?</script>|<style[\s\S]*?</style>', ' ', value, flags=re.I)
    value = re.sub(r'<[^>]+>', ' ', value)
    return re.sub(r'\s+', ' ', html.unescape(value)).strip()


def _source_url(path: str) -> str:
    return urllib.parse.urljoin(BASE_URL, path)


def _fetch(path: str, timeout: int = 15) -> str:
    request = urllib.request.Request(
        _source_url(path),
        headers={'User-Agent': 'SefroClinicWebsiteImporter/1.0', 'Accept': 'text/html'},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:  # nosec B310
        return response.read().decode('utf-8', errors='replace')


def parse_money(value: str) -> Decimal | None:
    """Parse Persian/Arabic/Latin site money text into whole Toman."""
    value = value.translate(PERSIAN_DIGITS).replace('٬', '').replace(',', '').replace(' ', '')
    match = re.search(r'\d+(?:\.\d+)?', value)
    if not match:
        return None
    try:
        return Decimal(match.group())
    except InvalidOperation:
        return None


def _money_values(fragment: str) -> list[Decimal]:
    span_values = [
        amount for amount in (
            parse_money(value)
            for value in re.findall(r'<span[^>]*>([^<]*)</span>', fragment, re.I)
        )
        if amount is not None
    ]
    if span_values:
        return span_values
    visible_text = _text(fragment)
    return [amount for amount in (parse_money(x) for x in MONEY_RE.findall(visible_text)) if amount is not None]


def _first(pattern: str, fragment: str, flags=re.I | re.S) -> str:
    match = re.search(pattern, fragment, flags)
    return _text(match.group(1)) if match else ''


def _image(fragment: str) -> str:
    match = re.search(r'<img[^>]+src="([^"]+)"', fragment, re.I)
    return html.unescape(urllib.parse.urljoin(BASE_URL, match.group(1))) if match else ''


def _category(source_category: str, name: str) -> str:
    source = f'{source_category} {name}'
    if 'مو' in source or 'hair' in source.lower():
        return SiteService.Category.HAIR
    if 'لیزر' in source or 'بدن' in source or 'body' in source.lower():
        return SiteService.Category.BODY
    if 'فیشیال' in source or 'پوست' in source or 'facial' in source.lower():
        return SiteService.Category.SKIN
    return SiteService.Category.FACE


def _service_rows(source: str) -> Iterable[dict]:
    pattern = re.compile(r'<a[^>]+href="(/services/[^"#?]+)"[^>]*>([\s\S]*?)</a>', re.I)
    for order, match in enumerate(pattern.finditer(source)):
        fragment = match.group(2)
        name = _first(r'<h3[^>]*>([\s\S]*?)</h3>', fragment)
        description = _first(r'<p[^>]*>([\s\S]*?)</p>', fragment)
        if not name:
            continue
        prices = _money_values(fragment)
        if not prices:
            continue
        category = _first(r'<span[^>]*>([^<]+)</span>', fragment)
        yield {
            'slug': match.group(1).rsplit('/', 1)[-1],
            'name': name,
            'description': description,
            'price': prices[-1],
            'is_from_price': bool(re.search(r'\bاز\b', _text(fragment))),
            'source_category': category,
            'image_url': _image(fragment),
            'source_url': _source_url(match.group(1)),
            'sort_order': order,
        }


def _option_row(fragment: str, order: int) -> dict | None:
    values = _money_values(fragment)
    if not values:
        return None
    label = _first(r'<div[^>]*>([\s\S]*?)</div>\s*(?:<svg|<span)', fragment)
    label = label or _text(fragment).split(str(values[-1]))[0].strip()
    normalized = label.translate(PERSIAN_DIGITS)
    count_match = re.search(r'(\d+)\s*جلسه', normalized)
    gift_match = re.search(r'\+\s*(\d+)\s*جلسه\s*هدیه', normalized)
    return {
        'label': label[:180],
        'session_count': int(count_match.group(1)) if count_match else (1 if 'تک جلسه' in label else None),
        'gift_session_count': int(gift_match.group(1)) if gift_match else 0,
        'price': values[-1],
        'sort_order': order,
    }


def _package_rows(source: str) -> Iterable[dict]:
    headings = list(re.finditer(r'<h3[^>]*>([\s\S]*?)</h3>', source, re.I))
    for order, heading in enumerate(headings):
        end = headings[order + 1].start() if order + 1 < len(headings) else len(source)
        fragment = source[heading.start():end]
        options = []
        for option_order, li in enumerate(re.findall(r'<li[^>]*>([\s\S]*?)</li>', fragment, re.I)):
            option = _option_row(li, option_order)
            if option:
                options.append(option)
        if not options:
            standalone = [
                _option_row(f'<div>{label}</div><span>{money}</span>', 0)
                for label, money in re.findall(
                    r'<p[^>]*>([\s\S]*?جلسه[\s\S]*?)</p>\s*<p[^>]*>\s*<span[^>]*>([^<]+)</span>',
                    fragment, re.I,
                )
            ]
            options.extend(option for option in standalone if option)
        if not options:
            continue
        name = _text(heading.group(1))
        tagline = _first(r'<p[^>]*>([\s\S]*?)</p>', fragment)
        slug = slugify(name, allow_unicode=True) or f'baran-package-{order + 1}'
        yield {
            'slug': slug,
            'name': name[:120],
            'tagline': tagline[:180],
            'badge': 'پیشنهاد ویژه' if 'پیشنهاد ویژه' in _text(fragment) else '',
            'options': options,
            'source_url': _source_url('/packages'),
            'sort_order': order,
        }


def _product_rows(source: str) -> Iterable[dict]:
    pattern = re.compile(r'<a[^>]+href="(/products/[^"#?]+)"[^>]*>([\s\S]*?)</a>', re.I)
    for order, match in enumerate(pattern.finditer(source)):
        fragment = match.group(2)
        headings = re.findall(r'<h[234][^>]*>([\s\S]*?)</h[234]>', fragment, re.I)
        name = _text(headings[0]) if headings else ''
        description = _first(r'<p[^>]*>([\s\S]*?)</p>', fragment)
        prices = _money_values(fragment)
        if name and prices:
            yield {
                'slug': match.group(1).rsplit('/', 1)[-1], 'name': name,
                'description': description, 'price': prices[-1],
                'image_url': _image(fragment), 'source_url': _source_url(match.group(1)),
                'sort_order': order,
            }


def _about_data(about_source: str, home_source: str) -> dict:
    numbers = re.findall(r'([۰-۹٠-٩0-9]+\+?|[۰-۹٠-٩0-9]+٪)', _text(about_source))
    stats = {}
    labels = ['experience_years', 'happy_customers', 'awards', 'satisfaction_percent']
    for label, number in zip(labels, numbers[:4]):
        stats[label] = number
    images = re.findall(r'<img[^>]+src="([^"]+)"[^>]*>', about_source, re.I)
    return {
        'address': _first(r'(تهران\s*—[\s\S]{0,180}?)(?:۰۹|09)', home_source),
        'phone_numbers': re.findall(r'09\d{9}', home_source.translate(PERSIAN_DIGITS)),
        'working_hours': _first(r'(شنبه\s*تا\s*پنجشنبه\s*[^<\n]+)', home_source),
        'about_title': _first(r'<h1[^>]*>([\s\S]*?)</h1>', about_source),
        'about_text': _first(r'(ما باور داریم[\s\S]{0,500}?)(?:<|</p>)', about_source),
        'statistics': stats,
        'hero_image_url': html.unescape(urllib.parse.urljoin(BASE_URL, images[0])) if images else '',
        'about_image_url': html.unescape(urllib.parse.urljoin(BASE_URL, images[1])) if len(images) > 1 else '',
    }


def _usd(toman: Decimal, rate: Decimal) -> Decimal:
    return usd_price_from_toman(toman, rate)


def import_website_catalog(rate: Decimal | None = None) -> WebsiteImportResult:
    """Fetch and atomically upsert the public Baran Clinic website catalog."""
    services_source = _fetch('/services')
    packages_source = _fetch('/packages')
    products_source = _fetch('/products')
    home_source = _fetch('/')
    about_source = _fetch('/about')
    service_rows = list(_service_rows(services_source))
    package_rows = list(_package_rows(packages_source))
    product_rows = list(_product_rows(products_source))
    if not service_rows or not package_rows or not product_rows:
        raise ValueError('The live website returned an incomplete catalog.')
    if rate is None:
        rate, _ = fetch_website_rate()
    if rate is None:
        rate = get_website_dashboard_rate()
    if rate is None or rate <= 0:
        raise ValueError('A valid exchange rate is required for the initial website import.')

    result = WebsiteImportResult()
    with transaction.atomic():
        seen_services = set()
        for row in service_rows:
            seen_services.add(row['slug'])
            if SiteService.objects.filter(slug=row['slug'], is_manually_managed=True).exists():
                continue
            defaults = {
                'name': row['name'], 'category': _category(row['source_category'], row['name']),
                'source_category': row['source_category'], 'short_description': row['description'][:255],
                'description': row['description'], 'price': row['price'],
                'price_usd': _usd(row['price'], rate), 'is_from_price': row['is_from_price'],
                'image_url': row['image_url'], 'source_url': row['source_url'],
                'is_active': True, 'sort_order': row['sort_order'],
            }
            SiteService.objects.update_or_create(slug=row['slug'], defaults=defaults)
        SiteService.objects.filter(is_manually_managed=False).exclude(slug__in=seen_services).update(is_active=False)
        result.services = len(seen_services)

        seen_packages = set()
        seen_options = set()
        for row in package_rows:
            seen_packages.add(row['slug'])
            existing_package = SitePackage.objects.filter(slug=row['slug']).first()
            if existing_package and existing_package.is_manually_managed:
                seen_options.update(existing_package.price_options.values_list('pk', flat=True))
                continue
            first = row['options'][0]
            package, _ = SitePackage.objects.update_or_create(
                slug=row['slug'],
                defaults={
                    'name': row['name'], 'tagline': row['tagline'], 'badge': row['badge'],
                    'price': first['price'], 'price_usd': _usd(first['price'], rate),
                    'original_price': None, 'original_price_usd': None,
                    'is_active': True, 'source_url': row['source_url'], 'sort_order': row['sort_order'],
                },
            )
            package.price_options.update(is_active=False)
            for option in row['options']:
                option_obj, _ = SitePackagePriceOption.objects.update_or_create(
                    package=package, label=option['label'],
                    defaults={
                        'session_count': option['session_count'],
                        'gift_session_count': option['gift_session_count'],
                        'price': option['price'], 'price_usd': _usd(option['price'], rate),
                        'source_url': row['source_url'], 'sort_order': option['sort_order'],
                        'is_active': True,
                    },
                )
                seen_options.add(option_obj.pk)
        SitePackage.objects.filter(is_manually_managed=False).exclude(slug__in=seen_packages).update(is_active=False)
        SitePackagePriceOption.objects.filter(package__is_manually_managed=False).exclude(pk__in=seen_options).update(is_active=False)
        result.packages = len(seen_packages)
        result.package_options = len(seen_options)

        seen_products = set()
        for row in product_rows:
            seen_products.add(row['slug'])
            if SiteProduct.objects.filter(slug=row['slug'], is_manually_managed=True).exists():
                continue
            SiteProduct.objects.update_or_create(
                slug=row['slug'],
                defaults={
                    'name': row['name'], 'short_description': row['description'][:255],
                    'price': row['price'], 'price_usd': _usd(row['price'], rate),
                    'image_url': row['image_url'], 'source_url': row['source_url'],
                    'is_active': True, 'sort_order': row['sort_order'],
                },
            )
        SiteProduct.objects.filter(is_manually_managed=False).exclude(slug__in=seen_products).update(is_active=False)
        result.products = len(seen_products)

        if not SiteSettings.objects.filter(singleton_key='default', is_manually_managed=True).exists():
            SiteSettings.objects.update_or_create(singleton_key='default', defaults=_about_data(about_source, home_source))

        team = TeamMember.objects.filter(source_key='import:team-main').first()
        if team is None:
            team = TeamMember.objects.filter(name='دکتر بهدخت سراجی', source_key__isnull=True).first()
        if team is None:
            team = TeamMember.objects.create(
                source_key='import:team-main', name='دکتر بهدخت سراجی',
                role='متخصص پوست و زیبایی', bio='', is_active=True, sort_order=0,
            )
        elif not team.is_manually_managed:
            team.source_key = 'import:team-main'
            team.name = 'دکتر بهدخت سراجی'
            team.role = 'متخصص پوست و زیبایی'
            team.bio = ''
            team.is_active = True
            team.sort_order = 0
            team.save()
        elif team.source_key is None:
            team.source_key = 'import:team-main'
            team.save(update_fields=['source_key'])
        result.team_members = 1 if team else 0
        testimonials = [
            ('سارا احمدی', 'مشتری وفادار', 'من از خدمات بوتاکس کلینیک زیبا بسیار راضی هستم. نتیجه عالی بود و پرسنل بسیار حرفه‌ای هستند.'),
            ('مریم حسینی', 'مشتری وفادار', 'لیزر موهای زائد در این کلینیک واقعاً تأثیرگذار بود. بعد از 6 جلسه کاملاً راضی هستم.'),
            ('نیلوفر کریمی', 'مشتری وفادار', 'پاکسازی پوست صورتم را اینجا انجام دادم و پوستم خیلی شفاف و نرم شد. حتماً دوباره مراجعه می‌کنم.'),
        ]
        for order, (name, label, text) in enumerate(testimonials):
            source_key = f'import:testimonial:{order}'
            testimonial = Testimonial.objects.filter(source_key=source_key).first()
            if testimonial is None:
                testimonial = Testimonial.objects.filter(
                    customer_name=name, text=text, source_key__isnull=True,
                ).first()
            if testimonial is None:
                Testimonial.objects.create(
                    source_key=source_key, customer_name=name, label=label,
                    text=text, is_active=True, sort_order=order,
                )
            elif not testimonial.is_manually_managed:
                testimonial.source_key = source_key
                testimonial.customer_name = name
                testimonial.label = label
                testimonial.text = text
                testimonial.is_active = True
                testimonial.sort_order = order
                testimonial.save()
            elif testimonial.source_key is None:
                testimonial.source_key = source_key
                testimonial.save(update_fields=['source_key'])
        result.testimonials = len(testimonials)
    return result
