from collections import defaultdict
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.db.models import Count, Sum
from django.utils import timezone

from logs.models import AuditLog

from ..models import (
    StaffCompensationRule,
    StaffPayout,
    StaffPayoutProduct,
)
from .exchange_rates import get_current_usd_to_toman_rate
from .financials import PAYOUT_OBLIGATION_STATUSES, calculate_visit_financials
from .inventory import record_product_usage
from .periods_guard import audit_event, ensure_open


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


def calculate_service_payout(visit, service, rule, revenue_usd, revenue_toman, rate):
    payout_cash_usd = Decimal('0')
    payout_cash_toman = Decimal('0')

    if rule.calculation_type == StaffCompensationRule.CalculationType.PERCENT_REVENUE:
        if rule.percent_revenue:
            pct = rule.percent_revenue / Decimal('100')
            payout_cash_usd = (revenue_usd * pct).quantize(Decimal('0.01'))
            payout_cash_toman = (revenue_toman * pct).quantize(Decimal('0.01'))

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
    if payout.status in SETTLED_STATUSES or payout.status == StaffPayout.Status.CANCELLED:
        return payout, False

    changed = [field for field in _SESSION_AMOUNT_FIELDS if getattr(payout, field) != defaults[field]]
    if changed:
        # Re-pricing an existing payout rewrites a liability line. If that
        # line was booked into a now-closed month, the closed books must not
        # move: reopen the month first.
        ensure_open(
            payout.created_at, action='re-price a staff payout',
            object_repr=f'StaffPayout#{payout.id}',
        )
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
        ensure_open(
            payout.created_at, action='cancel a staff payout',
            object_repr=f'StaffPayout#{payout.id}',
        )
        payout.status = StaffPayout.Status.CANCELLED
        notes = (payout.notes or '').strip()
        message = f'Cancelled: {reason}' if reason else 'Cancelled.'
        payout.notes = f'{notes} {message}'.strip()
        payout.save(update_fields=['status', 'notes', 'updated_at'])
        audit_event(
            None, AuditLog.Action.UPDATE, 'finance.staffpayout', payout.id,
            event='PAYOUT_CANCEL', object_repr=str(payout),
            reason=reason or None, visit=visit.pk,
        )
        changed += 1
    return changed


def generate_visit_payouts(visit, actor=None, strict_staff=True):
    """Create/update the staff compensation owed for one completed visit.

    Every compensable service is paid on **its own** revenue: the collected
    revenue allocated to that service (by list-price weight) times the role's
    ``percent_revenue``. A visit mixing a doctor service and a facial service
    therefore pays each role a percentage of its own allocated revenue, never
    a share of one visit-level total applied repeatedly.

    Idempotent: session payouts are keyed on (visit, staff, service) and monthly
    salaries on (staff, role, month), so re-running updates rather than
    duplicates. Rows that were already approved or paid keep that state and
    their settled amount.
    """
    # Pre-flight OUTSIDE the atomic body: re-pricing an existing payout
    # rewrites a liability line booked into its own accounting month, so a
    # visit from a closed month cannot be regenerated -- and the refusal's
    # audit row must outlive the rollback.
    if visit.status == 'completed':
        unsettled = StaffPayout.objects.filter(
            visit=visit, status__in=[
                StaffPayout.Status.PENDING, StaffPayout.Status.APPROVED,
            ],
        ).exclude(payout_kind=StaffPayout.PayoutKind.MONTHLY_SALARY)
        for payout in unsettled:
            ensure_open(
                payout.created_at, action='re-price a staff payout',
                object_repr=f'StaffPayout#{payout.id}',
            )
    return _generate_visit_payouts_locked(visit, actor=actor, strict_staff=strict_staff)


@transaction.atomic
def _generate_visit_payouts_locked(visit, actor=None, strict_staff=True):
    if visit.status != 'completed':
        return []

    # Resolve per-service operators first (idempotent: explicit assignments
    # and role-based auto-assignment), then refuse a visit whose compensable
    # services have no operator to pay — paying the wrong person or nobody
    # must never happen silently.
    uncovered = visit.resolve_operators()
    if strict_staff and uncovered:
        raise CompensationError(
            'This visit has a service that requires an operator, but no matching staff '
            f'member is assigned for: {", ".join(uncovered)}. Assign staff before '
            'completing the visit so compensation is not silently skipped.'
        )

    operator_by_service = visit.service_operator_map()
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
        # The operator who performs THIS service: per-service assignment
        # first, the visit's primary staff as the legacy fallback.
        operator = operator_by_service.get(service.id) or visit.staff
        if operator is None:
            continue

        try:
            rule = StaffCompensationRule.objects.get(role=role, is_active=True)
        except StaffCompensationRule.DoesNotExist:
            continue

        payout_calc = calculate_service_payout(
            visit, service, rule,
            service_financials['revenue_usd'], service_financials['revenue_toman'], rate,
        )
        payout_mode = (
            StaffPayout.PayoutMode.PRODUCT
            if rule.payout_type == StaffCompensationRule.PayoutType.PRODUCT
            else StaffPayout.PayoutMode.CASH
        )

        if rule.calculation_type == StaffCompensationRule.CalculationType.MONTHLY_SALARY:
            payout, created = _upsert_monthly_salary_payout(
                visit=visit, staff=operator, service=service, role=role,
                salary_period=salary_period, rate=rate,
                payout_calc=payout_calc, payout_mode=payout_mode,
            )
            if payout is None:
                continue
            if not any(existing.pk == payout.pk for existing in created_payouts):
                created_payouts.append(payout)
        else:
            payout, created = _upsert_session_payout(
                visit=visit, staff=operator, service=service, role=role,
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


#: Statuses that still represent money the clinic owes. Taken straight from
#: ``financials.PAYOUT_OBLIGATION_STATUSES`` so the payout summary and the
#: profit reports can never drift apart: a CANCELLED payout is a voided
#: obligation and must never inflate "what we owe".
PAYOUT_STATUSES_OWED = list(PAYOUT_OBLIGATION_STATUSES)

#: Query value that turns the status filter off (the raw ledger).
STATUS_ALL = 'all'


def payout_status_filter(status):
    """Turn a ``status`` query value into a list to filter on, or ``None``.

    Omitted/empty -> the owed set above. ``all`` -> no filter, for callers who
    want to inspect cancelled rows too. Anything else is taken as one status.
    """
    if not status:
        return list(PAYOUT_STATUSES_OWED)
    if status == STATUS_ALL:
        return None
    return [status]


def _payout_range(start, end):
    from datetime import time

    if start and end:
        if hasattr(start, 'date') is False:
            start = timezone.make_aware(timezone.datetime.combine(start, time.min))
        if hasattr(end, 'date') is False:
            end = timezone.make_aware(timezone.datetime.combine(end, time.max))
        return start, end
    now = timezone.now()
    start = start or timezone.make_aware(timezone.datetime.combine(now.date(), time.min))
    end = end or timezone.make_aware(timezone.datetime.combine(now.date(), time.max))
    return start, end


def staff_payout_summary(start=None, end=None, staff_id=None, role=None, status=None):
    """Total the staff obligation for a period.

    Same date convention as every other report (a bare call means *today*) and
    the same status convention as ``profit-by-staff``: only payouts that are
    still owed. Pass ``status='all'`` to see the raw ledger.
    """
    start, end = _payout_range(start, end)

    qs = StaffPayout.objects.filter(created_at__gte=start, created_at__lte=end)
    if staff_id:
        qs = qs.filter(staff_id=staff_id)
    if role:
        qs = qs.filter(role=role)
    statuses = payout_status_filter(status)
    if statuses is not None:
        qs = qs.filter(status__in=statuses)

    agg = qs.aggregate(
        total_cash_usd=Sum('payout_cash_usd'),
        total_cash_toman=Sum('payout_cash_toman'),
        total_product_value_usd=Sum('payout_product_value_usd'),
        total_product_value_toman=Sum('payout_product_value_toman'),
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


def staff_payout_detail(start=None, end=None, staff_id=None, status=None):
    """One row per payout for the period, on the same footing as the summary.

    Shares the range and status handling of :func:`staff_payout_summary` so the
    lines always add back up to the totals.
    """
    start, end = _payout_range(start, end)

    qs = StaffPayout.objects.filter(created_at__gte=start, created_at__lte=end).select_related(
        'staff', 'visit', 'service', 'payout_product'
    )
    if staff_id:
        qs = qs.filter(staff_id=staff_id)
    statuses = payout_status_filter(status)
    if statuses is not None:
        qs = qs.filter(status__in=statuses)

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


def _staff_display_name(row):
    full = ' '.join(
        part for part in (row.get('staff__first_name'), row.get('staff__last_name')) if part
    )
    return full or row.get('staff__username') or str(row.get('staff_id'))


def operator_month_payouts(start, end, status=None, staff_id=None, role=None):
    """Staff obligation grouped per (operator, role) for a period.

    One grouped query, folded into one row per operator+role, so a monthly
    report can show for every operator what they are owed, what is already
    paid, and how much comes from per-visit earnings versus a monthly salary.

    Anchored on ``StaffPayout.created_at`` - the same anchor as
    ``financials.staff_compensation_totals`` - so these rows add back up to
    ``build_report['staff_compensation']`` instead of telling a second story.
    """
    start, end = _payout_range(start, end)

    qs = StaffPayout.objects.filter(created_at__gte=start, created_at__lte=end)
    if staff_id:
        qs = qs.filter(staff_id=staff_id)
    if role:
        qs = qs.filter(role=role)
    statuses = payout_status_filter(status)
    if statuses is not None:
        qs = qs.filter(status__in=statuses)

    grouped: dict = {}
    for row in qs.values(
        'staff_id', 'staff__username', 'staff__first_name', 'staff__last_name',
        'role', 'status', 'payout_kind',
    ).annotate(
        cash_usd=Sum('payout_cash_usd'),
        cash_toman=Sum('payout_cash_toman'),
        product_usd=Sum('payout_product_value_usd'),
        product_toman=Sum('payout_product_value_toman'),
        count=Count('id'),
    ):
        key = (row['staff_id'], row['role'])
        entry = grouped.setdefault(key, {
            'staff_id': row['staff_id'],
            'staff_name': _staff_display_name(row),
            'role': row['role'],
            'session_usd': Decimal('0'),
            'session_toman': Decimal('0'),
            'salary_usd': Decimal('0'),
            'salary_toman': Decimal('0'),
            'cash_usd': Decimal('0'),
            'cash_toman': Decimal('0'),
            'product_usd': Decimal('0'),
            'product_toman': Decimal('0'),
            'payout_count': 0,
            'by_status': {},
        })

        cash_usd = row['cash_usd'] or Decimal('0')
        cash_toman = row['cash_toman'] or Decimal('0')
        product_usd = row['product_usd'] or Decimal('0')
        product_toman = row['product_toman'] or Decimal('0')
        owed_usd = cash_usd + product_usd
        owed_toman = cash_toman + product_toman

        entry['cash_usd'] += cash_usd
        entry['cash_toman'] += cash_toman
        entry['product_usd'] += product_usd
        entry['product_toman'] += product_toman
        entry['payout_count'] += row['count']

        if row['payout_kind'] == StaffPayout.PayoutKind.MONTHLY_SALARY:
            entry['salary_usd'] += owed_usd
            entry['salary_toman'] += owed_toman
        else:
            entry['session_usd'] += owed_usd
            entry['session_toman'] += owed_toman

        status_bucket = entry['by_status'].setdefault(
            row['status'], {'usd': Decimal('0'), 'toman': Decimal('0'), 'count': 0},
        )
        status_bucket['usd'] += owed_usd
        status_bucket['toman'] += owed_toman
        status_bucket['count'] += row['count']

    rows = []
    total_usd = Decimal('0')
    total_toman = Decimal('0')
    total_count = 0
    for entry in grouped.values():
        entry['owed_usd'] = (entry['cash_usd'] + entry['product_usd']).quantize(Decimal('0.01'))
        entry['owed_toman'] = (entry['cash_toman'] + entry['product_toman']).quantize(Decimal('0.01'))
        for field in (
            'session_usd', 'session_toman', 'salary_usd', 'salary_toman',
            'cash_usd', 'cash_toman', 'product_usd', 'product_toman',
        ):
            entry[field] = entry[field].quantize(Decimal('0.01'))
        for bucket in entry['by_status'].values():
            bucket['usd'] = bucket['usd'].quantize(Decimal('0.01'))
            bucket['toman'] = bucket['toman'].quantize(Decimal('0.01'))
        for status, name in (
            (StaffPayout.Status.PAID, 'paid'),
            (StaffPayout.Status.PENDING, 'pending'),
            (StaffPayout.Status.APPROVED, 'approved'),
        ):
            bucket = entry['by_status'].get(status) or {
                'usd': Decimal('0'), 'toman': Decimal('0'),
            }
            entry[f'{name}_usd'] = bucket['usd']
            entry[f'{name}_toman'] = bucket['toman']
        total_usd += entry['owed_usd']
        total_toman += entry['owed_toman']
        total_count += entry['payout_count']
        rows.append(entry)

    rows.sort(key=lambda r: (r['role'], r['staff_name']))
    return {
        'rows': rows,
        'total_usd': total_usd.quantize(Decimal('0.01')),
        'total_toman': total_toman.quantize(Decimal('0.01')),
        'payout_count': total_count,
    }
