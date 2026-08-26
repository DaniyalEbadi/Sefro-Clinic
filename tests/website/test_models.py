from decimal import Decimal

from django.db import IntegrityError, transaction
from django.test import TestCase

from website.models import (
    ContactMessage,
    SitePackage,
    SiteProduct,
    SiteService,
    TeamMember,
    Testimonial,
)


def make_service(**overrides):
    data = {
        'name': 'بوتاکس', 'slug': 'botox', 'category': 'face',
        'short_description': 'جوانسازی صورت', 'price': '2500000.00',
        'duration_label': '30 دقیقه', 'sort_order': 1,
    }
    data.update(overrides)
    return SiteService.objects.create(**data)


def make_package(**overrides):
    data = {
        'name': 'پکیج جوانسازی', 'slug': 'rejuvenation',
        'tier': 'standard', 'price': '6500000.00',
        'original_price': '8000000.00',
    }
    data.update(overrides)
    return SitePackage.objects.create(**data)


def make_product(**overrides):
    data = {
        'name': 'سروم ویتامین C', 'slug': 'vitamin-c-serum',
        'short_description': 'روشن‌کننده', 'price': '450000.00',
    }
    data.update(overrides)
    return SiteProduct.objects.create(**data)


class DiscountCalculationTests(TestCase):
    def test_discount_percent_rounded_correctly(self):
        package = make_package(price='6500000.00', original_price='8000000.00')
        self.assertEqual(package.discount_percent, 19)

    def test_no_original_price_means_zero_discount(self):
        package = make_package(original_price=None)
        self.assertEqual(package.discount_percent, 0)

    def test_equal_prices_mean_zero_discount(self):
        package = make_package(price='5000000.00', original_price='5000000.00')
        self.assertEqual(package.discount_percent, 0)

    def test_price_higher_than_original_never_negative_discount(self):
        package = make_package(price='9000000.00', original_price='8000000.00')
        self.assertEqual(package.discount_percent, 0)

    def test_exact_quarter_discount(self):
        package = make_package(price='7500000.00', original_price='10000000.00')
        self.assertEqual(package.discount_percent, 25)


class ModelBehaviorTests(TestCase):
    def test_service_ordering_respects_sort_order_then_name(self):
        second = make_service(name='آ', slug='a', sort_order=2)
        first = make_service(name='ب', slug='b', sort_order=1)
        listed = list(SiteService.objects.all())
        self.assertEqual(listed, [first, second])

    def test_duplicate_slug_rejected_at_db_level(self):
        make_service()
        with transaction.atomic():
            with self.assertRaises(IntegrityError):
                make_service(slug='botox', name='duplicate')

    def test_string_representations(self):
        service = make_service()
        package = make_package()
        product = SiteProduct.objects.create(name='کرم', slug='cream', price='100000.00')
        member = TeamMember.objects.create(name='دکتر تست')
        testimonial = Testimonial.objects.create(customer_name='مشتری', text='عالی بود')
        message = ContactMessage.objects.create(full_name='علی', phone='09121234567')
        self.assertEqual(str(service), 'بوتاکس')
        self.assertEqual(str(package), 'پکیج جوانسازی')
        self.assertEqual(str(product), 'کرم')
        self.assertEqual(str(member), 'دکتر تست')
        self.assertIn('مشتری', str(testimonial))
        self.assertIn('علی', str(message))

    def test_contact_message_ordering_newest_first(self):
        old = ContactMessage.objects.create(full_name='اول', phone='09120000001')
        new = ContactMessage.objects.create(full_name='دوم', phone='09120000002')
        listed = list(ContactMessage.objects.all())
        self.assertEqual(listed, [new, old])

    def test_money_fields_stay_decimal_from_db(self):
        service = make_service()
        reloaded = SiteService.objects.get(pk=service.pk)
        self.assertIsInstance(reloaded.price, Decimal)

    def test_defaults(self):
        service = make_service()
        package = make_package()
        self.assertTrue(service.is_active)
        self.assertTrue(package.is_active)
        self.assertEqual(package.tier, 'standard')
        self.assertEqual(package.free_service_count, 0)
