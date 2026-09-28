from datetime import date
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone
from rest_framework import status

from finance.models import ProductPurchase, PurchaseOrder
from finance.services.exchange_rates import set_rate
from inventory.models import Product
from tests.helpers import admin_client, employee_client, make_admin, make_employee

RATE = Decimal('100000')
URL = '/api/finance/purchase-orders/'
REPORT_URL = '/api/finance/reports/product-purchases/'


class PurchaseOrderAPITests(TestCase):
    def setUp(self):
        set_rate('USD', 'TOMAN', RATE, effective_at=timezone.now(), source='purchase-order-api')
        self.admin = make_admin()
        self.employee = make_employee(username='po_api_employee')
        self.client = admin_client()
        self.product = Product.objects.create(
            name='Botox vial', sku='PO-API-VIAL', unit_price=Decimal('50'),
            cost_usd=Decimal('10.00'), count=Decimal('5'),
        )
        self.other_product = Product.objects.create(
            name='Peel serum', sku='PO-API-SERUM', unit_price=Decimal('30'),
            cost_usd=Decimal('8.00'), count=Decimal('2'),
        )

    def payload(self, **overrides):
        data = {
            'supplier': 'Beauty Supply Co',
            'order_date': '2026-09-20',
            'items': [
                {'product': self.product.id, 'quantity': '3', 'unit_cost_usd': '12.50'},
            ],
        }
        data.update(overrides)
        return data

    def create(self, **overrides):
        response = self.client.post(URL, self.payload(**overrides), format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        return response

    # --- create / read -------------------------------------------------
    def test_admin_creates_order_with_nested_items_and_live_toman_total(self):
        response = self.create(idempotency_key='api-restock-1')

        body = response.data
        self.assertEqual(body['status'], PurchaseOrder.Status.DRAFT)
        self.assertEqual(body['created_by'], self.admin.id)
        self.assertEqual(Decimal(body['total_cost_usd']), Decimal('37.50'))
        # Draft: Toman is the live conversion, not a snapshot yet.
        self.assertEqual(Decimal(body['total_cost_toman']), (Decimal('37.50') * RATE).quantize(Decimal('0.01')))
        self.assertEqual(Decimal(body['exchange_rate']), RATE)
        self.assertIsNone(body['exchange_rate_snapshot'])
        self.assertEqual(len(body['items']), 1)
        item = body['items'][0]
        self.assertEqual(item['product_name'], 'Botox vial')
        self.assertEqual(Decimal(item['unit_cost_toman']), (Decimal('12.50') * RATE).quantize(Decimal('0.01')))
        # No stock or ledger effect yet.
        self.product.refresh_from_db()
        self.assertEqual(self.product.count, Decimal('5'))
        self.assertEqual(ProductPurchase.objects.count(), 0)

    def test_create_defaults_order_date_to_today_and_ignores_creator_spoofing(self):
        response = self.client.post(URL, self.payload(order_date=None, created_by=self.employee.id), format='json')
        # order_date=None is an invalid date → 400; omit it instead.
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        payload = self.payload()
        payload.pop('order_date')
        payload['created_by'] = self.employee.id
        response = self.client.post(URL, payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        body = response.data
        self.assertEqual(body['order_date'], timezone.now().date().isoformat())
        self.assertEqual(body['created_by'], self.admin.id)
        expected_name = f'{self.admin.first_name} {self.admin.last_name}'.strip() or self.admin.username
        self.assertEqual(body['created_by_name'], expected_name)

    def test_idempotent_create_returns_the_same_order(self):
        first = self.create(idempotency_key='retry-me')
        second = self.create(idempotency_key='retry-me')
        self.assertEqual(first.data['id'], second.data['id'])
        self.assertEqual(PurchaseOrder.objects.count(), 1)

    def test_validation_errors(self):
        cases = [
            {'items': []},
            {'items': [{'product': self.product.id, 'quantity': '1', 'unit_cost_usd': '5'},
                       {'product': self.product.id, 'quantity': '2', 'unit_cost_usd': '5'}]},
            {'items': [{'product': self.product.id, 'quantity': '0', 'unit_cost_usd': '5'}]},
            {'items': [{'product': 999999, 'quantity': '1', 'unit_cost_usd': '5'}]},
            {'items': [{'quantity': '1', 'unit_cost_usd': '5'}]},
        ]
        for override in cases:
            response = self.client.post(URL, self.payload(**override), format='json')
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, f'{override} → {response.data}')
        self.assertEqual(PurchaseOrder.objects.count(), 0)

    def test_employee_can_read_but_not_write(self):
        order_id = self.create().data['id']
        employee = employee_client(username='po_api_employee')

        listing = employee.get(URL)
        self.assertEqual(listing.status_code, status.HTTP_200_OK)
        self.assertEqual(listing.data['count'], 1)

        detail = employee.get(f'{URL}{order_id}/')
        self.assertEqual(detail.status_code, status.HTTP_200_OK)

        denied = employee.post(URL, self.payload(supplier='Nope'), format='json')
        self.assertEqual(denied.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(PurchaseOrder.objects.count(), 1)

    def test_anonymous_requests_are_rejected(self):
        from rest_framework.test import APIClient

        client = APIClient()
        self.assertEqual(client.get(URL).status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(client.post(URL, self.payload(), format='json').status_code, status.HTTP_401_UNAUTHORIZED)

    # --- lifecycle actions --------------------------------------------
    def test_full_lifecycle_mark_ordered_then_receive(self):
        order_id = self.create().data['id']

        ordered = self.client.post(f'{URL}{order_id}/mark-ordered/')
        self.assertEqual(ordered.status_code, status.HTTP_200_OK, ordered.data)
        self.assertEqual(ordered.data['status'], 'ordered')
        self.product.refresh_from_db()
        self.assertEqual(self.product.count, Decimal('5'))

        received = self.client.post(f'{URL}{order_id}/receive/')
        self.assertEqual(received.status_code, status.HTTP_200_OK, received.data)
        body = received.data
        self.assertEqual(body['status'], 'received')
        self.assertEqual(body['received_date'], timezone.now().date().isoformat())
        self.assertEqual(Decimal(body['exchange_rate']), RATE)
        self.assertEqual(Decimal(body['exchange_rate_snapshot']), RATE)
        self.assertEqual(Decimal(body['total_cost_toman']), (Decimal('37.50') * RATE).quantize(Decimal('0.01')))
        # Nested items now carry the stored receive-time snapshots.
        self.assertEqual(Decimal(body['items'][0]['unit_cost_toman']), (Decimal('12.50') * RATE).quantize(Decimal('0.01')))

        self.product.refresh_from_db()
        self.assertEqual(self.product.count, Decimal('8'))
        self.assertEqual(self.product.cost_usd, Decimal('12.50'))
        self.assertEqual(ProductPurchase.objects.count(), 0)

    def test_invalid_transitions_return_400(self):
        order_id = self.create().data['id']

        # draft cannot be marked ordered twice / cancelled from received
        first = self.client.post(f'{URL}{order_id}/mark-ordered/')
        self.assertEqual(first.status_code, status.HTTP_200_OK)
        again = self.client.post(f'{URL}{order_id}/mark-ordered/')
        self.assertEqual(again.status_code, status.HTTP_400_BAD_REQUEST)

        receive = self.client.post(f'{URL}{order_id}/receive/')
        self.assertEqual(receive.status_code, status.HTTP_200_OK)
        for action in ('receive', 'cancel', 'mark-ordered'):
            response = self.client.post(f'{URL}{order_id}/{action}/')
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, action)

        edit = self.client.patch(f'{URL}{order_id}/', {'supplier': 'Changed'}, format='json')
        self.assertEqual(edit.status_code, status.HTTP_400_BAD_REQUEST)
        self.product.refresh_from_db()
        self.assertEqual(self.product.count, Decimal('8'))

    def test_cancel_a_draft_order(self):
        order_id = self.create().data['id']
        cancelled = self.client.post(f'{URL}{order_id}/cancel/')
        self.assertEqual(cancelled.status_code, status.HTTP_200_OK)
        self.assertEqual(cancelled.data['status'], 'cancelled')

        receive = self.client.post(f'{URL}{order_id}/receive/')
        self.assertEqual(receive.status_code, status.HTTP_400_BAD_REQUEST)

    def test_employee_cannot_use_lifecycle_actions(self):
        order_id = self.create().data['id']
        employee = employee_client(username='po_api_employee')
        for action in ('mark-ordered', 'receive', 'cancel'):
            response = employee.post(f'{URL}{order_id}/{action}/')
            self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN, action)
        order = PurchaseOrder.objects.get(pk=order_id)
        self.assertEqual(order.status, PurchaseOrder.Status.DRAFT)

    def test_update_replaces_items_only_while_open(self):
        order_id = self.create().data['id']
        response = self.client.put(f'{URL}{order_id}/', self.payload(
            supplier='Updated Supplier',
            items=[
                {'product': self.product.id, 'quantity': '4', 'unit_cost_usd': '11.00'},
                {'product': self.other_product.id, 'quantity': '2', 'unit_cost_usd': '3.00'},
            ],
        ), format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(Decimal(response.data['total_cost_usd']), Decimal('50.00'))
        self.assertEqual(len(response.data['items']), 2)

        patched = self.client.patch(f'{URL}{order_id}/', {'notes': 'call before delivery'}, format='json')
        self.assertEqual(patched.status_code, status.HTTP_200_OK)
        self.assertEqual(patched.data['notes'], 'call before delivery')
        self.assertEqual(Decimal(patched.data['total_cost_usd']), Decimal('50.00'))

    def test_delete_rules(self):
        draft_id = self.create().data['id']
        received_id = self.create(supplier='Second', idempotency_key='second').data['id']
        self.client.post(f'{URL}{received_id}/receive/')

        blocked = self.client.delete(f'{URL}{received_id}/')
        self.assertEqual(blocked.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertTrue(PurchaseOrder.objects.filter(pk=received_id).exists())

        deleted = self.client.delete(f'{URL}{draft_id}/')
        self.assertEqual(deleted.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(PurchaseOrder.objects.filter(pk=draft_id).exists())

    # --- filters -------------------------------------------------------
    def test_list_filters(self):
        first_id = self.create().data['id']
        second_id = self.create(
            supplier='Beta Traders', idempotency_key='beta',
            items=[{'product': self.other_product.id, 'quantity': '10', 'unit_cost_usd': '1.00'}],
        ).data['id']
        self.client.post(f'{URL}{second_id}/receive/')

        by_status = self.client.get(f'{URL}?status=received')
        self.assertEqual([row['id'] for row in by_status.data['results']], [second_id])

        by_supplier = self.client.get(f'{URL}?supplier=beta')
        self.assertEqual([row['id'] for row in by_supplier.data['results']], [second_id])

        by_product = self.client.get(f'{URL}?product={self.other_product.id}')
        self.assertEqual([row['id'] for row in by_product.data['results']], [second_id])

        in_range = self.client.get(f'{URL}?date_from=2026-09-01&date_to=2026-09-30')
        self.assertEqual({row['id'] for row in in_range.data['results']}, {first_id, second_id})

        out_of_range = self.client.get(f'{URL}?date_from=2020-01-01&date_to=2020-12-31')
        self.assertEqual(out_of_range.data['count'], 0)

    # --- report --------------------------------------------------------
    def test_purchase_report_totals_in_usd_and_toman(self):
        received_id = self.create().data['id']
        self.client.post(f'{URL}{received_id}/receive/')
        self.create(supplier='Never Received', idempotency_key='open-order')

        response = self.client.get(REPORT_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        body = response.data
        self.assertEqual(body['order_count'], 1)
        self.assertEqual(Decimal(body['total_cost_usd']), Decimal('37.50'))
        self.assertEqual(Decimal(body['total_cost_toman']), (Decimal('37.50') * RATE).quantize(Decimal('0.01')))
        self.assertEqual(body['by_product'][0]['product_name'], 'Botox vial')
        self.assertEqual(body['by_supplier'][0]['supplier'], 'Beauty Supply Co')

    def test_purchase_report_filters_by_product_and_supplier(self):
        first = self.create(supplier='Alpha Traders').data['id']
        self.client.post(f'{URL}{first}/receive/')
        second = self.create(
            supplier='Beta Traders', idempotency_key='beta-report',
            items=[{'product': self.other_product.id, 'quantity': '10', 'unit_cost_usd': '1.00'}],
        ).data['id']
        self.client.post(f'{URL}{second}/receive/')

        by_product = self.client.get(f'{REPORT_URL}?product={self.other_product.id}')
        self.assertEqual(Decimal(by_product.data['total_cost_usd']), Decimal('10.00'))

        by_supplier = self.client.get(f'{REPORT_URL}?supplier=alpha')
        self.assertEqual(Decimal(by_supplier.data['total_cost_usd']), Decimal('37.50'))

        out_of_range = self.client.get(f'{REPORT_URL}?start_date=2020-01-01&end_date=2020-12-31')
        self.assertEqual(Decimal(out_of_range.data['total_cost_usd']), Decimal('0'))
        self.assertEqual(out_of_range.data['order_count'], 0)

    def test_report_respects_period_shortcut(self):
        received_id = self.create().data['id']
        self.client.post(f'{URL}{received_id}/receive/')
        response = self.client.get(f'{REPORT_URL}?period=today')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['order_count'], 1)

        response = self.client.get(f'{REPORT_URL}?start_date=2026-01-01&end_date=2026-01-02')
        self.assertEqual(response.data['order_count'], 0)

    def test_report_requires_authentication(self):
        from rest_framework.test import APIClient

        self.assertEqual(APIClient().get(REPORT_URL).status_code, status.HTTP_401_UNAUTHORIZED)

    def test_order_date_filter_accepts_iso_dates(self):
        order_id = self.create(order_date=date(2026, 3, 5)).data['id']
        hit = self.client.get(f'{URL}?date_from=2026-03-01&date_to=2026-03-31')
        self.assertEqual([row['id'] for row in hit.data['results']], [order_id])
