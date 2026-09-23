from collections import defaultdict
from decimal import Decimal, InvalidOperation
from typing import Optional

from django.db import transaction
from django.utils import timezone

from ..models import ProductUsage, ServiceItem
from .inventory import InventoryError, record_product_usage


class ConsumptionError(ValueError):
    """A user-correctable error in a visit consumption request."""


def _parse_quantity(value) -> Decimal:
    try:
        quantity = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ConsumptionError('Quantity must be a valid decimal.') from exc
    if not quantity.is_finite() or quantity <= 0:
        raise ConsumptionError('Quantity must be greater than zero.')
    if quantity.as_tuple().exponent < -3:
        raise ConsumptionError('Quantity cannot have more than three decimal places.')
    return quantity


def _normalise_selected_products(selected_products, service_ids):
    """Return service_id -> [(product_id, Decimal quantity)] with untrusted input checked."""
    if selected_products is None:
        return {}
    if not isinstance(selected_products, dict):
        raise ConsumptionError('selected_products must be an object keyed by service id.')

    selected = {}
    for raw_service_id, entries in selected_products.items():
        try:
            if isinstance(raw_service_id, bool):
                raise ValueError
            service_id = int(raw_service_id)
        except (TypeError, ValueError) as exc:
            raise ConsumptionError('Invalid service id in selected_products.') from exc
        if service_id not in service_ids:
            raise ConsumptionError(f'Service {service_id} does not belong to this visit.')
        if not isinstance(entries, (list, tuple)):
            raise ConsumptionError(f'Selections for service {service_id} must be a list.')

        parsed_entries = []
        seen_product_ids = set()
        for entry in entries:
            if not isinstance(entry, (list, tuple)) or len(entry) != 2:
                raise ConsumptionError('Each selected product must be [product_id, quantity].')
            raw_product_id, raw_quantity = entry
            try:
                if isinstance(raw_product_id, bool):
                    raise ValueError
                product_id = int(raw_product_id)
            except (TypeError, ValueError) as exc:
                raise ConsumptionError('Invalid product id.') from exc
            if product_id in seen_product_ids:
                raise ConsumptionError(f'Duplicate selection for product {product_id}.')
            seen_product_ids.add(product_id)
            parsed_entries.append((product_id, _parse_quantity(raw_quantity)))
        selected[service_id] = parsed_entries
    return selected


@transaction.atomic
def record_visit_consumption(visit, *, selected_products=None, at: Optional[object] = None, rate=None):
    """Atomically consume a visit recipe and snapshot actual product costs.

    The legacy ``{service_id: [[product_id, quantity]]}`` payload remains in
    use. Mandatory items are automatic; explicitly supplying a mandatory item
    is the previously supported quantity override. Every configured selection
    group requires exactly one selected item.
    """
    from customers.models import Service, Visit
    from inventory.models import Product

    at = at or timezone.now()
    try:
        visit = Visit.objects.select_for_update().get(pk=visit.pk)
    except Visit.DoesNotExist as exc:
        raise ConsumptionError('Visit not found.') from exc

    # A retry/double-click must not consume stock twice. Commission usage is a
    # distinct event and must not make normal treatment consumption look done.
    if ProductUsage.objects.filter(
        visit=visit, package_sale__isnull=True, is_commission=False,
    ).exists():
        raise ConsumptionError('Consumption has already been recorded for this visit.')

    service_ids = set(visit.services.values_list('id', flat=True))
    selected = _normalise_selected_products(selected_products, service_ids)
    services = list(Service.objects.filter(id__in=service_ids).order_by('id'))
    service_items = list(
        ServiceItem.objects.filter(service_id__in=service_ids)
        .select_related('product')
        .order_by('service_id', 'id')
    )
    items_by_service = defaultdict(list)
    for item in service_items:
        items_by_service[item.service_id].append(item)

    usage_specs = []
    for service in services:
        configured_items = items_by_service[service.id]
        allowed_by_product = {item.product_id: item for item in configured_items}
        service_selected = {product_id: quantity for product_id, quantity in selected.get(service.id, [])}

        for product_id in service_selected:
            if product_id not in allowed_by_product:
                raise ConsumptionError(
                    f'Product {product_id} is not configured for service {service.id}.'
                )

        # NULL (and legacy blank values) is the mandatory/default recipe.
        for item in configured_items:
            if not item.selection_group:
                usage_specs.append((service, item.product_id, service_selected.pop(item.product_id, item.quantity)))

        groups = defaultdict(list)
        for item in configured_items:
            if item.selection_group:
                groups[item.selection_group].append(item)
        for group_name, group_items in groups.items():
            group_product_ids = {item.product_id for item in group_items}
            group_selected = [product_id for product_id in service_selected if product_id in group_product_ids]
            if len(group_selected) != 1:
                if not group_selected:
                    raise ConsumptionError(
                        f'Missing required selection group "{group_name}" for service {service.id}.'
                    )
                raise ConsumptionError(
                    f'Multiple products selected for selection group "{group_name}" on service {service.id}.'
                )
            product_id = group_selected[0]
            usage_specs.append((service, product_id, service_selected.pop(product_id)))

        if service_selected:
            raise ConsumptionError(f'Invalid selection for service {service.id}.')

    product_ids = {product_id for _, product_id, _ in usage_specs}
    locked_products = {
        product.id: product
        for product in Product.objects.select_for_update().filter(id__in=product_ids).order_by('id')
    }
    if len(locked_products) != len(product_ids):
        raise ConsumptionError('One or more selected products do not exist.')

    total_by_product = defaultdict(lambda: Decimal('0'))
    for _, product_id, quantity in usage_specs:
        total_by_product[product_id] += _parse_quantity(quantity)
    for product_id, required_quantity in total_by_product.items():
        product = locked_products[product_id]
        if required_quantity > Decimal(product.count or 0):
            raise ConsumptionError(
                f'Insufficient stock for product "{product.name}": '
                f'available {product.count}, requested {required_quantity}.'
            )

    consumed = []
    try:
        for service, product_id, quantity in usage_specs:
            consumed.append(record_product_usage(
                product=locked_products[product_id],
                quantity=quantity,
                visit=visit,
                service=service,
                at=at,
                rate=rate,
                decrement_stock=True,
            ))
    except InventoryError as exc:
        raise ConsumptionError(str(exc)) from exc
    return consumed
