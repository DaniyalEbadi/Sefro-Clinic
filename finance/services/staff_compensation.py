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
from .financials import calculate_visit_financials, visit_requires_staff
from .inventory import record_product_usage


class CompensationError(Exception):
    """A visit cannot be compensated as requested (e.g. missing staff)."""


def get_rate():
    return get_current_usd_to_toman_rate() or Decimal('0')


def calculate_visit_profit(visit):
    """Whole-visit totals.

    Kept for callers that need a visit-level number. Compensation must NOT use
    this: each service is paid on its own profit (see
    ``financials.calculate_visit_financials``), because a visit routinely mixes
    a doctor's service with a facial operator's.
    """
    rate = get_rate()
    financials = calculate_visit_financials(visit, rate=rate)
    return {
        'revenue_usd': financials['revenue_usd'],
        'revenue_toman': financials['revenue_toman'],
        'product_cost_usd': financials['product_cost_usd'],
        'product_cost_toman': financials['product_cost_toman'],
        'profit_usd': (financials['revenue_usd'] - financials['product_cost_usd']).quantize(Decimal('0.01')),
        'profit_toman': (
            financials['revenue_toman'] - financials['product_cost_toman']
        ).quantize(Decimal('0.01')),
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


SETTLED_STATUSES = (StaffPayout.Status.APPROVED, StaffPayout.Status.PAID)

# Fields that make up a settled session payout. A payout that has already been
# approved or paid must keep the amount it was settled with, so recalculating
# only refreshes a row that is still PENDING.
_SESSION_AMOUNT_FIELDS = (
    'revenue_usd', 'revenue_toman', 'product_cost_usd', 'product_cost_toman',
    'profit_usd', 'profit_toman', 'exchange_rate', 'payout_cash_usd',
    'payout_cash_toman', 'payout_product', 'payout_product_qty',
    'payout_product_value_usd', 'payout_product_value_toman', 'payout_mode',
)


def _upsert_session_payout(*, visit, staff, service, role, financials, rate, payout_calc, payout_mode):
    """One session payout per (visit, staff, service).

    Returns ``(payout, created)``, or ``(None, False)`` when an existing row
    was already approved/paid and must keep its settled amount.
    """
    defaults = {
        'role': role,
        'revenue_usd': financials['revenue_usd'],
        'revenue_toman': financials['revenue_toman'],
        'product_cost_usd': financials['product_cost_usd'],
        'product_cost_toman': financials['product_cost_toman'],
        'profit_usd': financials['profit_usd'],
        'profit_toman': financials['profit_toman'],
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
                visit=visit,
                staff=staff,
                service=service,
                payout_kind=StaffPayout.PayoutKind.SESSION,
                defaults=defaults,
            )
    except IntegrityError:
        return None, False

    if created:
        return payout, True

    # Already settled: leave the agreed amount alone.
    if payout.status in SETTLED_STATUSES:
        return payout, False

    changed = [field for field in _SESSION_AMOUNT_FIELDS if getattr(payout, field) != defaults[field]]
    if changed:
        for field in changed:
            setattr(payout, field, defaults[field])
        payout.save(update_fields=[*changed, 'updated_at'])
    return payout, False


def cancel_payouts_for_visit(visit, reason=''):
    """Void the compensation owed for a visit whose revenue was cancelled/refunded.

    Payout rows are marked CANCELLED rather than deleted so the history stays
    auditable, and running it twice is harmless: already-cancelled rows are not
    touched again, so no duplicate reversal rows appear.

    Returns the number of payouts transitioned to CANCELLED.
    """
    payouts = StaffPayout.objects.filter(
        visit=visit, status__in=[
            StaffPayout.Status.PENDING, StaffPayout.Status.APPROVED,
        ],
    ).exclude(payout_kind=StaffPayout.PayoutKind.MONTHLY_SALARY)
    changed = 0
    for payout in payouts:
        payout.status = StaffPayout.Status.CANCELLED
        notes = (payout.notes or '').strip()
        message = f'Cancelled: {reason}' if reason else 'Cancelled.'
        payout.notes = f'{notes} {message}'.strip()
        payout.save(update_fields=['status', 'notes', 'updated_at'])
        changed += 1
    return changed


@transaction.atomic
def generate_visit_payouts(visit, actor=None, strict_staff=True):
    """Create/update the staff compensation owed for one completed visit.

    Every compensable service is paid on **its own** profit: the collected
    revenue allocated to that service minus the material cost actually recorded
    against it. A visit mixing a doctor service and a facial service therefore
    pays each role a percentage of its own profit, never a share of one
    visit-level total applied repeatedly.

    Idempotent: session payouts are keyed on (visit, staff, service) and monthly
    salaries on (staff, role, month), so re-running updates rather than
    duplicates. Rows that were already approved or paid keep that state and
    their settled amount.
    """
    if visit.status != 'completed':
        return []

    staff = visit.staff
    if not staff:
        if strict_staff and visit_requires_staff(visit):
            raise CompensationError(
                'This visit has a service that requires a staff member, but no staff '
                'is assigned. Assign staff before completing the visit so compensation '
                'is not silently skipped.'
            )
        return []

    rate = get_rate()
    financials = calculate_visit_financials(visit, rate=rate)
    salary_period = timezone.localtime(visit.start_at).date().replace(day=1)

    created_payouts = []
    for service in visit.services.all():
        role = service.compensation_role
        if role == 'none':
            continue
        service_financials = financials['services'].get(service.id)
        if service_financials is None:
            continue

        try:
            rule = StaffCompensationRule.objects.get(role=role, is_active=True)
        except StaffCompensationRule.DoesNotExist:
            continue

        payout_calc = calculate_service_payout(
            visit, service, rule,
            service_financials['profit_usd'], service_financials['profit_toman'], rate,
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
            payout, created = _upsert_session_payout(
                visit=visit, staff=staff, service=service, role=role,
                financials=service_financials, rate=rate,
                payout_calc=payout_calc, payout_mode=payout_mode,
            )
            if payout is None:
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
