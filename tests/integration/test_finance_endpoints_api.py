"""Endpoint coverage for the finance ViewSets that previously had no tests.

Previously zero API coverage for: packages, package items/services, wallet
reward rules, product purchases, product cost history, product usages, wallet
transactions, expense categories, the sales refund endpoint, the
record-consumption endpoint, and the profit/wallet report views.
"""
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from customers.models import Service, Visit
from finance.models import (
    Package,
    PackageItem,
    PackageService,
    PaymentComponent,
    ProductCostHistory,
    ProductUsage,
    Sale,
    ServiceItem,
    Wallet,
    WalletRewardRule,
    WalletTransaction,
)
from finance.services.exchange_rates import set_rate
from inventory.models import Product
from tests.helpers import admin_client, employee_client, make_customer

RATE = Decimal('100000')


def make_product(**overrides):
    base = {'name': 'Serum', 'sku': 'SKU-1', 'unit_price': Decimal('100'),
            'cost_usd': Decimal('20.00'), 'count': 5}
    base.update(overrides)
    return Product.objects.create(**base)


class PackageAPITests(TestCase):
    URL = '/api/finance/packages/'

    def setUp(self):
        self.client = admin_client()
        set_rate('USD', 'TOMAN', RATE)
        self.service = Service.objects.create(name='Botox', price_usd=Decimal('150'))
        self.product = make_product()

    def test_admin_can_create_list_update_and_delete(self):
        created = self.client.post(self.URL, {'name': 'Rejuvenation', 'price_usd': '300.00',
                                              'description': 'Bundle'}, format='json')
        self.assertEqual(created.status_code, 201, created.data)
        package_id = created.data['id']

        listed = self.client.get(self.URL)
        self.assertEqual(listed.data['count'], 1)

        updated = self.client.patch(f'{self.URL}{package_id}/', {'price_usd': '280.00'}, format='json')
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(Decimal(updated.data['price_usd']), Decimal('280.00'))

        deleted = self.client.delete(f'{self.URL}{package_id}/')
        self.assertEqual(deleted.status_code, 204)

    def test_created_package_exposes_toman_price_and_children(self):
        created = self.client.post(self.URL, {'name': 'Glow', 'price_usd': '250.00'}, format='json')
        package_id = created.data['id']
        PackageService.objects.create(package_id=package_id, service=self.service)
        PackageItem.objects.create(package_id=package_id, product=self.product, quantity=Decimal('2'))

        detail = self.client.get(f'{self.URL}{package_id}/')
        self.assertEqual(Decimal(detail.data['price_toman']), Decimal('25000000.00'))
        self.assertEqual(detail.data['services'], [self.service.id])
        self.assertEqual(detail.data['items'], [{'product': self.product.id, 'quantity': '2.000'}])

    def test_search_filter(self):
        self.client.post(self.URL, {'name': 'Radiance', 'price_usd': '100.00'}, format='json')
        self.client.post(self.URL, {'name': 'Detox', 'price_usd': '120.00'}, format='json')
        self.assertEqual(self.client.get(self.URL).data['count'], 2)
        self.assertEqual(self.client.get(f'{self.URL}?search=radiance').data['count'], 1)

    def test_employee_is_read_only(self):
        Package.objects.create(name='Bundle', price_usd=Decimal('50.00'))
        employee = employee_client()
        self.assertEqual(employee.get(self.URL).status_code, 200)
        self.assertEqual(
            employee.post(self.URL, {'name': 'X', 'price_usd': '1.00'}, format='json').status_code,
            403,
        )

    def test_anonymous_is_rejected(self):
        self.assertEqual(APIClient().get(self.URL).status_code, 401)


class PackageChildAPITests(TestCase):
    def setUp(self):
        self.client = admin_client()
        set_rate('USD', 'TOMAN', RATE)
        self.package = Package.objects.create(name='Combo', price_usd=Decimal('80.00'))
        self.service = Service.objects.create(name='Peel', price_usd=Decimal('60'))
        self.product = make_product()

    def test_package_service_link(self):
        response = self.client.post('/api/finance/package-services/', {
            'package': self.package.id, 'service': self.service.id,
        }, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        # duplicate pair must be rejected by the unique constraint
        dup = self.client.post('/api/finance/package-services/', {
            'package': self.package.id, 'service': self.service.id,
        }, format='json')
        self.assertEqual(dup.status_code, 400)

    def test_package_item_link(self):
        response = self.client.post('/api/finance/package-items/', {
            'package': self.package.id, 'product': self.product.id, 'quantity': '3',
        }, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(Decimal(response.data['quantity']), Decimal('3.000'))


class WalletRewardRuleAPITests(TestCase):
    URL = '/api/finance/reward-rules/'

    def setUp(self):
        self.client = admin_client()

    def _payload(self, name='Birthday Bonus'):
        return {
            'name': name, 'rule_type': WalletRewardRule.RuleType.PERCENTAGE,
            'value': '5.00', 'min_base_amount_usd': '100.00',
            'applies_to': WalletRewardRule.AppliesTo.PAYMENT,
            'is_active': True,
        }

    def test_admin_can_create_update_delete(self):
        created = self.client.post(self.URL, self._payload(), format='json')
        self.assertEqual(created.status_code, 201, created.data)
        rule_id = created.data['id']

        updated = self.client.patch(f'{self.URL}{rule_id}/', {'value': '7.50'}, format='json')
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(Decimal(updated.data['value']), Decimal('7.50'))

        self.assertEqual(self.client.delete(f'{self.URL}{rule_id}/').status_code, 204)
        self.assertEqual(self.client.get(self.URL).data['count'], 0)

    def test_read_is_allowed_for_employees(self):
        WalletRewardRule.objects.create(name='Referral', value='1.00')
        self.assertEqual(employee_client().get(self.URL).status_code, 200)

    def test_employee_cannot_create(self):
        response = employee_client().post(self.URL, self._payload(name='Emp Rule'), format='json')
        self.assertEqual(response.status_code, 403)


class ExpenseCategoryAPITests(TestCase):
    URL = '/api/finance/expense-categories/'

    def setUp(self):
        self.client = admin_client()

    def test_admin_can_create_and_list(self):
        created = self.client.post(self.URL, {'name': 'Rent', 'is_active': True}, format='json')
        self.assertEqual(created.status_code, 201, created.data)
        self.assertEqual(self.client.get(self.URL).data['count'], 1)

    def test_employee_cannot_create(self):
        response = employee_client().post(self.URL, {'name': 'Marketing'}, format='json')
        self.assertEqual(response.status_code, 403)

    def test_expenses_can_reference_category(self):
        category = self.client.post(self.URL, {'name': 'Utilities'}, format='json').data['id']
        response = self.client.post('/api/finance/expenses/', {
            'category': category, 'amount_usd': '40.00', 'vendor': 'Power Co',
            'expense_date': timezone.now().date().isoformat(),
        }, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data['category'], category)


class ProductPurchaseAPITests(TestCase):
    URL = '/api/finance/product-purchases/'

    def setUp(self):
        self.client = admin_client()
        set_rate('USD', 'TOMAN', RATE)
        self.product = make_product()

    def test_create_updates_stock_cost_and_history(self):
        today = timezone.now().date().isoformat()
        response = self.client.post(self.URL, {
            'product': self.product.id, 'quantity': '10',
            'unit_cost_usd': '15.00', 'supplier': 'Acme',
            'purchase_date': today,
        }, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(Decimal(response.data['total_cost_usd']), Decimal('150.00'))

        self.product.refresh_from_db()
        self.assertEqual(self.product.cost_usd, Decimal('15.00'))
        self.assertEqual(self.product.count, 15)

        history = ProductCostHistory.objects.filter(product=self.product, effective_to__isnull=True)
        self.assertEqual(history.count(), 1)
        self.assertEqual(history.get().cost_usd, Decimal('15.00'))

    def test_cost_history_endpoint_lists_entries(self):
        self.client.post(self.URL, {
            'product': self.product.id, 'quantity': '1',
            'unit_cost_usd': '12.00', 'purchase_date': timezone.now().date().isoformat(),
        }, format='json')
        listing = self.client.get('/api/finance/product-cost-history/')
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(listing.data['count'], 1)
        self.assertEqual(listing.data['results'][0]['cost_usd'], '12.00')

    def test_employee_cannot_create_purchase(self):
        response = employee_client().post(self.URL, {
            'product': self.product.id, 'quantity': '1',
            'unit_cost_usd': '1.00', 'purchase_date': timezone.now().date().isoformat(),
        }, format='json')
        self.assertEqual(response.status_code, 403)


class ProductUsageAPITests(TestCase):
    URL = '/api/finance/product-usages/'

    def setUp(self):
        self.client = admin_client()
        set_rate('USD', 'TOMAN', RATE)
        self.customer = make_customer()
        self.service = Service.objects.create(name='Massage', price_usd=Decimal('80'))
        self.product = make_product()
        self.visit = Visit.objects.create(
            customer=self.customer, start_at=timezone.now(),
            end_at=timezone.now() + timedelta(hours=1),
        )
        self.visit.services.add(self.service)
        ProductUsage.objects.create(
            product=self.product, visit=self.visit, service=self.service,
            quantity=Decimal('1'), unit_cost_usd_snapshot=Decimal('20.00'),
            total_cost_usd_snapshot=Decimal('20.00'), exchange_rate_snapshot=RATE,
        )

    def test_list_is_filterable_by_visit_service_and_product(self):
        self.assertEqual(self.client.get(self.URL).data['count'], 1)
        self.assertEqual(self.client.get(f'{self.URL}?visit={self.visit.id}').data['count'], 1)
        self.assertEqual(self.client.get(f'{self.URL}?service={self.service.id}').data['count'], 1)
        self.assertEqual(self.client.get(f'{self.URL}?product={self.product.id}').data['count'], 1)
        self.assertEqual(self.client.get(f'{self.URL}?visit=999999').data['count'], 0)

    def test_employee_can_read(self):
        self.assertEqual(employee_client().get(self.URL).status_code, 200)


class SaleAndRefundAPITests(TestCase):
    URL = '/api/finance/sales/'

    def setUp(self):
        self.client = admin_client()
        set_rate('USD', 'TOMAN', RATE)
        self.customer = make_customer()
        self.sale = Sale.objects.create(
            customer=self.customer, amount_usd=Decimal('100.00'),
            amount_toman=Decimal('10000000.00'), exchange_rate=RATE,
            status=Sale.Status.PAID,
        )
        PaymentComponent.objects.create(
            sale=self.sale, method=PaymentComponent.Method.CASH, amount_usd=Decimal('100.00'),
        )

    def test_list_and_filters(self):
        self.assertEqual(self.client.get(self.URL).data['count'], 1)
        self.assertEqual(self.client.get(f'{self.URL}?status={Sale.Status.PAID}').data['count'], 1)
        self.assertEqual(self.client.get(f'{self.URL}?status={Sale.Status.REFUNDED}').data['count'], 0)

    def test_partial_refund_creates_negative_sale(self):
        response = self.client.post(f'{self.URL}{self.sale.id}/refund/', {
            'refund_amount_usd': '40.00', 'reason': 'Customer changed mind',
        }, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(Decimal(response.data['amount_usd']), Decimal('-40.00'))
        self.assertEqual(response.data['status'], Sale.Status.REFUNDED)
        self.sale.refresh_from_db()
        self.assertEqual(self.sale.status, Sale.Status.PARTIALLY_REFUNDED)

    def test_full_refund_marks_sale_refunded(self):
        response = self.client.post(f'{self.URL}{self.sale.id}/refund/', {}, format='json')
        self.assertEqual(response.status_code, 201)
        self.sale.refresh_from_db()
        self.assertEqual(self.sale.status, Sale.Status.REFUNDED)

    def test_refund_larger_than_sale_is_rejected(self):
        response = self.client.post(f'{self.URL}{self.sale.id}/refund/', {
            'refund_amount_usd': '500.00',
        }, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertIn('error', response.data)

    def test_second_refund_is_rejected(self):
        self.client.post(f'{self.URL}{self.sale.id}/refund/', {'refund_amount_usd': '10.00'}, format='json')
        again = self.client.post(f'{self.URL}{self.sale.id}/refund/', {'refund_amount_usd': '10.00'}, format='json')
        self.assertEqual(again.status_code, 400)

    def test_anonymous_is_rejected(self):
        self.assertEqual(APIClient().get(self.URL).status_code, 401)


class ExchangeRateAPITests(TestCase):
    URL = '/api/finance/exchange-rates/'

    def setUp(self):
        self.client = admin_client()
        set_rate('USD', 'TOMAN', RATE)

    def test_admin_can_create_and_list(self):
        before = self.client.get(self.URL).data['count']
        created = self.client.post(self.URL, {
            'currency_from': 'USD', 'currency_to': 'TOMAN', 'rate': '95000.000000',
            'effective_at': timezone.now().isoformat(), 'source': 'test', 'is_active': True,
        }, format='json')
        self.assertEqual(created.status_code, 201, created.data)
        listing = self.client.get(self.URL)
        self.assertEqual(listing.data['count'], before + 1)
        self.assertEqual(
            [r for r in listing.data['results'] if r['source'] == 'test'][0]['rate'],
            '95000.000000',
        )

    def test_employee_cannot_create(self):
        response = employee_client().post(self.URL, {
            'currency_from': 'USD', 'currency_to': 'TOMAN', 'rate': '123',
        }, format='json')
        self.assertEqual(response.status_code, 403)

    def test_invalid_rate_is_rejected(self):
        response = self.client.post(self.URL, {
            'currency_from': 'USD', 'currency_to': 'TOMAN', 'rate': '-5',
        }, format='json')
        self.assertEqual(response.status_code, 400)


class WalletTransactionAPITests(TestCase):
    URL = '/api/finance/wallet-transactions/'

    def setUp(self):
        self.client = admin_client()
        self.customer = make_customer()
        self.wallet = Wallet.objects.create(customer=self.customer, balance=Decimal('50.00'))
        WalletTransaction.objects.create(
            wallet=self.wallet, transaction_type=WalletTransaction.Type.MANUAL_CREDIT,
            amount=Decimal('50.00'), balance_after=Decimal('50.00'),
        )

    def test_list_and_filter_by_wallet(self):
        listing = self.client.get(self.URL)
        self.assertEqual(listing.data['count'], 1)
        self.assertEqual(listing.data['results'][0]['wallet'], self.wallet.id)

        other = make_customer(mobile_number='09120000999', national_id='999-9999999')
        empty_wallet = Wallet.objects.create(customer=other, balance=Decimal('0'))
        self.assertEqual(self.client.get(f'{self.URL}?wallet={empty_wallet.id}').data['count'], 0)

    def test_employee_can_read(self):
        self.assertEqual(employee_client().get(self.URL).status_code, 200)


class RecordConsumptionAPITests(TestCase):
    URL = '/api/finance/visits/{pk}/record-consumption/'

    def setUp(self):
        self.client = admin_client()
        set_rate('USD', 'TOMAN', RATE)
        self.customer = make_customer()
        self.product = make_product()
        self.service = Service.objects.create(name='Facial', price_usd=Decimal('90'))
        ServiceItem.objects.create(service=self.service, product=self.product, quantity=Decimal('2'))
        self.visit = Visit.objects.create(
            customer=self.customer, start_at=timezone.now(),
            end_at=timezone.now() + timedelta(hours=1),
            status=Visit.Status.COMPLETED,
        )
        self.visit.services.add(self.service)

    def _post(self, pk, payload=None):
        return self.client.post(self.URL.format(pk=pk), payload or {}, format='json')

    def test_records_usage_from_service_items(self):
        response = self._post(self.visit.id)
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(Decimal(response.data[0]['total_cost_usd_snapshot']), Decimal('40.00'))
        self.assertEqual(ProductUsage.objects.count(), 1)
        self.product.refresh_from_db()
        self.assertEqual(self.product.count, Decimal('3.000'))

    def test_unknown_visit_returns_404(self):
        self.assertEqual(self._post(999999).status_code, 404)

    def test_selected_products_override_is_honoured_for_a_configured_product(self):
        other = make_product(name='Premium Serum', sku='SKU-2', cost_usd=Decimal('50.00'))
        ServiceItem.objects.create(
            service=self.service, product=other, quantity=Decimal('1'), selection_group='serum',
        )
        payload = {'selected_products': {str(self.service.id): [[other.id, '1']]}}
        response = self._post(self.visit.id, payload)
        self.assertEqual(response.status_code, 201, response.data)
        usage = ProductUsage.objects.get(product=other)
        self.assertEqual(usage.product, other)
        self.assertEqual(Decimal(usage.total_cost_usd_snapshot), Decimal('50.00'))

    def test_selection_group_requires_one_and_consumes_mandatory_items(self):
        alternative = make_product(name='Alternative Serum', sku='SKU-3', count=10)
        ServiceItem.objects.create(
            service=self.service, product=alternative, quantity=Decimal('1'), selection_group='serum',
        )
        missing = self._post(self.visit.id)
        self.assertEqual(missing.status_code, 400)
        self.assertIn('Missing required selection group', missing.data['error'])

        response = self._post(self.visit.id, {
            'selected_products': {str(self.service.id): [[alternative.id, '1.000']]},
        })
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(ProductUsage.objects.filter(product=self.product).count(), 1)
        self.assertEqual(ProductUsage.objects.filter(product=alternative).count(), 1)

    def test_multiple_group_selections_and_unconfigured_product_are_rejected(self):
        alternative = make_product(name='Alternative Serum', sku='SKU-4')
        second_alternative = make_product(name='Second Alternative Serum', sku='SKU-6')
        unrelated = make_product(name='Unrelated', sku='SKU-5')
        ServiceItem.objects.create(
            service=self.service, product=alternative, quantity=Decimal('1'), selection_group='serum',
        )
        ServiceItem.objects.create(
            service=self.service, product=second_alternative, quantity=Decimal('1'), selection_group='serum',
        )
        multiple = self._post(self.visit.id, {
            'selected_products': {str(self.service.id): [[alternative.id, '1'], [second_alternative.id, '1']]},
        })
        self.assertEqual(multiple.status_code, 400)
        self.assertEqual(ProductUsage.objects.count(), 0)

        rejected = self._post(self.visit.id, {
            'selected_products': {str(self.service.id): [[unrelated.id, '1']]},
        })
        self.assertEqual(rejected.status_code, 400)
        self.assertIn('not configured', rejected.data['error'])

    def test_invalid_quantity_insufficient_stock_and_duplicate_retry_are_safe(self):
        invalid = self._post(self.visit.id, {
            'selected_products': {str(self.service.id): [[self.product.id, '0']]},
        })
        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(ProductUsage.objects.count(), 0)

        negative = self._post(self.visit.id, {
            'selected_products': {str(self.service.id): [[self.product.id, '-1']]},
        })
        self.assertEqual(negative.status_code, 400)
        self.assertEqual(ProductUsage.objects.count(), 0)

        self.product.count = Decimal('1.000')
        self.product.save(update_fields=['count'])
        insufficient = self._post(self.visit.id)
        self.assertEqual(insufficient.status_code, 400)
        self.product.refresh_from_db()
        self.assertEqual(self.product.count, Decimal('1.000'))
        self.assertEqual(ProductUsage.objects.count(), 0)

        self.product.count = Decimal('5.000')
        self.product.save(update_fields=['count'])
        accepted = self._post(self.visit.id)
        self.assertEqual(accepted.status_code, 201, accepted.data)
        retry = self._post(self.visit.id)
        self.assertEqual(retry.status_code, 400)
        self.assertEqual(ProductUsage.objects.count(), 1)

    def test_insufficient_product_rolls_back_all_recipe_stock_and_usage(self):
        second = make_product(name='Needle', sku='NEEDLE-1', count=Decimal('0.500'))
        ServiceItem.objects.create(service=self.service, product=second, quantity=Decimal('1'))
        starting_stock = self.product.count

        response = self._post(self.visit.id)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(ProductUsage.objects.count(), 0)
        self.product.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(self.product.count, starting_stock)
        self.assertEqual(second.count, Decimal('0.500'))


class ServiceItemSelectionGroupAPITests(TestCase):
    def test_admin_can_configure_multiple_items_in_one_group(self):
        client = admin_client()
        service = Service.objects.create(name='Filler', price_usd=Decimal('100'))
        first = make_product(name='Filler A', sku='FILLER-A')
        second = make_product(name='Filler B', sku='FILLER-B')
        for product in (first, second):
            response = client.post('/api/finance/service-items/', {
                'service': service.id, 'product': product.id, 'quantity': '1', 'selection_group': 'filler',
            }, format='json')
            self.assertEqual(response.status_code, 201, response.data)
            self.assertEqual(response.data['selection_group'], 'filler')


class FinanceProfitReportAPITests(TestCase):
    def setUp(self):
        self.client = admin_client()
        set_rate('USD', 'TOMAN', RATE)
        self.customer = make_customer()
        self.product = make_product()
        self.service = Service.objects.create(name='Scrub', price_usd=Decimal('100'))
        ServiceItem.objects.create(service=self.service, product=self.product, quantity=Decimal('1'))
        self.visit = Visit.objects.create(
            customer=self.customer, start_at=timezone.now(),
            end_at=timezone.now() + timedelta(hours=1), status=Visit.Status.COMPLETED,
        )
        self.visit.services.add(self.service)
        ProductUsage.objects.create(
            product=self.product, visit=self.visit, service=self.service,
            quantity=Decimal('1'), unit_cost_usd_snapshot=Decimal('20.00'),
            total_cost_usd_snapshot=Decimal('20.00'), exchange_rate_snapshot=RATE,
        )

    def test_profit_by_service(self):
        response = self.client.get('/api/finance/reports/profit-by-service/')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(len(response.data), 1)
        row = response.data[0]
        self.assertEqual(row['service_id'], self.service.id)
        self.assertEqual(row['revenue_usd'], '100.00')
        self.assertEqual(row['product_cost_usd'], '20.00')
        self.assertEqual(row['profit_usd'], '80.00')

    def test_profit_by_service_ignores_unrelated_services(self):
        Service.objects.create(name='Unused', price_usd=Decimal('500'))
        response = self.client.get('/api/finance/reports/profit-by-service/')
        self.assertEqual([row['service_id'] for row in response.data], [self.service.id])

    def test_profit_by_package(self):
        package = Package.objects.create(name='Spa Day', price_usd=Decimal('120.00'))
        PackageService.objects.create(package=package, service=self.service)
        Sale.objects.create(
            customer=self.customer, visit=self.visit, package=package,
            amount_usd=Decimal('120.00'), amount_toman=Decimal('12000000.00'),
            exchange_rate=RATE, status=Sale.Status.PAID,
        )
        response = self.client.get('/api/finance/reports/profit-by-package/')
        self.assertEqual(response.status_code, 200, response.data)
        row = next(r for r in response.data if r['package_id'] == package.id)
        self.assertEqual(row['package_name'], 'Spa Day')

    def test_profit_by_package_empty_is_a_list(self):
        response = self.client.get('/api/finance/reports/profit-by-package/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, [])

    def test_wallet_summary_reports_zero_baseline(self):
        response = self.client.get('/api/finance/reports/wallet-summary/')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['total_liability_usd'], '0')

    def test_wallet_summary_counts_rewards_and_payments(self):
        from finance.services.wallet import credit, grant_reward
        # Rewards are only granted when an active reward rule matches.
        WalletRewardRule.objects.create(
            name='5%', rule_type=WalletRewardRule.RuleType.PERCENTAGE,
            value=Decimal('5'), min_base_amount_usd=Decimal('0'), is_active=True,
        )
        Wallet.objects.create(customer=self.customer, balance=Decimal('0'))
        # A 100.00 base at 5% yields a 5.00 reward.
        grant_reward(self.customer, Decimal('100.00'), reference_type='manual',
                     reference_id=1, rate=RATE, description='reward')
        credit(self.customer, Decimal('10.00'), WalletTransaction.Type.PAYMENT,
               reference_type='manual', reference_id=2, rate=RATE)

        response = self.client.get('/api/finance/reports/wallet-summary/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Decimal(response.data['rewards_issued_usd']), Decimal('5.00'))
        self.assertEqual(Decimal(response.data['wallet_payments_usd']), Decimal('10.00'))
