from collections import defaultdict
from decimal import Decimal, InvalidOperation
from typing import Optional

from django.db import transaction
from django.utils import timezone

from ..models import ProductUsage, ServiceItem
from .inventory import InventoryError, record_product_usage


class ConsumptionError(ValueError):
    """A user-correctable error in a visit consumption request."""


def missing_recipe_services(visit):
    """Return recipe-backed services whose actual consumption is incomplete."""
    from customers.models import Service

    service_ids = list(visit.services.values_list('id', flat=True))
    services = Service.objects.filter(id__in=service_ids).prefetch_related('items')
    usages = set(
        ProductUsage.objects.filter(
            visit=visit,
            package_sale__isnull=True,
            welcome_pack_usage__isnull=True,
            is_commission=False,
        ).values_list('service_id', 'product_id')
    )
    missing = []
    for service in services:
        items = list(service.items.all())
        if not items:
            continue
        used_products = {product_id for service_id, product_id in usages if service_id == service.id}
        mandatory_missing = any(
            not item.selection_group and item.product_id not in used_products
            for item in items
        )
        groups = {item.selection_group for item in items if item.selection_group}
        group_missing = any(
            not any(item.selection_group == group and item.product_id in used_products for item in items)
            for group in groups
        )
        if mandatory_missing or group_missing:
            missing.append(service.name)
    return missing


def _parse_quantity(value, *, allow_zero=False) -> Decimal:
    try:
        quantity = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ConsumptionError('Quantity must be a valid decimal.') from exc
    if not quantity.is_finite() or quantity < 0 or (quantity == 0 and not allow_zero):
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


def _normalise_extra_products(extra_products):
    """Return [(product_id, Decimal quantity)] for billable non-recipe products.

    Manual invoice extras («محصولات این صورتحساب») are not part of any service
    recipe but must still decrement stock and leave a cost snapshot so reports
    count their cost. Their ProductUsage rows carry ``service=None`` — summed
    as visit-unattributed cost, following the welcome-pack precedent.
    """
    if extra_products is None:
        return []
    if not isinstance(extra_products, (list, tuple)):
        raise ConsumptionError('extra_products must be a list of [product_id, quantity] pairs.')

    parsed = []
    seen_product_ids = set()
    for entry in extra_products:
        if not isinstance(entry, (list, tuple)) or len(entry) != 2:
            raise ConsumptionError('Each extra product must be [product_id, quantity].')
        raw_product_id, raw_quantity = entry
        try:
            if isinstance(raw_product_id, bool):
                raise ValueError
            product_id = int(raw_product_id)
        except (TypeError, ValueError) as exc:
            raise ConsumptionError('Invalid product id.') from exc
        if product_id in seen_product_ids:
            raise ConsumptionError(f'Duplicate extra product {product_id}.')
        seen_product_ids.add(product_id)
        parsed.append((product_id, _parse_quantity(raw_quantity)))
    return parsed


def _normalise_zero_consumption(zero_consumption, service_ids):
    if zero_consumption is None:
        return {}
    if not isinstance(zero_consumption, dict):
        raise ConsumptionError('zero_consumption must be an object keyed by service id.')
    result = {}
    for raw_service_id, reason in zero_consumption.items():
        try:
            service_id = int(raw_service_id)
        except (TypeError, ValueError) as exc:
            raise ConsumptionError('Invalid service id in zero_consumption.') from exc
        if service_id not in service_ids:
            raise ConsumptionError(f'Service {service_id} does not belong to this visit.')
        if not isinstance(reason, str) or not reason.strip():
            raise ConsumptionError(f'A reason is required for zero consumption on service {service_id}.')
        result[service_id] = reason.strip()
    return result


@transaction.atomic
def record_visit_consumption(
    visit, *, selected_products=None, extra_products=None, zero_consumption=None,
    at: Optional[object] = None, rate=None,
):
    """Atomically consume a visit recipe and snapshot actual product costs.

    The legacy ``{service_id: [[product_id, quantity]]}`` payload remains in
    use. Mandatory items are automatic; explicitly supplying a mandatory item
    is the previously supported quantity override. Every configured selection
    group requires exactly one selected item.

    ``extra_products`` are billable non-recipe products added to the invoice by
    the operator. They draw down stock and leave a cost snapshot just like
    recipe materials, but carry no service. A shortage on either a recipe item
    or an extra rolls the whole call back.
    """
    from customers.models import Service, Visit
    from inventory.models import Product

    at = at or timezone.now()
    try:
        visit = Visit.objects.select_for_update().get(pk=visit.pk)
    except Visit.DoesNotExist as exc:
        raise ConsumptionError('Visit not found.') from exc

    service_ids = set(visit.services.values_list('id', flat=True))
    selected = _normalise_selected_products(selected_products, service_ids)
    zero_services = _normalise_zero_consumption(zero_consumption, service_ids)
    extras = _normalise_extra_products(extra_products)
    # A visit may be recorded in multiple calls, one service at a time. A
    # retry for a service already recorded is rejected, while another service
    # on the same visit can still be recorded independently. Extras remain a
    # single visit-level event.
    requested_service_ids = set(selected) | set(zero_services)
    existing_usage = ProductUsage.objects.filter(
        visit=visit,
        service_id__in=requested_service_ids,
        package_sale__isnull=True,
        is_commission=False,
        welcome_pack_usage__isnull=True,
    ).exists()
    if existing_usage:
        raise ConsumptionError('Consumption has already been recorded for one of the requested services.')
    if extras and ProductUsage.objects.filter(
        visit=visit, service__isnull=True, package_sale__isnull=True,
        is_commission=False, welcome_pack_usage__isnull=True,
    ).exists():
        raise ConsumptionError('Visit extras consumption has already been recorded.')
    if not requested_service_ids and not extras and ProductUsage.objects.filter(
        visit=visit, package_sale__isnull=True, is_commission=False,
        welcome_pack_usage__isnull=True,
    ).exists():
        raise ConsumptionError('Consumption has already been recorded for this visit.')
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
        if configured_items and service.id not in requested_service_ids:
            # Multi-service visits may confirm each service in separate
            # requests. Completion checks the remaining services afterwards.
            continue
        if service.id in zero_services:
            usage_specs.extend(
                (service, item.product_id, Decimal('0'), zero_services[service.id])
                for item in configured_items
            )
            continue
        if configured_items and service.id not in selected:
            raise ConsumptionError(
                f'Actual consumption is required for service {service.id}; '
                'provide selected_products or zero_consumption.'
            )
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
                if item.product_id not in service_selected:
                    raise ConsumptionError(
                        f'Actual quantity is required for product {item.product_id} on service {service.id}.'
                    )
                usage_specs.append((service, item.product_id, service_selected.pop(item.product_id), None))

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
            usage_specs.append((service, product_id, service_selected.pop(product_id), None))

        if service_selected:
            raise ConsumptionError(f'Invalid selection for service {service.id}.')

    product_ids = {product_id for _, product_id, _, _ in usage_specs}
    product_ids.update(product_id for product_id, _ in extras)
    locked_products = {
        product.id: product
        for product in Product.objects.select_for_update().filter(id__in=product_ids).order_by('id')
    }
    if len(locked_products) != len(product_ids):
        raise ConsumptionError('One or more selected products do not exist.')

    total_by_product = defaultdict(lambda: Decimal('0'))
    for _, product_id, quantity, _ in usage_specs:
        total_by_product[product_id] += _parse_quantity(quantity, allow_zero=True)
    for product_id, quantity in extras:
        total_by_product[product_id] += quantity
    for product_id, required_quantity in total_by_product.items():
        product = locked_products[product_id]
        if required_quantity > Decimal(product.count or 0):
            raise ConsumptionError(
                f'Insufficient stock for product "{product.name}": '
                f'available {product.count}, requested {required_quantity}.'
            )

    consumed = []
    try:
        for service, product_id, quantity, zero_reason in usage_specs:
            consumed.append(record_product_usage(
                product=locked_products[product_id],
                quantity=quantity,
                visit=visit,
                service=service,
                at=at,
                rate=rate,
                zero_reason=zero_reason,
                decrement_stock=True,
            ))
        for product_id, quantity in extras:
            consumed.append(record_product_usage(
                product=locked_products[product_id],
                quantity=quantity,
                visit=visit,
                service=None,
                at=at,
                rate=rate,
                decrement_stock=True,
            ))
    except InventoryError as exc:
        raise ConsumptionError(str(exc)) from exc
    return consumed
