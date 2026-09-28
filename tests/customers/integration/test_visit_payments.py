from datetime import datetime, timedelta
from decimal import Decimal

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from customers.models import Customer, Payment, Service, Visit
from tests.helpers import ADMIN_PASSWORD, ADMIN_USERNAME, make_admin


def _aware(year, month, day, hour=10, minute=0):
    return timezone.make_aware(datetime(year, month, day, hour, minute))


class VisitPaymentLinkTest(TestCase):
    """The visit endpoint must expose the payments booked on that visit
    (id + customer), and both sides must always agree on the customer."""

    def setUp(self):
        self.client = APIClient()
        make_admin()
        login = self.client.post('/api/auth/token/', {
            'username': ADMIN_USERNAME, 'password': ADMIN_PASSWORD,
        }, format='json')
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {login.data["access"]}')

        self.customer = Customer.objects.create(
            first_name='Sara', last_name='Ahmadi',
            mobile_number='09123330001', national_id='111-0000001',
            file_sys_id='FSPA1111111111111111111111111111111',
        )
        self.other_customer = Customer.objects.create(
            first_name='Reza', last_name='Karimi',
            mobile_number='09123330002', national_id='111-0000002',
            file_sys_id='FSPB2222222222222222222222222222222',
        )
        self.service = Service.objects.create(name='Botox', price=800000, price_usd=100, time=30)
        self.visit = self._make_visit(self.customer, day=10)
        self.other_visit = self._make_visit(self.other_customer, day=11)

    def _make_visit(self, customer, day=10):
        start = _aware(2026, 7, day, 10)
        visit = Visit.objects.create(customer=customer, start_at=start, end_at=start + timedelta(minutes=30))
        visit.services.add(self.service)
        return visit

    def _pay(self, visit, amount='500000', customer=None, method='card'):
        return Payment.objects.create(
            customer=customer or visit.customer,
            visit=visit,
            amount=Decimal(amount),
            payment_method=method,
            paid_at=timezone.now(),
        )

    # ---------------------------------------------------------------- reads

    def test_visit_detail_embeds_payment_id_and_customer(self):
        payment = self._pay(self.visit)

        resp = self.client.get(f'/api/visits/{self.visit.id}/')

        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['customer'], self.customer.id)
        self.assertEqual(resp.data['customer_name'], 'Sara Ahmadi')
        self.assertEqual(len(resp.data['payments']), 1)
        row = resp.data['payments'][0]
        self.assertEqual(row['id'], payment.id)
        self.assertEqual(row['customer'], self.customer.id)
        self.assertEqual(row['customer_name'], 'Sara Ahmadi')
        self.assertEqual(Decimal(row['amount']), Decimal('500000.00'))
        self.assertEqual(row['payment_method'], 'card')
        self.assertIsNotNone(row['paid_at'])

    def test_visit_detail_without_payments_returns_empty_list_and_zero_total(self):
        resp = self.client.get(f'/api/visits/{self.visit.id}/')

        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['payments'], [])
        self.assertEqual(Decimal(str(resp.data['total_paid'])), Decimal('0'))

    def test_total_paid_sums_every_payment_of_the_visit(self):
        self._pay(self.visit, '500000')
        self._pay(self.visit, '250000.50', method='cash')

        resp = self.client.get(f'/api/visits/{self.visit.id}/')

        self.assertEqual(Decimal(str(resp.data['total_paid'])), Decimal('750000.50'))

    def test_visit_list_includes_payments_and_customer(self):
        self._pay(self.visit, '100000')
        self._pay(self.other_visit, '200000')

        resp = self.client.get('/api/visits/')

        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        by_id = {row['id']: row for row in resp.data['results']}
        own, other = by_id[self.visit.id], by_id[self.other_visit.id]
        self.assertEqual(own['customer'], self.customer.id)
        self.assertEqual([p['id'] for p in own['payments']], [self.visit.payments.first().id])
        self.assertEqual(Decimal(str(own['total_paid'])), Decimal('100000.00'))
        self.assertEqual(other['customer'], self.other_customer.id)
        self.assertEqual(Decimal(str(other['total_paid'])), Decimal('200000.00'))

    def test_every_embedded_payment_belongs_to_the_visit_customer(self):
        """Data integrity check: no payment row on a visit may point at
        another customer than the visit itself."""
        for visit in (self.visit, self.other_visit):
            for _ in range(3):
                self._pay(visit)

        resp = self.client.get('/api/visits/')
        for row in resp.data['results']:
            for payment in row['payments']:
                self.assertEqual(payment['customer'], row['customer'])

    def test_visit_list_does_not_query_payments_per_row(self):
        for day in range(20, 25):
            visit = self._make_visit(self.customer, day=day)
            for _ in range(2):
                self._pay(visit)

        with CaptureQueriesContext(connection) as ctx:
            resp = self.client.get('/api/visits/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

        payment_queries = [
            q for q in ctx.captured_queries
            if 'customers_payment' in q['sql'] and q['sql'].lstrip().upper().startswith('SELECT')
        ]
        self.assertEqual(len(payment_queries), 1, 'payments must be fetched with a single prefetch query')

    def test_visit_confirm_and_complete_return_payments(self):
        payment = self._pay(self.visit)

        confirm = self.client.post(f'/api/visits/{self.visit.id}/confirm/')
        complete = self.client.post(f'/api/visits/{self.visit.id}/complete/')

        self.assertEqual(confirm.status_code, status.HTTP_200_OK)
        self.assertEqual(complete.status_code, status.HTTP_200_OK)
        self.assertEqual(complete.data['status'], Visit.Status.COMPLETED)
        self.assertEqual([p['id'] for p in confirm.data['payments']], [payment.id])
        self.assertEqual([p['id'] for p in complete.data['payments']], [payment.id])

    # --------------------------------------------------------------- writes

    def test_payment_created_with_visit_inherits_the_visit_customer(self):
        resp = self.client.post('/api/payments/', {
            'visit': self.visit.id,
            'amount': '150000',
            'payment_method': 'cash',
            'paid_at': '1405-04-19 10:00',
        }, format='json')

        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        payment = Payment.objects.get(pk=resp.data['id'])
        self.assertEqual(payment.customer, self.customer)
        self.assertEqual(payment.visit, self.visit)
        self.assertEqual(resp.data['customer'], self.customer.id)

        visit_resp = self.client.get(f'/api/visits/{self.visit.id}/')
        self.assertIn(payment.id, [p['id'] for p in visit_resp.data['payments']])

    def test_payment_with_foreign_customer_on_visit_is_rejected(self):
        resp = self.client.post('/api/payments/', {
            'customer': self.other_customer.id,
            'visit': self.visit.id,
            'amount': '150000',
            'payment_method': 'cash',
            'paid_at': '1405-04-19 10:00',
        }, format='json')

        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('customer', resp.data)
        self.assertFalse(Payment.objects.filter(visit=self.visit).exists())

    def test_payment_reassigned_to_another_customers_visit_is_rejected(self):
        payment = self._pay(self.visit)

        resp = self.client.patch(f'/api/payments/{payment.id}/', {
            'visit': self.other_visit.id,
        }, format='json')

        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('customer', resp.data)
        payment.refresh_from_db()
        self.assertEqual(payment.visit, self.visit)

    def test_visit_customer_can_change_together_with_payments_guard(self):
        resp = self.client.post('/api/payments/', {
            'customer': self.customer.id,
            'visit': self.visit.id,
            'amount': '90000',
            'payment_method': 'card',
            'paid_at': '1405-04-19 11:00',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

        wrong = self.client.post('/api/payments/', {
            'customer': self.other_customer.id,
            'visit': self.visit.id,
            'amount': '90000',
            'payment_method': 'card',
            'paid_at': '1405-04-19 12:00',
        }, format='json')
        self.assertEqual(wrong.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(Payment.objects.filter(visit=self.visit).count(), 1)

    def test_payment_without_visit_is_untouched_by_the_guard(self):
        resp = self.client.post('/api/payments/', {
            'customer': self.other_customer.id,
            'amount': '40000',
            'payment_method': 'cash',
            'paid_at': '1405-04-19 13:00',
        }, format='json')

        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertIsNone(resp.data['visit'])

    # ------------------------------------------------------------ filtering

    def test_payments_endpoint_filters_by_visit(self):
        self._pay(self.visit, '100000')
        self._pay(self.visit, '200000')
        foreign = self._pay(self.other_visit, '300000')

        resp = self.client.get(f'/api/payments/?visit={self.visit.id}')

        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        returned = [p['id'] for p in resp.data['results']]
        self.assertEqual(sorted(returned), sorted(
            Payment.objects.filter(visit=self.visit).values_list('id', flat=True)
        ))
        self.assertNotIn(foreign.id, returned)

    def test_payments_endpoint_filters_by_customer(self):
        self._pay(self.visit, '100000')
        self._pay(self.other_visit, '300000')

        resp = self.client.get(f'/api/payments/?customer={self.customer.id}')

        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertTrue(resp.data['results'])
        self.assertTrue(all(p['customer'] == self.customer.id for p in resp.data['results']))

    def test_visit_detail_uses_shamsi_datetimes_for_payments(self):
        self._pay(self.visit)

        resp = self.client.get(f'/api/visits/{self.visit.id}/')

        paid_at = resp.data['payments'][0]['paid_at']
        self.assertIsInstance(paid_at, str)
        self.assertRegex(paid_at, r'^\d{4}-\d{2}-\d{2}')
