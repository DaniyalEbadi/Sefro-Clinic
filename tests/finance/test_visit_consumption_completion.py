from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from customers.models import Customer, Service, Visit
from finance.models import (
    ProductUsage,
    ServiceItem,
    WelcomePack,
    WelcomePackItem,
    WelcomePackUsage,
)
from finance.services.exchange_rates import set_rate
from inventory.models import Product
from tests.helpers import admin_client


class VisitConsumptionCompletionTests(TestCase):
    def setUp(self):
        self.client = admin_client()
        set_rate('USD', 'TOMAN', Decimal('100000'))
        self.customer = Customer.objects.create(
            first_name='Consumption', last_name='Tester',
            mobile_number='09127770001', national_id='777-0000001',
        )
        self.product = Product.objects.create(
            name='Serum', sku='CONSUMPTION-SERUM', count=Decimal('10'), cost_usd=Decimal('5'),
        )
        self.service = Service.objects.create(name='Recorded Facial', price_usd=Decimal('100'))
        ServiceItem.objects.create(service=self.service, product=self.product, quantity=Decimal('2'))

    def _visit(self, *services):
        visit = Visit.objects.create(
            customer=self.customer,
            start_at=timezone.now(),
            end_at=timezone.now(),
            status=Visit.Status.CONFIRMED,
        )
        visit.services.add(*(services or (self.service,)))
        return visit

    def _record(self, visit, quantity='1'):
        return self.client.post(
            f'/api/finance/visits/{visit.id}/record-consumption/',
            {'selected_products': {str(self.product_service_id(visit)): [[self.product.id, quantity]]}},
            format='json',
        )

    @staticmethod
    def product_service_id(visit):
        return visit.services.first().id

    def test_completion_requires_actual_consumption_and_then_succeeds(self):
        visit = self._visit()
        rejected = self.client.post(f'/api/visits/{visit.id}/complete/')
        self.assertEqual(rejected.status_code, 400)
        self.assertIn('Recorded Facial', rejected.data['error'])
        visit.refresh_from_db()
        self.assertEqual(visit.status, Visit.Status.CONFIRMED)

        recorded = self._record(visit, '1.25')
        self.assertEqual(recorded.status_code, 201, recorded.data)
        self.product.refresh_from_db()
        self.assertEqual(self.product.count, Decimal('8.750'))
        self.assertEqual(Decimal(recorded.data[0]['total_cost_usd_snapshot']), Decimal('6.25'))

        completed = self.client.post(f'/api/visits/{visit.id}/complete/')
        self.assertEqual(completed.status_code, 200, completed.data)
        self.assertEqual(completed.data['status'], 'completed')

    def test_patch_completion_is_subject_to_the_same_guard(self):
        visit = self._visit()
        rejected = self.client.patch(
            f'/api/visits/{visit.id}/', {'status': 'completed'}, format='json',
        )
        self.assertEqual(rejected.status_code, 400)
        visit.refresh_from_db()
        self.assertEqual(visit.status, Visit.Status.CONFIRMED)

    def test_zero_consumption_requires_reason_and_is_snapshot_recorded(self):
        visit = self._visit()
        missing_reason = self.client.post(
            f'/api/finance/visits/{visit.id}/record-consumption/',
            {'zero_consumption': {str(self.service.id): ''}}, format='json',
        )
        self.assertEqual(missing_reason.status_code, 400)

        recorded = self.client.post(
            f'/api/finance/visits/{visit.id}/record-consumption/',
            {'zero_consumption': {str(self.service.id): 'Product not required for this treatment'}},
            format='json',
        )
        self.assertEqual(recorded.status_code, 201, recorded.data)
        usage = ProductUsage.objects.get(visit=visit, service=self.service)
        self.assertEqual(usage.quantity, Decimal('0.000'))
        self.assertEqual(usage.zero_reason, 'Product not required for this treatment')
        self.product.refresh_from_db()
        self.assertEqual(self.product.count, Decimal('10.000'))
        self.assertEqual(self.client.post(f'/api/visits/{visit.id}/complete/').status_code, 200)

    def test_explicit_zero_consumption_is_distinct_from_missing_recording(self):
        visit = self._visit()
        missing = self.client.post(f'/api/visits/{visit.id}/complete/')
        self.assertEqual(missing.status_code, 400)

        recorded = self.client.post(
            f'/api/finance/visits/{visit.id}/record-consumption/',
            {'zero_consumption': {str(self.service.id): 'Confirmed no product used'}},
            format='json',
        )
        self.assertEqual(recorded.status_code, 201, recorded.data)
        completed = self.client.post(f'/api/visits/{visit.id}/complete/')
        self.assertEqual(completed.status_code, 200, completed.data)

    def test_service_without_recipe_can_complete(self):
        service = Service.objects.create(name='Consultation Only', price_usd=Decimal('20'))
        visit = self._visit(service)
        response = self.client.patch(f'/api/visits/{visit.id}/', {'status': 'completed'}, format='json')
        self.assertEqual(response.status_code, 200, response.data)

    def test_insufficient_stock_rolls_back_and_blocks_completion(self):
        self.product.count = Decimal('0.5')
        self.product.save(update_fields=['count'])
        visit = self._visit()
        recorded = self._record(visit, '1')
        self.assertEqual(recorded.status_code, 400)
        self.assertFalse(ProductUsage.objects.filter(visit=visit).exists())
        self.product.refresh_from_db()
        self.assertEqual(self.product.count, Decimal('0.500'))
        self.assertEqual(self.client.post(f'/api/visits/{visit.id}/complete/').status_code, 400)

    def test_repeated_recording_does_not_deduct_twice_and_cost_is_historical(self):
        visit = self._visit()
        first = self._record(visit, '1')
        self.assertEqual(first.status_code, 201)
        retry = self._record(visit, '1')
        self.assertEqual(retry.status_code, 400)
        self.assertEqual(ProductUsage.objects.filter(visit=visit).count(), 1)
        self.product.cost_usd = Decimal('99')
        self.product.save(update_fields=['cost_usd'])
        usage = ProductUsage.objects.get(visit=visit)
        self.assertEqual(usage.unit_cost_usd_snapshot, Decimal('5.00'))

    def test_multiple_services_require_independent_consumption_and_pack_cost_once(self):
        second_product = Product.objects.create(
            name='Second Serum', sku='CONSUMPTION-SERUM-2', count=Decimal('5'), cost_usd=Decimal('3'),
        )
        second_service = Service.objects.create(name='Recorded Laser', price_usd=Decimal('80'))
        ServiceItem.objects.create(service=second_service, product=second_product, quantity=Decimal('2'))
        pack_product = Product.objects.create(
            name='Welcome Towel', sku='CONSUMPTION-PACK-1', count=Decimal('4'), cost_usd=Decimal('2'),
        )
        pack = WelcomePack.objects.create(name='Consumption Pack')
        WelcomePackItem.objects.create(welcome_pack=pack, product=pack_product, quantity=Decimal('1'))

        visit = self._visit(self.service, second_service)
        first = self.client.post(
            f'/api/finance/visits/{visit.id}/record-consumption/',
            {'selected_products': {str(self.service.id): [[self.product.id, '0.5']]}},
            format='json',
        )
        self.assertEqual(first.status_code, 201, first.data)
        blocked = self.client.post(f'/api/visits/{visit.id}/complete/')
        self.assertEqual(blocked.status_code, 400)
        self.assertIn('Recorded Laser', blocked.data['error'])

        second = self.client.post(
            f'/api/finance/visits/{visit.id}/record-consumption/',
            {'selected_products': {str(second_service.id): [[second_product.id, '1.5']]}},
            format='json',
        )
        self.assertEqual(second.status_code, 201, second.data)
        issued = self.client.post(
            f'/api/finance/welcome-packs/{pack.id}/issue/',
            {'customer': self.customer.id, 'visit': visit.id, 'quantity': '1'},
            format='json',
        )
        self.assertEqual(issued.status_code, 201, issued.data)
        self.assertEqual(self.client.post(f'/api/visits/{visit.id}/complete/').status_code, 200)

        self.product.refresh_from_db()
        second_product.refresh_from_db()
        pack_product.refresh_from_db()
        self.assertEqual(self.product.count, Decimal('9.500'))
        self.assertEqual(second_product.count, Decimal('3.500'))
        self.assertEqual(pack_product.count, Decimal('3.000'))
        self.assertEqual(ProductUsage.objects.filter(visit=visit, service=self.service).count(), 1)
        self.assertEqual(ProductUsage.objects.filter(visit=visit, service=second_service).count(), 1)
        self.assertEqual(WelcomePackUsage.objects.filter(visit=visit).count(), 1)

        from finance.services.financials import calculate_visit_financials
        financials = calculate_visit_financials(visit)
        self.assertEqual(financials['product_cost_usd'], Decimal('7.00'))
        self.assertEqual(financials['services'][self.service.id]['product_cost_usd'], Decimal('2.50'))
        self.assertEqual(financials['services'][second_service.id]['product_cost_usd'], Decimal('4.50'))
        self.assertEqual(financials['welcome_pack_cost_usd'], Decimal('2.00'))
