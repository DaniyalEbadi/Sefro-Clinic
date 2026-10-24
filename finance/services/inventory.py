from datetime import datetime, time
from decimal import Decimal, InvalidOperation
from typing import Optional

from django.db import transaction
from django.utils import timezone

from Sefro_Clinic.shamsi_storage import shamsi_storage_value

from ..models import ProductCostHistory, ProductPurchase, ProductUsage
from .exchange_rates import convert_usd_to_toman, get_rate
from .periods_guard import ensure_open


class InventoryError(ValueError):
    """A user-correctable inventory validation failure."""


def _valid_quantity(value: Decimal) -> Decimal:
    try:
        quantity = Decimal(str(value))
    except Exception as exc:
        raise InventoryError('Quantity must be a valid decimal.') from exc
    if not quantity.is_finite() or quantity <= 0:
        raise InventoryError('Quantity must be greater than zero.')
    if quantity.as_tuple().exponent < -3:
        raise InventoryError('Quantity cannot have more than three decimal places.')
    return quantity


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


def _toman_snapshot(amount_usd: Decimal, rate) -> Decimal:
    """Freeze ``amount_usd`` into Toman using the rate in effect at consumption.

    The rate is a point-in-time fact stored alongside the USD cost, so a
    missing or unusable rate degrades to 0 instead of raising: a stock
    draw-down must never fail because of a currency problem.
    """
    if rate is None:
        return Decimal('0')
    try:
        return convert_usd_to_toman(amount_usd, rate)
    except (ValueError, TypeError, InvalidOperation):
        return Decimal('0')


def _resolve_customer(*, customer=None, visit=None, package_sale=None, welcome_pack_usage=None):
    """Denormalise the consuming customer onto the usage row.

    Every source of a consumption already knows who it belongs to; copying it
    here keeps consumption reportable per customer without a three-way join
    and without losing the link if the source row is later detached.
    """
    if customer is not None:
        return customer
    for source in (visit, package_sale, welcome_pack_usage):
        if source is not None:
            linked = getattr(source, 'customer', None)
            if linked is not None:
                return linked
    return None


@transaction.atomic
def apply_purchase_receipt(*, product, quantity: Decimal, unit_cost_usd: Decimal, purchase_date=None):
    """Add bought stock to a product: lock, set cost, increment count, roll history.

    Shared by the one-shot ``ProductPurchase`` ledger and the purchase-order
    receive step so both keep identical stock/cost semantics. Creates no ledger
    row of its own.
    """
    purchase_date = purchase_date or timezone.now().date()
    quantity = _valid_quantity(quantity)
    unit_cost_usd = Decimal(unit_cost_usd).quantize(Decimal('0.01'))

    # Locking prevents a purchase and a consumption from losing each other's
    # stock update when they happen at the same time.
    product = product.__class__.objects.select_for_update().get(pk=product.pk)

    product.cost_usd = unit_cost_usd
    product.count = Decimal(product.count or 0) + quantity
    product.save(update_fields=['cost_usd', 'count'])

    # Close the previously active cost history entry.
    effective_to = timezone.make_aware(datetime.combine(purchase_date, time.min))
    ProductCostHistory.objects.filter(
        product=product,
        effective_to__isnull=True,
    ).update(
        effective_to=effective_to,
        effective_to_shamsi=shamsi_storage_value(effective_to),
    )

    ProductCostHistory.objects.create(
        product=product,
        cost_usd=unit_cost_usd,
        effective_from=timezone.make_aware(
            datetime.combine(purchase_date, time.min),
        ),
        effective_to=None,
    )
    return product


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
    # A backdated buy would add purchases (and stock cost history) to a month
    # that may already be closed. Guard outside the atomic body below so the
    # refusal's audit row survives its rollback.
    ensure_open(purchase_date, action='record a product purchase in that month',
                object_repr=str(product))
    return _record_product_purchase(
        product=product, quantity=quantity, unit_cost_usd=unit_cost_usd,
        supplier=supplier, purchase_date=purchase_date, rate=rate, created_by=created_by,
    )


@transaction.atomic
def _record_product_purchase(
    *,
    product,
    quantity: Decimal,
    unit_cost_usd: Decimal,
    supplier: str = '',
    purchase_date=None,
    rate: Optional[Decimal] = None,
    created_by=None,
):
    rate = rate if rate is not None else get_rate('USD', 'TOMAN')
    unit_cost_usd = Decimal(unit_cost_usd).quantize(Decimal('0.01'))
    quantity = _valid_quantity(quantity)
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

    apply_purchase_receipt(
        product=product,
        quantity=quantity,
        unit_cost_usd=unit_cost_usd,
        purchase_date=purchase_date,
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
    welcome_pack_usage=None,
    customer=None,
    at: Optional[object] = None,
    rate: Optional[Decimal] = None,
    is_commission: bool = False,
    zero_reason: Optional[str] = None,
    decrement_stock: bool = False,
):
    """Consume stock and freeze the price of that consumption.

    Whatever draws the stock down (recipe materials, invoice extras, welcome
    packs, commission products) lands here, so every row carries the same
    point-in-time facts: unit/total cost in USD, the exchange rate seen at
    that moment, the same cost restated in Toman, and the customer the
    product was given to.
    """
    at = at or timezone.now()
    # The rate is looked up for the moment of consumption, not "now", so a
    # backdated usage carries the exchange rate that was actually in effect.
    rate = rate if rate is not None else get_rate('USD', 'TOMAN', at=at)
    try:
        quantity = Decimal(str(quantity))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise InventoryError('Quantity must be a valid decimal.') from exc
    if quantity == 0:
        if not zero_reason:
            raise InventoryError('A zero consumption quantity requires a reason.')
        if quantity.as_tuple().exponent < -3:
            raise InventoryError('Quantity cannot have more than three decimal places.')
    else:
        quantity = _valid_quantity(quantity)
    if decrement_stock or is_commission:
        product = product.__class__.objects.select_for_update().get(pk=product.pk)
        stock = Decimal(product.count or 0)
        if quantity > stock:
            raise InventoryError(
                f'Insufficient stock for product "{product.name}": available {stock}, requested {quantity}.'
            )
        product.count = stock - quantity
        product.save(update_fields=['count'])
    unit_cost = current_cost(product, at=at)
    total_cost = (unit_cost * quantity).quantize(Decimal('0.01'))
    unit_cost_toman = _toman_snapshot(unit_cost, rate)
    total_cost_toman = _toman_snapshot(total_cost, rate)

    usage = ProductUsage.objects.create(
        product=product,
        visit=visit,
        service=service,
        package_sale=package_sale,
        welcome_pack_usage=welcome_pack_usage,
        customer=_resolve_customer(
            customer=customer,
            visit=visit,
            package_sale=package_sale,
            welcome_pack_usage=welcome_pack_usage,
        ),
        quantity=quantity,
        unit_cost_usd_snapshot=unit_cost,
        total_cost_usd_snapshot=total_cost,
        unit_cost_toman_snapshot=unit_cost_toman,
        total_cost_toman_snapshot=total_cost_toman,
        exchange_rate_snapshot=rate,
        is_commission=is_commission,
        zero_reason=zero_reason,
    )
    return usage


def total_product_cost_usd(usages) -> Decimal:
    return sum((u.total_cost_usd_snapshot or Decimal('0') for u in usages), Decimal('0')).quantize(Decimal('0.01'))
