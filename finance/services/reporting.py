from datetime import datetime, time
from decimal import Decimal

from django.db.models import Sum
from django.utils import timezone

from ..models import (
    Expense,
    PaymentComponent,
    ProductUsage,
    Sale,
    Wallet,
    WalletTransaction,
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


def financial_summary(start=None, end=None, *, service_id=None, package_id=None, product_id=None, personnel_id=None):
    start, end = _range(start, end)

    sales = Sale.objects.filter(created_at__gte=start, created_at__lte=end)
    if personnel_id:
        sales = sales.filter(visit__staff_id=personnel_id)
    if package_id:
        sales = sales.filter(package_id=package_id)

    revenue_usd = sales.aggregate(total=Sum('amount_usd'))['total'] or Decimal('0')
    revenue_toman = sales.aggregate(total=Sum('amount_toman'))['total'] or Decimal('0')

    usages = ProductUsage.objects.filter(created_at__gte=start, created_at__lte=end)
    if service_id:
        usages = usages.filter(service_id=service_id)
    if product_id:
        usages = usages.filter(product_id=product_id)
    product_cost_usd = usages.aggregate(total=Sum('total_cost_usd_snapshot'))['total'] or Decimal('0')
    product_cost_toman = Decimal('0')
    for u in usages.only('total_cost_usd_snapshot', 'exchange_rate_snapshot'):
        product_cost_toman += (u.total_cost_usd_snapshot or Decimal('0')) * (u.exchange_rate_snapshot or get_rate())
    product_cost_toman = product_cost_toman.quantize(Decimal('0.01'))

    gross_profit_usd = (revenue_usd - product_cost_usd).quantize(Decimal('0.01'))
    gross_profit_toman = (revenue_toman - product_cost_toman).quantize(Decimal('0.01'))

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
    avg_txn = (revenue_usd / sale_count).quantize(Decimal('0.01')) if sale_count else Decimal('0')

    comps = PaymentComponent.objects.filter(sale__in=sales)
    method_breakdown = {}
    for method in (PaymentComponent.Method.CASH, PaymentComponent.Method.CARD, PaymentComponent.Method.WALLET):
        method_breakdown[method] = comps.filter(method=method).aggregate(total=Sum('amount_usd'))['total'] or Decimal('0')

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

    return {
        'period': {'start': start, 'end': end},
        'revenue': {'usd': revenue_usd, 'toman': revenue_toman},
        'product_cost': {'usd': product_cost_usd, 'toman': product_cost_toman},
        'gross_profit': {'usd': gross_profit_usd, 'toman': gross_profit_toman},
        'expenses': {'usd': expenses_usd, 'toman': expenses_toman},
        'net_profit': {'usd': net_profit_usd, 'toman': net_profit_toman},
        'payment_methods': method_breakdown,
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
    start, end = _range(start, end)
    usages = ProductUsage.objects.filter(
        created_at__gte=start, created_at__lte=end, service__isnull=False,
    ).select_related('service')
    rows = {}
    for u in usages:
        svc = u.service
        key = svc.id
        if key not in rows:
            rows[key] = {
                'service_id': svc.id,
                'service_name': svc.name,
                'revenue_usd': Decimal('0'),
                'product_cost_usd': Decimal('0'),
                'count': 0,
            }
        rows[key]['product_cost_usd'] += u.total_cost_usd_snapshot or Decimal('0')
        rows[key]['revenue_usd'] += svc.price_usd or Decimal('0')
        rows[key]['count'] += 1
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
