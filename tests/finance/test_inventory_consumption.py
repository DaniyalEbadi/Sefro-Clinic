from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
from threading import Barrier

from django.db import close_old_connections
from django.test import TransactionTestCase
from django.utils import timezone

from customers.models import Service, Visit
from finance.models import ProductUsage, ServiceItem
from finance.services import accounting
from finance.services.accounting import ConsumptionError
from inventory.models import Product
from tests.helpers import make_customer


class ConcurrentVisitConsumptionTests(TransactionTestCase):
    """Regression coverage for row locking on treatment inventory."""

    reset_sequences = True

    def setUp(self):
        self.product = Product.objects.create(
            name='Concurrent vial', unit_price=Decimal('10'), cost_usd=Decimal('5'), count=Decimal('1'),
        )
        self.service = Service.objects.create(name='Concurrent treatment', price_usd=Decimal('50'))
        ServiceItem.objects.create(service=self.service, product=self.product, quantity=Decimal('1'))
        self.visit = Visit.objects.create(
            customer=make_customer(),
            start_at=timezone.now(), end_at=timezone.now() + timedelta(minutes=30),
            status=Visit.Status.COMPLETED,
        )
        self.visit.services.add(self.service)

    def test_concurrent_requests_consume_stock_only_once(self):
        barrier = Barrier(2)

        def consume():
            close_old_connections()
            try:
                visit = Visit.objects.get(pk=self.visit.pk)
                barrier.wait(timeout=10)
                accounting.record_visit_consumption(visit, rate=Decimal('100000'))
                return 'consumed'
            except ConsumptionError:
                return 'rejected'
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: consume(), range(2)))

        self.assertCountEqual(results, ['consumed', 'rejected'])
        self.product.refresh_from_db()
        self.assertEqual(self.product.count, Decimal('0.000'))
        self.assertEqual(ProductUsage.objects.filter(visit=self.visit, is_commission=False).count(), 1)
