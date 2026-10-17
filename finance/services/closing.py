"""Monthly financial closing: freeze one Shamsi month into an immutable row.

Closing is an explicit POST -- the GET report never closes anything. The
operation recomputes the month with the same ``reporting._render_month`` the
live report uses (so what is stored is exactly what was on screen), embeds the
outstanding payouts/claims as an informational block (close never blocks on
them, by policy), and writes one ``MonthlyClose`` row under a unique
per-month constraint inside ``transaction.atomic`` with a row lock, so
concurrent closes yield exactly one record.

Reopening flips that row back to ``reopened`` with a mandatory reason; the
month becomes mutable again and the next close refreshes the same row's
payload. Both events land in the audit trail with the acting user.

Roles: any authenticated staff (admin or employee) may close and reopen, by
business decision. The audit log records who did it.
"""
from decimal import Decimal

import jdatetime
from django.db import IntegrityError, transaction
from django.utils import timezone

from logs.models import AuditLog
from Sefro_Clinic.periods import shamsi_months_of_year

from ..models import Expense, MonthlyClose, StaffPayout
from . import reporting
from .exchange_rates import get_rate
from .periods_guard import audit_event

ZERO = Decimal('0')
CENT = Decimal('0.01')

#: Payout statuses still owed at close time (mirrors financials semantics).
UNPAID_PAYOUT_STATUSES = (StaffPayout.Status.PENDING, StaffPayout.Status.APPROVED)


class ClosingError(Exception):
    """The close/reopen request itself is invalid (not a period-guard block)."""


def _jsonable(value):
    """JSON-safe copy of a report payload: Decimals -> str, dates -> iso."""
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (jdatetime.date, jdatetime.datetime)):
        return str(value)
    if hasattr(value, 'isoformat'):
        return value.isoformat()
    return value


def _outstanding_block(start, end):
    """Unpaid obligations inside the month -- reported, never a close blocker."""
    payout_usd = payout_toman = ZERO
    payout_count = 0
    for payout in StaffPayout.objects.filter(
        created_at__gte=start, created_at__lte=end, status__in=UNPAID_PAYOUT_STATUSES,
    ):
        payout_usd += payout.payout_cash_usd + payout.payout_product_value_usd
        payout_toman += payout.payout_cash_toman + payout.payout_product_value_toman
        payout_count += 1

    claims = Expense.objects.filter(
        expense_date__gte=start.date(), expense_date__lte=end.date(),
        status=Expense.Status.APPROVED,
    )
    claim_usd = sum((c.amount_usd for c in claims), ZERO)
    claim_toman = sum((c.amount_toman for c in claims), ZERO)

    return {
        'unpaid_payouts': {
            'count': payout_count,
            'usd': payout_usd.quantize(CENT),
            'toman': payout_toman.quantize(CENT),
        },
        'unpaid_claims': {
            'count': claims.count(),
            'usd': claim_usd.quantize(CENT),
            'toman': claim_toman.quantize(CENT),
        },
    }


def _bounds_for(year, month):
    for entry in shamsi_months_of_year(year):
        if entry['month'] == month:
            return entry
    raise ClosingError(f'Invalid Shamsi month {month} for year {year}.')


def get_close_row(year, month):
    return MonthlyClose.objects.filter(shamsi_year=year, shamsi_month=month).first()


@transaction.atomic
def close_month(year, month, *, user=None, note=''):
    """Finalize one past Shamsi month. Idempotent: an already-closed month
    returns its existing row untouched.

    Returns ``(row, already_closed)``.
    """
    try:
        year, month = int(year), int(month)
    except (TypeError, ValueError) as exc:
        raise ClosingError('year and month must be integers.') from exc
    if not 1 <= month <= 12:
        raise ClosingError('month must be between 1 and 12.')

    bounds = _bounds_for(year, month)
    now = timezone.now()
    if bounds['end'] >= now:
        raise ClosingError(
            'Only past months can be closed; the current or a future month is '
            'still open for trading.',
        )

    row = MonthlyClose.objects.select_for_update().filter(
        shamsi_year=year, shamsi_month=month,
    ).first()
    if row is not None and row.status == MonthlyClose.Status.CLOSED:
        return row, True

    month_payload = reporting._render_month(bounds)
    month_payload['outstanding'] = _outstanding_block(bounds['start'], bounds['end'])
    payload = _jsonable(month_payload)

    try:
        rate = get_rate('USD', 'TOMAN')
    except Exception:
        rate = None

    fields = {
        'gregorian_start': bounds['start'].date(),
        'gregorian_end': bounds['end'].date(),
        'status': MonthlyClose.Status.CLOSED,
        'payload': payload,
        'revenue_usd': month_payload['revenue']['usd'],
        'product_cost_usd': month_payload['product_cost']['usd'],
        'welcome_pack_cost_usd': month_payload['welcome_pack_cost']['usd'],
        'gross_profit_usd': month_payload['gross_profit']['usd'],
        'staff_compensation_usd': month_payload['staff_compensation_total']['usd'],
        'operating_expenses_usd': month_payload['operating_expenses']['usd'],
        'staff_expense_claims_usd': month_payload['staff_expense_claims']['usd'],
        'net_profit_usd': month_payload['net_profit']['usd'],
        'purchases_usd': month_payload['purchases']['usd'],
        'net_profit_after_purchases_usd': month_payload['net_profit_after_purchases']['usd'],
        'rate_used': rate,
        'close_note': note or '',
        'closed_at': now,
        'closed_by': user if getattr(user, 'is_authenticated', False) else None,
    }

    if row is None:
        created = True
        try:
            # Inner savepoint: an IntegrityError here (a concurrent close won
            # the unique constraint) must roll back ONLY this create, or the
            # fallback query below would run on a poisoned transaction.
            with transaction.atomic():
                row = MonthlyClose.objects.create(shamsi_year=year, shamsi_month=month, **fields)
        except IntegrityError:
            # A concurrent close won the unique constraint; return its row.
            row = MonthlyClose.objects.select_for_update().get(
                shamsi_year=year, shamsi_month=month,
            )
            return row, True
    else:
        created = False
        for name, value in fields.items():
            setattr(row, name, value)
        row.save(update_fields=[*fields, 'updated_at'])

    audit_event(
        user, AuditLog.Action.CREATE if created else AuditLog.Action.UPDATE,
        'finance.monthlyclose', row.id,
        event='MONTHLY_CLOSE',
        object_repr=str(row),
        period=row.period_key,
        note=note or None,
        net_profit_usd=str(row.net_profit_usd),
        revenue_usd=str(row.revenue_usd),
        outstanding_unpaid_payouts=month_payload['outstanding']['unpaid_payouts']['count'],
        outstanding_unpaid_claims=month_payload['outstanding']['unpaid_claims']['count'],
    )
    return row, False


@transaction.atomic
def reopen_month(year, month, *, user=None, reason=''):
    """Un-freeze a closed month. Reason is mandatory; both events are audited.

    Returns the updated row.
    """
    reason = (reason or '').strip()
    if not reason:
        raise ClosingError('A written reason is required to reopen a month.')
    try:
        year, month = int(year), int(month)
    except (TypeError, ValueError) as exc:
        raise ClosingError('year and month must be integers.') from exc

    row = MonthlyClose.objects.select_for_update().filter(
        shamsi_year=year, shamsi_month=month,
    ).first()
    if row is None:
        raise ClosingError('That month has never been closed.')
    if row.status != MonthlyClose.Status.CLOSED:
        raise ClosingError('That month is already open.')

    now = timezone.now()
    row.status = MonthlyClose.Status.REOPENED
    row.reopened_at = now
    row.reopened_by = user if getattr(user, 'is_authenticated', False) else None
    row.reopen_reason = reason
    row.save(update_fields=['status', 'reopened_at', 'reopened_by', 'reopen_reason', 'updated_at'])

    audit_event(
        user, AuditLog.Action.UPDATE, 'finance.monthlyclose', row.id,
        event='MONTHLY_REOPEN',
        object_repr=str(row),
        period=row.period_key,
        reason=reason,
    )
    return row
