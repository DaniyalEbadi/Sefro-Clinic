from datetime import datetime

import jdatetime
from django.test import TestCase
from django.utils import timezone

from customers.models import Customer, Payment, Service, Visit
from tests.helpers import admin_client, employee_client, make_admin


def shamsi_today_str():
    local_now = timezone.localtime(timezone.now())
    return jdatetime.datetime.fromgregorian(datetime=local_now).strftime('%Y-%m-%d')


def shamsi_str(y, m, d):
    return f'{y}-{m:02d}-{d:02d}'


class ReportsAccessTests(TestCase):
    ENDPOINTS = [
        '/api/reports/',
        '/api/reports/daily/',
        '/api/reports/weekly/',
        '/api/reports/monthly/',
        '/api/reports/quarterly/',
        '/api/reports/yearly/',
        '/api/reports/all/',
        '/api/reports/visits/',
        '/api/reports/customers/',
        '/api/reports/referral/',
    ]

    def setUp(self):
        make_admin()

    def test_anonymous_is_rejected_on_every_report_endpoint(self):
        from rest_framework.test import APIClient
        anon = APIClient()
        for url in self.ENDPOINTS:
            response = anon.get(url)
            self.assertEqual(response.status_code, 401, url)

    def test_employee_is_forbidden_on_every_report_endpoint(self):
        client = employee_client()
        for url in self.ENDPOINTS:
            response = client.get(url)
            self.assertEqual(response.status_code, 403, url)

    def test_admin_gets_ok_on_every_report_endpoint(self):
        client = admin_client()
        for url in self.ENDPOINTS:
            response = client.get(url)
            self.assertEqual(response.status_code, 200, url)


class ReportsAPIViewTests(TestCase):
    def setUp(self):
        self.client = admin_client()
        self.customer = Customer.objects.create(
            first_name='Ali', last_name='Rezaei',
            mobile_number='09121111111', national_id='001-0000001',
        )
        Payment.objects.create(customer=self.customer, amount='150000', paid_at=timezone.now())
        Payment.objects.create(customer=self.customer, amount='50000', paid_at=timezone.now())

    def test_response_contains_all_documented_keys(self):
        response = self.client.get('/api/reports/')
        self.assertEqual(response.status_code, 200)
        for key in ['daily', 'weekly', 'monthly', 'quarterly', 'yearly',
                    'total_sales', 'avg_satisfaction', 'service_popularity',
                    'total_visits', 'customer_breakdown']:
            self.assertIn(key, response.data, key)

    def test_total_sales_sums_all_payments_when_unfiltered(self):
        response = self.client.get('/api/reports/')
        self.assertEqual(response.data['total_sales'], 200000.0)

    def test_date_range_filters_payments(self):
        today = shamsi_today_str()
        response = self.client.get(f'/api/reports/?date_from={today}&date_to={today}')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(float(response.data['total_sales']), 200000.0)

    def test_out_of_range_dates_exclude_payments(self):
        response = self.client.get('/api/reports/?date_from=1300-01-01&date_to=1300-01-02')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(float(response.data['total_sales']), 0)

    def test_invalid_shamsi_date_returns_400_not_500(self):
        response = self.client.get('/api/reports/?date_from=not-a-date')
        self.assertEqual(response.status_code, 400)

    def test_service_popularity_lists_services_with_usage_counts(self):
        service = Service.objects.create(name='Consultation')
        visit = Visit.objects.create(
            customer=self.customer,
            start_at=timezone.make_aware(datetime(2025, 6, 1, 10, 0)),
            end_at=timezone.make_aware(datetime(2025, 6, 1, 11, 0)),
        )
        visit.services.add(service)
        response = self.client.get('/api/reports/')
        popular = list(response.data['service_popularity'])
        self.assertEqual(popular[0]['name'], 'Consultation')
        self.assertEqual(popular[0]['usage'], 1)


class PeriodReportTests(TestCase):
    def setUp(self):
        self.client = admin_client()
        self.customer = Customer.objects.create(
            first_name='Sara', last_name='Karimi',
            mobile_number='09122222222', national_id='002-0000002',
        )

    def _seed_payment_now(self):
        Payment.objects.create(customer=self.customer, amount='25000', paid_at=timezone.now())

    def test_daily_report_period_and_total(self):
        self._seed_payment_now()
        response = self.client.get('/api/reports/daily/')
        self.assertEqual(response.status_code, 200)
        self.assertRegex(response.data['period'], r'^\d{4}-\d{2}-\d{2}$')
        self.assertEqual(float(response.data['total']), 25000.0)

    def test_weekly_report_shape(self):
        self._seed_payment_now()
        response = self.client.get('/api/reports/weekly/')
        self.assertEqual(response.status_code, 200)
        self.assertRegex(response.data['period'], r'^\d{4}-W\d{2}$')
        self.assertEqual(float(response.data['total']), 25000.0)

    def test_monthly_report_shape(self):
        self._seed_payment_now()
        response = self.client.get('/api/reports/monthly/')
        self.assertEqual(response.status_code, 200)
        self.assertRegex(response.data['period'], r'^\d{4}-\d{2}$')
        self.assertEqual(float(response.data['total']), 25000.0)

    def test_quarterly_report_shape(self):
        self._seed_payment_now()
        response = self.client.get('/api/reports/quarterly/')
        self.assertEqual(response.status_code, 200)
        self.assertRegex(response.data['period'], r'^\d{4}-Q[1-4]$')
        self.assertEqual(float(response.data['total']), 25000.0)

    def test_yearly_report_shape(self):
        self._seed_payment_now()
        response = self.client.get('/api/reports/yearly/')
        self.assertEqual(response.status_code, 200)
        self.assertRegex(response.data['period'], r'^\d{4}$')
        self.assertEqual(float(response.data['total']), 25000.0)


class VisitReportViewTests(TestCase):
    def setUp(self):
        self.client = admin_client()
        self.customer = Customer.objects.create(
            first_name='Mina', last_name='Ahmadi',
            mobile_number='09123333333', national_id='003-0000003',
        )

    def _visit_at_shamsi(self, y, m, d):
        greg = jdatetime.date(y, m, d).togregorian()
        return Visit.objects.create(
            customer=self.customer,
            start_at=timezone.make_aware(datetime(greg.year, greg.month, greg.day, 10, 0)),
            end_at=timezone.make_aware(datetime(greg.year, greg.month, greg.day, 11, 0)),
        )

    def test_current_count_and_change_percent(self):
        self._visit_at_shamsi(1404, 1, 2)
        self._visit_at_shamsi(1404, 1, 5)
        self._visit_at_shamsi(1403, 12, 25)
        response = self.client.get('/api/reports/visits/?date_from=1404-01-01&date_to=1404-01-10')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['current_count'], 2)
        self.assertEqual(response.data['previous_count'], 1)
        self.assertEqual(response.data['change_percent'], 100.0)

    def test_empty_previous_period_yields_none_change(self):
        self._visit_at_shamsi(1404, 1, 2)
        response = self.client.get('/api/reports/visits/?date_from=1404-01-01&date_to=1404-01-10')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['current_count'], 1)
        self.assertIsNone(response.data['change_percent'])

    def test_without_range_change_fields_are_none(self):
        self._visit_at_shamsi(1404, 1, 2)
        response = self.client.get('/api/reports/visits/')
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.data['previous_count'])
        self.assertIsNone(response.data['change_percent'])

    def test_invalid_date_param_returns_400(self):
        response = self.client.get('/api/reports/visits/?date_from=bogus')
        self.assertEqual(response.status_code, 400)


class CustomerReportViewTests(TestCase):
    def setUp(self):
        self.client = admin_client()

    def test_breakdown_and_segments(self):
        from datetime import timedelta
        alice = Customer.objects.create(
            first_name='Alice', last_name='A',
            mobile_number='09124444444', national_id='004-0000004',
        )
        bob = Customer.objects.create(
            first_name='Bob', last_name='B',
            mobile_number='09125555555', national_id='005-0000005',
        )
        for day in range(1, 6):
            Visit.objects.create(
                customer=alice,
                status='completed',
                start_at=timezone.make_aware(datetime(2025, 6, day, 9, 0)),
                end_at=timezone.make_aware(datetime(2025, 6, day, 10, 0)),
            )
        Visit.objects.create(
            customer=bob,
            status='canceled',
            start_at=timezone.now(),
            end_at=timezone.now() + timedelta(hours=1),
        )
        response = self.client.get('/api/reports/customers/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['total'], 2)
        self.assertEqual(response.data['by_visit_status']['completed'], 5)
        self.assertEqual(response.data['by_visit_status']['canceled'], 1)
        self.assertEqual(response.data['loyal_customers'], 1)
        self.assertEqual(response.data['new_customers'], 0)


class ReferralReportViewTests(TestCase):
    def setUp(self):
        self.client = admin_client()

    def test_referral_rate_math(self):
        returning = Customer.objects.create(
            first_name='Ret', last_name='Urn',
            mobile_number='09126666666', national_id='006-0000006',
        )
        single = Customer.objects.create(
            first_name='Sin', last_name='Gle',
            mobile_number='09127777777', national_id='007-0000007',
        )
        for _ in range(2):
            Visit.objects.create(
                customer=returning,
                start_at=timezone.now(),
                end_at=timezone.now(),
            )
        Visit.objects.create(customer=single, start_at=timezone.now(), end_at=timezone.now())

        response = self.client.get('/api/reports/referral/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['total_visits'], 3)
        self.assertEqual(response.data['total_customers'], 2)
        self.assertEqual(response.data['returning_customers'], 1)
        self.assertEqual(response.data['referral_rate'], 50.0)

    def test_referral_rate_zero_division_guarded(self):
        response = self.client.get('/api/reports/referral/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['referral_rate'], 0)


class AllReportsViewTests(TestCase):
    def test_all_periods_and_status_breakdown_present(self):
        client = admin_client()
        response = client.get('/api/reports/all/')
        self.assertEqual(response.status_code, 200)
        for period in ['daily', 'weekly', 'monthly', 'quarterly', 'yearly']:
            self.assertIn(period, response.data['sales_chart'])
        for label in ['pending', 'confirmed', 'completed', 'canceled']:
            self.assertIn(label, response.data['customer_status'])
        self.assertIn('total_sales', response.data)
        self.assertIn('service_popularity', response.data)
