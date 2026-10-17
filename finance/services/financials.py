"""Authoritative clinic financial calculation (single source of truth).

Every report (financial-summary, dashboard, profit-by-service, profit-by-staff)
reads its numbers from here so they cannot disagree.

The financial chain is:

    Revenue (actually collected, Sale ledger)
      - Product/material cost (actual ProductUsage snapshots)
      - Welcome-pack cost (WelcomePackUsage snapshots)
      - Staff compensation (StaffPayout cash + product value)
    = Clinic Share                    <- the clinic's take per service

      - Operating expenses (OperatingExpense)
      - Approved/paid staff claims (Expense)
    = Net Profit

    gross_profit is reported as revenue minus product cost and welcome-pack
    cost (staff and overhead sit below that line, as before).

    Stock purchases are reported alongside, never inside, the P&L:

    Net Profit
      - Stock bought this period (PurchaseOrder received + ProductPurchase)
    = Net Profit After Purchases      <- cash view only

    Deducting purchases from net_profit would charge the same product twice:
    once when bought, again as product cost when consumed.

Cost basis rule: consumption cost always comes from the immutable
``ProductUsage.total_cost_usd_snapshot`` captured at the moment of use. Live
``Product.cost_usd`` is only a fallback for a service whose consumption was
never recorded, so staff compensation and financial reporting can never
silently disagree.
"""
from decimal import Decimal

from django.db.models import Count, Sum

from ..models import (
    Expense,
    OperatingExpense,
    PaymentComponent,
    ProductPurchase,
    ProductUsage,
    PurchaseOrder,
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
#: Welcome-pack cost attribution label: visit packs are split across the
#: visit's services by revenue share (see reporting.profit_by_service), so
#: rows sum back to the visit total. Kept for backward-compatible imports.
WELCOME_PACK_COST_BASIS_ALLOCATED = 'allocated_by_revenue_share'
WELCOME_PACK_COST_BASIS_EXCLUDED = WELCOME_PACK_COST_BASIS_ALLOCATED

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

    # Compensation owed for this visit, read from the payout ledger (the same
    # source the period report uses) rather than recomputed, so the per-visit
    # figures and the financial summary cannot disagree.
    payout_rows = StaffPayout.objects.filter(
        visit=visit, status__in=PAYOUT_OBLIGATION_STATUSES,
    ).values_list('service_id', 'payout_cash_usd', 'payout_cash_toman', 'payout_product_value_usd', 'payout_product_value_toman')
    payout_usd = {}
    payout_toman = {}
    for sid, cash_usd, cash_toman, prod_usd, prod_toman in payout_rows:
        payout_usd[sid] = payout_usd.get(sid, ZERO) + _q(cash_usd) + _q(prod_usd)
        payout_toman[sid] = payout_toman.get(sid, ZERO) + _q(cash_toman) + _q(prod_toman)

    # Welcome-pack cost issued on this visit: a clinic cost (never a customer
    # charge), snapshotted at issuance time.
    wp_agg = WelcomePackUsage.objects.filter(visit=visit).aggregate(
        usd=Sum('total_cost_usd_snapshot'), toman=Sum('total_cost_toman_snapshot'),
    )
    welcome_pack_cost_usd = _q(wp_agg['usd']).quantize(Decimal('0.01'))
    welcome_pack_cost_toman = _q(wp_agg['toman']).quantize(Decimal('0.01'))

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

        # The recipe estimate is always computed so it can be compared with the
        # actual consumption snapshot, even when the actual cost was recorded.
        estimate_usd = ZERO
        for item in service.items.select_related('product').all():
            product_cost = _q(item.product.cost_usd) if item.product else ZERO
            estimate_usd += (_q(item.quantity) * product_cost).quantize(Decimal('0.01'))
        estimate_usd = estimate_usd.quantize(Decimal('0.01'))

        recorded = costs.get(service.id)
        if recorded is not None:
            cost_usd, cost_toman = recorded
            cost_basis = 'product_usage_snapshot'
        else:
            # Consumption not recorded for this service. Estimate from the
            # recipe so compensation and reporting still work, and say so.
            cost_usd = estimate_usd
            cost_toman = (cost_usd * rate).quantize(Decimal('0.01'))
            cost_basis = 'service_item_estimate'

        operator_compensation_usd = payout_usd.get(service.id, ZERO).quantize(Decimal('0.01'))
        operator_compensation_toman = payout_toman.get(service.id, ZERO).quantize(Decimal('0.01'))
        # Welcome-pack cost has no natural service owner; allocating it by the
        # same revenue weight used for the revenue split keeps the per-service
        # rows additive: they sum to the visit's exact totals. A visit that
        # billed nothing (a free service, or an unbilled one) still owes the
        # pack cost, so with no revenue to weight by it is split evenly rather
        # than dropped.
        if revenue_usd > 0:
            wp_share_usd = (welcome_pack_cost_usd * (share / revenue_usd)).quantize(Decimal('0.01'))
            wp_share_toman = (welcome_pack_cost_toman * (share_toman / revenue_toman)).quantize(Decimal('0.01')) if revenue_toman > 0 else ZERO
        else:
            even_share = Decimal(1) / Decimal(len(services))
            wp_share_usd = (welcome_pack_cost_usd * even_share).quantize(Decimal('0.01'))
            wp_share_toman = (welcome_pack_cost_toman * even_share).quantize(Decimal('0.01'))

        profit_usd = (share - cost_usd).quantize(Decimal('0.01'))
        clinic_share_usd = (share - cost_usd - operator_compensation_usd - wp_share_usd).quantize(Decimal('0.01'))
        clinic_share_toman = (share_toman - cost_toman - operator_compensation_toman - wp_share_toman).quantize(Decimal('0.01'))
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
            'recipe_estimate_cost_usd': estimate_usd,
            'recipe_estimate_cost_toman': (estimate_usd * rate).quantize(Decimal('0.01')),
            'operator_compensation_usd': operator_compensation_usd,
            'operator_compensation_toman': operator_compensation_toman,
            'welcome_pack_cost_usd': wp_share_usd,
            'welcome_pack_cost_toman': wp_share_toman,
            'profit_usd': profit_usd,
            'profit_toman': (share_toman - cost_toman).quantize(Decimal('0.01')),
            'clinic_share_usd': clinic_share_usd,
            'clinic_share_toman': clinic_share_toman,
            'cost_basis': cost_basis,
            'revenue_basis': basis,
        }

    # Quantising each share can leave a rounding residual, so the per-service
    # rows would not add back to the visit. Hand the remainder to the last
    # service (and take it back out of its clinic share) so they do.
    if rows:
        residual_usd = welcome_pack_cost_usd - sum(
            row['welcome_pack_cost_usd'] for row in rows.values()
        )
        residual_toman = welcome_pack_cost_toman - sum(
            row['welcome_pack_cost_toman'] for row in rows.values()
        )
        if residual_usd or residual_toman:
            last = rows[list(rows)[-1]]
            last['welcome_pack_cost_usd'] = (
                last['welcome_pack_cost_usd'] + residual_usd
            ).quantize(Decimal('0.01'))
            last['welcome_pack_cost_toman'] = (
                last['welcome_pack_cost_toman'] + residual_toman
            ).quantize(Decimal('0.01'))
            last['clinic_share_usd'] = (last['clinic_share_usd'] - residual_usd).quantize(Decimal('0.01'))
            last['clinic_share_toman'] = (last['clinic_share_toman'] - residual_toman).quantize(Decimal('0.01'))

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
        'welcome_pack_cost_usd': welcome_pack_cost_usd,
        'welcome_pack_cost_toman': welcome_pack_cost_toman,
        'operator_compensation_usd': sum(p.quantize(Decimal('0.01')) for p in payout_usd.values()),
        'operator_compensation_toman': sum(p.quantize(Decimal('0.01')) for p in payout_toman.values()),
        'clinic_share_usd': (
            revenue_usd - summed_cost_usd.quantize(Decimal('0.01'))
            - welcome_pack_cost_usd
            - sum(p.quantize(Decimal('0.01')) for p in payout_usd.values())
        ).quantize(Decimal('0.01')),
        'clinic_share_toman': (
            revenue_toman - summed_cost_toman.quantize(Decimal('0.01'))
            - welcome_pack_cost_toman
            - sum(p.quantize(Decimal('0.01')) for p in payout_toman.values())
        ).quantize(Decimal('0.01')),
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
        count=Count('id'),
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


def purchase_totals(start, end):
    """Stock-purchase cash out for the period, from both purchase ledgers.

    Purchases never enter net profit: inventory is charged to profit exactly
    once, at consumption (ProductUsage snapshots). This reports the money that
    actually left the clinic on stock so callers can show
    ``net_profit_after_purchases`` as a cash view *next to* the P&L.

    Two ledgers exist and both must be read or purchases silently vanish:
      * ``PurchaseOrderItem`` behind orders that reached ``received``
      * ``ProductPurchase``, the one-shot restock ledger
    """
    g_start, g_end = start.date(), end.date()

    orders = PurchaseOrder.objects.filter(
        status=PurchaseOrder.Status.RECEIVED,
        received_date__gte=g_start, received_date__lte=g_end,
    )
    po_usd = _q(orders.aggregate(t=Sum('total_cost_usd'))['t'])
    po_toman = _q(orders.aggregate(t=Sum('total_cost_toman'))['t'])
    po_count = orders.count()

    direct = ProductPurchase.objects.filter(
        purchase_date__gte=g_start, purchase_date__lte=g_end,
    )
    dr_usd = ZERO
    dr_toman = ZERO
    for cost_usd, snapshot_rate in direct.values_list('total_cost_usd', 'exchange_rate_snapshot'):
        cost = _q(cost_usd)
        dr_usd += cost
        dr_toman += cost * (snapshot_rate or get_rate('USD', 'TOMAN'))
    dr_usd = dr_usd.quantize(Decimal('0.01'))
    dr_toman = dr_toman.quantize(Decimal('0.01'))
    dr_count = direct.count()

    return {
        'usd': (po_usd + dr_usd).quantize(Decimal('0.01')),
        'toman': (po_toman + dr_toman).quantize(Decimal('0.01')),
        'count': po_count + dr_count,
        'by_source': {
            'purchase_order': {
                'usd': po_usd.quantize(Decimal('0.01')),
                'toman': po_toman.quantize(Decimal('0.01')),
                'count': po_count,
            },
            'direct': {
                'usd': dr_usd,
                'toman': dr_toman,
                'count': dr_count,
            },
        },
    }


def operator_attribution(start, end, *, totals=None):
    """Revenue and material cost produced by each staff member.

    Same anchors and the same costing rule as :func:`build_report`
    (``Sale.created_at`` / ``ProductUsage.created_at``, cost = snapshot USD x
    its snapshot rate), so the rows are comparable with the report totals.

    ``StaffPayout`` cannot be used for this: a ``monthly_salary`` payout row
    stores ``revenue = 0`` and ``profit = 0`` on purpose, so the laser tech's
    produced revenue would simply be missing.

    Pass ``totals`` (the whole ``build_report`` payload -- it reads ``revenue``
    and ``product_cost`` off it) to get an ``unattributed`` residual row that
    makes the parts sum back to the whole exactly, rounding included. Without
    it the residual is only the sales and usages whose visit has no assigned
    staff.
    """
    sales = Sale.objects.filter(
        created_at__gte=start, created_at__lte=end, status__in=REVENUE_STATUSES,
    )
    revenue: dict = {}
    for staff_id, usd, toman in sales.values_list('visit__staff_id').annotate(
        usd=Sum('amount_usd'), toman=Sum('amount_toman'),
    ):
        revenue[staff_id] = {'usd': _q(usd), 'toman': _q(toman)}

    cost: dict = {}
    rate = get_rate('USD', 'TOMAN')
    usage_rows = consumable_usages(
        ProductUsage.objects.filter(created_at__gte=start, created_at__lte=end)
    ).values_list('visit__staff_id', 'total_cost_usd_snapshot', 'exchange_rate_snapshot')
    for staff_id, usd, snapshot_rate in usage_rows:
        row = cost.setdefault(staff_id, {'usd': ZERO, 'toman': ZERO})
        row['usd'] += _q(usd)
        row['toman'] += _q(usd) * (snapshot_rate or rate)

    rows = {}
    for staff_id in set(revenue) | set(cost):
        rev = revenue.get(staff_id, {'usd': ZERO, 'toman': ZERO})
        cst = cost.get(staff_id, {'usd': ZERO, 'toman': ZERO})
        rows[staff_id] = {
            'revenue_usd': rev['usd'].quantize(Decimal('0.01')),
            'revenue_toman': rev['toman'].quantize(Decimal('0.01')),
            'product_cost_usd': cst['usd'].quantize(Decimal('0.01')),
            'product_cost_toman': cst['toman'].quantize(Decimal('0.01')),
            'material_profit_usd': (rev['usd'] - cst['usd']).quantize(Decimal('0.01')),
            'material_profit_toman': (rev['toman'] - cst['toman']).quantize(Decimal('0.01')),
        }

    if totals is not None:
        attributed_usd = sum((r['revenue_usd'] for r in rows.values()), ZERO)
        attributed_toman = sum((r['revenue_toman'] for r in rows.values()), ZERO)
        cost_usd = sum((r['product_cost_usd'] for r in rows.values()), ZERO)
        cost_toman = sum((r['product_cost_toman'] for r in rows.values()), ZERO)
        residual_rev_usd = (totals['revenue']['usd'] - attributed_usd).quantize(Decimal('0.01'))
        residual_rev_toman = (totals['revenue']['toman'] - attributed_toman).quantize(Decimal('0.01'))
        residual_cost_usd = (totals['product_cost']['usd'] - cost_usd).quantize(Decimal('0.01'))
        residual_cost_toman = (totals['product_cost']['toman'] - cost_toman).quantize(Decimal('0.01'))
    else:
        unattributed = rows.pop(None, None) or {
            'revenue_usd': ZERO, 'revenue_toman': ZERO,
            'product_cost_usd': ZERO, 'product_cost_toman': ZERO,
        }
        residual_rev_usd = unattributed['revenue_usd']
        residual_rev_toman = unattributed['revenue_toman']
        residual_cost_usd = unattributed['product_cost_usd']
        residual_cost_toman = unattributed['product_cost_toman']
        rows.pop(None, None)

    rows[None] = {
        'revenue_usd': residual_rev_usd,
        'revenue_toman': residual_rev_toman,
        'product_cost_usd': residual_cost_usd,
        'product_cost_toman': residual_cost_toman,
        'material_profit_usd': (residual_rev_usd - residual_cost_usd).quantize(Decimal('0.01')),
        'material_profit_toman': (residual_rev_toman - residual_cost_toman).quantize(Decimal('0.01')),
    }
    return rows


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

    # Cash view: what is left once the stock bought this period is also paid
    # for. Deliberately NOT subtracted from net_profit (that would charge the
    # same product twice, here and again as product cost at consumption).
    purchases = purchase_totals(start, end)
    net_after_purchases_usd = (net_usd - purchases['usd']).quantize(Decimal('0.01'))
    net_after_purchases_toman = (net_toman - purchases['toman']).quantize(Decimal('0.01'))

    # The clinic's immediate take: what is left after material cost, welcome
    # packs and the compensation owed to operators. Operating expenses and
    # staff claims are reported below this line (see net_profit).
    clinic_share_usd = (
        revenue_usd - product_cost_usd - welcome_pack_cost['usd'] - staff['total_usd']
    ).quantize(Decimal('0.01'))
    clinic_share_toman = (
        revenue_toman - product_cost_toman - welcome_pack_cost['toman'] - staff['total_toman']
    ).quantize(Decimal('0.01'))

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
        'clinic_share': {'usd': clinic_share_usd, 'toman': clinic_share_toman},
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
        'purchases': purchases,
        'net_profit_after_purchases': {
            'usd': net_after_purchases_usd, 'toman': net_after_purchases_toman,
        },
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
