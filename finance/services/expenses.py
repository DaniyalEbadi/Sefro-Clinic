from decimal import Decimal

from django.db import transaction

from ..models import Expense
from .exchange_rates import get_rate, to_toman


class ExpenseError(Exception):
    pass


Status = Expense.Status


@transaction.atomic
def create_expense(*, created_by, category, amount_usd, expense_date, vendor='', description='', receipt=None, rate=None):
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


@transaction.atomic
def reprice_expense(expense: Expense, amount_usd, rate=None):
    """Re-derive the money columns after ``amount_usd`` changes.

    Mirrors ``create_expense``: the toman figure and the rate snapshot are
    never edited by hand, so a claim whose USD amount is changed must be
    re-priced at the current rate or the ledger keeps a stale conversion and
    every expense report drifts.
    """
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


@transaction.atomic
def submit_expense(expense: Expense):
    _require_status(expense, Expense.Status.DRAFT)
    expense.status = Expense.Status.SUBMITTED
    expense.save(update_fields=['status', 'updated_at'])
    return expense


@transaction.atomic
def approve_expense(expense: Expense, approved_by):
    _require_status(expense, Expense.Status.SUBMITTED)
    if approved_by is not None and approved_by == expense.created_by:
        raise ExpenseError('You cannot approve your own expense.')
    expense.status = Expense.Status.APPROVED
    expense.approved_by = approved_by
    expense.save(update_fields=['status', 'approved_by', 'updated_at'])
    return expense


@transaction.atomic
def reject_expense(expense: Expense, approved_by):
    _require_status(expense, Expense.Status.SUBMITTED)
    if approved_by is not None and approved_by == expense.created_by:
        raise ExpenseError('You cannot reject your own expense.')
    expense.status = Expense.Status.REJECTED
    expense.approved_by = approved_by
    expense.save(update_fields=['status', 'approved_by', 'updated_at'])
    return expense


@transaction.atomic
def pay_expense(expense: Expense, approved_by=None):
    _require_status(expense, Expense.Status.APPROVED)
    expense.status = Expense.Status.PAID
    if approved_by is not None:
        expense.approved_by = approved_by
    expense.save(update_fields=['status', 'approved_by', 'updated_at'])
    return expense


@transaction.atomic
def cancel_expense(expense: Expense):
    if expense.status in (Expense.Status.PAID, Expense.Status.CANCELLED):
        raise ExpenseError('Expense cannot be cancelled in its current state.')
    expense.status = Expense.Status.CANCELLED
    expense.save(update_fields=['status', 'updated_at'])
    return expense
