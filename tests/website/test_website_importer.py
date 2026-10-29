from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from rest_framework import status

from tests.helpers import website_manager_client
from tests.website.test_models import make_package, make_service
from website.models import (
    SitePackage,
    SitePackagePriceOption,
    SiteProduct,
    SiteService,
    SiteSettings,
    TeamMember,
    Testimonial,
)
from website.services.importer import _team_rows, _testimonial_rows, import_website_catalog, parse_money
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
PRODUCT_DETAIL_HTML = '<h1>سروم</h1><p>محصول مراقبتی</p><p>توضیح کامل محصول و روش استفاده.</p>'
ABOUT_HTML = (
    '<h1>درباره کلینیک</h1><p>ما باور داریم که زیبایی تنها ظاهر نیست.</p>'
    '<img src="/about.jpg"><h2>تیم متخصص ما</h2>'
    '<h3>دکتر اول</h3><p>متخصص پوست</p><p>رزومه</p>'
)
HOME_HTML = (
    'تهران — آدرس کلینیک ۰۹۱۰۰۳۰۰۸۷۵ شنبه تا پنجشنبه ۹ تا ۲۰'
    '<p>“<!-- -->خدمت خوب بود.<!-- -->”</p><div><p>مراجع اول</p><p>مراجع</p></div>'
    '<p>“<!-- -->خدمت دوم خوب بود.<!-- -->”</p><div><p>مراجع دوم</p><p>مراجع</p></div>'
    '<p>“<!-- -->خدمت سوم خوب بود.<!-- -->”</p><div><p>مراجع سوم</p><p>مراجع</p></div>'
)
CONTACT_HTML = (
    '<h3>آدرس</h3><p>تهران — آدرس کلینیک</p>'
    '<h3>تلفن</h3><p>۰۹۱۰۰۳۰۰۸۷۵</p>'
    '<h3>ساعات کاری</h3><p>شنبه تا پنجشنبه ۹ تا ۲۰</p>'
)


class WebsiteImporterTests(TestCase):
    @patch('website.services.importer.fetch_website_rate', return_value=(Decimal('100000'), 'test'))
    @patch('website.services.importer._fetch')
    def test_import_preserves_dashboard_managed_service_pages(self, fetch, _rate):
        manual = make_service(slug='one', name='نسخه ویرایش شده', is_manually_managed=True,
                              image_url='https://cdn.example.com/custom.png')
        custom = make_service(slug='custom', name='صفحه جدید', is_manually_managed=True)
        pages = {
            '/services': SERVICES_HTML, '/packages': PACKAGES_HTML,
            '/products': PRODUCTS_HTML, '/about': ABOUT_HTML, '/': HOME_HTML,
            '/contact': CONTACT_HTML, '/products/serum': PRODUCT_DETAIL_HTML,
        }
        fetch.side_effect = lambda path: pages[path]
        import_website_catalog()
        manual.refresh_from_db()
        custom.refresh_from_db()
        self.assertEqual(manual.name, 'نسخه ویرایش شده')
        self.assertEqual(manual.image_url, 'https://cdn.example.com/custom.png')
        self.assertTrue(custom.is_active)

    @patch('website.services.importer.fetch_website_rate', return_value=(Decimal('100000'), 'test'))
    @patch('website.services.importer._fetch')
    def test_import_is_idempotent_and_deactivates_missing_records(self, fetch, rate):
        old = make_service(name='قدیمی', slug='old', category='face')
        pages = {
            '/services': SERVICES_HTML, '/packages': PACKAGES_HTML,
            '/products': PRODUCTS_HTML, '/about': ABOUT_HTML, '/': HOME_HTML,
            '/contact': CONTACT_HTML, '/products/serum': PRODUCT_DETAIL_HTML,
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

    def test_team_and_testimonials_are_extracted_from_source(self):
        about = '<section><h2>تیم متخصص ما</h2><h3>دکتر نمونه</h3><p>متخصص پوست</p><p>رزومه</p></section>'
        home = '<p>“<!-- -->خدمت عالی بود.<!-- -->”</p><div><p>مراجع نمونه</p><p>مراجع</p></div>'
        self.assertEqual(list(_team_rows(about))[0]['name'], 'دکتر نمونه')
        self.assertEqual(list(_testimonial_rows(home))[0]['text'], 'خدمت عالی بود.')

    @patch('website.services.importer.fetch_website_rate', return_value=(Decimal('100000'), 'test'))
    @patch('website.services.importer._fetch')
    def test_import_uses_live_team_and_review_copy(self, fetch, _rate):
        about = '<h1>درباره کلینیک</h1><h2>تیم متخصص ما</h2><h3>دکتر نمونه</h3><p>متخصص پوست</p><p>رزومه</p>'
        home = '<p>“<!-- -->خدمت عالی بود.<!-- -->”</p><div><p>مراجع نمونه</p><p>مراجع</p></div>'
        fetch.side_effect = lambda path: {
            '/services': SERVICES_HTML, '/packages': PACKAGES_HTML,
            '/products': PRODUCTS_HTML, '/products/serum': PRODUCT_DETAIL_HTML,
            '/about': about, '/': home, '/contact': CONTACT_HTML,
        }[path]
        result = import_website_catalog()
        self.assertEqual((result.team_members, result.testimonials), (1, 1))
        self.assertEqual(TeamMember.objects.get().name, 'دکتر نمونه')
        self.assertEqual(Testimonial.objects.get().text, 'خدمت عالی بود.')
        import_website_catalog()
        self.assertEqual((TeamMember.objects.count(), Testimonial.objects.count()), (1, 1))

    @patch('website.services.importer.get_website_dashboard_rate', return_value=None)
    @patch('website.services.importer.fetch_website_rate', return_value=(None, ''))
    @patch('website.services.importer._fetch')
    def test_import_preserves_live_toman_without_rate_then_initializes_usd(self, fetch, _rate, _cached):
        fetch.side_effect = lambda path: {
            '/services': SERVICES_HTML, '/packages': PACKAGES_HTML,
            '/products': PRODUCTS_HTML, '/about': ABOUT_HTML, '/': HOME_HTML,
            '/contact': CONTACT_HTML, '/products/serum': PRODUCT_DETAIL_HTML,
        }[path]

        import_website_catalog()
        service = SiteService.objects.get(slug='one')
        package = SitePackage.objects.get()
        option = package.price_options.get(label='تک جلسه')
        product = SiteProduct.objects.get()
        self.assertEqual(product.description, 'توضیح کامل محصول و روش استفاده.')
        self.assertEqual(
            self.client.get('/api/v2/products/serum/').data['description'],
            'توضیح کامل محصول و روش استفاده.',
        )
        self.assertEqual(service.price, Decimal('1800000'))
        self.assertEqual(service.price_usd, Decimal('0'))
        self.assertEqual(package.price_usd, Decimal('0'))
        self.assertEqual(option.price_usd, Decimal('0'))
        self.assertEqual(product.price_usd, Decimal('0'))

        run = sync_website_prices(rate_override=Decimal('100000'))
        self.assertEqual(run.status, 'succeeded')
        for item in (service, package, option, product):
            old_price = item.price
            item.refresh_from_db()
            self.assertEqual(item.price, old_price)
            self.assertGreater(item.price_usd, 0)


class WebsitePackageOptionTests(TestCase):
    def test_sync_rounds_package_options_up(self):
        package = make_package()
        option = SitePackagePriceOption.objects.create(
            package=package, label='تک جلسه', price='1.00', price_usd='0.01',
        )
        with patch('website.services.sync.ExternalExchangeRateProvider.get_usd_to_toman_rate', return_value=Decimal('79999.9')):
            sync_website_prices()
        option.refresh_from_db()
        self.assertEqual(option.price, Decimal('800.00'))

    def test_employee_can_update_package_option(self):
        package = make_package()
        option = SitePackagePriceOption.objects.create(
            package=package, label='تک جلسه', price='100000.00', price_usd='1.00',
        )
        with patch('website.views.get_current_usd_to_toman_rate', return_value=Decimal('100000')):
            response = website_manager_client().patch(
                f'/api/v2/site-dashboard/package-price-options/{option.pk}/',
                {'price_usd': '2.00'}, format='json',
            )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        option.refresh_from_db()
        self.assertEqual(option.price, Decimal('200000.00'))
