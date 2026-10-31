"""Mirror public Baran website images to the dedicated Liara bucket prefix."""

import hashlib
import io
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from html.parser import HTMLParser

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from PIL import Image, UnidentifiedImageError

from website.models import SiteMediaAsset, SiteProduct, SiteService, SiteSettings, TeamMember

BASE = 'https://barancliniccenter.com'
ROOTS = ('/', '/services', '/packages', '/products', '/about', '/contact')
DETAIL = re.compile(r'^/(?:services|packages|products)/[^/?#]+/?$')
FORMATS = {'JPEG': ('jpg', 'image/jpeg'), 'PNG': ('png', 'image/png'), 'WEBP': ('webp', 'image/webp')}
MAX_BYTES = 15 * 1024 * 1024


class PageImages(HTMLParser):
    def __init__(self):
        super().__init__()
        self.images = set()
        self.links = set()

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'img' and attrs.get('src'):
            self.images.add(attrs['src'])
        elif tag == 'link' and attrs.get('as') == 'image' and attrs.get('href'):
            self.images.add(attrs['href'])
        elif tag == 'a' and attrs.get('href'):
            path = urllib.parse.urlsplit(attrs['href']).path
            if DETAIL.fullmatch(path):
                self.links.add(path)


def source_path(url):
    """Resolve Next image optimizer URLs to their original website image path."""
    parsed = urllib.parse.urlsplit(urllib.parse.urljoin(BASE, url))
    if parsed.hostname != 'barancliniccenter.com':
        return None
    path = parsed.path
    if path == '/_next/image':
        path = urllib.parse.parse_qs(parsed.query).get('url', [''])[0]
    path = urllib.parse.unquote(path)
    if not path.startswith('/images/') or '..' in path.split('/'):
        return None
    return path


def source_url(path):
    return BASE + urllib.parse.quote(path, safe='/')


def fetch(url):
    request = urllib.request.Request(url, headers={'User-Agent': 'SefroClinicImageMirror/1.0'})
    with urllib.request.urlopen(request, timeout=30) as response:  # nosec B310
        if response.status != 200:
            raise ValueError(f'HTTP {response.status}: {url}')
        content = response.read(MAX_BYTES + 1)
    if len(content) > MAX_BYTES:
        raise ValueError(f'Image exceeds 15 MB: {url}')
    return content


def discover():
    pages = {}
    for path in ROOTS:
        page = PageImages()
        page.feed(fetch(BASE + path).decode('utf-8', errors='replace'))
        pages[path] = page
    details = sorted(set().union(*(page.links for page in pages.values())))
    for path in details:
        page = PageImages()
        page.feed(fetch(BASE + path).decode('utf-8', errors='replace'))
        pages[path] = page
    paths = {source_path(image) for page in pages.values() for image in page.images}
    paths.discard(None)
    return sorted(paths), len(pages)


def inspect_image(content):
    try:
        with Image.open(io.BytesIO(content)) as image:
            image.verify()
        with Image.open(io.BytesIO(content)) as image:
            if image.format in FORMATS:
                return FORMATS[image.format]
    except (UnidentifiedImageError, OSError, ValueError):
        pass
    # The live product .jpg URLs currently contain SVG placeholder artwork.
    # Keep the real format and MIME type so the mirrored URLs can load.
    if b'<!DOCTYPE' in content.upper() or b'<script' in content.lower():
        raise ValueError('Unsafe SVG image')
    try:
        root = ET.fromstring(content)
    except ET.ParseError as exc:
        raise ValueError('Source is not a supported image') from exc
    if root.tag != '{http://www.w3.org/2000/svg}svg':
        raise ValueError('Source is not a supported image')
    for element in root.iter():
        if element.tag.rsplit('}', 1)[-1] in {'script', 'foreignObject'}:
            raise ValueError('Unsafe SVG image')
        if any(name.rsplit('}', 1)[-1] == 'href' for name in element.attrib):
            raise ValueError('SVG with external references is not supported')
    return 'svg', 'image/svg+xml'


def public_url(key):
    base = settings.LIARA_WEBSITE_PUBLIC_BASE_URL or (
        f'{settings.LIARA_WEBSITE_ENDPOINT_URL}/{settings.LIARA_WEBSITE_BUCKET}'
    )
    return f'{base.rstrip("/")}/{key}'


def update_links(links):
    """Switch only matching source URLs; preserve manually uploaded images."""
    for service in SiteService.objects.exclude(image_url='').iterator():
        path = source_path(service.image_url)
        if path in links and not service.image_object_key:
            service.image_url = links[path][1]
            service.image_object_key = links[path][0]
            service.save(update_fields=['image_url', 'image_object_key'])
    for model in (SiteProduct, TeamMember):
        for item in model.objects.exclude(image_url='').iterator():
            path = source_path(item.image_url)
            if path in links:
                item.image_url = links[path][1]
                item.save(update_fields=['image_url'])
    for site_settings in SiteSettings.objects.all().iterator():
        changed = []
        for field in ('hero_image_url', 'about_image_url', 'logo_url'):
            path = source_path(getattr(site_settings, field))
            if path in links:
                setattr(site_settings, field, links[path][1])
                changed.append(field)
        if changed:
            site_settings.save(update_fields=changed + ['updated_at'])


class Command(BaseCommand):
    help = 'Mirror all public website images to farabaks3/baran-clinic/ and link Site API records.'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='Discover and validate without uploading or writing.')

    def handle(self, *args, **options):
        try:
            paths, page_count = discover()
            if not paths:
                raise ValueError('No website images were discovered')
            assets = []
            for path in paths:
                content = fetch(source_url(path))
                extension, content_type = inspect_image(content)
                digest = hashlib.sha256(content).hexdigest()
                key = f'{settings.LIARA_WEBSITE_PREFIX}/site-images/{digest[:2]}/{digest}.{extension}'
                assets.append((path, content, content_type, digest, key))
            self.stdout.write(f'Found {len(assets)} valid images on {page_count} pages; '
                              f'{sum(a[2] == "image/svg+xml" for a in assets)} are SVG placeholders.')
            if options['dry_run']:
                return
            if not settings.LIARA_ACCESS_KEY or not settings.LIARA_SECRET_KEY:
                raise ValueError('LIARA_ACCESS_KEY and LIARA_SECRET_KEY are required')
            import boto3
            from botocore.config import Config
            from botocore.exceptions import ClientError

            client = boto3.client(
                's3', endpoint_url=settings.LIARA_WEBSITE_ENDPOINT_URL,
                aws_access_key_id=settings.LIARA_ACCESS_KEY,
                aws_secret_access_key=settings.LIARA_SECRET_KEY,
                config=Config(s3={'addressing_style': 'path'}),
            )
            existing = {a.source_path: a for a in SiteMediaAsset.objects.all()}
            links = {}
            for path, content, content_type, digest, key in assets:
                prior = existing.get(path)
                url = public_url(key)
                if prior is None or prior.sha256 != digest or prior.object_key != key:
                    try:
                        current = client.head_object(Bucket=settings.LIARA_WEBSITE_BUCKET, Key=key)
                        uploaded = current['ContentLength'] == len(content)
                    except ClientError as exc:
                        if exc.response['Error']['Code'] not in {'404', 'NoSuchKey', 'NotFound'}:
                            raise
                        uploaded = False
                    if not uploaded:
                        client.put_object(
                            Bucket=settings.LIARA_WEBSITE_BUCKET, Key=key, Body=content,
                            ContentType=content_type, CacheControl='public, max-age=31536000, immutable',
                        )
                request = urllib.request.Request(url, method='GET')
                with urllib.request.urlopen(request, timeout=15) as response:  # nosec B310
                    if response.status != 200 or not response.headers.get('Content-Type', '').startswith('image/'):
                        raise ValueError(f'Mirrored image is not publicly readable: {path}')
                links[path] = (key, url)
            with transaction.atomic():
                for path, content, content_type, digest, key in assets:
                    SiteMediaAsset.objects.update_or_create(source_path=path, defaults={
                        'source_url': source_url(path), 'public_url': links[path][1],
                        'object_key': key, 'content_type': content_type,
                        'byte_size': len(content), 'sha256': digest,
                    })
                update_links(links)
            self.stdout.write(self.style.SUCCESS(f'Mirrored {len(assets)} images into '
                                                 f'{settings.LIARA_WEBSITE_BUCKET}/{settings.LIARA_WEBSITE_PREFIX}/.'))
        except Exception as exc:
            raise CommandError(str(exc)) from exc
