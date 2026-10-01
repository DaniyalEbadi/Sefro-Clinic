"""Report layer.

Thin rendering over :mod:`finance.services.financials`, which owns the actual
business calculation. Nothing here re-derives revenue, cost or profit, so two
endpoints can never disagree about Gross or Net Profit.
"""
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
from . import financials
from .exchange_rates import get_rate

# Re-exported so existing imports keep working.
REVENUE_STATUSES = financials.REVENUE_STATUSES
EXPENSE_STATUSES = financials.EXPENSE_STATUSES
CASH_METHODS = financials.CASH_METHODS
REVENUE_BASIS_LIST_PRICE = financials.REVENUE_BASIS_LIST_PRICE
REVENUE_BASIS_LEDGER = financials.REVENUE_BASIS_LEDGER
WELCOME_PACK_COST_BASIS_EXCLUDED = financials.WELCOME_PACK_COST_BASIS_EXCLUDED

ZERO = Decimal('0')


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


def payment_method_breakdown(comps):
    return financials.payment_method_breakdown(comps)


def financial_summary(start=None, end=None, *, service_id=None, package_id=None, product_id=None, personnel_id=None):
    """The authoritative period report. See ``financials.build_report``."""
    start, end = _range(start, end)
    return financials.build_report(
        start, end,
        service_id=service_id, package_id=package_id,
        product_id=product_id, personnel_id=personnel_id,
    )


def profit_by_service(start=None, end=None):
    """Service-level contribution for the period.

    Revenue is the collected sale amount allocated to each service in proportion
    to list price; material cost is the actual ``ProductUsage`` snapshot for
    that service on that visit. Services sold with no consumable recipe, and
    services whose consumption was never recorded, both still appear.

    Welcome-pack cost is excluded (packs belong to no service) and only
    accounted for in the summary's Net Profit.
    """
    from customers.models import Visit

    start, end = _range(start, end)
    visits = Visit.objects.filter(
        start_at__gte=start, start_at__lte=end, status=Visit.Status.COMPLETED,
    ).prefetch_related('services')

    rows = {}
    list_price_only = False
    for visit in visits:
        per_visit = financials.calculate_visit_financials(visit)
        if per_visit['revenue_basis'] == financials.REVENUE_BASIS_LIST_PRICE:
            list_price_only = True
        for service_row in per_visit['services'].values():
            key = service_row['service_id']
            row = rows.setdefault(key, {
                'service_id': key,
                'service_name': service_row['service_name'],
                'revenue_usd': ZERO,
                'product_cost_usd': ZERO,
                'count': 0,
                'revenue_basis': service_row['revenue_basis'],
                'welcome_pack_cost_basis': WELCOME_PACK_COST_BASIS_EXCLUDED,
            })
            row['revenue_usd'] += service_row['revenue_usd']
            row['product_cost_usd'] += service_row['product_cost_usd']
            row['count'] += 1

    for row in rows.values():
        row['revenue_usd'] = row['revenue_usd'].quantize(Decimal('0.01'))
        row['product_cost_usd'] = row['product_cost_usd'].quantize(Decimal('0.01'))
        row['profit_usd'] = (row['revenue_usd'] - row['product_cost_usd']).quantize(Decimal('0.01'))
        row['profit_margin_percent'] = (
            (row['profit_usd'] / row['revenue_usd'] * 100).quantize(Decimal('0.01'))
            if row['revenue_usd'] else ZERO
        )
        if row['revenue_basis'] == financials.REVENUE_BASIS_LIST_PRICE:
            row['revenue_basis'] = REVENUE_BASIS_LIST_PRICE
    if list_price_only and rows:
        for row in rows.values():
            if row['revenue_basis'] != REVENUE_BASIS_LEDGER:
                row['revenue_basis'] = REVENUE_BASIS_LIST_PRICE
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
                'revenue_usd': ZERO,
                'product_cost_usd': ZERO,
                'count': 0,
                'revenue_basis': REVENUE_BASIS_LEDGER,
                'welcome_pack_cost_basis': WELCOME_PACK_COST_BASIS_EXCLUDED,
            }
        rows[key]['revenue_usd'] += sale.amount_usd
        rows[key]['count'] += 1
    usage_cost = {}
    for package_id, cost in financials.consumable_usages(
        ProductUsage.objects.filter(
            created_at__gte=start, created_at__lte=end, package_sale__isnull=False,
        )
    ).values_list('package_sale__package_id', 'total_cost_usd_snapshot'):
        usage_cost[package_id] = usage_cost.get(package_id, ZERO) + (cost or ZERO)
    for key, row in rows.items():
        row['product_cost_usd'] = usage_cost.get(key, ZERO).quantize(Decimal('0.01'))
        row['revenue_usd'] = row['revenue_usd'].quantize(Decimal('0.01'))
        row['profit_usd'] = (row['revenue_usd'] - row['product_cost_usd']).quantize(Decimal('0.01'))
        row['profit_margin_percent'] = (
            (row['profit_usd'] / row['revenue_usd'] * 100).quantize(Decimal('0.01'))
            if row['revenue_usd'] else ZERO
        )
    return sorted(rows.values(), key=lambda r: r['profit_usd'], reverse=True)


def wallet_summary():
    liability = Wallet.objects.aggregate(total=Sum('balance'))['total'] or ZERO
    rewards = WalletTransaction.objects.filter(
        transaction_type=WalletTransaction.Type.REWARD,
    ).aggregate(total=Sum('amount'))['total'] or ZERO
    reward_reverses = WalletTransaction.objects.filter(
        transaction_type=WalletTransaction.Type.REWARD_REVERSE,
    ).aggregate(total=Sum('amount'))['total'] or ZERO
    payments = WalletTransaction.objects.filter(
        transaction_type=WalletTransaction.Type.PAYMENT,
    ).aggregate(total=Sum('amount'))['total'] or ZERO
    refunds = WalletTransaction.objects.filter(
        transaction_type=WalletTransaction.Type.REFUND,
    ).aggregate(total=Sum('amount'))['total'] or ZERO
    return {
        'total_liability_usd': liability,
        'rewards_issued_usd': rewards,
        'reward_reversals_usd': reward_reverses,
        'wallet_payments_usd': abs(payments),
        'wallet_refunds_usd': refunds,
    }


def operating_expense_summary(start=None, end=None):
    """Totals for direct clinic operating costs (OperatingExpense).

    These are part of the clinic's Net Profit (see ``financials.build_report``);
    this endpoint exists for the expenses screen itself.
    """
    start, end = _range(start, end)
    qs = OperatingExpense.objects.filter(
        expense_date__gte=start.date(), expense_date__lte=end.date(),
    )
    total_usd = qs.aggregate(total=Sum('amount_usd'))['total'] or ZERO
    total_toman = qs.aggregate(total=Sum('amount_toman'))['total'] or ZERO
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


def welcome_pack_report(start=None, end=None):
    start, end = _range(start, end)
    usages = WelcomePackUsage.objects.filter(issued_at__gte=start, issued_at__lte=end)
    return {
        'period': {'start': start, 'end': end},
        'total_usage_count': usages.count(),
        'total_packs_issued': usages.aggregate(total=Sum('quantity'))['total'] or ZERO,
        'total_cost_usd': usages.aggregate(total=Sum('total_cost_usd_snapshot'))['total'] or ZERO,
        'total_cost_toman': usages.aggregate(total=Sum('total_cost_toman_snapshot'))['total'] or ZERO,
        'by_pack': list(
            usages.values('welcome_pack_id', 'welcome_pack__name')
            .annotate(
                count=Sum('quantity'),
                cost_usd=Sum('total_cost_usd_snapshot'),
                cost_toman=Sum('total_cost_toman_snapshot'),
                usage_count=Count('id'),
            )
            .order_by('-cost_usd')
        ),
    }


__all__ = [
    'REVENUE_STATUSES', 'EXPENSE_STATUSES', 'CASH_METHODS',
    'REVENUE_BASIS_LIST_PRICE', 'REVENUE_BASIS_LEDGER', 'WELCOME_PACK_COST_BASIS_EXCLUDED',
    'payment_method_breakdown', 'financial_summary', 'profit_by_service',
    'profit_by_package', 'wallet_summary', 'operating_expense_summary', 'welcome_pack_report',
    'Expense', 'PaymentComponent', 'get_rate',
]
