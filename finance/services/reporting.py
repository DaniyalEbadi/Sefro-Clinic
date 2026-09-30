from datetime import datetime, time
from decimal import Decimal

from django.db.models import Count, Sum
from django.utils import timezone

from ..models import (
    Expense,
    OperatingExpense,
    PaymentComponent,
    ProductUsage,
    Sale,
    Wallet,
    WalletTransaction,
    WelcomePackUsage,
)
from .exchange_rates import get_rate


def _range(start, end):
    if start and end:
        if hasattr(start, 'date') is False:
            start = timezone.make_aware(datetime.combine(start, time.min))
        if hasattr(end, 'date') is False:
            end = timezone.make_aware(datetime.combine(end, time.max))
        return start, end
    now = timezone.now()
    start = start or timezone.make_aware(datetime.combine(now.date(), time.min))
    end = end or timezone.make_aware(datetime.combine(now.date(), time.max))
    return start, end


REVENUE_STATUSES = [Sale.Status.PAID, Sale.Status.REFUNDED, Sale.Status.PARTIALLY_REFUNDED]
EXPENSE_STATUSES = [Expense.Status.APPROVED, Expense.Status.PAID]

# Cash is recorded under three method codes (the checkout writes `cash_toman`,
# sometimes `cash_usd`); they are all real cash, so they share one bucket.
CASH_METHODS = (
    PaymentComponent.Method.CASH,
    PaymentComponent.Method.CASH_TOMAN,
    PaymentComponent.Method.CASH_USD,
)

# Provenance labels so a report can never be read as "cash collected" or
# "revenue" when it is really list price or excludes welcome packs.
REVENUE_BASIS_LIST_PRICE = 'list_price'
REVENUE_BASIS_LEDGER = 'sale_ledger'
WELCOME_PACK_COST_BASIS_EXCLUDED = 'excluded'


def payment_method_breakdown(comps):
    """Fold a PaymentComponent queryset into the cash/card/wallet tiles the UI renders.

    Returns ``(breakdown, by_method)``: ``breakdown`` keeps the historical
    three keys with all cash variants summed into ``cash``, while ``by_method``
    exposes the untouched per-code totals for callers that need the split.
    Single query, shared by every report so the two copies cannot drift again.
    """
    by_method = {
        row['method']: (row['total'] or Decimal('0'))
        for row in comps.values('method').annotate(total=Sum('amount_usd'))
    }
    cash = sum((by_method.get(method, Decimal('0')) for method in CASH_METHODS), Decimal('0'))
    breakdown = {
        PaymentComponent.Method.CASH: cash,
        PaymentComponent.Method.CARD: by_method.get(PaymentComponent.Method.CARD, Decimal('0')),
        PaymentComponent.Method.WALLET: by_method.get(PaymentComponent.Method.WALLET, Decimal('0')),
    }
    # `by_method` keeps every raw code (including the cash variants) and adds
    # the folded `cash` total, so neither view is lost.
    return breakdown, {**by_method, PaymentComponent.Method.CASH: cash}


def financial_summary(start=None, end=None, *, service_id=None, package_id=None, product_id=None, personnel_id=None):
    start, end = _range(start, end)

    # Only revenue-bearing sales count. Pending/cancelled sales are not money.
    # Refunded sales stay in (their amount_usd is negative), so a refund keeps
    # subtracting from revenue.
    sales = Sale.objects.filter(
        created_at__gte=start, created_at__lte=end, status__in=REVENUE_STATUSES,
    )
    if personnel_id:
        sales = sales.filter(visit__staff_id=personnel_id)
    if package_id:
        sales = sales.filter(package_id=package_id)

    revenue_usd = sales.aggregate(total=Sum('amount_usd'))['total'] or Decimal('0')
    revenue_toman = sales.aggregate(total=Sum('amount_toman'))['total'] or Decimal('0')
    # Average ticket is derived from the same revenue-bearing set as the
    # revenue itself, so the two can never disagree.
    revenue_sale_count = sales.count()

    usages = ProductUsage.objects.filter(created_at__gte=start, created_at__lte=end)
    if service_id:
        usages = usages.filter(service_id=service_id)
    if product_id:
        usages = usages.filter(product_id=product_id)
    # Welcome-pack consumption is costed from the immutable WelcomePackUsage
    # snapshots below, so its ProductUsage rows are excluded here; counting both
    # would charge the same inventory twice. Historical pack issuances predate
    # those rows and are still covered by the snapshot path.
    cost_usages = usages.filter(welcome_pack_usage__isnull=True)
    product_cost_usd = cost_usages.aggregate(total=Sum('total_cost_usd_snapshot'))['total'] or Decimal('0')
    product_cost_toman = Decimal('0')
    for u in cost_usages.only('total_cost_usd_snapshot', 'exchange_rate_snapshot'):
        product_cost_toman += (u.total_cost_usd_snapshot or Decimal('0')) * (u.exchange_rate_snapshot or get_rate())
    product_cost_toman = product_cost_toman.quantize(Decimal('0.01'))

    # Welcome Pack costs (from immutable usage snapshots)
    wp_usages = WelcomePackUsage.objects.filter(issued_at__gte=start, issued_at__lte=end)
    if product_id:
        # The snapshot total is a period-wide figure and cannot be narrowed to a
        # single product, so use that product's pack consumption rows instead.
        welcome_pack_cost_usd = usages.filter(welcome_pack_usage__isnull=False).aggregate(
            total=Sum('total_cost_usd_snapshot'),
        )['total'] or Decimal('0')
        welcome_pack_cost_toman = Decimal('0')
        for u in usages.filter(welcome_pack_usage__isnull=False).only('total_cost_usd_snapshot', 'exchange_rate_snapshot'):
            welcome_pack_cost_toman += (u.total_cost_usd_snapshot or Decimal('0')) * (u.exchange_rate_snapshot or get_rate())
        welcome_pack_cost_toman = welcome_pack_cost_toman.quantize(Decimal('0.01'))
    else:
        welcome_pack_cost_usd = wp_usages.aggregate(total=Sum('total_cost_usd_snapshot'))['total'] or Decimal('0')
        welcome_pack_cost_toman = wp_usages.aggregate(total=Sum('total_cost_toman_snapshot'))['total'] or Decimal('0')

    gross_profit_usd = (revenue_usd - product_cost_usd - welcome_pack_cost_usd).quantize(Decimal('0.01'))
    gross_profit_toman = (revenue_toman - product_cost_toman - welcome_pack_cost_toman).quantize(Decimal('0.01'))

    expenses = Expense.objects.filter(
        expense_date__gte=start.date(), expense_date__lte=end.date(),
        status__in=EXPENSE_STATUSES,
    )
    if personnel_id:
        expenses = expenses.filter(created_by_id=personnel_id)
    expenses_usd = expenses.aggregate(total=Sum('amount_usd'))['total'] or Decimal('0')
    expenses_toman = expenses.aggregate(total=Sum('amount_toman'))['total'] or Decimal('0')

    net_profit_usd = (gross_profit_usd - expenses_usd).quantize(Decimal('0.01'))
    net_profit_toman = (gross_profit_toman - expenses_toman).quantize(Decimal('0.01'))

    paid_sales = sales.filter(status=Sale.Status.PAID)
    sale_count = paid_sales.count()
    avg_txn = (revenue_usd / revenue_sale_count).quantize(Decimal('0.01')) if revenue_sale_count else Decimal('0')

    comps = PaymentComponent.objects.filter(sale__in=sales)
    method_breakdown, method_breakdown_by_method = payment_method_breakdown(comps)

    rewards_issued = WalletTransaction.objects.filter(
        transaction_type=WalletTransaction.Type.REWARD,
        created_at__gte=start, created_at__lte=end,
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0')

    wallet_payments = comps.filter(method=PaymentComponent.Method.WALLET).aggregate(total=Sum('amount_usd'))['total'] or Decimal('0')
    refunds = abs(
        sales.filter(status__in=[Sale.Status.REFUNDED, Sale.Status.PARTIALLY_REFUNDED], amount_usd__lt=0)
        .aggregate(total=Sum('amount_usd'))['total'] or Decimal('0')
    )

    from customers.models import Visit
    appointments = Visit.objects.filter(
        start_at__gte=start, start_at__lte=end, status=Visit.Status.COMPLETED,
    ).count()
    packages_sold = sales.filter(package__isnull=False, status=Sale.Status.PAID).count()
    products_sold = usages.aggregate(total=Sum('quantity'))['total'] or Decimal('0')

    # A product with no cost history falls back to Product.cost_usd, which is
    # 0.00 for anything never purchased. That silently overstates profit, so
    # surface exactly which consumptions were costed at zero.
    zero_cost_usages = usages.filter(total_cost_usd_snapshot=Decimal('0'))
    zero_cost_rows = zero_cost_usages.count()
    cost_coverage = {
        'usage_rows': usages.count(),
        'zero_cost_rows': zero_cost_rows,
        'products_missing_cost': sorted(set(
            zero_cost_usages.values_list('product_id', flat=True).distinct(),
        )),
    }
    if cost_coverage['products_missing_cost']:
        cost_coverage['warning'] = (
            'Some consumed products have no recorded cost and were priced at $0.00, '
            'so product cost and profit are overstated.'
        )

    return {
        'period': {'start': start, 'end': end},
        'revenue': {'usd': revenue_usd, 'toman': revenue_toman},
        'revenue_basis': REVENUE_BASIS_LEDGER,
        'product_cost': {'usd': product_cost_usd, 'toman': product_cost_toman},
        'welcome_pack_cost': {'usd': welcome_pack_cost_usd, 'toman': welcome_pack_cost_toman},
        'cost_coverage': cost_coverage,
        'gross_profit': {'usd': gross_profit_usd, 'toman': gross_profit_toman},
        'expenses': {'usd': expenses_usd, 'toman': expenses_toman},
        'net_profit': {'usd': net_profit_usd, 'toman': net_profit_toman},
        'payment_methods': method_breakdown,
        'payment_methods_by_method': method_breakdown_by_method,
        'wallet': {
            'rewards_issued': rewards_issued,
            'wallet_payments': wallet_payments,
            'refunds': refunds,
        },
        'counts': {
            'appointments': appointments,
            'packages_sold': packages_sold,
            'products_sold_quantity': products_sold,
            'paid_sales': sale_count,
            'average_transaction_value': avg_txn,
        },
    }


def profit_by_service(start=None, end=None):
    """Service-level contribution for the period.

    Revenue definition: **list price of each distinct completed visit-service
    pair** (one visit of a service counts once, no matter how many consumable
    lines the service recipe has). It is potential revenue, not collected cash:
    discounts, packages and partial payments are not reflected, because
    ``Sale`` records a whole visit (or package) and has no per-service line to
    allocate from. Consumption contributes cost only.

    Welcome-pack cost is **excluded** here (packs belong to no service) and is
    only accounted for in ``financial_summary``.
    """
    from customers.models import Visit

    start, end = _range(start, end)
    visits = Visit.objects.filter(
        start_at__gte=start, start_at__lte=end, status=Visit.Status.COMPLETED,
    ).prefetch_related('services')

    rows = {}
    for visit in visits:
        for svc in visit.services.all():
            row = rows.setdefault(svc.id, {
                'service_id': svc.id,
                'service_name': svc.name,
                'revenue_usd': Decimal('0'),
                'product_cost_usd': Decimal('0'),
                'count': 0,
                'revenue_basis': REVENUE_BASIS_LIST_PRICE,
                'welcome_pack_cost_basis': WELCOME_PACK_COST_BASIS_EXCLUDED,
            })
            row['revenue_usd'] += svc.price_usd or Decimal('0')
            row['count'] += 1

    usages = ProductUsage.objects.filter(
        created_at__gte=start, created_at__lte=end, service__isnull=False,
        welcome_pack_usage__isnull=True,
    ).values_list('service_id', 'total_cost_usd_snapshot')
    for service_id, total_cost in usages:
        if service_id in rows:
            rows[service_id]['product_cost_usd'] += total_cost or Decimal('0')

    for row in rows.values():
        row['revenue_usd'] = row['revenue_usd'].quantize(Decimal('0.01'))
        row['product_cost_usd'] = row['product_cost_usd'].quantize(Decimal('0.01'))
        row['profit_usd'] = (row['revenue_usd'] - row['product_cost_usd']).quantize(Decimal('0.01'))
        row['profit_margin_percent'] = (
            (row['profit_usd'] / row['revenue_usd'] * 100).quantize(Decimal('0.01'))
            if row['revenue_usd'] else Decimal('0')
        )
    return sorted(rows.values(), key=lambda r: r['profit_usd'], reverse=True)


def profit_by_package(start=None, end=None):
    start, end = _range(start, end)
    sales = Sale.objects.filter(
        created_at__gte=start, created_at__lte=end, package__isnull=False, status=Sale.Status.PAID,
    ).select_related('package')
    rows = {}
    for sale in sales:
        pkg = sale.package
        key = pkg.id
        if key not in rows:
            rows[key] = {
                'package_id': pkg.id,
                'package_name': pkg.name,
                'revenue_usd': Decimal('0'),
                'product_cost_usd': Decimal('0'),
                'count': 0,
                'revenue_basis': REVENUE_BASIS_LEDGER,
                'welcome_pack_cost_basis': WELCOME_PACK_COST_BASIS_EXCLUDED,
            }
        rows[key]['revenue_usd'] += sale.amount_usd
        rows[key]['count'] += 1
    usage_cost = {}
    for u in ProductUsage.objects.filter(
        created_at__gte=start, created_at__lte=end, package_sale__isnull=False,
    ).select_related('package_sale'):
        pk = u.package_sale.package_id
        usage_cost[pk] = usage_cost.get(pk, Decimal('0')) + (u.total_cost_usd_snapshot or Decimal('0'))
    for key, row in rows.items():
        row['product_cost_usd'] = usage_cost.get(key, Decimal('0')).quantize(Decimal('0.01'))
        row['revenue_usd'] = row['revenue_usd'].quantize(Decimal('0.01'))
        row['profit_usd'] = (row['revenue_usd'] - row['product_cost_usd']).quantize(Decimal('0.01'))
        row['profit_margin_percent'] = (
            (row['profit_usd'] / row['revenue_usd'] * 100).quantize(Decimal('0.01'))
            if row['revenue_usd'] else Decimal('0')
        )
    return sorted(rows.values(), key=lambda r: r['profit_usd'], reverse=True)


def wallet_summary():
    liability = Wallet.objects.aggregate(total=Sum('balance'))['total'] or Decimal('0')
    rewards = WalletTransaction.objects.filter(
        transaction_type=WalletTransaction.Type.REWARD,
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0')
    reward_reverses = WalletTransaction.objects.filter(
        transaction_type=WalletTransaction.Type.REWARD_REVERSE,
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0')
    payments = WalletTransaction.objects.filter(
        transaction_type=WalletTransaction.Type.PAYMENT,
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0')
    refunds = WalletTransaction.objects.filter(
        transaction_type=WalletTransaction.Type.REFUND,
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0')
    return {
        'total_liability_usd': liability,
        'rewards_issued_usd': rewards,
        'reward_reversals_usd': reward_reverses,
        'wallet_payments_usd': abs(payments),
        'wallet_refunds_usd': refunds,
    }


def operating_expense_summary(start=None, end=None):
    """Totals for direct clinic operating costs (OperatingExpense).

    Kept deliberately separate from ``financial_summary``'s Expense
    aggregation (employee-submitted claims). Combine both upstream for a
    total-clinic-cost view; neither query is duplicated or mixed here.
    """
    start, end = _range(start, end)
    qs = OperatingExpense.objects.filter(
        expense_date__gte=start.date(), expense_date__lte=end.date(),
    )
    total_usd = qs.aggregate(total=Sum('amount_usd'))['total'] or Decimal('0')
    total_toman = qs.aggregate(total=Sum('amount_toman'))['total'] or Decimal('0')
    by_category = list(
        qs.values('category_id', 'category__name')
        .annotate(
            total_usd=Sum('amount_usd'),
            total_toman=Sum('amount_toman'),
            count=Count('id'),
        )
        .order_by('-total_usd')
    )
    by_method = list(
        qs.values('payment_method')
        .annotate(total_usd=Sum('amount_usd'), count=Count('id'))
        .order_by('payment_method')
    )
    return {
        'period': {'start': start, 'end': end},
        'total_usd': total_usd,
        'total_toman': total_toman,
        'count': qs.count(),
        'by_category': by_category,
        'by_payment_method': by_method,
    }
