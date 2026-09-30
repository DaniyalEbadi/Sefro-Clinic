"""Welcome-pack issuance must consume real inventory (P0 #1, Q1/Q2 decisions).

Decision under test: issuing a pack **hard-fails** when stock is short,
matching the consumables path, so nothing is issued. Issuing also records a
``ProductUsage`` row per item, which means pack cost exists in two places --
the report layer must therefore charge it exactly once.
"""
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from customers.models import Visit
from finance.models import ProductUsage, WelcomePack, WelcomePackItem, WelcomePackUsage
from finance.services import reporting
from finance.services.exchange_rates import set_rate
from finance.services.welcome_pack import issue_welcome_pack
from inventory.models import Product
from tests.helpers import admin_client, make_customer, make_employee

RATE = Decimal('100000')


class WelcomePackStockTests(TestCase):
    packs_url = '/api/finance/welcome-packs/'

    def setUp(self):
        set_rate('USD', 'TOMAN', RATE, effective_at=timezone.now(), source='pack-stock-test')
        self.client = admin_client()
        self.customer = make_customer()
        self.employee = make_employee(username='pack_stock_employee')
        self.serum = Product.objects.create(
            name='Pack serum', sku='PACK-SERUM', unit_price=Decimal('10'),
            cost_usd=Decimal('12.50'), count=Decimal('20'),
        )
        self.towel = Product.objects.create(
            name='Pack towel', sku='PACK-TOWEL', unit_price=Decimal('5'),
            cost_usd=Decimal('2.00'), count=Decimal('3'),
        )
        self.pack = WelcomePack.objects.create(name='Stock pack')
        WelcomePackItem.objects.create(welcome_pack=self.pack, product=self.serum, quantity=Decimal('2'))
        WelcomePackItem.objects.create(welcome_pack=self.pack, product=self.towel, quantity=Decimal('1.5'))

    def _issue(self, **kwargs):
        payload = {'customer': self.customer.id}
        payload.update(kwargs)
        return self.client.post(f'{self.packs_url}{self.pack.id}/issue/', payload, format='json')

    # --- stock is actually drawn down -------------------------------------

    def test_issuing_decrements_stock_by_item_quantity_times_pack_quantity(self):
        response = self._issue(quantity='2')
        self.assertEqual(response.status_code, 201, response.data)

        self.serum.refresh_from_db()
        self.towel.refresh_from_db()
        # serum: 2 per pack x 2 packs = 4 of 20 ; towel: 1.5 x 2 = 3 of 3
        self.assertEqual(self.serum.count, Decimal('16.000'))
        self.assertEqual(self.towel.count, Decimal('0.000'))

    def test_partial_pack_quantity_decrements_proportionally(self):
        self.assertEqual(self._issue(quantity='1').status_code, 201)
        self.serum.refresh_from_db()
        self.towel.refresh_from_db()
        self.assertEqual(self.serum.count, Decimal('18.000'))
        self.assertEqual(self.towel.count, Decimal('1.500'))

    def test_fractional_quantities_round_up_to_stock_precision(self):
        # Item and pack quantities are both stored with 3 decimals, so their
        # product needs up to 6. Stock cannot hold that, and rounding down
        # would under-decrement the warehouse.
        pack = WelcomePack.objects.create(name='Tiny pack')
        WelcomePackItem.objects.create(welcome_pack=pack, product=self.serum, quantity=Decimal('0.333'))
        usage = issue_welcome_pack(welcome_pack=pack, customer=self.customer, quantity='0.333', rate=RATE)
        self.serum.refresh_from_db()
        # 0.333 * 0.333 = 0.110889 -> 0.111 (rounded up)
        self.assertEqual(self.serum.count, Decimal('19.889'))
        self.assertEqual(
            [r.quantity for r in ProductUsage.objects.filter(welcome_pack_usage=usage)],
            [Decimal('0.111')],
        )

    def test_issuing_creates_product_usage_rows_linked_to_the_pack(self):
        response = self._issue(quantity='2')
        usage = WelcomePackUsage.objects.get(pk=response.data['id'])

        rows = ProductUsage.objects.filter(welcome_pack_usage=usage).order_by('product_id')
        self.assertEqual(rows.count(), 2)
        self.assertEqual([r.product_id for r in rows], [self.serum.id, self.towel.id])
        self.assertEqual([r.quantity for r in rows], [Decimal('4.000'), Decimal('3.000')])
        # Cost snapshot must agree with the pack snapshot it was derived from.
        self.assertEqual(
            sum(r.total_cost_usd_snapshot for r in rows),
            usage.total_cost_usd_snapshot,
        )

    def test_pack_consumption_appears_in_the_product_usage_list(self):
        usage = issue_welcome_pack(welcome_pack=self.pack, customer=self.customer, quantity='1', rate=RATE)
        response = self.client.get('/api/finance/product-usages/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 2)
        self.assertEqual({row['welcome_pack_usage'] for row in response.data['results']}, {usage.id})

    # --- hard fail on shortage --------------------------------------------

    def test_issuing_fails_when_an_item_has_insufficient_stock(self):
        WelcomePackItem.objects.filter(welcome_pack=self.pack, product=self.serum).update(quantity=Decimal('30'))
        before_serum = self.serum.count
        before_towel = self.towel.count

        response = self._issue(quantity='1')

        self.assertEqual(response.status_code, 400)
        self.assertIn('Insufficient stock', response.data['error'])
        # Nothing issued, nothing consumed -- including the item that was fine.
        self.assertEqual(WelcomePackUsage.objects.count(), 0)
        self.assertEqual(ProductUsage.objects.count(), 0)
        self.serum.refresh_from_db()
        self.towel.refresh_from_db()
        self.assertEqual(self.serum.count, before_serum)
        self.assertEqual(self.towel.count, before_towel)

    def test_issuing_fails_for_a_zero_stock_item(self):
        WelcomePackItem.objects.filter(welcome_pack=self.pack, product=self.towel).delete()
        WelcomePackItem.objects.create(welcome_pack=self.pack, product=self.towel, quantity=Decimal('1'))
        Product.objects.filter(pk=self.towel.pk).update(count=Decimal('0'))

        response = self._issue(quantity='1')

        self.assertEqual(response.status_code, 400)
        self.assertIn('Insufficient stock', response.data['error'])
        self.assertEqual(WelcomePackUsage.objects.count(), 0)
        self.serum.refresh_from_db()
        self.assertEqual(self.serum.count, Decimal('20.000'), 'stock of a satisfied item must not move')

    def test_rejected_issuance_does_not_leave_partial_stock_deductions(self):
        # towel is short, serum is plentiful: the rollback must undo serum too.
        Product.objects.filter(pk=self.towel.pk).update(count=Decimal('0.500'))
        response = self._issue(quantity='2')
        self.assertEqual(response.status_code, 400)
        self.serum.refresh_from_db()
        self.assertEqual(self.serum.count, Decimal('20.000'))

    # --- pack cost is charged exactly once --------------------------------

    def test_pack_cost_is_not_double_counted_in_financial_summary(self):
        issue_welcome_pack(welcome_pack=self.pack, customer=self.customer, quantity='1', rate=RATE)
        summary = reporting.financial_summary(
            timezone.now() - timedelta(days=1), timezone.now() + timedelta(days=1),
        )
        # serum 12.50*2 + towel 2.00*1.5 = 28.00, charged once.
        self.assertEqual(summary['welcome_pack_cost']['usd'], Decimal('28.00'))
        self.assertEqual(summary['product_cost']['usd'], Decimal('0'))
        self.assertEqual(summary['gross_profit']['usd'], Decimal('-28.00'))

    def test_non_pack_consumption_still_counts_towards_product_cost(self):
        issue_welcome_pack(welcome_pack=self.pack, customer=self.customer, quantity='1', rate=RATE)
        ProductUsage.objects.create(
            product=self.serum, quantity=Decimal('1'),
            unit_cost_usd_snapshot=Decimal('12.50'), total_cost_usd_snapshot=Decimal('12.50'),
        )
        summary = reporting.financial_summary(
            timezone.now() - timedelta(days=1), timezone.now() + timedelta(days=1),
        )
        self.assertEqual(summary['product_cost']['usd'], Decimal('12.50'))
        self.assertEqual(summary['welcome_pack_cost']['usd'], Decimal('28.00'))
        self.assertEqual(summary['gross_profit']['usd'], Decimal('-40.50'))

    def test_pack_consumption_is_excluded_from_profit_by_service(self):
        from customers.models import Service

        visit = Visit.objects.create(
            customer=self.customer, staff=self.employee, start_at=timezone.now(),
            end_at=timezone.now() + timedelta(minutes=30), status=Visit.Status.COMPLETED,
        )
        service = Service.objects.create(name='Pack service', price_usd=Decimal('100'))
        visit.services.add(service)
        issue_welcome_pack(welcome_pack=self.pack, customer=self.customer, quantity='1', visit=visit, rate=RATE)

        rows = reporting.profit_by_service(
            timezone.now() - timedelta(days=1), timezone.now() + timedelta(days=1),
        )
        row = next(r for r in rows if r['service_id'] == service.id)
        self.assertEqual(row['product_cost_usd'], Decimal('0.00'))
        self.assertEqual(row['welcome_pack_cost_basis'], 'excluded')

    def test_pack_consumption_is_excluded_from_dashboard_product_cost(self):
        issue_welcome_pack(welcome_pack=self.pack, customer=self.customer, quantity='1', rate=RATE)
        response = self.client.get('/api/finance/reports/dashboard/')
        self.assertEqual(response.status_code, 200)
        summary = response.data['sales_summary']
        self.assertEqual(Decimal(summary['product_cost_usd']), Decimal('0'))
        self.assertEqual(Decimal(summary['welcome_pack_cost_usd']), Decimal('28.00'))
        self.assertEqual(Decimal(summary['gross_profit_usd']), Decimal('-28.00'))
