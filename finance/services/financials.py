"""Authoritative clinic financial calculation (single source of truth).

Every report (financial-summary, dashboard, profit-by-service, profit-by-staff)
reads its numbers from here so they cannot disagree.

The financial chain is:

    Revenue (actually collected, Sale ledger)
      - Product/material cost (actual ProductUsage snapshots)
      - Welcome-pack cost (WelcomePackUsage snapshots)
    = Gross Profit                      <- staff and overhead are BELOW this line

      - Staff compensation (StaffPayout cash + product value)
      - Operating expenses (OperatingExpense)
      - Approved/paid staff claims (Expense)
    = Net Profit

Cost basis rule: consumption cost always comes from the immutable
``ProductUsage.total_cost_usd_snapshot`` captured at the moment of use. Live
``Product.cost_usd`` is only a fallback for a service whose consumption was
never recorded, so staff compensation and financial reporting can never
silently disagree.
"""
from decimal import Decimal

from django.db.models import Sum

from ..models import (
    Expense,
    OperatingExpense,
    PaymentComponent,
    ProductUsage,
    Sale,
    StaffPayout,
    WalletTransaction,
    WelcomePackUsage,
)
from .exchange_rates import get_rate

ZERO = Decimal('0')

#: Sale statuses that represent money the clinic actually kept or gave back.
REVENUE_STATUSES = [Sale.Status.PAID, Sale.Status.REFUNDED, Sale.Status.PARTIALLY_REFUNDED]

#: Payout states that still represent a real liability to staff.
PAYOUT_OBLIGATION_STATUSES = [
    StaffPayout.Status.PENDING, StaffPayout.Status.APPROVED, StaffPayout.Status.PAID,
]

#: Claim states that count against net profit.
EXPENSE_STATUSES = [Expense.Status.APPROVED, Expense.Status.PAID]

REVENUE_BASIS_LEDGER = 'sale_ledger'
REVENUE_BASIS_LIST_PRICE = 'list_price'
WELCOME_PACK_COST_BASIS_EXCLUDED = 'excluded'

# Cash is recorded under three codes; all of them are real cash.
CASH_METHODS = (
    PaymentComponent.Method.CASH,
    PaymentComponent.Method.CASH_TOMAN,
    PaymentComponent.Method.CASH_USD,
)


def _q(value) -> Decimal:
    return Decimal(value or 0)


def consumable_usages(queryset):
    """Filter out the two consumption kinds that are not clinic material cost.

    - ``welcome_pack_usage`` rows are costed from the WelcomePackUsage snapshot
      (see below), so counting them again here would charge the same inventory
      twice.
    - ``is_commission`` rows are stock handed to staff as part of their payout.
      That is staff compensation (below the gross-profit line), not consumed
      material, and it is deducted again as part of the payout value.
    """
    return queryset.filter(welcome_pack_usage__isnull=True, is_commission=False)


def service_costs_for_visit(visit, rate=None):
    """Actual material cost per service for one visit, keyed by service id.

    Returns ``({service_id: (usd, toman)}, total_usd, total_toman)``.
    """
    rate = rate if rate is not None else get_rate('USD', 'TOMAN')
    rows = consumable_usages(ProductUsage.objects.filter(visit=visit)).values_list(
        'service_id', 'total_cost_usd_snapshot', 'exchange_rate_snapshot',
    )
    per_service = {}
    total_usd = ZERO
    total_toman = ZERO
    for service_id, cost_usd, snapshot_rate in rows:
        cost_usd = _q(cost_usd)
        if service_id is None:
            # Cost that cannot be attributed to a service still belongs to the
            # visit, so it is added to the total but not to any service.
            total_usd += cost_usd
            total_toman += (cost_usd * (snapshot_rate or rate))
            continue
        bucket = per_service.setdefault(service_id, [ZERO, ZERO])
        bucket[0] += cost_usd
        bucket[1] += cost_usd * (snapshot_rate or rate)
        total_usd += cost_usd
        total_toman += cost_usd * (snapshot_rate or rate)
    return (
        {k: (v[0].quantize(Decimal('0.01')), v[1].quantize(Decimal('0.01'))) for k, v in per_service.items()},
        total_usd.quantize(Decimal('0.01')),
        total_toman.quantize(Decimal('0.01')),
    )


def visit_revenue(visit, rate=None):
    """Revenue actually collected for a visit, net of refunds.

    Returns ``(usd, toman, basis)``. When the visit has no revenue-bearing sale
    the basis falls back to list price, which is *potential* revenue rather than
    money taken, and callers must label it as such.
    """
    rate = rate if rate is not None else get_rate('USD', 'TOMAN')
    sales = Sale.objects.filter(visit=visit, status__in=REVENUE_STATUSES)
    collected_usd = _q(sales.aggregate(t=Sum('amount_usd'))['t'])
    collected_toman = _q(sales.aggregate(t=Sum('amount_toman'))['t'])
    if sales.exists():
        return collected_usd, collected_toman, REVENUE_BASIS_LEDGER

    # No sale recorded: potential revenue from list prices, labelled honestly.
    list_usd = ZERO
    for service in visit.services.all():
        list_usd += _q(service.price_usd)
    return (
        list_usd.quantize(Decimal('0.01')),
        (list_usd * rate).quantize(Decimal('0.01')),
        REVENUE_BASIS_LIST_PRICE,
    )


def calculate_visit_financials(visit, rate=None):
    """Per-service revenue, material cost and profit for one visit.

    The collected sale total is split across the visit's services in proportion
    to their list price, so each service is credited with the part of the money
    that its price represents and the parts always add back up to the total.
    Services whose consumption was never recorded fall back to the recipe
    estimate so a payout is still possible, and are flagged via ``cost_basis``.
    """
    rate = rate if rate is not None else get_rate('USD', 'TOMAN')
    services = list(visit.services.all())

    revenue_usd, revenue_toman, basis = visit_revenue(visit, rate=rate)
    costs, unattributed_usd, unattributed_toman = service_costs_for_visit(visit, rate=rate)

    weights = [_q(service.price_usd) for service in services]
    weight_total = sum(weights, ZERO)

    rows = {}
    summed_cost_usd = unattributed_usd
    summed_cost_toman = unattributed_toman
    for index, service in enumerate(services):
        price_usd = _q(service.price_usd)
        if weight_total > 0:
            share = (revenue_usd * (price_usd / weight_total)).quantize(Decimal('0.01'))
            share_toman = (revenue_toman * (price_usd / weight_total)).quantize(Decimal('0.01'))
        elif services:
            # No prices at all: split evenly so the parts still sum to the total.
            share = (revenue_usd / Decimal(len(services))).quantize(Decimal('0.01'))
            share_toman = (revenue_toman / Decimal(len(services))).quantize(Decimal('0.01'))
        else:
            share = share_toman = ZERO

        recorded = costs.get(service.id)
        if recorded is not None:
            cost_usd, cost_toman = recorded
            cost_basis = 'product_usage_snapshot'
        else:
            # Consumption not recorded for this service. Estimate from the
            # recipe so compensation is still computable, and say so.
            cost_usd = ZERO
            for item in service.items.select_related('product').all():
                product_cost = _q(item.product.cost_usd) if item.product else ZERO
                cost_usd += (_q(item.quantity) * product_cost).quantize(Decimal('0.01'))
            cost_usd = cost_usd.quantize(Decimal('0.01'))
            cost_toman = (cost_usd * rate).quantize(Decimal('0.01'))
            cost_basis = 'service_item_estimate'

        profit_usd = (share - cost_usd).quantize(Decimal('0.01'))
        summed_cost_usd += cost_usd
        summed_cost_toman += cost_toman
        rows[service.id] = {
            'service_id': service.id,
            'service': service,
            'service_name': service.name,
            'compensation_role': service.compensation_role,
            'revenue_usd': share,
            'revenue_toman': share_toman,
            'product_cost_usd': cost_usd,
            'product_cost_toman': cost_toman,
            'profit_usd': profit_usd,
            'profit_toman': (share_toman - cost_toman).quantize(Decimal('0.01')),
            'cost_basis': cost_basis,
            'revenue_basis': basis,
        }

    return {
        'visit': visit,
        'rate': rate,
        'revenue_usd': revenue_usd,
        'revenue_toman': revenue_toman,
        'revenue_basis': basis,
        # The visit total is the sum of the per-service costs (recorded where a
        # snapshot exists, estimated from the recipe otherwise) plus any
        # consumption that cannot be attributed to a service. The parts always
        # add back up to this figure.
        'product_cost_usd': summed_cost_usd.quantize(Decimal('0.01')),
        'product_cost_toman': summed_cost_toman.quantize(Decimal('0.01')),
        'services': rows,
    }


def visit_requires_staff(visit):
    """True when any service on the visit carries a compensation role.

    Such a visit must have a staff member, otherwise compensation would be
    silently skipped.
    """
    return visit.services.exclude(compensation_role='none').exists()


def payment_method_breakdown(comps):
    """Cash/card/wallet tiles plus the untouched per-code split.

    ``breakdown`` keeps the historical three keys with every cash variant folded
    into ``cash``; ``by_method`` keeps every raw code and adds the folded cash
    total so neither view is lost.
    """
    by_method = {
        row['method']: _q(row['total'])
        for row in comps.values('method').annotate(total=Sum('amount_usd'))
    }
    cash = sum((by_method.get(method, ZERO) for method in CASH_METHODS), ZERO)
    breakdown = {
        PaymentComponent.Method.CASH: cash,
        PaymentComponent.Method.CARD: by_method.get(PaymentComponent.Method.CARD, ZERO),
        PaymentComponent.Method.WALLET: by_method.get(PaymentComponent.Method.WALLET, ZERO),
    }
    return breakdown, {**by_method, PaymentComponent.Method.CASH: cash}


def cost_coverage(usages):
    """Which consumptions were priced at zero because no cost was ever recorded."""
    zero_rows = usages.filter(total_cost_usd_snapshot=ZERO)
    products = sorted(set(zero_rows.values_list('product_id', flat=True)))
    coverage = {
        'usage_rows': usages.count(),
        'zero_cost_rows': zero_rows.count(),
        'products_missing_cost': products,
    }
    if products:
        coverage['warning'] = (
            'Some consumed products have no recorded cost and were priced at $0.00, '
            'so product cost and profit are overstated.'
        )
    return coverage


def staff_compensation_totals(start, end):
    """Staff cost owed for the period, split by role, still a real liability."""
    qs = StaffPayout.objects.filter(
        created_at__gte=start, created_at__lte=end, status__in=PAYOUT_OBLIGATION_STATUSES,
    )
    agg = qs.aggregate(
        cash_usd=Sum('payout_cash_usd'),
        cash_toman=Sum('payout_cash_toman'),
        product_usd=Sum('payout_product_value_usd'),
        product_toman=Sum('payout_product_value_toman'),
    )
    cash_usd = _q(agg['cash_usd']).quantize(Decimal('0.01'))
    cash_toman = _q(agg['cash_toman']).quantize(Decimal('0.01'))
    product_usd = _q(agg['product_usd']).quantize(Decimal('0.01'))
    product_toman = _q(agg['product_toman']).quantize(Decimal('0.01'))

    by_role = {}
    for row in qs.values('role').annotate(
        cash_usd=Sum('payout_cash_usd'),
        cash_toman=Sum('payout_cash_toman'),
        product_usd=Sum('payout_product_value_usd'),
        product_toman=Sum('payout_product_value_toman'),
        count=Sum('id'),
    ):
        by_role[row['role']] = {
            'role': row['role'],
            'count': row['count'],
            'cash_usd': _q(row['cash_usd']).quantize(Decimal('0.01')),
            'cash_toman': _q(row['cash_toman']).quantize(Decimal('0.01')),
            'product_usd': _q(row['product_usd']).quantize(Decimal('0.01')),
            'product_toman': _q(row['product_toman']).quantize(Decimal('0.01')),
            'total_usd': (_q(row['cash_usd']) + _q(row['product_usd'])).quantize(Decimal('0.01')),
            'total_toman': (_q(row['cash_toman']) + _q(row['product_toman'])).quantize(Decimal('0.01')),
        }

    return {
        'cash_usd': cash_usd,
        'cash_toman': cash_toman,
        'product_usd': product_usd,
        'product_toman': product_toman,
        'total_usd': (cash_usd + product_usd).quantize(Decimal('0.01')),
        'total_toman': (cash_toman + product_toman).quantize(Decimal('0.01')),
        'payout_count': qs.count(),
        'by_role': by_role,
    }


def operating_expense_totals(start, end):
    qs = OperatingExpense.objects.filter(
        expense_date__gte=start.date(), expense_date__lte=end.date(),
    )
    total_usd = _q(qs.aggregate(t=Sum('amount_usd'))['t']).quantize(Decimal('0.01'))
    total_toman = _q(qs.aggregate(t=Sum('amount_toman'))['t']).quantize(Decimal('0.01'))
    return {
        'total_usd': total_usd,
        'total_toman': total_toman,
        'count': qs.count(),
    }


def claim_totals(start, end, personnel_id=None):
    qs = Expense.objects.filter(
        expense_date__gte=start.date(), expense_date__lte=end.date(),
        status__in=EXPENSE_STATUSES,
    )
    if personnel_id:
        qs = qs.filter(created_by_id=personnel_id)
    total_usd = _q(qs.aggregate(t=Sum('amount_usd'))['t']).quantize(Decimal('0.01'))
    total_toman = _q(qs.aggregate(t=Sum('amount_toman'))['t']).quantize(Decimal('0.01'))
    return {
        'total_usd': total_usd,
        'total_toman': total_toman,
        'count': qs.count(),
    }


def welcome_pack_totals(start, end, product_id=None):
    """Welcome-pack cost for the period, counted exactly once.

    Pack cost is only ever read from the WelcomePackUsage snapshot. The
    pack-linked ProductUsage rows exist for the consumption log and are
    excluded from product cost, so the same inventory is never charged twice.
    """
    if product_id:
        # A period snapshot total cannot be narrowed to one product, so use that
        # product's pack consumption rows instead.
        rows = ProductUsage.objects.filter(
            created_at__gte=start, created_at__lte=end,
            welcome_pack_usage__isnull=False,
        )
        total_usd = _q(rows.aggregate(t=Sum('total_cost_usd_snapshot'))['t'])
        total_toman = ZERO
        for cost_usd, snapshot_rate in rows.values_list('total_cost_usd_snapshot', 'exchange_rate_snapshot'):
            total_toman += _q(cost_usd) * (snapshot_rate or get_rate('USD', 'TOMAN'))
        total_toman = total_toman.quantize(Decimal('0.01'))
        return {'usd': total_usd.quantize(Decimal('0.01')), 'toman': total_toman, 'source': 'product_usage'}

    wp_usages = WelcomePackUsage.objects.filter(issued_at__gte=start, issued_at__lte=end)
    return {
        'usd': _q(wp_usages.aggregate(t=Sum('total_cost_usd_snapshot'))['t']).quantize(Decimal('0.01')),
        'toman': _q(wp_usages.aggregate(t=Sum('total_cost_toman_snapshot'))['t']).quantize(Decimal('0.01')),
        'source': 'welcome_pack_usage',
    }


def build_report(start, end, *, service_id=None, package_id=None, product_id=None, personnel_id=None):
    """The authoritative period report every endpoint renders."""
    from customers.models import Visit

    sales = Sale.objects.filter(
        created_at__gte=start, created_at__lte=end, status__in=REVENUE_STATUSES,
    )
    if personnel_id:
        sales = sales.filter(visit__staff_id=personnel_id)
    if package_id:
        sales = sales.filter(package_id=package_id)

    revenue_usd = _q(sales.aggregate(t=Sum('amount_usd'))['t']).quantize(Decimal('0.01'))
    revenue_toman = _q(sales.aggregate(t=Sum('amount_toman'))['t']).quantize(Decimal('0.01'))
    revenue_sale_count = sales.count()

    usages = ProductUsage.objects.filter(created_at__gte=start, created_at__lte=end)
    if service_id:
        usages = usages.filter(service_id=service_id)
    if product_id:
        usages = usages.filter(product_id=product_id)
    cost_usages = consumable_usages(usages)

    product_cost_usd = _q(cost_usages.aggregate(t=Sum('total_cost_usd_snapshot'))['t']).quantize(Decimal('0.01'))
    product_cost_toman = ZERO
    for cost_usd, snapshot_rate in cost_usages.values_list('total_cost_usd_snapshot', 'exchange_rate_snapshot'):
        product_cost_toman += _q(cost_usd) * (snapshot_rate or get_rate('USD', 'TOMAN'))
    product_cost_toman = product_cost_toman.quantize(Decimal('0.01'))

    welcome_pack_cost = welcome_pack_totals(start, end, product_id=product_id)

    gross_usd = (revenue_usd - product_cost_usd - welcome_pack_cost['usd']).quantize(Decimal('0.01'))
    gross_toman = (
        revenue_toman - product_cost_toman - welcome_pack_cost['toman']
    ).quantize(Decimal('0.01'))

    staff = staff_compensation_totals(start, end)
    operating = operating_expense_totals(start, end)
    claims = claim_totals(start, end, personnel_id=personnel_id)

    below_line_usd = (staff['total_usd'] + operating['total_usd'] + claims['total_usd']).quantize(Decimal('0.01'))
    below_line_toman = (
        staff['total_toman'] + operating['total_toman'] + claims['total_toman']
    ).quantize(Decimal('0.01'))

    net_usd = (gross_usd - below_line_usd).quantize(Decimal('0.01'))
    net_toman = (gross_toman - below_line_toman).quantize(Decimal('0.01'))

    comps = PaymentComponent.objects.filter(sale__in=sales)
    method_breakdown, method_by_method = payment_method_breakdown(comps)

    refunds = abs(_q(
        sales.filter(status__in=[Sale.Status.REFUNDED, Sale.Status.PARTIALLY_REFUNDED], amount_usd__lt=0)
        .aggregate(t=Sum('amount_usd'))['t']
    ))

    appointments = Visit.objects.filter(
        start_at__gte=start, start_at__lte=end, status=Visit.Status.COMPLETED,
    ).count()
    packages_sold = sales.filter(package__isnull=False, status=Sale.Status.PAID).count()
    products_sold = _q(usages.aggregate(t=Sum('quantity'))['t'])

    return {
        'period': {'start': start, 'end': end},
        'revenue': {'usd': revenue_usd, 'toman': revenue_toman},
        'revenue_basis': REVENUE_BASIS_LEDGER,
        'product_cost': {'usd': product_cost_usd, 'toman': product_cost_toman},
        'welcome_pack_cost': {
            'usd': welcome_pack_cost['usd'], 'toman': welcome_pack_cost['toman'],
        },
        'gross_profit': {'usd': gross_usd, 'toman': gross_toman},
        # Original key, preserved: 'expenses' has always meant staff expense
        # claims here. Kept alongside the explicit name so existing clients
        # keep working while the distinction from operating expenses is clear.
        'expenses': {'usd': claims['total_usd'], 'toman': claims['total_toman']},
        'staff_compensation': {
            'cash': {'usd': staff['cash_usd'], 'toman': staff['cash_toman']},
            'product': {'usd': staff['product_usd'], 'toman': staff['product_toman']},
            'total': {'usd': staff['total_usd'], 'toman': staff['total_toman']},
            'payout_count': staff['payout_count'],
            'by_role': staff['by_role'],
        },
        'operating_expenses': {
            'usd': operating['total_usd'], 'toman': operating['total_toman'],
            'count': operating['count'],
        },
        'staff_expense_claims': {
            'usd': claims['total_usd'], 'toman': claims['total_toman'],
            'count': claims['count'],
        },
        'below_the_line_total': {'usd': below_line_usd, 'toman': below_line_toman},
        'net_profit': {'usd': net_usd, 'toman': net_toman},
        'cost_coverage': cost_coverage(usages),
        'payment_methods': method_breakdown,
        'payment_methods_by_method': method_by_method,
        'wallet': {
            'rewards_issued': _q(
                WalletTransaction.objects.filter(
                    transaction_type=WalletTransaction.Type.REWARD,
                    created_at__gte=start, created_at__lte=end,
                ).aggregate(t=Sum('amount'))['t']
            ),
            'wallet_payments': _q(
                PaymentComponent.objects.filter(
                    sale__in=sales, method=PaymentComponent.Method.WALLET,
                ).aggregate(t=Sum('amount_usd'))['t']
            ),
            'refunds': refunds,
        },
        'counts': {
            'appointments': appointments,
            'packages_sold': packages_sold,
            'products_sold_quantity': products_sold,
            'paid_sales': sales.filter(status=Sale.Status.PAID).count(),
            'revenue_sales': revenue_sale_count,
            'average_transaction_value': (
                (revenue_usd / revenue_sale_count).quantize(Decimal('0.01'))
                if revenue_sale_count else ZERO
            ),
        },
    }
