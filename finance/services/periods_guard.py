"""Closed-period integrity guard.

One question -- "is this instant inside a finalized accounting month?" -- asked
by every mutation path that could otherwise rewrite closed books: refunds,
expense workflows, operating-expense CRUD, payout cancellations and re-pricing,
purchase-order receiving, and the Django admin.

The answer lives in ``finance_monthlyclose``: a row with status ``closed`` for
the Shamsi month containing the instant freezes that month. No row, or a
``reopened`` row, means the month is live.

Every refusal is written to the audit trail (``changes.event = BLOCKED:*``)
before raising, because a blocked attempt is a business event the Logs section
must show even though no model row changed.
"""
from logs.middleware import get_current_user
from logs.models import AuditLog
from Sefro_Clinic.periods import shamsi_of  # noqa: F401  (shared calendar helper, re-exported)

from ..models import MonthlyClose


class PeriodClosedError(Exception):
    """The target instant falls inside a CLOSED accounting month."""

    def __init__(self, message, *, year=None, month=None):
        super().__init__(message)
        self.year = year
        self.month = month


def closed_row_for(moment):
    """The CLOSED row covering ``moment``, or ``None`` when the month is open."""
    year, month = shamsi_of(moment)
    row = MonthlyClose.objects.filter(
        shamsi_year=year, shamsi_month=month, status=MonthlyClose.Status.CLOSED,
    ).first()
    return row


def ensure_open(moment, *, action, user=None, object_repr='', **context):
    """Raise :class:`PeriodClosedError` (and audit the refusal) when closed.

    ``action`` is a short imperative used in the error message and the audit
    event name (``BLOCKED:refund sale``); ``context`` is copied into the audit
    ``changes`` payload.
    """
    row = closed_row_for(moment)
    if row is None:
        return
    year, month = row.shamsi_year, row.shamsi_month
    audit_event(
        user,
        AuditLog.Action.UPDATE,
        'finance.monthlyclose',
        row.id,
        event=f'BLOCKED:{action}',
        period=f'{year}-{month:02d}',
        target=object_repr,
        **context,
    )
    raise PeriodClosedError(
        f'{year}-{month:02d} is closed. Reopen that month before you {action}.',
        year=year, month=month,
    )


def audit_event(user, action, model_name, object_id=None, *, event, object_repr='', **changes):
    """Write an explicit business event to the audit trail.

    The automatic ``post_save``/``post_delete`` signals cover row mutations;
    this covers what signals cannot see -- closes, reopens, blocked attempts,
    and the reason behind an action. Secrets are never accepted here; callers
    pass only business facts.
    """
    payload = {'event': event}
    payload.update({k: v for k, v in changes.items() if v not in (None, '')})
    AuditLog.objects.create(
        user=user if user is not None and getattr(user, 'is_authenticated', False) else _system_user(),
        action=action,
        model_name=model_name,
        object_id=object_id,
        object_repr=object_repr[:255],
        changes=payload,
    )


def _system_user():
    user = get_current_user()
    if user is not None and getattr(user, 'is_authenticated', False):
        return user
    return None
