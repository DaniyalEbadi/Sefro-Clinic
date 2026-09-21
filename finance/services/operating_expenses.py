"""Direct clinic operating costs (هزینه‌های جاری).

Distinct from the employee expense-claim workflow (``expenses.py``):
an OperatingExpense is a direct clinic business expenditure paid with clinic
money. It never touches the customer Wallet, Sale, or PaymentComponent ledgers.

Money convention: USD is authoritative; the Toman value is derived once at
creation using the exchange rate current at that moment and snapshotted on the
row. Historical rows are never repriced with a newer rate.
"""

from decimal import Decimal
from typing import Optional

from django.db import transaction

from ..models import OperatingExpense
from .exchange_rates import get_rate, to_toman


class OperatingExpenseError(Exception):
    pass


def resolve_operating_expense_rate(rate: Optional[Decimal] = None) -> Decimal:
    """Rate used for a new operating expense: explicit override or the shared
    exchange-rate helper (latest active DB rate, else configured fallback)."""
    return rate if rate is not None else get_rate('USD', 'TOMAN')


def _toman_snapshot(amount_usd: Decimal, rate: Optional[Decimal]) -> Decimal:
    if rate is None:
        return Decimal('0')
    return to_toman(amount_usd, rate)


@transaction.atomic
def create_operating_expense(
    *,
    created_by,
    category,
    title: str,
    amount_usd: Decimal,
    expense_date,
    payment_method: str = OperatingExpense.PaymentMethod.CASH,
    description: str = '',
    vendor: str = '',
    receipt=None,
    notes: str = '',
    rate: Optional[Decimal] = None,
    idempotency_key: Optional[str] = None,
) -> OperatingExpense:
    amount_usd = Decimal(amount_usd).quantize(Decimal('0.01'))
    if amount_usd < 0:
        raise OperatingExpenseError('Amount must be non-negative.')
    if not category.is_active:
        raise OperatingExpenseError('Cannot record an expense against an inactive category.')

    if idempotency_key:
        existing = OperatingExpense.objects.filter(idempotency_key=idempotency_key).first()
        if existing is not None:
            return existing

    rate = resolve_operating_expense_rate(rate)
    return OperatingExpense.objects.create(
        created_by=created_by,
        category=category,
        title=title,
        description=description,
        amount_usd=amount_usd,
        exchange_rate=rate,
        amount_toman=_toman_snapshot(amount_usd, rate),
        expense_date=expense_date,
        payment_method=payment_method,
        vendor=vendor,
        receipt=receipt,
        notes=notes,
        idempotency_key=idempotency_key or None,
    )


@transaction.atomic
def update_operating_expense(expense: OperatingExpense, **fields) -> OperatingExpense:
    """Apply editable fields. If the amount changes, the Toman value is
    recomputed against the expense's ORIGINAL exchange-rate snapshot so the
    historical rate is never silently repriced to today's rate."""
    category = fields.get('category')
    if category is not None and category != expense.category and not category.is_active:
        raise OperatingExpenseError('Cannot move an expense to an inactive category.')

    amount_changed = 'amount_usd' in fields and fields['amount_usd'] is not None
    if amount_changed:
        amount_usd = Decimal(fields['amount_usd']).quantize(Decimal('0.01'))
        if amount_usd < 0:
            raise OperatingExpenseError('Amount must be non-negative.')
        fields['amount_usd'] = amount_usd

    editable = (
        'category', 'title', 'description', 'amount_usd', 'expense_date',
        'payment_method', 'vendor', 'receipt', 'notes',
    )
    for name in editable:
        if name in fields:
            setattr(expense, name, fields[name])

    if amount_changed:
        expense.amount_toman = _toman_snapshot(expense.amount_usd, expense.exchange_rate)

    expense.save()
    return expense


@transaction.atomic
def delete_operating_expense(expense: OperatingExpense) -> None:
    # The global audit signals record the DELETE with the acting user.
    expense.delete()
