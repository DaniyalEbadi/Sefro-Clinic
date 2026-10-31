from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from website.management.commands.mirror_website_images import inspect_image, source_path, update_links
from website.models import SiteMediaAsset, SiteProduct, SiteService, SiteSettings
from website.services.importer import _mirrored_url


class WebsiteMediaMirrorTests(TestCase):
    def test_next_image_url_maps_to_original_site_path(self):
        optimized = (
            'https://barancliniccenter.com/_next/image?url=%2Fimages%2Fservices%2F'
            'filler%2520and%2520botax%2Ffacial-botax.jpeg&w=3840&q=75'
        )
        path = '/images/services/filler and botax/facial-botax.jpeg'
        cdn = 'https://storage.c2.liara.site/farabaks3/baran-clinic/site-images/photo.jpeg'
        self.assertEqual(source_path(optimized), path)
        self.assertEqual(_mirrored_url(optimized, {path: cdn}), cdn)
        self.assertIsNone(source_path('https://other.example/images/photo.jpg'))

    def test_mislabeled_product_svg_is_identified_by_content(self):
        svg = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"><rect width="1" height="1"/></svg>'
        self.assertEqual(inspect_image(svg), ('svg', 'image/svg+xml'))
        with self.assertRaises(ValueError):
            inspect_image(b'<svg xmlns="http://www.w3.org/2000/svg"><script/></svg>')

    def test_catalog_links_switch_to_liara_and_keep_manual_uploads(self):
        service = SiteService.objects.create(
            name='Botox', slug='botox', category='face', price=Decimal('100'),
            image_url='https://barancliniccenter.com/images/services/botox.jpg',
        )
        manual = SiteService.objects.create(
            name='Manual', slug='manual', category='face', price=Decimal('100'),
            image_url='https://barancliniccenter.com/images/services/botox.jpg',
            image_object_key='baran-clinic/services/manual/upload.jpg',
        )
        product = SiteProduct.objects.create(
            name='Serum', slug='serum', price=Decimal('100'),
            image_url='https://barancliniccenter.com/images/products/serum.jpg',
        )
        site_settings = SiteSettings.objects.create(
            hero_image_url='https://barancliniccenter.com/images/hero.webp',
        )
        links = {
            '/images/services/botox.jpg': ('baran-clinic/site-images/botox.jpg', 'https://cdn.example/botox.jpg'),
            '/images/products/serum.jpg': ('baran-clinic/site-images/serum.jpg', 'https://cdn.example/serum.jpg'),
            '/images/hero.webp': ('baran-clinic/site-images/hero.webp', 'https://cdn.example/hero.webp'),
        }
        update_links(links)
        service.refresh_from_db()
        manual.refresh_from_db()
        product.refresh_from_db()
        site_settings.refresh_from_db()
        self.assertEqual(service.image_url, 'https://cdn.example/botox.jpg')
        self.assertEqual(service.image_object_key, links['/images/services/botox.jpg'][0])
        self.assertEqual(manual.image_object_key, 'baran-clinic/services/manual/upload.jpg')
        self.assertEqual(product.image_url, 'https://cdn.example/serum.jpg')
        self.assertEqual(site_settings.hero_image_url, 'https://cdn.example/hero.webp')

    def test_public_media_list_exposes_stored_links(self):
        SiteMediaAsset.objects.create(
            source_path='/images/hero.webp', source_url='https://barancliniccenter.com/images/hero.webp',
            public_url='https://storage.c2.liara.site/farabaks3/baran-clinic/site-images/hero.webp',
            object_key='baran-clinic/site-images/hero.webp', content_type='image/webp',
            byte_size=10, sha256='a' * 64,
        )
        response = APIClient().get('/api/v2/media/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 1)
        self.assertEqual(response.data['results'][0]['source_path'], '/images/hero.webp')
