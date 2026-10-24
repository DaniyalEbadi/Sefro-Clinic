"""Isolated Liara client for public website service photos only."""

from io import BytesIO
from uuid import uuid4

from django.conf import settings
from PIL import Image, UnidentifiedImageError
from rest_framework.exceptions import ValidationError

IMAGE_FORMATS = {'JPEG': ('jpg', 'image/jpeg'), 'PNG': ('png', 'image/png'), 'WEBP': ('webp', 'image/webp')}


def upload_service_image(service, uploaded_file):
    if not settings.LIARA_ACCESS_KEY or not settings.LIARA_SECRET_KEY:
        raise RuntimeError('Liara website object-storage credentials are not configured.')
    if uploaded_file.size > settings.LIARA_WEBSITE_MAX_IMAGE_MB * 1024 * 1024:
        raise ValidationError({'image': 'Image exceeds the 5 MB limit.'})
    if not uploaded_file.size:
        raise ValidationError({'image': 'Image is empty.'})
    try:
        uploaded_file.seek(0)
        content = uploaded_file.read()
        with Image.open(BytesIO(content)) as image:
            image.verify()
        with Image.open(BytesIO(content)) as image:
            image_format = image.format
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise ValidationError({'image': 'Upload a valid JPEG, PNG, or WebP image.'}) from exc
    if image_format not in IMAGE_FORMATS:
        raise ValidationError({'image': 'Upload a valid JPEG, PNG, or WebP image.'})

    extension, content_type = IMAGE_FORMATS[image_format]
    key = f'{settings.LIARA_WEBSITE_PREFIX}/services/{service.slug}/{uuid4().hex}.{extension}'
    import boto3

    client = boto3.client(
        's3', endpoint_url=settings.LIARA_WEBSITE_ENDPOINT_URL,
        aws_access_key_id=settings.LIARA_ACCESS_KEY,
        aws_secret_access_key=settings.LIARA_SECRET_KEY,
    )
    client.put_object(
        Bucket=settings.LIARA_WEBSITE_BUCKET, Key=key, Body=content,
        ContentType=content_type, CacheControl='public, max-age=31536000, immutable',
    )
    base_url = settings.LIARA_WEBSITE_PUBLIC_BASE_URL or (
        f'{settings.LIARA_WEBSITE_ENDPOINT_URL}/{settings.LIARA_WEBSITE_BUCKET}'
    )
    return key, f'{base_url}/{key}'
