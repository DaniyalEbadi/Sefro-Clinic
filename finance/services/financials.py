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
    PackageService,
    PaymentComponent,
    ProductPurchase,
    ProductUsage,
    PurchaseOrder,
    PurchaseOrderItem,
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


def _opt_int(value):
    """A filter id from a query string as ``int``, or ``None`` when absent.

    Callers that expose this to HTTP validate first (a 400 beats a 500); this
    coercion only keeps direct service-layer callers honest.
    """
    if value in (None, ''):
        return None
    return int(value)


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
    Completed visits use only ProductUsage snapshots for material cost. A
    completed visit missing a snapshot is treated as zero actual cost and
    flagged, rather than silently using today's recipe price. Incomplete
    visits retain the recipe estimate as a planning value only.
    """
    rate = rate if rate is not None else get_rate('USD', 'TOMAN')
    services = list(visit.services.all())

    revenue_usd, revenue_toman, basis = visit_revenue(visit, rate=rate)
    costs, total_product_cost_usd, total_product_cost_toman = service_costs_for_visit(visit, rate=rate)

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
    # ``service_costs_for_visit`` already returns the visit total, including
    # usage rows that cannot be attributed to a service.  Start from that
    # total; adding each service row again would double-count material cost.
    summed_cost_usd = total_product_cost_usd
    summed_cost_toman = total_product_cost_toman
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
        elif visit.status == 'completed':
            cost_usd = ZERO
            cost_toman = ZERO
            cost_basis = 'missing_consumption_snapshot'
        else:
            # Incomplete visits may show the recipe estimate as planning data,
            # but it is never authoritative for a completed visit.
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


def staff_compensation_totals(start, end, *, staff_id=None, service_id=None, payout_ids=None):
    """Staff cost owed for the period, split by role, still a real liability.

    ``payout_ids`` (a set) replaces the date window with an explicit row set:
    package-attribution callers pass the payouts already scoped to one
    package's unambiguous visit linkage (see :func:`package_attribution`).
    ``staff_id`` / ``service_id`` narrow on top of either scope.
    """
    qs = StaffPayout.objects.filter(status__in=PAYOUT_OBLIGATION_STATUSES)
    if payout_ids is not None:
        qs = qs.filter(id__in=payout_ids)
    else:
        qs = qs.filter(created_at__gte=start, created_at__lte=end)
    if staff_id is not None:
        qs = qs.filter(staff_id=staff_id)
    if service_id is not None:
        qs = qs.filter(service_id=service_id)
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


def purchase_totals(start, end, product_id=None):
    """Stock-purchase cash out for the period, from both purchase ledgers.

    Purchases never enter net profit: inventory is charged to profit exactly
    once, at consumption (ProductUsage snapshots). This reports the money that
    actually left the clinic on stock so callers can show
    ``net_profit_after_purchases`` as a cash view *next to* the P&L.

    Two ledgers exist and both must be read or purchases silently vanish:
      * ``PurchaseOrderItem`` behind orders that reached ``received``
      * ``ProductPurchase``, the one-shot restock ledger

    ``product_id`` narrows both ledgers to that product (order rows, not
    order totals, so sibling lines on a shared order are never charged).
    """
    g_start, g_end = start.date(), end.date()

    if product_id is not None:
        items = PurchaseOrderItem.objects.filter(
            order__status=PurchaseOrder.Status.RECEIVED,
            order__received_date__gte=g_start, order__received_date__lte=g_end,
            product_id=product_id,
        )
        po_usd = _q(items.aggregate(t=Sum('total_cost_usd'))['t'])
        po_toman = _q(items.aggregate(t=Sum('total_cost_toman'))['t'])
        po_count = items.count()
    else:
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
    if product_id is not None:
        direct = direct.filter(product_id=product_id)
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


def _visit_operator_maps(visit_ids):
    """``visit_id -> (per-service operator map, primary staff id)``.

    The per-service assignment (``VisitService.staff``) wins; the visit's
    primary ``staff_id`` is the fallback key used when a service has no
    assigned operator (legacy / untagged users). Both maps are built in two
    queries for a whole period.
    """
    from customers.models import Visit, VisitService

    visit_ids = [visit_id for visit_id in set(visit_ids) if visit_id is not None]
    links: dict = {}
    primaries: dict = {}
    if visit_ids:
        for link in VisitService.objects.filter(
            visit_id__in=visit_ids, staff_id__isnull=False,
        ).select_related('staff'):
            links.setdefault(link.visit_id, {})[link.service_id] = link.staff
        primaries = dict(
            Visit.objects.filter(id__in=visit_ids).values_list('id', 'staff_id'),
        )
    return links, primaries


def operator_attribution(start, end, *, totals=None):
    """Revenue and material cost produced by each staff member.

    Rows are keyed on the operator who performed each *service* on the visit
    (the per-service assignment first, the visit's primary staff as the
    fallback), so a mixed visit credits its revenue and material cost to the
    right people. A sale is split across the visit's services by the same
    list-price weight the compensation engine uses; product usages carry
    their service directly.

    Same anchors and the same costing rule as :func:`build_report`
    (``Sale.created_at`` / ``ProductUsage.created_at``, cost = snapshot USD x
    its snapshot rate), so the rows are comparable with the report totals.

    ``StaffPayout`` cannot be used for this: a ``monthly_salary`` payout row
    stores ``revenue = 0`` and ``profit = 0`` on purpose, so the laser tech's
    produced revenue would simply be missing.

    Pass ``totals`` (the whole ``build_report`` payload -- it reads ``revenue``
    and ``product_cost`` off it) to get an ``unattributed`` residual row that
    makes the parts sum back to the whole exactly, rounding included. Without
    it the residual is only the sales and usages whose visit has neither a
    primary staff member nor an assigned operator.
    """
    sales = (
        Sale.objects
        .filter(created_at__gte=start, created_at__lte=end, status__in=REVENUE_STATUSES)
        .select_related('visit')
        .prefetch_related('visit__services')
    )
    sales_by_visit: dict = {}
    for sale in sales:
        sales_by_visit.setdefault(sale.visit_id, []).append(sale)

    usage_rows = list(
        consumable_usages(
            ProductUsage.objects.filter(created_at__gte=start, created_at__lte=end)
        ).values_list('visit_id', 'service_id', 'total_cost_usd_snapshot', 'exchange_rate_snapshot'),
    )

    links, primaries = _visit_operator_maps(
        list(sales_by_visit) + [row[0] for row in usage_rows],
    )

    def staff_key(visit_id, service_id=None):
        """The operator this row belongs to: per-service first, primary next."""
        if visit_id is None:
            return None
        operator = links.get(visit_id, {}).get(service_id) if service_id is not None else None
        if operator is not None:
            return operator.id
        return primaries.get(visit_id)

    revenue: dict = {}

    def add_revenue(key, usd, toman):
        bucket = revenue.setdefault(key, {'usd': ZERO, 'toman': ZERO})
        bucket['usd'] += _q(usd)
        bucket['toman'] += _q(toman)

    for visit_id, visit_sales in sales_by_visit.items():
        if visit_id is None:
            for sale in visit_sales:
                add_revenue(None, sale.amount_usd, sale.amount_toman)
            continue
        services = list(visit_sales[0].visit.services.all()) if visit_sales[0].visit else []
        if not services:
            # A visit without service lines cannot be split: the whole sale
            # belongs to the visit's primary staff (legacy shape).
            for sale in visit_sales:
                add_revenue(primaries.get(visit_id), sale.amount_usd, sale.amount_toman)
            continue
        for sale in visit_sales:
            for service in services:
                share_usd, share_toman = _service_share(
                    services, sale.amount_usd, sale.amount_toman, service.id,
                )
                add_revenue(staff_key(visit_id, service.id), share_usd, share_toman)

    cost: dict = {}
    rate = get_rate('USD', 'TOMAN')
    for visit_id, service_id, usd, snapshot_rate in usage_rows:
        row = cost.setdefault(staff_key(visit_id, service_id), {'usd': ZERO, 'toman': ZERO})
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


def package_attribution(start, end):
    """Costs unambiguously attributed to in-period package sales.

    A visit can carry more than one package sale, so a visit-level cost cannot
    simply be copied onto every package sold on that visit (that was the old
    duplication bug in ``reporting.profit_by_package``). Every rule here
    prefers exclusion over a guess:

    * only ``session`` payouts are candidates -- a ``monthly_salary`` row is
      anchored on an arbitrary visit/service from its month settlement, never
      on a package's work;
    * a payout goes to package P when the visit sold P inside the period, the
      payout's service is listed in P's services, and exactly one of the
      packages sold on that visit lists that service;
    * a welcome-pack issuance goes to package P when exactly one package was
      sold on that visit inside the period;
    * anything that fails is counted in ``excluded`` and charged to no package.

    Returns per-package id/currency maps plus the excluded counters. Anchored
    on the package sale's visit (the same linkage
    ``reporting.profit_by_package`` renders), not on payout/pack timestamps.
    """
    sales = Sale.objects.filter(
        created_at__gte=start, created_at__lte=end,
        package__isnull=False, status=Sale.Status.PAID, visit_id__isnull=False,
    ).values_list('package_id', 'visit_id')

    visit_to_packages: dict[int, set] = {}
    package_ids = set()
    for pkg_id, visit_id in sales:
        visit_to_packages.setdefault(visit_id, set()).add(pkg_id)
        package_ids.add(pkg_id)

    pkg_services: dict[int, set] = {}
    if package_ids:
        for pkg_id, service_id in PackageService.objects.filter(
            package_id__in=package_ids,
        ).values_list('package_id', 'service_id'):
            pkg_services.setdefault(pkg_id, set()).add(service_id)

    payout_ids_by_package: dict[int, set] = {}
    payout_usd_by_package: dict[int, Decimal] = {}
    payout_toman_by_package: dict[int, Decimal] = {}
    excluded_payout_count = 0
    if visit_to_packages:
        payouts = StaffPayout.objects.filter(
            visit_id__in=visit_to_packages.keys(),
            status__in=PAYOUT_OBLIGATION_STATUSES,
            payout_kind=StaffPayout.PayoutKind.SESSION,
        ).values_list(
            'id', 'visit_id', 'service_id',
            'payout_cash_usd', 'payout_cash_toman',
            'payout_product_value_usd', 'payout_product_value_toman',
        )
        for (
            payout_id, visit_id, service_id,
            cash_usd, cash_toman, prod_usd, prod_toman,
        ) in payouts:
            candidates = {
                pkg_id for pkg_id in visit_to_packages[visit_id]
                if service_id in pkg_services.get(pkg_id, ())
            }
            if len(candidates) != 1:
                excluded_payout_count += 1
                continue
            pkg_id = next(iter(candidates))
            payout_ids_by_package.setdefault(pkg_id, set()).add(payout_id)
            payout_usd_by_package[pkg_id] = (
                payout_usd_by_package.get(pkg_id, ZERO)
                + _q(cash_usd) + _q(prod_usd)
            )
            payout_toman_by_package[pkg_id] = (
                payout_toman_by_package.get(pkg_id, ZERO)
                + _q(cash_toman) + _q(prod_toman)
            )

    welcome_pack_ids_by_package: dict[int, set] = {}
    welcome_pack_usd_by_package: dict[int, Decimal] = {}
    welcome_pack_toman_by_package: dict[int, Decimal] = {}
    excluded_welcome_pack_count = 0
    if visit_to_packages:
        for usage_id, visit_id, usd, toman in WelcomePackUsage.objects.filter(
            visit_id__in=visit_to_packages.keys(),
        ).values_list('id', 'visit_id', 'total_cost_usd_snapshot', 'total_cost_toman_snapshot'):
            packages_on_visit = visit_to_packages[visit_id]
            if len(packages_on_visit) != 1:
                excluded_welcome_pack_count += 1
                continue
            pkg_id = next(iter(packages_on_visit))
            welcome_pack_ids_by_package.setdefault(pkg_id, set()).add(usage_id)
            welcome_pack_usd_by_package[pkg_id] = welcome_pack_usd_by_package.get(pkg_id, ZERO) + _q(usd)
            welcome_pack_toman_by_package[pkg_id] = welcome_pack_toman_by_package.get(pkg_id, ZERO) + _q(toman)

    return {
        'payout_ids_by_package': payout_ids_by_package,
        'payout_usd_by_package': {
            pkg_id: total.quantize(Decimal('0.01'))
            for pkg_id, total in payout_usd_by_package.items()
        },
        'payout_toman_by_package': {
            pkg_id: total.quantize(Decimal('0.01'))
            for pkg_id, total in payout_toman_by_package.items()
        },
        'welcome_pack_ids_by_package': welcome_pack_ids_by_package,
        'welcome_pack_usd_by_package': {
            pkg_id: total.quantize(Decimal('0.01'))
            for pkg_id, total in welcome_pack_usd_by_package.items()
        },
        'welcome_pack_toman_by_package': {
            pkg_id: total.quantize(Decimal('0.01'))
            for pkg_id, total in welcome_pack_toman_by_package.items()
        },
        'excluded_payout_count': excluded_payout_count,
        'excluded_welcome_pack_count': excluded_welcome_pack_count,
        'basis': 'unambiguous_visit_linkage',
    }


def _service_share(services, amount_usd, amount_toman, service_id):
    """One service's list-price share of an amount across ``services``.

    Same weight rule as ``calculate_visit_financials``: list-price proportion,
    or an even split when every service is free. Returns ``(usd, toman)``.
    """
    if not services:
        return ZERO, ZERO
    weights = [_q(service.price_usd) for service in services]
    weight_total = sum(weights, ZERO)
    amount_usd = _q(amount_usd)
    amount_toman = _q(amount_toman)
    if weight_total > 0:
        for service, weight in zip(services, weights):
            if service.id == service_id:
                return (
                    (amount_usd * (weight / weight_total)).quantize(Decimal('0.01')),
                    (amount_toman * (weight / weight_total)).quantize(Decimal('0.01')),
                )
        return ZERO, ZERO
    share = amount_usd / Decimal(len(services))
    share_toman = amount_toman / Decimal(len(services))
    return share.quantize(Decimal('0.01')), share_toman.quantize(Decimal('0.01'))


def _sale_service_share(sale, service_id):
    """The sale's list-price share of one service on its visit.

    Same weight rule as ``calculate_visit_financials``: list-price proportion,
    or an even split when every service on the visit is free. Returns
    ``(usd, toman)``.
    """
    visit = sale.visit
    if visit is None:
        return ZERO, ZERO
    return _service_share(list(visit.services.all()), sale.amount_usd, sale.amount_toman, service_id)


def _welcome_pack_service_share(start, end, service_id, staff_id=None):
    """The service's revenue-share slice of period pack issuances on its visits.

    Pack cost has no natural service owner; it is split across the visit's
    services by the same list-price weight the revenue split uses (evenly when
    every service is free), mirroring ``calculate_visit_financials``. Rows are
    anchored on ``issued_at`` like the unfiltered period total.
    """
    usages = WelcomePackUsage.objects.filter(
        issued_at__gte=start, issued_at__lte=end, visit__services=service_id,
    )
    if staff_id is not None:
        usages = usages.filter(visit__staff_id=staff_id)
    total_usd = ZERO
    total_toman = ZERO
    for usage in usages.select_related('visit').prefetch_related('visit__services'):
        services = list(usage.visit.services.all())
        if not services:
            continue
        weights = [_q(service.price_usd) for service in services]
        weight_total = sum(weights, ZERO)
        pack_usd = _q(usage.total_cost_usd_snapshot)
        pack_toman = _q(usage.total_cost_toman_snapshot)
        if weight_total > 0:
            for service, weight in zip(services, weights):
                if service.id == service_id:
                    total_usd += pack_usd * (weight / weight_total)
                    total_toman += pack_toman * (weight / weight_total)
                    break
        else:
            total_usd += pack_usd / Decimal(len(services))
            total_toman += pack_toman / Decimal(len(services))
    return {
        'usd': total_usd.quantize(Decimal('0.01')),
        'toman': total_toman.quantize(Decimal('0.01')),
        'source': 'welcome_pack_usage_allocated',
    }


def _empty_compensation():
    z = lambda: Decimal('0.00')  # noqa: E731 - one-line zero factory
    return {
        'cash_usd': z(), 'cash_toman': z(),
        'product_usd': z(), 'product_toman': z(),
        'total_usd': z(), 'total_toman': z(),
        'payout_count': 0, 'by_role': {},
    }


def _empty_period_totals():
    """Zeroed operating/claim/purchase blocks for filters with no attribution."""
    z = lambda: Decimal('0.00')  # noqa: E731 - one-line zero factory
    empty_line = {'total_usd': z(), 'total_toman': z(), 'count': 0}
    return {
        'operating': dict(empty_line),
        'claims': dict(empty_line),
        'purchases': {
            'usd': z(), 'toman': z(), 'count': 0,
            'by_source': {
                'purchase_order': {'usd': z(), 'toman': z(), 'count': 0},
                'direct': {'usd': z(), 'toman': z(), 'count': 0},
            },
        },
    }


def welcome_pack_totals(start, end, product_id=None, *, staff_id=None, service_id=None):
    """Welcome-pack cost for the period, counted exactly once.

    Pack cost is only ever read from the WelcomePackUsage snapshot. The
    pack-linked ProductUsage rows exist for the consumption log and are
    excluded from product cost, so the same inventory is never charged twice.

    ``product_id`` narrows to that product's pack consumption rows (a period
    snapshot cannot be split per product). ``staff_id`` follows the visit's
    staff; ``service_id`` is only meaningful on the product path -- snapshot
    rows carry no service, so the caller allocates those by revenue share
    (see build_report).
    """
    if product_id:
        # A period snapshot total cannot be narrowed to one product, so use that
        # product's pack consumption rows instead.
        rows = ProductUsage.objects.filter(
            created_at__gte=start, created_at__lte=end,
            welcome_pack_usage__isnull=False, product_id=product_id,
        )
        if staff_id is not None:
            rows = rows.filter(visit__staff_id=staff_id)
        if service_id is not None:
            rows = rows.filter(service_id=service_id)
        total_usd = _q(rows.aggregate(t=Sum('total_cost_usd_snapshot'))['t'])
        total_toman = ZERO
        for cost_usd, snapshot_rate in rows.values_list('total_cost_usd_snapshot', 'exchange_rate_snapshot'):
            total_toman += _q(cost_usd) * (snapshot_rate or get_rate('USD', 'TOMAN'))
        total_toman = total_toman.quantize(Decimal('0.01'))
        return {'usd': total_usd.quantize(Decimal('0.01')), 'toman': total_toman, 'source': 'product_usage'}

    wp_usages = WelcomePackUsage.objects.filter(issued_at__gte=start, issued_at__lte=end)
    if staff_id is not None:
        wp_usages = wp_usages.filter(visit__staff_id=staff_id)
    return {
        'usd': _q(wp_usages.aggregate(t=Sum('total_cost_usd_snapshot'))['t']).quantize(Decimal('0.01')),
        'toman': _q(wp_usages.aggregate(t=Sum('total_cost_toman_snapshot'))['t']).quantize(Decimal('0.01')),
        'source': 'welcome_pack_usage',
    }


def build_report(start, end, *, service_id=None, package_id=None, product_id=None, personnel_id=None):
    """The authoritative period report every endpoint renders.

    Filter scoping: every active filter must narrow each component through an
    established attribution, or that component is reported as zero -- never
    silently left clinic-wide.

    * ``personnel_id``: revenue/usages/welcome packs via the visit's staff,
      compensation via ``StaffPayout.staff``, claims via ``Expense.created_by``,
      appointments via ``Visit.staff``.
    * ``package_id``: revenue via ``Sale.package``, material cost via
      ``ProductUsage.package_sale``, compensation and welcome packs via the
      unambiguous visit-linkage rules in :func:`package_attribution`.
    * ``service_id``: revenue as each sale's list-price share of that service
      on its visit, material cost via ``ProductUsage.service``, compensation
      via ``StaffPayout.service``, welcome packs as that service's revenue
      share of each visit's pack issuance, appointments via visit membership.
    * ``product_id``: material cost via ``ProductUsage.product``, welcome packs
      via that product's pack consumption rows, purchases via the product
      ledgers, revenue as sales of visits that consumed the product (the same
      visit-linkage family welcome-pack attribution uses).
    * Operating expenses, staff claims (beyond personnel), wallet rewards and
      purchases (beyond product) carry no filterable attribution and are
      reported as zero while any filter is active.
    """
    from customers.models import Visit

    service_id = _opt_int(service_id)
    package_id = _opt_int(package_id)
    product_id = _opt_int(product_id)
    personnel_id = _opt_int(personnel_id)
    any_filter = any(
        value is not None
        for value in (service_id, package_id, product_id, personnel_id)
    )

    sales = Sale.objects.filter(
        created_at__gte=start, created_at__lte=end, status__in=REVENUE_STATUSES,
    )
    if personnel_id is not None:
        sales = sales.filter(visit__staff_id=personnel_id)
    if package_id is not None:
        sales = sales.filter(package_id=package_id)

    product_visit_ids = None
    if product_id is not None:
        product_visit_ids = set(
            ProductUsage.objects.filter(
                created_at__gte=start, created_at__lte=end, product_id=product_id,
            ).exclude(visit_id=None).values_list('visit_id', flat=True)
        )
        sales = sales.filter(visit_id__in=product_visit_ids)

    if service_id is not None:
        sales = sales.filter(visit__services=service_id)

    if service_id is not None:
        revenue_usd = ZERO
        revenue_toman = ZERO
        revenue_sale_count = 0
        for sale in sales.select_related('visit').prefetch_related('visit__services'):
            share_usd, share_toman = _sale_service_share(sale, service_id)
            revenue_usd += share_usd
            revenue_toman += share_toman
            revenue_sale_count += 1
        revenue_usd = revenue_usd.quantize(Decimal('0.01'))
        revenue_toman = revenue_toman.quantize(Decimal('0.01'))
    else:
        revenue_usd = _q(sales.aggregate(t=Sum('amount_usd'))['t']).quantize(Decimal('0.01'))
        revenue_toman = _q(sales.aggregate(t=Sum('amount_toman'))['t']).quantize(Decimal('0.01'))
        revenue_sale_count = sales.count()

    usages = ProductUsage.objects.filter(created_at__gte=start, created_at__lte=end)
    if service_id is not None:
        usages = usages.filter(service_id=service_id)
    if product_id is not None:
        usages = usages.filter(product_id=product_id)
    if personnel_id is not None:
        usages = usages.filter(visit__staff_id=personnel_id)
    if package_id is not None:
        usages = usages.filter(package_sale__package_id=package_id)
    cost_usages = consumable_usages(usages)

    product_cost_usd = _q(cost_usages.aggregate(t=Sum('total_cost_usd_snapshot'))['t']).quantize(Decimal('0.01'))
    product_cost_toman = ZERO
    for cost_usd, snapshot_rate in cost_usages.values_list('total_cost_usd_snapshot', 'exchange_rate_snapshot'):
        product_cost_toman += _q(cost_usd) * (snapshot_rate or get_rate('USD', 'TOMAN'))
    product_cost_toman = product_cost_toman.quantize(Decimal('0.01'))

    package_attr = None
    if package_id is not None:
        package_attr = package_attribution(start, end)
        welcome_pack_cost = {
            'usd': package_attr['welcome_pack_usd_by_package'].get(package_id, ZERO).quantize(Decimal('0.01')),
            'toman': package_attr['welcome_pack_toman_by_package'].get(package_id, ZERO).quantize(Decimal('0.01')),
            'source': 'package_attribution',
        }
    elif product_id is not None:
        welcome_pack_cost = welcome_pack_totals(
            start, end, product_id=product_id, staff_id=personnel_id, service_id=service_id,
        )
    elif service_id is not None:
        welcome_pack_cost = _welcome_pack_service_share(start, end, service_id, staff_id=personnel_id)
    elif personnel_id is not None:
        welcome_pack_cost = welcome_pack_totals(start, end, staff_id=personnel_id)
    else:
        welcome_pack_cost = welcome_pack_totals(start, end)

    gross_usd = (revenue_usd - product_cost_usd - welcome_pack_cost['usd']).quantize(Decimal('0.01'))
    gross_toman = (
        revenue_toman - product_cost_toman - welcome_pack_cost['toman']
    ).quantize(Decimal('0.01'))

    if package_id is not None:
        payout_ids = package_attr['payout_ids_by_package'].get(package_id, set())
        if personnel_id is not None:
            payout_ids = set(
                StaffPayout.objects.filter(id__in=payout_ids, staff_id=personnel_id)
                .values_list('id', flat=True)
            )
        if service_id is not None:
            payout_ids = set(
                StaffPayout.objects.filter(id__in=payout_ids, service_id=service_id)
                .values_list('id', flat=True)
            )
        staff = staff_compensation_totals(start, end, payout_ids=payout_ids)
    elif product_id is not None:
        staff = _empty_compensation()
    else:
        staff = staff_compensation_totals(start, end, staff_id=personnel_id, service_id=service_id)

    if service_id is not None or package_id is not None or product_id is not None:
        # Claims are only attributable to a person (the claimant). Service,
        # package and product filters carry no claim attribution.
        claims = _empty_period_totals()['claims']
    else:
        claims = claim_totals(start, end, personnel_id=personnel_id)

    if any_filter:
        zeros = _empty_period_totals()
        operating = zeros['operating']
    else:
        operating = operating_expense_totals(start, end)

    below_line_usd = (staff['total_usd'] + operating['total_usd'] + claims['total_usd']).quantize(Decimal('0.01'))
    below_line_toman = (
        staff['total_toman'] + operating['total_toman'] + claims['total_toman']
    ).quantize(Decimal('0.01'))

    net_usd = (gross_usd - below_line_usd).quantize(Decimal('0.01'))
    net_toman = (gross_toman - below_line_toman).quantize(Decimal('0.01'))

    # Cash view: what is left once the stock bought this period is also paid
    # for. Deliberately NOT subtracted from net_profit (that would charge the
    # same product twice, here and again as product cost at consumption).
    if product_id is not None:
        purchases = purchase_totals(start, end, product_id=product_id)
    elif any_filter:
        purchases = _empty_period_totals()['purchases']
    else:
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

    appointments_qs = Visit.objects.filter(
        start_at__gte=start, start_at__lte=end, status=Visit.Status.COMPLETED,
    )
    if any_filter:
        if personnel_id is not None:
            appointments_qs = appointments_qs.filter(staff_id=personnel_id)
        if service_id is not None:
            appointments_qs = appointments_qs.filter(services=service_id)
        if product_id is not None:
            appointments_qs = appointments_qs.filter(id__in=product_visit_ids or set())
        if package_id is not None:
            appointments_qs = appointments_qs.filter(
                sales__package_id=package_id, sales__status=Sale.Status.PAID,
            ).distinct()
    appointments = appointments_qs.count()
    packages_sold = sales.filter(package__isnull=False, status=Sale.Status.PAID).count()
    products_sold = _q(usages.aggregate(t=Sum('quantity'))['t'])

    rewards_issued = (
        ZERO if any_filter else _q(
            WalletTransaction.objects.filter(
                transaction_type=WalletTransaction.Type.REWARD,
                created_at__gte=start, created_at__lte=end,
            ).aggregate(t=Sum('amount'))['t']
        )
    )

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
            'rewards_issued': rewards_issued,
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
