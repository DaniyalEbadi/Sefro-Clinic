from decimal import Decimal
from typing import Optional

from django.db import transaction
from django.utils import timezone

from ..models import WelcomePack, WelcomePackItem, WelcomePackUsage
from .exchange_rates import convert_usd_to_toman, get_current_usd_to_toman_rate
from .inventory import current_cost


def calculate_welcome_pack_cost_usd(welcome_pack: WelcomePack, at=None) -> Decimal:
    """Calculate the total USD cost of a WelcomePack based on current/historical product costs.

    Does NOT include exchange rate conversion. Pure USD cost from product cost history.
    """
    when = at or timezone.now()
    items = welcome_pack.items.select_related('product').all()
    total = Decimal('0')
    for item in items:
        unit_cost = current_cost(item.product, at=when)
        total += (unit_cost * Decimal(str(item.quantity))).quantize(Decimal('0.01'))
    return total.quantize(Decimal('0.01'))


def calculate_welcome_pack_cost_toman(welcome_pack: WelcomePack, at=None, rate: Optional[Decimal] = None) -> Optional[Decimal]:
    """Calculate the total Toman cost of a WelcomePack.

    Uses the current exchange rate by default, or a provided rate.
    Returns None if no valid exchange rate is available.
    """
    cost_usd = calculate_welcome_pack_cost_usd(welcome_pack, at=at)
    if rate is None:
        rate = get_current_usd_to_toman_rate()
    if rate is None:
        return None
    return convert_usd_to_toman(cost_usd, rate)


class WelcomePackError(Exception):
    pass


def _valid_quantity(value) -> Decimal:
    try:
        quantity = Decimal(str(value))
    except Exception as exc:
        raise WelcomePackError('Quantity must be a valid decimal.') from exc
    if not quantity.is_finite() or quantity <= 0:
        raise WelcomePackError('Quantity must be greater than zero.')
    if quantity.as_tuple().exponent < -3:
        raise WelcomePackError('Quantity cannot have more than three decimal places.')
    return quantity


@transaction.atomic
def issue_welcome_pack(
    *,
    welcome_pack: WelcomePack,
    customer,
    quantity: Decimal = Decimal('1'),
    visit=None,
    issued_by=None,
    at=None,
    rate: Optional[Decimal] = None,
) -> WelcomePackUsage:
    """Issue a WelcomePack to a customer, creating a financial event.

    This is the ONLY operation that creates a financial impact for Welcome Packs.
    Creating/editing a WelcomePack definition does NOT affect finances.

    Returns a WelcomePackUsage snapshot with costs frozen at issuance time.
    """
    if not welcome_pack.is_active:
        raise WelcomePackError('Welcome pack is not active.')

    quantity = _valid_quantity(quantity)
    at = at or timezone.now()
    rate = rate if rate is not None else get_current_usd_to_toman_rate()
    if rate is None:
        raise WelcomePackError('Exchange rate unavailable. Cannot record financial event.')

    # Calculate costs at issuance time
    unit_cost_usd = calculate_welcome_pack_cost_usd(welcome_pack, at=at)
    total_cost_usd = (unit_cost_usd * quantity).quantize(Decimal('0.01'))
    total_cost_toman = convert_usd_to_toman(total_cost_usd, rate)

    usage = WelcomePackUsage.objects.create(
        welcome_pack=welcome_pack,
        customer=customer,
        visit=visit,
        issued_by=issued_by,
        quantity=quantity,
        total_cost_usd_snapshot=total_cost_usd,
        exchange_rate_snapshot=rate,
        total_cost_toman_snapshot=total_cost_toman,
        issued_at=at,
    )
    return usage


def get_welcome_pack_items(welcome_pack: WelcomePack):
    """Get items with product details for a welcome pack."""
    return welcome_pack.items.select_related('product').all()


def validate_welcome_pack_items(items_data, instance=None):
    """Validate welcome pack items data for create/update.

    Args:
        items_data: List of dicts with 'product' (id) and 'quantity'
        instance: Existing WelcomePack instance (for update validation)

    Returns:
        List of validated (product, quantity) tuples

    Raises:
        WelcomePackError: If validation fails
    """
    from inventory.models import Product

    if not items_data:
        return []

    seen_products = set()
    validated_items = []

    for idx, item in enumerate(items_data):
        product_id = item.get('product')
        quantity = item.get('quantity')

        if product_id is None:
            raise WelcomePackError(f'Item {idx}: product is required.')
        if quantity is None:
            raise WelcomePackError(f'Item {idx}: quantity is required.')

        try:
            quantity = _valid_quantity(quantity)
        except WelcomePackError as exc:
            raise WelcomePackError(f'Item {idx}: {exc}') from exc

        try:
            product = Product.objects.get(id=product_id)
        except Product.DoesNotExist:
            raise WelcomePackError(f'Item {idx}: product with id {product_id} does not exist.')

        if product.status == Product.StatusChoices.FINISHED:
            raise WelcomePackError(f'Item {idx}: product "{product.name}" is finished/inactive.')

        if product_id in seen_products:
            raise WelcomePackError(f'Item {idx}: duplicate product "{product.name}" in welcome pack.')
        seen_products.add(product_id)

        validated_items.append((product, quantity))

    return validated_items


@transaction.atomic
def create_welcome_pack_with_items(*, name, description='', is_active=True, items_data, created_by):
    """Create a WelcomePack with its items in a single transaction."""
    pack = WelcomePack.objects.create(
        name=name,
        description=description,
        is_active=is_active,
        created_by=created_by,
    )

    validated_items = validate_welcome_pack_items(items_data)
    for product, quantity in validated_items:
        WelcomePackItem.objects.create(
            welcome_pack=pack,
            product=product,
            quantity=quantity,
        )

    return pack


@transaction.atomic
def update_welcome_pack_with_items(pack: WelcomePack, *, name=None, description=None, is_active=None, items_data=None, updated_by=None):
    """Update a WelcomePack and optionally its items.

    If items_data is provided, replaces all items (atomic replace).
    """
    if name is not None:
        pack.name = name
    if description is not None:
        pack.description = description
    if is_active is not None:
        pack.is_active = is_active
    pack.save(update_fields=[f for f in ['name', 'description', 'is_active'] if locals().get(f) is not None])

    if items_data is not None:
        validated_items = validate_welcome_pack_items(items_data, instance=pack)
        # Delete existing items and create new ones
        pack.items.all().delete()
        for product, quantity in validated_items:
            WelcomePackItem.objects.create(
                welcome_pack=pack,
                product=product,
                quantity=quantity,
            )

    return pack


def get_welcome_pack_usage_summary(start=None, end=None):
    """Get summary of welcome pack usage for reporting.

    Returns aggregated counts and costs over the period.
    """
    from django.db.models import Count, Sum

    from .reporting import _range

    start, end = _range(start, end)

    usages = WelcomePackUsage.objects.filter(issued_at__gte=start, issued_at__lte=end)

    total_count = usages.aggregate(total=Sum('quantity'))['total'] or Decimal('0')
    total_cost_usd = usages.aggregate(total=Sum('total_cost_usd_snapshot'))['total'] or Decimal('0')
    total_cost_toman = usages.aggregate(total=Sum('total_cost_toman_snapshot'))['total'] or Decimal('0')
    usage_count = usages.count()

    by_pack = list(
        usages.values('welcome_pack_id', 'welcome_pack__name')
        .annotate(
            count=Sum('quantity'),
            cost_usd=Sum('total_cost_usd_snapshot'),
            cost_toman=Sum('total_cost_toman_snapshot'),
            usage_count=Count('id'),
        )
        .order_by('-cost_usd')
    )

    return {
        'period': {'start': start, 'end': end},
        'total_usage_count': usage_count,
        'total_packs_issued': total_count,
        'total_cost_usd': total_cost_usd,
        'total_cost_toman': total_cost_toman,
        'by_pack': by_pack,
    }
