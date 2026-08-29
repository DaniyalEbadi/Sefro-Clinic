from datetime import datetime, time
from decimal import Decimal
from typing import Optional

from django.db import transaction
from django.utils import timezone

from ..models import ProductCostHistory, ProductPurchase, ProductUsage
from .exchange_rates import get_rate


def current_cost(product, at: Optional[object] = None) -> Decimal:
    when = at or timezone.now()
    if isinstance(when, str):
        when = timezone.now()
    history = ProductCostHistory.objects.filter(
        product=product,
        effective_from__lte=when,
    ).filter(
        models_Q_effective_to(when),
    ).order_by('-effective_from').first()
    if history is not None:
        return history.cost_usd
    return product.cost_usd or Decimal('0')


def models_Q_effective_to(when):
    from django.db.models import Q
    return Q(effective_to__isnull=True) | Q(effective_to__gte=when)


@transaction.atomic
def record_product_purchase(
    *,
    product,
    quantity: Decimal,
    unit_cost_usd: Decimal,
    supplier: str = '',
    purchase_date=None,
    rate: Optional[Decimal] = None,
    created_by=None,
):
    purchase_date = purchase_date or timezone.now().date()
    rate = rate if rate is not None else get_rate('USD', 'TOMAN')
    unit_cost_usd = Decimal(unit_cost_usd).quantize(Decimal('0.01'))
    quantity = Decimal(quantity)
    total_cost_usd = (unit_cost_usd * quantity).quantize(Decimal('0.01'))

    purchase = ProductPurchase.objects.create(
        product=product,
        quantity=quantity,
        unit_cost_usd=unit_cost_usd,
        total_cost_usd=total_cost_usd,
        supplier=supplier,
        purchase_date=purchase_date,
        exchange_rate_snapshot=rate,
    )

    product.cost_usd = unit_cost_usd
    product.count = (product.count or 0) + int(quantity)
    product.save(update_fields=['cost_usd', 'count'])

    # Close the previously active cost history entry.
    ProductCostHistory.objects.filter(
        product=product,
        effective_to__isnull=True,
    ).update(effective_to=timezone.make_aware(
        datetime.combine(purchase_date, time.min),
    ))

    ProductCostHistory.objects.create(
        product=product,
        cost_usd=unit_cost_usd,
        effective_from=timezone.make_aware(
            datetime.combine(purchase_date, time.min),
        ),
        effective_to=None,
    )
    return purchase


@transaction.atomic
def record_product_usage(
    *,
    product,
    quantity: Decimal,
    visit=None,
    service=None,
    package_sale=None,
    at: Optional[object] = None,
    rate: Optional[Decimal] = None,
):
    at = at or timezone.now()
    rate = rate if rate is not None else get_rate('USD', 'TOMAN')
    quantity = Decimal(quantity)
    unit_cost = current_cost(product, at=at)
    total_cost = (unit_cost * quantity).quantize(Decimal('0.01'))
    usage = ProductUsage.objects.create(
        product=product,
        visit=visit,
        service=service,
        package_sale=package_sale,
        quantity=quantity,
        unit_cost_usd_snapshot=unit_cost,
        total_cost_usd_snapshot=total_cost,
        exchange_rate_snapshot=rate,
    )
    return usage


def total_product_cost_usd(usages) -> Decimal:
    return sum((u.total_cost_usd_snapshot or Decimal('0') for u in usages), Decimal('0')).quantize(Decimal('0.01'))
