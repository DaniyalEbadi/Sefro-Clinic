from decimal import Decimal
from typing import Optional

from django.db import IntegrityError, models, transaction
from django.utils import timezone

from ..models import Wallet, WalletRewardRule, WalletTransaction


class WalletError(Exception):
    pass


class InsufficientFunds(WalletError):
    pass


def get_or_create_wallet(customer) -> Wallet:
    wallet, _ = Wallet.objects.get_or_create(customer=customer)
    return wallet


def current_balance(customer) -> Decimal:
    wallet = Wallet.objects.filter(customer=customer).first()
    if wallet is None:
        return Decimal('0')
    return wallet.balance


def _apply(
    wallet: Wallet,
    amount: Decimal,
    txn_type: str,
    *,
    reference_type: str = '',
    reference_id: Optional[int] = None,
    description: str = '',
    rate: Optional[Decimal] = None,
    lock: bool = True,
) -> WalletTransaction:
    amount = Decimal(amount).quantize(Decimal('0.01'))
    if amount == 0:
        raise WalletError('Transaction amount must be non-zero.')

    def _do():
        if lock:
            wallet_locked = Wallet.objects.select_for_update().get(pk=wallet.pk)
        else:
            wallet_locked = wallet
        new_balance = (wallet_locked.balance + amount).quantize(Decimal('0.01'))
        if new_balance < 0:
            raise InsufficientFunds(
                f'Wallet balance {wallet_locked.balance} insufficient for debit of {abs(amount)}.'
            )
        wallet_locked.balance = new_balance
        wallet_locked.save(update_fields=['balance', 'updated_at'])
        return WalletTransaction.objects.create(
            wallet=wallet_locked,
            transaction_type=txn_type,
            amount=amount,
            balance_after=new_balance,
            reference_type=reference_type,
            reference_id=reference_id,
            description=description,
            exchange_rate_snapshot=rate,
        )

    if lock:
        with transaction.atomic():
            return _do()
    return _do()


def credit(customer, amount: Decimal, txn_type: str, **kwargs) -> WalletTransaction:
    wallet = get_or_create_wallet(customer)
    return _apply(wallet, amount, txn_type, **kwargs)


def debit(customer, amount: Decimal, txn_type: str, **kwargs) -> WalletTransaction:
    wallet = get_or_create_wallet(customer)
    return _apply(wallet, -Decimal(amount).quantize(Decimal('0.01')), txn_type, **kwargs)


def manual_adjust(wallet: Wallet, amount: Decimal, txn_type: str, **kwargs) -> WalletTransaction:
    return _apply(wallet, amount, txn_type, lock=True, **kwargs)


def compute_reward(base_amount_usd: Decimal, at: Optional[object] = None) -> Decimal:
    when = at or timezone.now()
    if base_amount_usd <= 0:
        return Decimal('0')
    rules = WalletRewardRule.objects.filter(
        is_active=True,
        applies_to=WalletRewardRule.AppliesTo.PAYMENT,
        min_base_amount_usd__lte=base_amount_usd,
    )
    if isinstance(when, object) and hasattr(when, 'date'):
        rules = rules.filter(
            models.Q(start_date__isnull=True) | models.Q(start_date__lte=when.date()),
        ).filter(
            models.Q(end_date__isnull=True) | models.Q(end_date__gte=when.date()),
        )
    rules = rules.order_by('-value' if False else 'id')
    best = rules.first()
    if best is None:
        return Decimal('0')
    if best.rule_type == WalletRewardRule.RuleType.PERCENTAGE:
        reward = (base_amount_usd * best.value / Decimal('100')).quantize(Decimal('0.01'))
    else:
        reward = best.value.quantize(Decimal('0.01'))
    return reward


def grant_reward(
    customer,
    base_amount_usd: Decimal,
    *,
    reference_type: str,
    reference_id: int,
    rate: Optional[Decimal] = None,
    description: str = '',
) -> Optional[WalletTransaction]:
    reward = compute_reward(base_amount_usd)
    if reward <= 0:
        return None
    try:
        return _apply(
            get_or_create_wallet(customer),
            reward,
            WalletTransaction.Type.REWARD,
            reference_type=reference_type,
            reference_id=reference_id,
            description=description or f'Reward for {reference_type}#{reference_id}',
            rate=rate,
        )
    except IntegrityError:
        return None


def reverse_reward(
    customer,
    *,
    reference_type: str,
    reference_id: int,
    original_reward: Decimal,
    rate: Optional[Decimal] = None,
    description: str = '',
) -> Optional[WalletTransaction]:
    if original_reward is None or original_reward <= 0:
        return None
    wallet = Wallet.objects.filter(customer=customer).first()
    if wallet is None:
        return None
    # Only reverse the portion that is still available (unspent) to avoid a
    # negative balance. This preserves ledger integrity.
    available = wallet.balance
    to_reverse = min(original_reward, available).quantize(Decimal('0.01'))
    if to_reverse <= 0:
        return None
    try:
        return _apply(
            wallet,
            -to_reverse,
            WalletTransaction.Type.REWARD_REVERSE,
            reference_type=reference_type,
            reference_id=reference_id,
            description=description or f'Reward reversal for {reference_type}#{reference_id}',
            rate=rate,
        )
    except IntegrityError:
        return None


def wallet_transactions(customer, *, limit=None):
    qs = WalletTransaction.objects.filter(wallet__customer=customer).select_related('wallet')
    if limit:
        qs = qs[:limit]
    return qs
