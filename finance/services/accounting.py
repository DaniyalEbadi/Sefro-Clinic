from decimal import Decimal
from typing import Optional

from django.db import transaction
from django.utils import timezone

from ..models import ServiceItem
from .inventory import record_product_usage


@transaction.atomic
def record_visit_consumption(visit, *, selected_products=None, at: Optional[object] = None, rate=None):
    """Record actual product consumption for a completed visit.

    `selected_products` is an optional dict mapping service_id -> list of
    (product_id, quantity) tuples, allowing the operator to choose which exact
    product/brand was used. When omitted, the service's configured ServiceItem
    relations are used. Historical cost is snapshotted at record time.
    """
    at = at or timezone.now()
    from customers.models import Service
    from inventory.models import Product

    consumed = []
    service_ids = list(visit.services.values_list('id', flat=True))
    services = Service.objects.filter(id__in=service_ids)
    products_cache = {p.id: p for p in Product.objects.filter(
        id__in=_collect_product_ids(service_ids, selected_products),
    )}

    for service in services:
        if selected_products and service.id in selected_products:
            items = [
                (products_cache[pid], Decimal(qty))
                for pid, qty in selected_products[service.id]
                if pid in products_cache
            ]
        else:
            items = [
                (si.product, si.quantity)
                for si in ServiceItem.objects.filter(service=service).select_related('product')
            ]
        for product, qty in items:
            usage = record_product_usage(
                product=product,
                quantity=qty,
                visit=visit,
                service=service,
                at=at,
                rate=rate,
            )
            consumed.append(usage)
    return consumed


def _collect_product_ids(service_ids, selected_products):
    ids = set()
    if selected_products:
        for sid, lst in selected_products.items():
            for pid, _ in lst:
                ids.add(pid)
    for si in ServiceItem.objects.filter(service_id__in=service_ids).values_list('product_id', flat=True):
        ids.add(si)
    return ids
