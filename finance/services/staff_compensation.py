from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from ..models import (
    ProductUsage,
    Sale,
    StaffCompensationRule,
    StaffPayout,
)
from .exchange_rates import get_current_usd_to_toman_rate


def get_rate():
    return get_current_usd_to_toman_rate() or Decimal('0')


def calculate_visit_profit(visit):
    rate = get_rate()
    services = visit.services.all()

    total_revenue_usd = Decimal('0')
    total_cost_usd = Decimal('0')

    for svc in services:
        total_revenue_usd += svc.price_usd or Decimal('0')
        for item in svc.items.select_related('product').all():
            qty = item.quantity
            cost = item.product.cost_usd if item.product else Decimal('0')
            total_cost_usd += (Decimal(str(qty)) * Decimal(str(cost))).quantize(Decimal('0.01'))

    revenue_toman = (total_revenue_usd * rate).quantize(Decimal('0.01'))
    cost_toman = (total_cost_usd * rate).quantize(Decimal('0.01'))
    profit_usd = (total_revenue_usd - total_cost_usd).quantize(Decimal('0.01'))
    profit_toman = (revenue_toman - cost_toman).quantize(Decimal('0.01'))

    return {
        'revenue_usd': total_revenue_usd,
        'revenue_toman': revenue_toman,
        'product_cost_usd': total_cost_usd,
        'product_cost_toman': cost_toman,
        'profit_usd': profit_usd,
        'profit_toman': profit_toman,
        'rate': rate,
    }


def calculate_service_payout(visit, service, rule, profit_usd, profit_toman, rate):
    payout_cash_usd = Decimal('0')
    payout_cash_toman = Decimal('0')
    payout_product = None
    payout_product_qty = Decimal('0')
    payout_product_value_usd = Decimal('0')
    payout_product_value_toman = Decimal('0')

    if rule.calculation_type == StaffCompensationRule.CalculationType.PERCENT_PROFIT:
        if rule.percent_profit:
            pct = rule.percent_profit / Decimal('100')
            payout_cash_usd = (profit_usd * pct).quantize(Decimal('0.01'))
            payout_cash_toman = (profit_toman * pct).quantize(Decimal('0.01'))

            if rule.transport_usd:
                payout_cash_usd += rule.transport_usd
                payout_cash_toman += rule.transport_usd * rate
            elif rule.transport_toman:
                payout_cash_toman += rule.transport_toman
                payout_cash_usd += (rule.transport_toman / rate).quantize(Decimal('0.01')) if rate else Decimal('0')

    elif rule.calculation_type == StaffCompensationRule.CalculationType.FIXED_PER_SESSION:
        if rule.fixed_amount_usd:
            payout_cash_usd = rule.fixed_amount_usd
            payout_cash_toman = (rule.fixed_amount_usd * rate).quantize(Decimal('0.01'))
        elif rule.fixed_amount_toman:
            payout_cash_toman = rule.fixed_amount_toman
            payout_cash_usd = (rule.fixed_amount_toman / rate).quantize(Decimal('0.01')) if rate else Decimal('0')

        if rule.transport_usd:
            payout_cash_usd += rule.transport_usd
            payout_cash_toman += rule.transport_usd * rate
        elif rule.transport_toman:
            payout_cash_toman += rule.transport_toman
            payout_cash_usd += (rule.transport_toman / rate).quantize(Decimal('0.01')) if rate else Decimal('0')

    if rule.payout_type in (StaffCompensationRule.PayoutType.PRODUCT, StaffCompensationRule.PayoutType.HYBRID):
        if rule.product and rule.product_qty:
            payout_product = rule.product
            payout_product_qty = rule.product_qty
            payout_product_value_usd = (rule.product.cost_usd * rule.product_qty).quantize(Decimal('0.01'))
            payout_product_value_toman = (payout_product_value_usd * rate).quantize(Decimal('0.01'))

    return {
        'payout_cash_usd': payout_cash_usd,
        'payout_cash_toman': payout_cash_toman,
        'payout_product': payout_product,
        'payout_product_qty': payout_product_qty,
        'payout_product_value_usd': payout_product_value_usd,
        'payout_product_value_toman': payout_product_value_toman,
    }


@transaction.atomic
def generate_visit_payouts(visit, actor=None):
    if visit.status != 'completed':
        return []

    staff = visit.staff
    if not staff:
        return []

    rate = get_rate()
    profit_data = calculate_visit_profit(visit)

    created_payouts = []
    for service in visit.services.all():
        role = service.compensation_role
        if role == 'none':
            continue

        try:
            rule = StaffCompensationRule.objects.get(role=role, is_active=True)
        except StaffCompensationRule.DoesNotExist:
            continue

        payout_calc = calculate_service_payout(
            visit, service, rule,
            profit_data['profit_usd'], profit_data['profit_toman'], rate
        )

        payout, created = StaffPayout.objects.update_or_create(
            visit=visit,
            staff=staff,
            service=service,
            defaults={
                'role': role,
                'revenue_usd': profit_data['revenue_usd'],
                'revenue_toman': profit_data['revenue_toman'],
                'product_cost_usd': profit_data['product_cost_usd'],
                'product_cost_toman': profit_data['product_cost_toman'],
                'profit_usd': profit_data['profit_usd'],
                'profit_toman': profit_data['profit_toman'],
                'exchange_rate': rate,
                'payout_cash_usd': payout_calc['payout_cash_usd'],
                'payout_cash_toman': payout_calc['payout_cash_toman'],
                'payout_product': payout_calc['payout_product'],
                'payout_product_qty': payout_calc['payout_product_qty'],
                'payout_product_value_usd': payout_calc['payout_product_value_usd'],
                'payout_product_value_toman': payout_calc['payout_product_value_toman'],
                'status': StaffPayout.Status.PENDING,
                'payout_mode': StaffPayout.PayoutMode.PRODUCT if rule.payout_type == StaffCompensationRule.PayoutType.PRODUCT else StaffPayout.PayoutMode.CASH,
            }
        )
        created_payouts.append(payout)

        if created and rule.payout_type in (StaffCompensationRule.PayoutType.PRODUCT, StaffCompensationRule.PayoutType.HYBRID):
            if rule.product and rule.product_qty:
                from finance.services.inventory import record_product_usage
                record_product_usage(
                    product=rule.product,
                    quantity=rule.product_qty,
                    visit=visit,
                    service=service,
                    at=timezone.now(),
                    rate=rate,
                    is_commission=True,
                )

    return created_payouts


def staff_payout_summary(start=None, end=None, staff_id=None, role=None):
    from datetime import time

    if start and end:
        if hasattr(start, 'date') is False:
            start = timezone.make_aware(timezone.datetime.combine(start, time.min))
        if hasattr(end, 'date') is False:
            end = timezone.make_aware(timezone.datetime.combine(end, time.max))
    else:
        now = timezone.now()
        start = start or timezone.make_aware(timezone.datetime.combine(now.date(), time.min))
        end = end or timezone.make_aware(timezone.datetime.combine(now.date(), time.max))

    qs = StaffPayout.objects.filter(created_at__gte=start, created_at__lte=end)
    if staff_id:
        qs = qs.filter(staff_id=staff_id)
    if role:
        qs = qs.filter(role=role)

    agg = qs.aggregate(
        total_cash_usd=Sum('payout_cash_usd'),
        total_cash_toman=Sum('payout_cash_toman'),
        total_product_value_usd=Sum('payout_product_value_usd'),
        total_product_value_toman=Sum('payout_product_value_toman'),
        count=Sum('id'),
    )

    return {
        'period': {'start': start, 'end': end},
        'total_cash_usd': agg['total_cash_usd'] or Decimal('0'),
        'total_cash_toman': agg['total_cash_toman'] or Decimal('0'),
        'total_product_value_usd': agg['total_product_value_usd'] or Decimal('0'),
        'total_product_value_toman': agg['total_product_value_toman'] or Decimal('0'),
        'total_payout_usd': (agg['total_cash_usd'] or Decimal('0')) + (agg['total_product_value_usd'] or Decimal('0')),
        'total_payout_toman': (agg['total_cash_toman'] or Decimal('0')) + (agg['total_product_value_toman'] or Decimal('0')),
        'payout_count': qs.count(),
    }


def staff_payout_detail(start=None, end=None, staff_id=None):
    from datetime import time

    if start and end:
        if hasattr(start, 'date') is False:
            start = timezone.make_aware(timezone.datetime.combine(start, time.min))
        if hasattr(end, 'date') is False:
            end = timezone.make_aware(timezone.datetime.combine(end, time.max))
    else:
        now = timezone.now()
        start = start or timezone.make_aware(timezone.datetime.combine(now.date(), time.min))
        end = end or timezone.make_aware(timezone.datetime.combine(now.date(), time.max))

    qs = StaffPayout.objects.filter(created_at__gte=start, created_at__lte=end).select_related(
        'staff', 'visit', 'service', 'payout_product'
    )
    if staff_id:
        qs = qs.filter(staff_id=staff_id)

    return list(qs.values(
        'id', 'staff__username', 'staff__first_name', 'staff__last_name',
        'visit__id', 'service__name', 'role',
        'revenue_usd', 'revenue_toman',
        'product_cost_usd', 'product_cost_toman',
        'profit_usd', 'profit_toman',
        'payout_cash_usd', 'payout_cash_toman',
        'payout_product__name', 'payout_product_qty',
        'payout_product_value_usd', 'payout_product_value_toman',
        'exchange_rate', 'status', 'payout_mode', 'created_at'
    ))