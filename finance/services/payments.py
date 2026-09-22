from decimal import Decimal
from typing import Optional

from django.db import transaction
from django.utils import timezone

from ..models import PaymentComponent, Sale, WalletTransaction
from .exchange_rates import get_rate, to_toman, to_usd as from_toman
from .wallet import InsufficientFunds, debit, grant_reward, reverse_reward


class PaymentError(Exception):
    pass


def _wallet_portion(components) -> Decimal:
    return sum(
        (Decimal(c['amount_usd']) for c in components if c['method'] == 'wallet'),
        Decimal('0'),
    ).quantize(Decimal('0.01'))


def _components_sum_usd(components, rate: Decimal) -> Decimal:
    """Calculate the sum of components in USD, converting cash_toman from Toman to USD."""
    total = Decimal('0')
    for c in components:
        method = c['method']
        amt = Decimal(c['amount_usd'])
        if method == 'cash_toman':
            total += from_toman(amt, rate)
        else:
            total += amt
    return total.quantize(Decimal('0.01'))


@transaction.atomic
def checkout(
    *,
    customer,
    amount_usd: Decimal,
    components: list,
    discount_usd: Decimal = Decimal('0'),
    visit=None,
    package=None,
    rate: Optional[Decimal] = None,
    idempotency_key: Optional[str] = None,
    description: str = '',
):
    amount_usd = Decimal(amount_usd).quantize(Decimal('0.01'))
    discount_usd = Decimal(discount_usd).quantize(Decimal('0.01'))
    if amount_usd < 0:
        raise PaymentError('Amount must be non-negative.')
    if not components:
        raise PaymentError('At least one payment component is required.')

    rate = rate if rate is not None else get_rate('USD', 'TOMAN')

    component_sum_usd = _components_sum_usd(components, rate)
    if component_sum_usd != amount_usd:
        raise PaymentError('Payment components must sum to the sale amount (after currency conversion).')

    if idempotency_key:
        existing = Sale.objects.filter(idempotency_key=idempotency_key).first()
        if existing is not None:
            return existing

    wallet_needed = _wallet_portion(components)
    if wallet_needed > 0:
        from .wallet import get_or_create_wallet
        wallet = get_or_create_wallet(customer)
        wallet_locked = wallet.__class__.objects.select_for_update().get(pk=wallet.pk)
        if wallet_locked.balance < wallet_needed:
            raise InsufficientFunds(
                f'Wallet balance {wallet_locked.balance} is less than required {wallet_needed}.'
            )

    sale = Sale.objects.create(
        customer=customer,
        visit=visit,
        package=package,
        amount_usd=amount_usd,
        discount_usd=discount_usd,
        exchange_rate=rate,
        amount_toman=to_toman(amount_usd, rate),
        status=Sale.Status.PAID,
        idempotency_key=idempotency_key,
    )

    for comp in components:
        method = comp['method']
        amt = Decimal(comp['amount_usd']).quantize(Decimal('0.01'))
        if amt == 0:
            continue
        wallet_txn = None
        amt_usd = amt
        amount_toman = to_toman(amt, rate)
        
        if method == 'wallet':
            wallet_txn = debit(
                customer,
                amt,
                WalletTransaction.Type.PAYMENT,
                reference_type='sale',
                reference_id=sale.id,
                description=description or f'Wallet payment for sale {sale.id}',
                rate=rate,
            )
        else:
            from customers.models import Payment
            if method == 'cash_toman':
                amt_usd = from_toman(amt, rate)
                amount_toman = amt
            else:
                amt_usd = amt
                amount_toman = to_toman(amt, rate)
            Payment.objects.create(
                customer=customer,
                visit=visit,
                amount=amount_toman,
                amount_usd=amt_usd,
                exchange_rate=rate,
                payment_method=method,
                paid_at=timezone.now(),
                notes=description or f'Sale {sale.id}',
            )
        PaymentComponent.objects.create(
            sale=sale,
            method=method,
            amount_usd=amt_usd,
            wallet_transaction=wallet_txn,
        )

    grant_reward(
        customer,
        amount_usd,
        reference_type='sale',
        reference_id=sale.id,
        rate=rate,
        description=f'Reward for sale {sale.id}',
    )
    return sale


@transaction.atomic
def refund_sale(sale: Sale, *, refund_amount_usd: Optional[Decimal] = None, reason: str = ''):
    if sale.status != Sale.Status.PAID:
        # Refund sales carry no back-reference to the original sale, so the
        # already-refunded total cannot be recomputed. Allowing a second refund
        # from a PARTIALLY_REFUNDED sale would let cumulative refunds exceed the
        # amount actually paid, so exactly one refund is permitted.
        raise PaymentError('Only paid sales can be refunded.')
    refund_amount_usd = Decimal(refund_amount_usd if refund_amount_usd is not None else sale.amount_usd).quantize(
        Decimal('0.01')
    )
    if refund_amount_usd <= 0 or refund_amount_usd > sale.amount_usd:
        raise PaymentError('Invalid refund amount.')

    rate = sale.exchange_rate or get_rate('USD', 'TOMAN')
    wallet_portion = Decimal('0')
    for comp in sale.components.all():
        if comp.method == 'wallet':
            wallet_portion += comp.amount_usd

    wallet_refund = min(wallet_portion, refund_amount_usd).quantize(Decimal('0.01'))

    refund = Sale.objects.create(
        customer=sale.customer,
        visit=sale.visit,
        package=sale.package,
        amount_usd=-refund_amount_usd,
        discount_usd=Decimal('0'),
        exchange_rate=rate,
        amount_toman=-to_toman(refund_amount_usd, rate),
        status=Sale.Status.REFUNDED,
    )

    if wallet_refund > 0:
        from .wallet import credit
        wt = credit(
            sale.customer,
            wallet_refund,
            WalletTransaction.Type.REFUND,
            reference_type='sale_refund',
            reference_id=sale.id,
            description=reason or f'Refund to wallet for sale {sale.id}',
            rate=rate,
        )
        PaymentComponent.objects.create(
            sale=refund,
            method='wallet',
            amount_usd=-wallet_refund,
            wallet_transaction=wt,
        )

    # Reverse the reward issued for this sale (only the unspent portion).
    reward_txn = WalletTransaction.objects.filter(
        wallet__customer=sale.customer,
        transaction_type=WalletTransaction.Type.REWARD,
        reference_type='sale',
        reference_id=sale.id,
    ).first()
    if reward_txn is not None:
        reverse_reward(
            sale.customer,
            reference_type='sale',
            reference_id=sale.id,
            original_reward=reward_txn.amount,
            rate=rate,
        )

    sale.status = (
        Sale.Status.REFUNDED
        if refund_amount_usd >= sale.amount_usd
        else Sale.Status.PARTIALLY_REFUNDED
    )
    sale.save(update_fields=['status'])
    return refund
