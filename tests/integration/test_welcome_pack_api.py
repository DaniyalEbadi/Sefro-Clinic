from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from customers.models import Visit
from finance.models import WelcomePack, WelcomePackItem, WelcomePackUsage
from finance.services import reporting
from finance.services.exchange_rates import set_rate
from finance.services.welcome_pack import WelcomePackError, issue_welcome_pack, validate_welcome_pack_items
from inventory.models import Product
from tests.helpers import admin_client, employee_client, make_admin, make_customer, make_employee


RATE = Decimal('100000')


class WelcomePackAPITests(TestCase):
    packs_url = '/api/finance/welcome-packs/'
    items_url = '/api/finance/welcome-pack-items/'
    usages_url = '/api/finance/welcome-pack-usages/'
    report_url = '/api/finance/reports/welcome-packs/'

    def setUp(self):
        set_rate('USD', 'TOMAN', RATE, effective_at=timezone.now(), source='welcome-pack-test')
        self.admin = make_admin()
        self.client = admin_client()
        self.employee = make_employee(username='welcome_pack_employee')
        self.customer = make_customer()
        self.other_customer = make_customer(mobile_number='09120000019', national_id='000-0000019')
        self.product = Product.objects.create(
            name='Welcome serum', sku='WELCOME-SERUM', unit_price=Decimal('10'),
            cost_usd=Decimal('12.50'), count=Decimal('20'),
        )
        self.other_product = Product.objects.create(
            name='Welcome towel', sku='WELCOME-TOWEL', unit_price=Decimal('5'),
            cost_usd=Decimal('2.00'), count=Decimal('50'),
        )

    def create_pack(self, **overrides):
        payload = {
            'name': 'Starter pack',
            'description': 'First visit gift',
            'items': [
                {'product': self.product.id, 'quantity': '2.000'},
                {'product': self.other_product.id, 'quantity': '1.500'},
            ],
        }
        payload.update(overrides)
        response = self.client.post(self.packs_url, payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        return response

    def test_create_returns_nested_items_and_never_creates_financial_usage(self):
        response = self.create_pack()

        pack = WelcomePack.objects.get(pk=response.data['id'])
        self.assertEqual(pack.created_by_id, self.admin.id)
        self.assertEqual(pack.items.count(), 2)
        self.assertEqual(WelcomePackUsage.objects.count(), 0)
        self.assertEqual(Decimal(response.data['total_cost_usd']), Decimal('28.00'))
        self.assertEqual(Decimal(response.data['total_cost_toman']), Decimal('2800000.00'))
        self.assertEqual(len(response.data['items']), 2)

    def test_create_rejects_bad_items_atomically_and_prevents_creator_spoofing(self):
        response = self.client.post(self.packs_url, {
            'name': 'Invalid pack',
            'created_by': self.employee.id,
            'items': [{'product': 999999, 'quantity': '1'}],
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(WelcomePack.objects.filter(name='Invalid pack').exists())

        created = self.create_pack(name='Creator pack', created_by=self.employee.id)
        self.assertNotEqual(created.data['created_by'], self.employee.id)

    def test_update_replaces_items_only_when_supplied_and_preserves_atomicity(self):
        pack_id = self.create_pack().data['id']
        partial = self.client.patch(
            f'{self.packs_url}{pack_id}/', {'description': 'Updated'}, format='json',
        )
        self.assertEqual(partial.status_code, status.HTTP_200_OK, partial.data)
        self.assertEqual(WelcomePack.objects.get(pk=pack_id).items.count(), 2)

        replacement = self.client.patch(f'{self.packs_url}{pack_id}/', {
            'items': [{'product': self.other_product.id, 'quantity': '3.000'}],
        }, format='json')
        self.assertEqual(replacement.status_code, status.HTTP_200_OK, replacement.data)
        self.assertEqual(WelcomePackItem.objects.filter(welcome_pack_id=pack_id).count(), 1)

        rejected = self.client.patch(f'{self.packs_url}{pack_id}/', {
            'name': 'Must not persist', 'items': [{'product': 999999, 'quantity': '1'}],
        }, format='json')
        self.assertEqual(rejected.status_code, status.HTTP_400_BAD_REQUEST)
        pack = WelcomePack.objects.get(pk=pack_id)
        self.assertNotEqual(pack.name, 'Must not persist')
        self.assertEqual(pack.items.count(), 1)

    def test_list_search_active_filter_and_employee_access(self):
        active = self.create_pack(name='Active radiance pack').data['id']
        inactive = self.create_pack(name='Inactive radiance pack', is_active=False).data['id']

        response = self.client.get(f'{self.packs_url}?is_active=true&search=radiance')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([row['id'] for row in response.data['results']], [active])
        self.assertNotIn(inactive, [row['id'] for row in response.data['results']])

        employee_response = employee_client(username='welcome_pack_employee').get(self.packs_url)
        self.assertEqual(employee_response.status_code, status.HTTP_200_OK)

    def test_item_endpoint_validates_product_and_quantity(self):
        pack_id = self.create_pack().data['id']
        finished = Product.objects.create(
            name='Finished welcome item', sku='FINISHED-WELCOME', unit_price=Decimal('1'),
            cost_usd=Decimal('1'), count=Decimal('0'), status=Product.StatusChoices.FINISHED,
        )
        invalid = self.client.post(self.items_url, {
            'welcome_pack': pack_id, 'product': finished.id, 'quantity': '1',
        }, format='json')
        self.assertEqual(invalid.status_code, status.HTTP_400_BAD_REQUEST)

        item = WelcomePack.objects.get(pk=pack_id).items.first()
        update = self.client.patch(f'{self.items_url}{item.id}/', {'quantity': '0'}, format='json')
        self.assertEqual(update.status_code, status.HTTP_400_BAD_REQUEST)

    def test_issue_snapshots_cost_rate_and_optional_matching_visit(self):
        pack_id = self.create_pack().data['id']
        visit = Visit.objects.create(
            customer=self.customer, staff=self.employee, start_at=timezone.now(),
            end_at=timezone.now() + timedelta(minutes=30), status=Visit.Status.COMPLETED,
        )
        response = self.client.post(f'{self.packs_url}{pack_id}/issue/', {
            'customer': self.customer.id, 'visit': visit.id, 'quantity': '2.000',
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        usage = WelcomePackUsage.objects.get(pk=response.data['id'])
        self.assertEqual(usage.quantity, Decimal('2.000'))
        self.assertEqual(usage.total_cost_usd_snapshot, Decimal('56.00'))
        self.assertEqual(usage.exchange_rate_snapshot, RATE)
        self.assertEqual(usage.total_cost_toman_snapshot, Decimal('5600000.00'))
        self.assertEqual(usage.visit_id, visit.id)

        self.product.cost_usd = Decimal('999')
        self.product.save(update_fields=['cost_usd'])
        usage.refresh_from_db()
        self.assertEqual(usage.total_cost_usd_snapshot, Decimal('56.00'))

    def test_issue_rejects_inactive_pack_bad_quantities_and_foreign_visit(self):
        pack_id = self.create_pack().data['id']
        foreign_visit = Visit.objects.create(
            customer=self.other_customer, start_at=timezone.now(),
            end_at=timezone.now() + timedelta(minutes=30), status=Visit.Status.COMPLETED,
        )
        for quantity in ('0', '-1', 'NaN', '1.0001'):
            response = self.client.post(f'{self.packs_url}{pack_id}/issue/', {
                'customer': self.customer.id, 'quantity': quantity,
            }, format='json')
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.data)
        foreign = self.client.post(f'{self.packs_url}{pack_id}/issue/', {
            'customer': self.customer.id, 'visit': foreign_visit.id,
        }, format='json')
        self.assertEqual(foreign.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('does not belong', foreign.data['error'])

        WelcomePack.objects.filter(pk=pack_id).update(is_active=False)
        inactive = self.client.post(f'{self.packs_url}{pack_id}/issue/', {'customer': self.customer.id}, format='json')
        self.assertEqual(inactive.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(WelcomePackUsage.objects.count(), 0)

    def test_usage_is_read_only_filterable_and_reported_in_financial_summary(self):
        pack_id = self.create_pack().data['id']
        issue = self.client.post(f'{self.packs_url}{pack_id}/issue/', {'customer': self.customer.id}, format='json')
        self.assertEqual(issue.status_code, status.HTTP_201_CREATED, issue.data)
        usage_id = issue.data['id']

        listing = self.client.get(f'{self.usages_url}?welcome_pack={pack_id}&customer={self.customer.id}')
        self.assertEqual(listing.status_code, status.HTTP_200_OK)
        self.assertEqual(listing.data['count'], 1)
        self.assertEqual(listing.data['results'][0]['id'], usage_id)
        self.assertEqual(self.client.patch(f'{self.usages_url}{usage_id}/', {'quantity': '9'}, format='json').status_code, 405)
        self.assertEqual(self.client.delete(f'{self.usages_url}{usage_id}/').status_code, 405)

        report = self.client.get(self.report_url)
        self.assertEqual(report.status_code, status.HTTP_200_OK)
        self.assertEqual(Decimal(report.data['total_cost_usd']), Decimal('28.00'))

        summary = reporting.financial_summary(timezone.now() - timedelta(days=1), timezone.now() + timedelta(days=1))
        self.assertEqual(summary['welcome_pack_cost']['usd'], Decimal('28.00'))
        self.assertEqual(summary['gross_profit']['usd'], Decimal('-28.00'))

    def test_anonymous_requests_are_rejected(self):
        anonymous = APIClient()
        for url in (self.packs_url, self.items_url, self.usages_url, self.report_url):
            self.assertEqual(anonymous.get(url).status_code, status.HTTP_401_UNAUTHORIZED)


class WelcomePackServiceInputHardeningTests(TestCase):
    def test_service_rejects_non_finite_and_overprecision_quantities(self):
        product = Product.objects.create(
            name='Validation product', sku='VALIDATION-PRODUCT', unit_price=Decimal('1'),
            cost_usd=Decimal('1'), count=Decimal('5'),
        )
        customer = make_customer()
        pack = WelcomePack.objects.create(name='Validation pack')
        WelcomePackItem.objects.create(welcome_pack=pack, product=product, quantity=Decimal('1'))

        for invalid in ('NaN', 'Infinity', '-Infinity', '0', '-1', '1.0001'):
            with self.assertRaises(WelcomePackError):
                issue_welcome_pack(
                    welcome_pack=pack, customer=customer, quantity=invalid, rate=RATE,
                )
        self.assertEqual(WelcomePackUsage.objects.count(), 0)

        for invalid in ('NaN', 'Infinity', '1.0001'):
            with self.assertRaises(WelcomePackError):
                validate_welcome_pack_items([{'product': product.id, 'quantity': invalid}])
