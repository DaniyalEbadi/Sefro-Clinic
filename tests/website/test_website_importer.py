from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from rest_framework import status

from tests.helpers import employee_client
from tests.website.test_models import make_package, make_service
from website.models import SitePackagePriceOption, SiteSettings
from website.services.importer import import_website_catalog, parse_money
from website.services.sync import sync_website_prices

SERVICES_HTML = (
    '<a href="/services/one"><img src="/one.jpg"><span>فیلر و بوتاکس</span>'
    '<h3>خدمت اول</h3><p>توضیح خدمت</p><span>۱٬۸۰۰٬۰۰۰</span> تومان</a>'
    '<a href="/services/two"><img src="/two.jpg"><span>لیزر بانوان</span>'
    '<h3>خدمت دوم</h3><p>از توضیح دوم</p><span>از ۲٬۰۰۰٬۰۰۰</span> تومان</a>'
)
PACKAGES_HTML = (
    '<h3>پکیج اول</h3><p>توضیح پکیج</p><ul>'
    '<li><div>تک جلسه</div><span>۱٬۵۰۰٬۰۰۰</span></li>'
    '<li><div>هر جلسه با رزرو پکیج ۳ جلسه‌ای</div><span>۴٬۰۰۰٬۰۰۰</span></li>'
    '</ul>'
)
PRODUCTS_HTML = (
    '<a href="/products/serum"><h3>سروم</h3><p>محصول مراقبتی</p>'
    '<span>۴۵۰٬۰۰۰</span> تومان</a>'
)
ABOUT_HTML = '<h1>درباره کلینیک</h1><p>ما باور داریم که زیبایی تنها ظاهر نیست.</p><img src="/about.jpg">'
HOME_HTML = 'تهران — آدرس کلینیک ۰۹۱۰۰۳۰۰۸۷۵ شنبه تا پنجشنبه ۹ تا ۲۰'


class WebsiteImporterTests(TestCase):
    @patch('website.services.importer.fetch_website_rate', return_value=(Decimal('100000'), 'test'))
    @patch('website.services.importer._fetch')
    def test_import_is_idempotent_and_deactivates_missing_records(self, fetch, rate):
        old = make_service(name='قدیمی', slug='old', category='face')
        pages = {
            '/services': SERVICES_HTML, '/packages': PACKAGES_HTML,
            '/products': PRODUCTS_HTML, '/about': ABOUT_HTML, '/': HOME_HTML,
        }
        fetch.side_effect = lambda path: pages[path]

        result = import_website_catalog()
        self.assertEqual(result.services, 2)
        self.assertEqual(result.packages, 1)
        self.assertEqual(result.package_options, 2)
        self.assertEqual(result.products, 1)
        self.assertEqual(SitePackagePriceOption.objects.count(), 2)
        self.assertEqual(SiteSettings.objects.count(), 1)
        self.assertFalse(old.__class__.objects.get(pk=old.pk).is_active)
        self.assertEqual(import_website_catalog().services, 2)
        self.assertEqual(old.__class__.objects.filter(slug='one').count(), 1)

    def test_parse_persian_toman_and_decimal(self):
        self.assertEqual(parse_money('از ۷۹۹٬۰۰۰ تومان'), Decimal('799000'))
        self.assertEqual(parse_money('800.5 تومان'), Decimal('800.5'))


class WebsitePackageOptionTests(TestCase):
    def test_sync_rounds_package_options_up(self):
        package = make_package()
        option = SitePackagePriceOption.objects.create(
            package=package, label='تک جلسه', price='1.00', price_usd='0.01',
        )
        with patch('website.services.sync.ExternalExchangeRateProvider.get_usd_to_toman_rate', return_value=Decimal('79999.9')):
            with patch('website.services.sync.BrsApiExchangeRateProvider.get_usd_to_toman_rate', return_value=None):
                sync_website_prices()
        option.refresh_from_db()
        self.assertEqual(option.price, Decimal('800.00'))

    def test_employee_can_update_package_option(self):
        package = make_package()
        option = SitePackagePriceOption.objects.create(
            package=package, label='تک جلسه', price='100000.00', price_usd='1.00',
        )
        with patch('website.views.get_current_usd_to_toman_rate', return_value=Decimal('100000')):
            response = employee_client().patch(
                f'/api/v2/site-dashboard/package-price-options/{option.pk}/',
                {'price_usd': '2.00'}, format='json',
            )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        option.refresh_from_db()
        self.assertEqual(option.price, Decimal('200000.00'))
