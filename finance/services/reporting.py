"""Report layer.

Thin rendering over :mod:`finance.services.financials`, which owns the actual
business calculation. Nothing here re-derives revenue, cost or profit, so two
endpoints can never disagree about Gross or Net Profit.
"""
from datetime import datetime, time
from decimal import Decimal

import jdatetime
from django.contrib.auth import get_user_model
from django.db.models import Count, Sum
from django.utils import timezone

from Sefro_Clinic.periods import shamsi_months_of_year

from ..models import (
    Expense,
    MonthlyClose,
    OperatingExpense,
    PaymentComponent,
    ProductUsage,
    Sale,
    StaffCompensationRule,
    Wallet,
    WalletTransaction,
    WelcomePackUsage,
)
from . import financials, staff_compensation
from .exchange_rates import get_rate

# Re-exported so existing imports keep working.
REVENUE_STATUSES = financials.REVENUE_STATUSES
EXPENSE_STATUSES = financials.EXPENSE_STATUSES
CASH_METHODS = financials.CASH_METHODS
REVENUE_BASIS_LIST_PRICE = financials.REVENUE_BASIS_LIST_PRICE
REVENUE_BASIS_LEDGER = financials.REVENUE_BASIS_LEDGER
WELCOME_PACK_COST_BASIS_ALLOCATED = financials.WELCOME_PACK_COST_BASIS_ALLOCATED
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


def _annotate_profit_basis(row):
    """Name the several "profit" numbers a row carries so they cannot be confused.

    ``profit_usd`` keeps its historical key but is *material profit*: revenue
    minus product cost only. It excludes welcome-pack cost and the operator's
    own pay, both of which the clinic actually spends. ``material_profit_usd``
    is that same value under an honest name, ``after_welcome_pack_profit_usd``
    also removes the pack, and ``clinic_share_usd`` is what is left for the
    clinic once every cost on the row is paid.
    """
    row['profit_basis'] = 'revenue_minus_product_cost'
    row['material_profit_usd'] = row['profit_usd']
    row['after_welcome_pack_profit_usd'] = (
        row['revenue_usd'] - row['product_cost_usd'] - row['welcome_pack_cost_usd']
    ).quantize(Decimal('0.01'))
    if row['revenue_usd']:
        row['clinic_share_margin_percent'] = (
            (row['clinic_share_usd'] / row['revenue_usd'] * 100).quantize(Decimal('0.01'))
        )
    else:
        row['clinic_share_margin_percent'] = ZERO
    return row


def profit_by_service(start=None, end=None):
    """Service-level contribution for the period.

    Revenue is the collected sale amount allocated to each service in proportion
    to list price; material cost is the actual ``ProductUsage`` snapshot for
    that service on that visit. Services sold with no consumable recipe, and
    services whose consumption was never recorded, both still appear.

    Welcome-pack cost issued on each visit is attributed to that visit's
    services by the same revenue weight used to split the revenue, so per-service
    rows add back up to the visit (and clinic-share) totals.
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
                'operator_compensation_usd': ZERO,
                'welcome_pack_cost_usd': ZERO,
                'recipe_estimate_cost_usd': ZERO,
                'count': 0,
                'revenue_basis': service_row['revenue_basis'],
                'welcome_pack_cost_basis': 'allocated_by_revenue_share',
            })
            row['revenue_usd'] += service_row['revenue_usd']
            row['product_cost_usd'] += service_row['product_cost_usd']
            row['operator_compensation_usd'] += service_row['operator_compensation_usd']
            row['welcome_pack_cost_usd'] += service_row['welcome_pack_cost_usd']
            row['recipe_estimate_cost_usd'] += service_row['recipe_estimate_cost_usd']
            row['count'] += 1

    for row in rows.values():
        row['revenue_usd'] = row['revenue_usd'].quantize(Decimal('0.01'))
        row['product_cost_usd'] = row['product_cost_usd'].quantize(Decimal('0.01'))
        row['operator_compensation_usd'] = row['operator_compensation_usd'].quantize(Decimal('0.01'))
        row['welcome_pack_cost_usd'] = row['welcome_pack_cost_usd'].quantize(Decimal('0.01'))
        row['recipe_estimate_cost_usd'] = row['recipe_estimate_cost_usd'].quantize(Decimal('0.01'))
        row['profit_usd'] = (row['revenue_usd'] - row['product_cost_usd']).quantize(Decimal('0.01'))
        row['clinic_share_usd'] = (
            row['revenue_usd']
            - row['product_cost_usd']
            - row['operator_compensation_usd']
            - row['welcome_pack_cost_usd']
        ).quantize(Decimal('0.01'))
        row['profit_margin_percent'] = (
            (row['profit_usd'] / row['revenue_usd'] * 100).quantize(Decimal('0.01'))
            if row['revenue_usd'] else ZERO
        )
        _annotate_profit_basis(row)
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
                'operator_compensation_usd': ZERO,
                'welcome_pack_cost_usd': ZERO,
                'count': 0,
                'revenue_basis': REVENUE_BASIS_LEDGER,
                'welcome_pack_cost_basis': 'allocated_by_visit_linkage',
                # Session payouts only, and only when the payout's service
                # belongs to exactly one package sold on the visit. Anything
                # ambiguous (or a monthly-salary row, which is anchored on an
                # arbitrary visit) is excluded rather than split or copied.
                'operator_compensation_basis': 'session_payout_unambiguous_visit_linkage',
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

    # Staff compensation and welcome-pack cost of the visits behind these
    # package sales, from the same unambiguous visit-linkage helper the
    # filtered financial summary uses -- never a cost copied onto every
    # package sold on one visit.
    attribution = financials.package_attribution(start, end)

    for key, row in rows.items():
        row['product_cost_usd'] = usage_cost.get(key, ZERO).quantize(Decimal('0.01'))
        row['revenue_usd'] = row['revenue_usd'].quantize(Decimal('0.01'))
        row['operator_compensation_usd'] = attribution['payout_usd_by_package'].get(
            key, ZERO,
        ).quantize(Decimal('0.01'))
        row['welcome_pack_cost_usd'] = attribution['welcome_pack_usd_by_package'].get(
            key, ZERO,
        ).quantize(Decimal('0.01'))
        row['profit_usd'] = (row['revenue_usd'] - row['product_cost_usd']).quantize(Decimal('0.01'))
        row['clinic_share_usd'] = (
            row['revenue_usd'] - row['product_cost_usd'] - row['operator_compensation_usd']
            - row['welcome_pack_cost_usd']
        ).quantize(Decimal('0.01'))
        row['profit_margin_percent'] = (
            (row['profit_usd'] / row['revenue_usd'] * 100).quantize(Decimal('0.01'))
            if row['revenue_usd'] else ZERO
        )
        _annotate_profit_basis(row)
    return sorted(rows.values(), key=lambda r: r['profit_usd'], reverse=True)


def _empty_attribution():
    """A zeroed production row, for filters that leave nothing attributed."""
    zero = lambda: Decimal('0.00')  # noqa: E731 - one-line zero factory
    return {
        'revenue_usd': zero(), 'revenue_toman': zero(),
        'product_cost_usd': zero(), 'product_cost_toman': zero(),
        'material_profit_usd': zero(), 'material_profit_toman': zero(),
    }


def _coerce_staff_id(value):
    """Query strings reach this layer as text; the keys they filter are ints."""
    if value in (None, ''):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _empty_operator(staff_id):
    money = lambda: Decimal('0')  # noqa: E731 - one-line zero factory
    return {
        'staff_id': staff_id,
        'staff_name': '',
        'roles': [],
        'revenue_usd': money(), 'revenue_toman': money(),
        'product_cost_usd': money(), 'product_cost_toman': money(),
        'material_profit_usd': money(), 'material_profit_toman': money(),
        'session_payout_usd': money(), 'session_payout_toman': money(),
        'salary_payout_usd': money(), 'salary_payout_toman': money(),
        'cash_payout_usd': money(), 'cash_payout_toman': money(),
        'product_payout_usd': money(), 'product_payout_toman': money(),
        'owed_usd': money(), 'owed_toman': money(),
        'paid_usd': money(), 'paid_toman': money(),
        'pending_usd': money(), 'pending_toman': money(),
        'approved_usd': money(), 'approved_toman': money(),
        'payout_count': 0,
        'by_role': {},
        'by_status': {},
        'calculation': {},
    }


#: Per-role payout figures, carried identically in each operator's
#: ``by_role`` bucket and in the month's ``role_totals``. One tuple so the two
#: can never drift apart.
ROLE_PAYOUT_FIELDS = (
    'owed_usd', 'owed_toman',
    'session_usd', 'session_toman',
    'salary_usd', 'salary_toman',
    'paid_usd', 'paid_toman',
    'pending_usd', 'pending_toman',
    'approved_usd', 'approved_toman',
)


def _merge_operators(attribution, payouts):
    """One row per operator: what they produced + what they are owed.

    Revenue comes from the sale/usage attribution, money owed from the payout
    ledger. They are kept on separate rows joined by staff because a
    ``monthly_salary`` payout carries no revenue at all (it is stored as zero),
    so joining them inside the payout query would erase the laser tech's
    production for the month.
    """
    rules = {
        rule.role: {
            'calculation_type': rule.calculation_type,
            'percent_revenue': rule.percent_revenue,
            'fixed_amount_usd': rule.fixed_amount_usd,
            'fixed_amount_toman': rule.fixed_amount_toman,
        }
        for rule in StaffCompensationRule.objects.filter(is_active=True)
    }

    by_staff: dict = {}
    for staff_id, attr in attribution.items():
        if staff_id is None:
            continue
        entry = by_staff[staff_id] = _empty_operator(staff_id)
        for field in (
            'revenue_usd', 'revenue_toman', 'product_cost_usd', 'product_cost_toman',
            'material_profit_usd', 'material_profit_toman',
        ):
            entry[field] = attr[field]

    for row in payouts['rows']:
        entry = by_staff.setdefault(row['staff_id'], _empty_operator(row['staff_id']))
        entry['staff_name'] = entry['staff_name'] or row['staff_name']
        if row['role'] not in entry['roles']:
            entry['roles'].append(row['role'])
            entry['calculation'][row['role']] = rules.get(row['role'], {})

        entry['session_payout_usd'] += row['session_usd']
        entry['session_payout_toman'] += row['session_toman']
        entry['salary_payout_usd'] += row['salary_usd']
        entry['salary_payout_toman'] += row['salary_toman']
        entry['cash_payout_usd'] += row['cash_usd']
        entry['cash_payout_toman'] += row['cash_toman']
        entry['product_payout_usd'] += row['product_usd']
        entry['product_payout_toman'] += row['product_toman']
        entry['owed_usd'] += row['owed_usd']
        entry['owed_toman'] += row['owed_toman']
        entry['payout_count'] += row['payout_count']

        role_bucket = entry['by_role'].setdefault(row['role'], {
            'role': row['role'], 'count': 0,
            **{field: Decimal('0') for field in ROLE_PAYOUT_FIELDS},
        })
        for field in ROLE_PAYOUT_FIELDS:
            role_bucket[field] += row[field]
        role_bucket['count'] += row['payout_count']

        for status_key, bucket in row['by_status'].items():
            entry['by_status'].setdefault(
                status_key, {'usd': Decimal('0'), 'toman': Decimal('0'), 'count': 0},
            )
            status_entry = entry['by_status'][status_key]
            status_entry['usd'] += bucket['usd']
            status_entry['toman'] += bucket['toman']
            status_entry['count'] += bucket['count']

        entry['paid_usd'] += row['paid_usd']
        entry['paid_toman'] += row['paid_toman']
        entry['pending_usd'] += row['pending_usd']
        entry['pending_toman'] += row['pending_toman']
        entry['approved_usd'] += row['approved_usd']
        entry['approved_toman'] += row['approved_toman']

    # Operators who produced revenue but were owed nothing this month still
    # belong on the report, under their own name.
    missing = [sid for sid, entry in by_staff.items() if not entry['staff_name']]
    if missing:
        user_model = get_user_model()
        for user in user_model.objects.filter(id__in=missing).only(
            'id', 'username', 'first_name', 'last_name',
        ):
            full = ' '.join(p for p in (user.first_name, user.last_name) if p)
            by_staff[user.id]['staff_name'] = full or user.username

    for entry in by_staff.values():
        for bucket in entry['by_status'].values():
            bucket['usd'] = bucket['usd'].quantize(Decimal('0.01'))
            bucket['toman'] = bucket['toman'].quantize(Decimal('0.01'))
            bucket['count'] = int(bucket['count'])
        for bucket in entry['by_role'].values():
            for field in ROLE_PAYOUT_FIELDS:
                bucket[field] = bucket[field].quantize(Decimal('0.01'))
            bucket['count'] = int(bucket['count'])
        for field in (
            'revenue_usd', 'revenue_toman', 'product_cost_usd', 'product_cost_toman',
            'material_profit_usd', 'material_profit_toman',
            'session_payout_usd', 'session_payout_toman',
            'salary_payout_usd', 'salary_payout_toman',
            'cash_payout_usd', 'cash_payout_toman',
            'product_payout_usd', 'product_payout_toman',
            'owed_usd', 'owed_toman', 'paid_usd', 'paid_toman',
            'pending_usd', 'pending_toman', 'approved_usd', 'approved_toman',
        ):
            entry[field] = entry[field].quantize(Decimal('0.01'))

    rows = sorted(by_staff.values(), key=lambda r: (r['roles'], r['staff_name'], r['staff_id']))

    role_totals: dict = {}
    for entry in rows:
        for bucket in entry['by_role'].values():
            totals = role_totals.setdefault(bucket['role'], {
                'role': bucket['role'], 'operator_count': 0, 'payout_count': 0,
                **{field: Decimal('0') for field in ROLE_PAYOUT_FIELDS},
            })
            for field in ROLE_PAYOUT_FIELDS:
                totals[field] += bucket[field]
            totals['payout_count'] += bucket['count']
            totals['operator_count'] += 1

    for totals in role_totals.values():
        for field in ROLE_PAYOUT_FIELDS:
            totals[field] = totals[field].quantize(Decimal('0.01'))

    return rows, sorted(role_totals.values(), key=lambda r: r['role'])


def _sum_months(months, fields):
    total = {}
    for field in fields:
        # Frozen months carry stringified Decimals (JSON snapshot); live ones
        # carry Decimals. Coerce both so the year total never mixes types.
        usd = sum((Decimal(str(m[field]['usd'])) for m in months), Decimal('0'))
        toman = sum((Decimal(str(m[field]['toman'])) for m in months), Decimal('0'))
        total[field] = {
            'usd': usd.quantize(Decimal('0.01')),
            'toman': toman.quantize(Decimal('0.01')),
        }
    return total


#: P&L keys summed into the year total.
MONTHLY_SUM_KEYS = (
    'revenue', 'product_cost', 'welcome_pack_cost', 'gross_profit',
    'clinic_share', 'staff_compensation_total', 'operating_expenses',
    'staff_expense_claims', 'below_the_line_total', 'net_profit',
    'purchases', 'net_profit_after_purchases',
)


def _render_month(bounds, *, status=None, staff_id=None, role=None):
    """One month's full report row, computed live from the ledgers.

    The single renderer shared by the GET report (open months) and
    ``closing.close_month`` (the snapshot it stores), so what a user sees on
    screen is byte-for-byte what closing freezes.
    """
    year = bounds['year']
    start, end = bounds['start'], bounds['end']
    report = financials.build_report(start, end)
    attribution = financials.operator_attribution(start, end, totals=report)
    narrowed = staff_id is not None or role not in (None, '')
    if staff_id is not None:
        # ?staff= narrows the operator *rows*, not just their pay: without
        # this the other staff's production would still be listed.
        attribution = {
            sid: row for sid, row in attribution.items() if sid == staff_id
        }
    payouts = staff_compensation.operator_month_payouts(
        start, end, status=status, staff_id=staff_id, role=role,
    )
    operators, role_totals = _merge_operators(attribution, payouts)
    if role:
        # Production is attributed to people, not to roles, so the only
        # rows that can honestly claim a role are the ones that carry one.
        operators = [row for row in operators if role in row['by_role']]

    # The residual explains the whole month's revenue; once a filter has
    # deliberately dropped part of it, there is nothing left to explain.
    unattributed = attribution.get(None) if not narrowed else None
    unattributed = unattributed or _empty_attribution()
    return {
        'key': bounds['key'],
        'year': year,
        'month': bounds['month'],
        'month_name': bounds['month_name'],
        'shamsi_start': jdatetime.date.fromgregorian(date=start.date()).strftime('%Y-%m-%d'),
        'shamsi_end': jdatetime.date.fromgregorian(date=end.date()).strftime('%Y-%m-%d'),
        # Kept for existing consumers; new code should read shamsi_start/end.
        'gregorian_start': start.date().isoformat(),
        'gregorian_end': end.date().isoformat(),
        'period': {'start': start, 'end': end},
        'is_current': start <= timezone.now() <= end,
        'is_closed': False,
        'closed_at': None,
        'closed_by': None,
        'closed_by_name': '',
        'close_note': '',
        'was_reopened': False,
        'reopened_at': None,
        'reopen_reason': '',
        'revenue': report['revenue'],
        'product_cost': report['product_cost'],
        'welcome_pack_cost': report['welcome_pack_cost'],
        'gross_profit': report['gross_profit'],
        'clinic_share': report['clinic_share'],
        'staff_compensation': report['staff_compensation'],
        'staff_compensation_total': report['staff_compensation']['total'],
        'operating_expenses': report['operating_expenses'],
        'staff_expense_claims': report['staff_expense_claims'],
        'below_the_line_total': report['below_the_line_total'],
        'net_profit': report['net_profit'],
        'purchases': report['purchases'],
        'net_profit_after_purchases': report['net_profit_after_purchases'],
        'payment_methods': report['payment_methods'],
        'counts': report['counts'],
        'cost_coverage': report['cost_coverage'],
        'operators': operators,
        'role_totals': role_totals,
        'unattributed': unattributed,
        'payout_total': {
            'usd': payouts['total_usd'],
            'toman': payouts['total_toman'],
            'payout_count': payouts['payout_count'],
        },
    }


def _frozen_month(row, bounds):
    """A closed month's row: the stored snapshot, verbatim, plus its history.

    The payload was JSON-encoded at close time, so its money values are
    strings -- exactly the shape the API already returns -- and its period
    timestamps are ISO strings. Nothing is recomputed: that is the point of a
    closed book. Only the closure metadata and the live ``is_current`` flag
    (always false for a past month) are added here.
    """
    month_row = dict(row.payload)
    month_row.update({
        'key': bounds['key'],
        'year': row.shamsi_year,
        'month': row.shamsi_month,
        'month_name': bounds['month_name'],
        'is_current': bounds['start'] <= timezone.now() <= bounds['end'],
        'is_closed': True,
        'closed_at': _shamsi_dt(row.closed_at),
        'closed_by': row.closed_by_id,
        'closed_by_name': (
            row.closed_by.get_username() if row.closed_by_id and row.closed_by else ''
        ),
        'close_note': row.close_note or '',
        # The reopen history belongs to the ROW, not the snapshot: after a
        # reopen followed by a re-close, the frozen month must not pretend it
        # was never opened again.
        'was_reopened': row.reopened_at is not None,
        'reopened_at': _shamsi_dt(row.reopened_at),
        'reopen_reason': row.reopen_reason or '',
    })
    return month_row


def _shamsi_dt(value):
    """An aware datetime as a Shamsi 'YYYY-MM-DD HH:MM' string (Tehran local)."""
    if not value:
        return None
    return jdatetime.datetime.fromgregorian(
        datetime=value.astimezone(timezone.get_current_timezone()),
    ).strftime('%Y-%m-%d %H:%M')


def _reopened_month(bounds, row):
    """A reopened month: live numbers again, but its closing history stays visible."""
    month_row = _render_month(bounds)
    month_row.update({
        'is_closed': False,
        'was_reopened': True,
        'reopened_at': _shamsi_dt(row.reopened_at),
        'reopen_reason': row.reopen_reason or '',
        'closed_at': _shamsi_dt(row.closed_at),
        'closed_by': row.closed_by_id,
        'closed_by_name': (
            row.closed_by.get_username() if row.closed_by_id and row.closed_by else ''
        ),
        'close_note': row.close_note or '',
    })
    return month_row


def monthly_close(year=None, month=None, *, status=None, staff_id=None, role=None):
    """A Shamsi year of monthly P&L rows, each with its operators' pay.

    This is the "close one month, move to the next" report: every month of the
    requested Shamsi year carries revenue, cost, gross profit, net profit,
    purchases, net profit after purchases, and a per-operator breakdown of
    what was produced and what is owed/paid.

    Every number inside a month comes from ``financials.build_report`` for that
    month's range, so a month here can never disagree with
    ``/reports/financial-summary/`` for the same dates. Payout rows use
    ``StaffPayout.created_at``, the anchor that report uses too.

    A CLOSED month is served from its frozen ``MonthlyClose`` snapshot instead
    of the ledgers -- closing freezes the numbers; a reopened month is live
    again and carries its closing history.

    Args:
        year: Shamsi year. Defaults to the current Shamsi year.
        month: 1-12 or a ``'1405-05'`` key. Omit for the whole year.
        status: payout status filter (defaults to still-owed; ``'all'`` to
            include cancelled rows).
        staff_id: narrow the operator rows to one staff member.
        role: narrow the operator rows to one role (doctor | facial | laser).
    """
    shamsi_now = jdatetime.datetime.fromgregorian(datetime=timezone.localtime(timezone.now()))
    try:
        year = int(year) if year not in (None, '') else shamsi_now.year
    except (TypeError, ValueError):
        year = shamsi_now.year

    wanted_month = None
    if month not in (None, ''):
        try:
            parsed = int(str(month).split('-')[-1])
            wanted_month = parsed if 1 <= parsed <= 12 else None
        except (TypeError, ValueError):
            wanted_month = None

    staff_id = _coerce_staff_id(staff_id)
    closes = {
        row.shamsi_month: row
        for row in MonthlyClose.objects.filter(shamsi_year=year).select_related('closed_by')
    }

    months_payload = []
    for bounds in shamsi_months_of_year(year):
        if wanted_month and bounds['month'] != wanted_month:
            continue

        row = closes.get(bounds['month'])
        if row is not None and row.status == MonthlyClose.Status.CLOSED:
            month_row = _frozen_month(row, bounds)
        elif row is not None:
            month_row = _reopened_month(bounds, row)
        else:
            month_row = _render_month(
                bounds, status=status, staff_id=staff_id, role=role,
            )
        months_payload.append(month_row)

    year_total = _sum_months(months_payload, MONTHLY_SUM_KEYS)
    year_total['payout_total_usd'] = sum(
        (Decimal(str(m['payout_total']['usd'])) for m in months_payload), Decimal('0')
    ).quantize(Decimal('0.01'))
    year_total['payout_total_toman'] = sum(
        (Decimal(str(m['payout_total']['toman'])) for m in months_payload), Decimal('0')
    ).quantize(Decimal('0.01'))
    year_total['payout_count'] = sum(m['payout_total']['payout_count'] for m in months_payload)

    return {
        'calendar': 'shamsi',
        'year': year,
        'month': wanted_month,
        'status_filter': status or 'owed',
        'payout_anchor': 'StaffPayout.created_at',
        'months': months_payload,
        'year_total': year_total,
        'closed_month_count': sum(1 for m in months_payload if m.get('is_closed')),
    }


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
    'REVENUE_BASIS_LIST_PRICE', 'REVENUE_BASIS_LEDGER',
    'WELCOME_PACK_COST_BASIS_ALLOCATED', 'WELCOME_PACK_COST_BASIS_EXCLUDED',
    'payment_method_breakdown', 'financial_summary', 'profit_by_service',
    'profit_by_package', 'monthly_close', 'wallet_summary',
    'operating_expense_summary', 'welcome_pack_report',
    'Expense', 'PaymentComponent', 'get_rate',
]
