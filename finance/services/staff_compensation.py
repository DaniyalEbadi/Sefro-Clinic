from collections import defaultdict
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.utils import timezone

from ..models import (
    StaffCompensationRule,
    StaffPayout,
    StaffPayoutProduct,
)
from .exchange_rates import get_current_usd_to_toman_rate
from .inventory import record_product_usage


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


def _rule_product_lines(rule):
    """(product, quantity) lines to pay out for a rule.

    Prefers the StaffCompensationRuleProduct rows; falls back to the legacy
    single product/product_qty pair so rules written before the multi-product
    change (or directly via the ORM) still pay out.
    """
    if rule.payout_type not in (
        StaffCompensationRule.PayoutType.PRODUCT,
        StaffCompensationRule.PayoutType.HYBRID,
    ):
        return []
    lines = [(line.product, line.quantity) for line in rule.product_lines.select_related('product').all()]
    if not lines and rule.product_id:
        lines = [(rule.product, rule.product_qty)]
    return [(product, quantity) for product, quantity in lines if product and quantity and quantity > 0]


def calculate_service_payout(visit, service, rule, profit_usd, profit_toman, rate):
    payout_cash_usd = Decimal('0')
    payout_cash_toman = Decimal('0')

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

    elif rule.calculation_type in (
        StaffCompensationRule.CalculationType.FIXED_PER_SESSION,
        StaffCompensationRule.CalculationType.MONTHLY_SALARY,
    ):
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

    payout_products = []
    for product, quantity in _rule_product_lines(rule):
        value_usd = (product.cost_usd * quantity).quantize(Decimal('0.01'))
        payout_products.append({
            'product': product,
            'quantity': quantity,
            'value_usd': value_usd,
            'value_toman': (value_usd * rate).quantize(Decimal('0.01')),
        })

    return {
        'payout_cash_usd': payout_cash_usd,
        'payout_cash_toman': payout_cash_toman,
        'payout_product': payout_products[0]['product'] if payout_products else None,
        'payout_product_qty': payout_products[0]['quantity'] if payout_products else Decimal('0'),
        'payout_product_value_usd': sum((line['value_usd'] for line in payout_products), Decimal('0')),
        'payout_product_value_toman': sum((line['value_toman'] for line in payout_products), Decimal('0')),
        'payout_products': payout_products,
    }


def _upsert_monthly_salary_payout(*, visit, staff, service, role, salary_period, rate, payout_calc, payout_mode):
    """One salary settlement row per (staff, role, month).

    Returns (payout, created); (None, False) when the row cannot be written
    (e.g. a per-visit payout already occupies this visit/staff/service and the
    rule was switched to monthly_salary mid-month).
    """
    defaults = {
        'visit': visit,
        'service': service,
        'revenue_usd': Decimal('0'),
        'revenue_toman': Decimal('0'),
        'product_cost_usd': Decimal('0'),
        'product_cost_toman': Decimal('0'),
        'profit_usd': Decimal('0'),
        'profit_toman': Decimal('0'),
        'exchange_rate': rate,
        'payout_cash_usd': payout_calc['payout_cash_usd'],
        'payout_cash_toman': payout_calc['payout_cash_toman'],
        'payout_product': payout_calc['payout_product'],
        'payout_product_qty': payout_calc['payout_product_qty'],
        'payout_product_value_usd': payout_calc['payout_product_value_usd'],
        'payout_product_value_toman': payout_calc['payout_product_value_toman'],
        'status': StaffPayout.Status.PENDING,
        'payout_mode': payout_mode,
    }
    try:
        with transaction.atomic():
            payout, created = StaffPayout.objects.get_or_create(
                staff=staff,
                role=role,
                payout_kind=StaffPayout.PayoutKind.MONTHLY_SALARY,
                salary_period=salary_period,
                defaults=defaults,
            )
    except IntegrityError:
        return None, False

    if not created and payout.status == StaffPayout.Status.PENDING:
        # Track an amount change made before the row was approved/paid;
        # approved rows keep the amount they were settled with.
        changed = [
            field for field in ('exchange_rate', 'payout_cash_usd', 'payout_cash_toman')
            if getattr(payout, field) != defaults[field]
        ]
        if changed:
            for field in changed:
                setattr(payout, field, defaults[field])
            payout.save(update_fields=[*changed, 'updated_at'])
    return payout, created


@transaction.atomic
def generate_visit_payouts(visit, actor=None):
    if visit.status != 'completed':
        return []

    staff = visit.staff
    if not staff:
        return []

    rate = get_rate()
    profit_data = calculate_visit_profit(visit)
    salary_period = timezone.localtime(visit.start_at).date().replace(day=1)

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
        payout_mode = (
            StaffPayout.PayoutMode.PRODUCT
            if rule.payout_type == StaffCompensationRule.PayoutType.PRODUCT
            else StaffPayout.PayoutMode.CASH
        )

        if rule.calculation_type == StaffCompensationRule.CalculationType.MONTHLY_SALARY:
            payout, created = _upsert_monthly_salary_payout(
                visit=visit, staff=staff, service=service, role=role,
                salary_period=salary_period, rate=rate,
                payout_calc=payout_calc, payout_mode=payout_mode,
            )
            if payout is None:
                continue
            if not any(existing.pk == payout.pk for existing in created_payouts):
                created_payouts.append(payout)
        else:
            try:
                with transaction.atomic():
                    payout, created = StaffPayout.objects.update_or_create(
                        visit=visit,
                        staff=staff,
                        service=service,
                        payout_kind=StaffPayout.PayoutKind.SESSION,
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
                            'payout_mode': payout_mode,
                        }
                    )
            except IntegrityError:
                continue
            created_payouts.append(payout)

        if created:
            for line in payout_calc['payout_products']:
                StaffPayoutProduct.objects.create(
                    payout=payout,
                    product=line['product'],
                    quantity=line['quantity'],
                    value_usd=line['value_usd'],
                    value_toman=line['value_toman'],
                )
                record_product_usage(
                    product=line['product'],
                    quantity=line['quantity'],
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

    rows = list(qs.values(
        'id', 'staff__username', 'staff__first_name', 'staff__last_name',
        'visit__id', 'service__name', 'role',
        'revenue_usd', 'revenue_toman',
        'product_cost_usd', 'product_cost_toman',
        'profit_usd', 'profit_toman',
        'payout_cash_usd', 'payout_cash_toman',
        'payout_product__name', 'payout_product_qty',
        'payout_product_value_usd', 'payout_product_value_toman',
        'exchange_rate', 'status', 'payout_mode', 'payout_kind', 'salary_period', 'created_at'
    ))

    lines_by_payout = defaultdict(list)
    payout_ids = [row['id'] for row in rows]
    if payout_ids:
        for line in StaffPayoutProduct.objects.filter(payout_id__in=payout_ids).select_related('product'):
            lines_by_payout[line.payout_id].append({
                'product': line.product_id,
                'product_name': str(line.product),
                'quantity': line.quantity,
                'value_usd': line.value_usd,
                'value_toman': line.value_toman,
            })
    for row in rows:
        row['payout_products'] = lines_by_payout.get(row['id'], [])
    return rows
