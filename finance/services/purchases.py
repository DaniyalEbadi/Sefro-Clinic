"""Purchase orders: buying products (stock) with USD costs and Toman snapshots.

Separate from the one-shot ``ProductPurchase`` ledger: a purchase order is
drafted, marked as ordered, and only mutates stock / cost history / profit when
it is **received**. Money convention: USD is authoritative; Toman figures are
snapshotted once, at receive time, using the exchange rate then in force.

Profit stays correct by construction: receiving a purchase builds stock and
opens a new ``ProductCostHistory`` range, so the cost only reaches the P&L when
the product is later consumed (``ProductUsage`` / COGS).
"""

from decimal import Decimal

from django.db import transaction
from django.db.models import Count, Sum
from django.utils import timezone

from inventory.models import Product

from ..models import PurchaseOrder, PurchaseOrderItem
from .exchange_rates import get_rate
from .inventory import InventoryError, _valid_quantity, apply_purchase_receipt


class PurchaseOrderError(Exception):
    """A user-correctable purchase-order validation failure."""


EDITABLE_STATUSES = (PurchaseOrder.Status.DRAFT, PurchaseOrder.Status.ORDERED)
CENT = Decimal('0.01')


def _resolve_product(value) -> Product:
    if isinstance(value, Product):
        return value
    try:
        product_id = int(value)
    except (TypeError, ValueError) as exc:
        raise PurchaseOrderError('Each item needs a valid product id.') from exc
    try:
        return Product.objects.get(pk=product_id)
    except Product.DoesNotExist as exc:
        raise PurchaseOrderError(f'Product {product_id} does not exist.') from exc


def normalize_items(items_data) -> list:
    """Validate a raw `items` payload into product/quantity/cost tuples."""
    if not isinstance(items_data, (list, tuple)) or not items_data:
        raise PurchaseOrderError('At least one product line is required.')

    lines, seen = [], set()
    for raw in items_data:
        if not isinstance(raw, dict):
            raise PurchaseOrderError('Each item must be an object.')

        product = _resolve_product(raw.get('product'))
        if product.pk in seen:
            raise PurchaseOrderError(
                f'Product "{product.name}" appears more than once; combine the quantities into one line.'
            )
        seen.add(product.pk)

        try:
            quantity = _valid_quantity(raw.get('quantity'))
        except InventoryError as exc:
            raise PurchaseOrderError(str(exc)) from exc

        try:
            unit_cost_usd = Decimal(str(raw.get('unit_cost_usd', '0')))
        except Exception as exc:
            raise PurchaseOrderError('unit_cost_usd must be a decimal.') from exc
        if not unit_cost_usd.is_finite() or unit_cost_usd < 0:
            raise PurchaseOrderError('unit_cost_usd must be zero or more.')
        unit_cost_usd = unit_cost_usd.quantize(CENT)

        lines.append({
            'product': product,
            'quantity': quantity,
            'unit_cost_usd': unit_cost_usd,
            'total_cost_usd': (unit_cost_usd * quantity).quantize(CENT),
        })
    return lines


def _write_items(order: PurchaseOrder, lines: list):
    order.items.all().delete()
    PurchaseOrderItem.objects.bulk_create([
        PurchaseOrderItem(order=order, **line) for line in lines
    ])
    order.total_cost_usd = sum(
        (line['total_cost_usd'] for line in lines), Decimal('0')
    ).quantize(CENT)
    order.save(update_fields=['total_cost_usd', 'updated_at'])


@transaction.atomic
def create_purchase_order(
    *,
    items_data,
    supplier: str = '',
    order_date=None,
    notes: str = '',
    created_by=None,
    idempotency_key: str = '',
):
    """Create a draft order with its lines. No stock or cost effect."""
    key = (idempotency_key or '').strip() or None
    if key:
        existing = PurchaseOrder.objects.filter(idempotency_key=key).first()
        if existing is not None:
            return existing, False

    lines = normalize_items(items_data)
    order = PurchaseOrder.objects.create(
        supplier=supplier or '',
        status=PurchaseOrder.Status.DRAFT,
        order_date=order_date or timezone.now().date(),
        notes=notes or '',
        created_by=created_by,
        idempotency_key=key,
    )
    _write_items(order, lines)
    return order, True


@transaction.atomic
def update_purchase_order(order: PurchaseOrder, **fields):
    """Edit supplier/date/notes/lines while the order is still draft/ordered."""
    if order.status not in EDITABLE_STATUSES:
        raise PurchaseOrderError('Only draft or ordered purchase orders can be edited.')

    if 'supplier' in fields and fields['supplier'] is not None:
        order.supplier = fields['supplier']
    if 'order_date' in fields and fields['order_date'] is not None:
        order.order_date = fields['order_date']
    if 'notes' in fields and fields['notes'] is not None:
        order.notes = fields['notes']

    items_data = fields.get('items_data')
    if items_data is not None:
        _write_items(order, normalize_items(items_data))

    order.save()
    # The viewset prefetches `items`; reload so the response does not render a
    # stale item cache after the line set was replaced.
    order.refresh_from_db()
    return order


def mark_ordered(order: PurchaseOrder):
    """draft → ordered. Still no financial effect."""
    if order.status != PurchaseOrder.Status.DRAFT:
        raise PurchaseOrderError('Only a draft purchase order can be marked as ordered.')
    order.status = PurchaseOrder.Status.ORDERED
    order.save(update_fields=['status', 'updated_at'])
    order.refresh_from_db()
    return order


@transaction.atomic
def receive_purchase_order(order: PurchaseOrder, *, rate=None, received_date=None):
    """ordered/draft → received: add stock, roll cost history, snapshot Toman."""
    if order.status == PurchaseOrder.Status.RECEIVED:
        raise PurchaseOrderError('This purchase order has already been received.')
    if order.status == PurchaseOrder.Status.CANCELLED:
        raise PurchaseOrderError('A cancelled purchase order cannot be received.')

    items = list(order.items.select_related('product'))
    if not items:
        raise PurchaseOrderError('Cannot receive a purchase order without product lines.')

    rate = rate if rate is not None else get_rate('USD', 'TOMAN')
    if rate is None or rate <= 0:
        raise PurchaseOrderError(
            'No valid USD→Toman exchange rate is configured; set one via /api/finance/exchange-rates/.'
        )
    received_date = received_date or timezone.now().date()

    total_usd = Decimal('0')
    total_toman = Decimal('0')

    # Sorted by product so concurrent receipts always lock products in the
    # same order and cannot deadlock against each other.
    for item in sorted(items, key=lambda i: i.product_id):
        unit_usd = item.unit_cost_usd.quantize(CENT)
        quantity = _valid_quantity(item.quantity)

        apply_purchase_receipt(
            product=item.product,
            quantity=quantity,
            unit_cost_usd=unit_usd,
            purchase_date=received_date,
        )

        item.unit_cost_usd = unit_usd
        item.total_cost_usd = (unit_usd * quantity).quantize(CENT)
        item.unit_cost_toman = (unit_usd * rate).quantize(CENT)
        item.total_cost_toman = (item.total_cost_usd * rate).quantize(CENT)
        item.save(update_fields=[
            'unit_cost_usd', 'total_cost_usd', 'unit_cost_toman', 'total_cost_toman',
        ])

        total_usd += item.total_cost_usd
        total_toman += item.total_cost_toman

    order.status = PurchaseOrder.Status.RECEIVED
    order.received_date = received_date
    order.exchange_rate_snapshot = rate
    order.total_cost_usd = total_usd
    order.total_cost_toman = total_toman
    order.save(update_fields=[
        'status', 'received_date', 'exchange_rate_snapshot',
        'total_cost_usd', 'total_cost_toman', 'updated_at',
    ])
    # Drop the caller's prefetched item cache so the response shows the
    # snapshots written above.
    order.refresh_from_db()
    return order


@transaction.atomic
def cancel_purchase_order(order: PurchaseOrder):
    """Any state except received → cancelled."""
    if order.status == PurchaseOrder.Status.RECEIVED:
        raise PurchaseOrderError('A received purchase order cannot be cancelled; stock was already added.')
    order.status = PurchaseOrder.Status.CANCELLED
    order.save(update_fields=['status', 'updated_at'])
    order.refresh_from_db()
    return order


def purchase_summary(start=None, end=None, *, product_id=None, supplier=None):
    """Received-purchase totals (USD + Toman) for a Gregorian date range."""
    today = timezone.localtime(timezone.now()).date()
    start_date = start.date() if hasattr(start, 'date') else (start or today)
    end_date = end.date() if hasattr(end, 'date') else (end or today)

    lines = PurchaseOrderItem.objects.filter(
        order__status=PurchaseOrder.Status.RECEIVED,
        order__received_date__gte=start_date,
        order__received_date__lte=end_date,
    )
    if product_id:
        lines = lines.filter(product_id=product_id)
    if supplier:
        lines = lines.filter(order__supplier__icontains=supplier)

    totals = lines.aggregate(
        quantity=Sum('quantity'),
        total_cost_usd=Sum('total_cost_usd'),
        total_cost_toman=Sum('total_cost_toman'),
    )

    by_product = list(
        lines.values('product_id', 'product__name')
        .annotate(
            quantity=Sum('quantity'),
            total_cost_usd=Sum('total_cost_usd'),
            total_cost_toman=Sum('total_cost_toman'),
            line_count=Count('id'),
        )
        .order_by('-total_cost_usd')
    )

    by_supplier = list(
        lines.values('order__supplier')
        .annotate(
            total_cost_usd=Sum('total_cost_usd'),
            total_cost_toman=Sum('total_cost_toman'),
            line_count=Count('id'),
            order_count=Count('order_id', distinct=True),
        )
        .order_by('-total_cost_usd')
    )

    return {
        'period': {'start': start_date, 'end': end_date},
        'order_count': lines.values('order_id').distinct().count(),
        'line_count': lines.count(),
        'total_quantity': totals['quantity'] or Decimal('0'),
        'total_cost_usd': totals['total_cost_usd'] or Decimal('0'),
        'total_cost_toman': totals['total_cost_toman'] or Decimal('0'),
        'by_product': [
            {
                'product_id': row['product_id'],
                'product_name': row['product__name'],
                'quantity': row['quantity'] or Decimal('0'),
                'total_cost_usd': row['total_cost_usd'] or Decimal('0'),
                'total_cost_toman': row['total_cost_toman'] or Decimal('0'),
                'line_count': row['line_count'],
            }
            for row in by_product
        ],
        'by_supplier': [
            {
                'supplier': row['order__supplier'] or '',
                'total_cost_usd': row['total_cost_usd'] or Decimal('0'),
                'total_cost_toman': row['total_cost_toman'] or Decimal('0'),
                'line_count': row['line_count'],
                'order_count': row['order_count'],
            }
            for row in by_supplier
        ],
    }
