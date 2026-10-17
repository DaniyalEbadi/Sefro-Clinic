from decimal import Decimal

from django.db import transaction

from logs.models import AuditLog

from ..models import Expense
from .exchange_rates import get_rate, to_toman
from .periods_guard import audit_event, ensure_open


class ExpenseError(Exception):
    pass


Status = Expense.Status


def create_expense(*, created_by, category, amount_usd, expense_date, vendor='', description='', receipt=None, rate=None):
    # Guard outside the transaction: a refused attempt must leave its audit
    # row even though the enclosing block rolls back on the raise.
    ensure_open(expense_date, action='create an expense claim', object_repr=vendor or description or '')
    with transaction.atomic():
        rate = rate if rate is not None else get_rate('USD', 'TOMAN')
        amount_usd = Decimal(amount_usd).quantize(Decimal('0.01'))
        expense = Expense.objects.create(
            created_by=created_by,
            category=category,
            amount_usd=amount_usd,
            exchange_rate_snapshot=rate,
            amount_toman=to_toman(amount_usd, rate),
            vendor=vendor,
            description=description,
            expense_date=expense_date,
            receipt=receipt,
            status=Expense.Status.DRAFT,
        )
        return expense


def reprice_expense(expense: Expense, amount_usd, rate=None):
    """Re-derive the money columns after ``amount_usd`` changes.

    Mirrors ``create_expense``: the toman figure and the rate snapshot are
    never edited by hand, so a claim whose USD amount is changed must be
    re-priced at the current rate or the ledger keeps a stale conversion and
    every expense report drifts.
    """
    ensure_open(expense.expense_date, action='reprice an expense claim', object_repr=f'Expense#{expense.id}')
    with transaction.atomic():
        amount_usd = Decimal(amount_usd).quantize(Decimal('0.01'))
        rate = rate if rate is not None else get_rate('USD', 'TOMAN')
        expense.amount_usd = amount_usd
        expense.exchange_rate_snapshot = rate
        expense.amount_toman = to_toman(amount_usd, rate)
        expense.save(update_fields=['amount_usd', 'exchange_rate_snapshot', 'amount_toman', 'updated_at'])
        return expense


def _require_status(expense: Expense, *statuses):
    if expense.status not in statuses:
        raise ExpenseError(f'Cannot transition expense from {expense.status}.')


def submit_expense(expense: Expense):
    _require_status(expense, Expense.Status.DRAFT)
    ensure_open(expense.expense_date, action='submit an expense claim', object_repr=f'Expense#{expense.id}')
    with transaction.atomic():
        expense.status = Expense.Status.SUBMITTED
        expense.save(update_fields=['status', 'updated_at'])
        audit_event(None, AuditLog.Action.UPDATE, 'finance.expense', expense.id,
                    event='EXPENSE_SUBMIT', object_repr=str(expense), status=expense.status)
        return expense


def approve_expense(expense: Expense, approved_by):
    _require_status(expense, Expense.Status.SUBMITTED)
    if approved_by is not None and approved_by == expense.created_by:
        raise ExpenseError('You cannot approve your own expense.')
    ensure_open(expense.expense_date, action='approve an expense claim', object_repr=f'Expense#{expense.id}')
    with transaction.atomic():
        expense.status = Expense.Status.APPROVED
        expense.approved_by = approved_by
        expense.save(update_fields=['status', 'approved_by', 'updated_at'])
        audit_event(approved_by, AuditLog.Action.UPDATE, 'finance.expense', expense.id,
                    event='EXPENSE_APPROVE', object_repr=str(expense), status=expense.status)
        return expense


def reject_expense(expense: Expense, approved_by):
    _require_status(expense, Expense.Status.SUBMITTED)
    if approved_by is not None and approved_by == expense.created_by:
        raise ExpenseError('You cannot reject your own expense.')
    ensure_open(expense.expense_date, action='reject an expense claim', object_repr=f'Expense#{expense.id}')
    with transaction.atomic():
        expense.status = Expense.Status.REJECTED
        expense.approved_by = approved_by
        expense.save(update_fields=['status', 'approved_by', 'updated_at'])
        audit_event(approved_by, AuditLog.Action.UPDATE, 'finance.expense', expense.id,
                    event='EXPENSE_REJECT', object_repr=str(expense), status=expense.status)
        return expense


def pay_expense(expense: Expense, approved_by=None):
    _require_status(expense, Expense.Status.APPROVED)
    ensure_open(expense.expense_date, action='pay an expense claim', object_repr=f'Expense#{expense.id}')
    with transaction.atomic():
        expense.status = Expense.Status.PAID
        if approved_by is not None:
            expense.approved_by = approved_by
        expense.save(update_fields=['status', 'approved_by', 'updated_at'])
        audit_event(approved_by, AuditLog.Action.UPDATE, 'finance.expense', expense.id,
                    event='EXPENSE_PAY', object_repr=str(expense), status=expense.status)
        return expense


def cancel_expense(expense: Expense):
    if expense.status in (Expense.Status.PAID, Expense.Status.CANCELLED):
        raise ExpenseError('Expense cannot be cancelled in its current state.')
    ensure_open(expense.expense_date, action='cancel an expense claim', object_repr=f'Expense#{expense.id}')
    with transaction.atomic():
        expense.status = Expense.Status.CANCELLED
        expense.save(update_fields=['status', 'updated_at'])
        audit_event(None, AuditLog.Action.UPDATE, 'finance.expense', expense.id,
                    event='EXPENSE_CANCEL', object_repr=str(expense), status=expense.status)
        return expense
