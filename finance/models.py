from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone

from Sefro_Clinic.validators import TEXT_SANITIZERS

USD_MAX_DIGITS = 14
USD_DECIMAL_PLACES = 2
TOMAN_MAX_DIGITS = 18
TOMAN_DECIMAL_PLACES = 2
RATE_MAX_DIGITS = 18
RATE_DECIMAL_PLACES = 6


def usd_field(**kwargs):
    kwargs.setdefault('max_digits', USD_MAX_DIGITS)
    kwargs.setdefault('decimal_places', USD_DECIMAL_PLACES)
    kwargs.setdefault('validators', [MinValueValidator(Decimal('0'))])
    return models.DecimalField(**kwargs)


def toman_field(**kwargs):
    kwargs.setdefault('max_digits', TOMAN_MAX_DIGITS)
    kwargs.setdefault('decimal_places', TOMAN_DECIMAL_PLACES)
    kwargs.setdefault('validators', [MinValueValidator(Decimal('0'))])
    return models.DecimalField(**kwargs)


def rate_field(**kwargs):
    kwargs.setdefault('max_digits', RATE_MAX_DIGITS)
    kwargs.setdefault('decimal_places', RATE_DECIMAL_PLACES)
    kwargs.setdefault('validators', [MinValueValidator(Decimal('0'))])
    return models.DecimalField(**kwargs)


class ExchangeRate(models.Model):
    currency_from = models.CharField(max_length=10, default='USD')
    currency_to = models.CharField(max_length=10, default='TOMAN')
    rate = rate_field()
    effective_at = models.DateTimeField()
    source = models.CharField(max_length=100, blank=True, validators=TEXT_SANITIZERS)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-effective_at']
        indexes = [
            models.Index(fields=['currency_from', 'currency_to', '-effective_at']),
            models.Index(fields=['currency_from', 'currency_to', 'is_active']),
        ]

    def __str__(self):
        return f'{self.currency_from}->{self.currency_to} {self.rate} @ {self.effective_at:%Y-%m-%d}'


class Wallet(models.Model):
    customer = models.OneToOneField(
        'customers.Customer', on_delete=models.CASCADE, related_name='wallet',
    )
    currency = models.CharField(max_length=10, default='USD')
    balance = usd_field(default=Decimal('0'))
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                check=models.Q(balance__gte=Decimal('0')),
                name='wallet_balance_non_negative',
            ),
        ]

    def __str__(self):
        return f'Wallet({self.customer}) {self.balance}'


class WalletTransaction(models.Model):
    class Type(models.TextChoices):
        REWARD = 'reward', 'Reward'
        PAYMENT = 'payment', 'Payment'
        REFUND = 'refund', 'Refund'
        MANUAL_CREDIT = 'manual_credit', 'Manual Credit'
        MANUAL_DEBIT = 'manual_debit', 'Manual Debit'
        ADJUSTMENT = 'adjustment', 'Adjustment'
        EXPIRATION = 'expiration', 'Expiration'
        REWARD_REVERSE = 'reward_reverse', 'Reward Reversal'

    wallet = models.ForeignKey(Wallet, on_delete=models.CASCADE, related_name='transactions')
    transaction_type = models.CharField(max_length=20, choices=Type.choices)
    amount = models.DecimalField(
        max_digits=USD_MAX_DIGITS, decimal_places=USD_DECIMAL_PLACES,
        help_text='Signed amount. Positive = credit to customer, negative = debit.',
    )
    balance_after = usd_field(default=Decimal('0'))
    reference_type = models.CharField(max_length=40, blank=True, validators=TEXT_SANITIZERS)
    reference_id = models.PositiveIntegerField(null=True, blank=True)
    description = models.TextField(blank=True, validators=TEXT_SANITIZERS)
    exchange_rate_snapshot = rate_field(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['wallet', '-created_at']),
            models.Index(fields=['reference_type', 'reference_id']),
        ]
        constraints = [
            models.CheckConstraint(
                check=~models.Q(amount=Decimal('0')),
                name='wallet_txn_amount_nonzero',
            ),
            models.CheckConstraint(
                check=models.Q(balance_after__gte=Decimal('0')),
                name='wallet_txn_balance_non_negative',
            ),
            models.UniqueConstraint(
                fields=['reference_type', 'reference_id', 'transaction_type'],
                condition=models.Q(transaction_type='reward'),
                name='uniq_reward_per_reference',
            ),
            models.UniqueConstraint(
                fields=['reference_type', 'reference_id', 'transaction_type'],
                condition=models.Q(transaction_type='reward_reverse'),
                name='uniq_reward_reverse_per_reference',
            ),
        ]

    def __str__(self):
        return f'{self.transaction_type} {self.amount} ({self.wallet})'


class WalletRewardRule(models.Model):
    class RuleType(models.TextChoices):
        PERCENTAGE = 'percentage', 'Percentage'
        FIXED = 'fixed', 'Fixed Amount'

    class AppliesTo(models.TextChoices):
        PAYMENT = 'payment', 'Payment'

    name = models.CharField(max_length=120, validators=TEXT_SANITIZERS)
    rule_type = models.CharField(max_length=20, choices=RuleType.choices, default=RuleType.PERCENTAGE)
    value = usd_field(help_text='Percentage (0-100) or fixed USD amount depending on rule_type.')
    min_base_amount_usd = usd_field(default=Decimal('0'))
    applies_to = models.CharField(max_length=20, choices=AppliesTo.choices, default=AppliesTo.PAYMENT)
    is_active = models.BooleanField(default=True)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class ProductCostHistory(models.Model):
    product = models.ForeignKey('inventory.Product', on_delete=models.CASCADE, related_name='cost_history')
    cost_usd = usd_field()
    effective_from = models.DateTimeField()
    effective_to = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-effective_from']
        indexes = [
            models.Index(fields=['product', '-effective_from']),
        ]

    def __str__(self):
        return f'{self.product} cost {self.cost_usd} from {self.effective_from:%Y-%m-%d}'


class ServiceItem(models.Model):
    service = models.ForeignKey('customers.Service', on_delete=models.CASCADE, related_name='items')
    # Maintain backward-compatible alias for spec naming (service_products)
    # Access via service.service_products if using the alias property below.
    product = models.ForeignKey('inventory.Product', on_delete=models.PROTECT, related_name='service_usages')
    quantity = models.DecimalField(
        max_digits=12, decimal_places=3, default=Decimal('1'),
        validators=[MinValueValidator(Decimal('0'))],
    )

    class Meta:
        ordering = ['service', 'product']
        constraints = [
            models.UniqueConstraint(fields=['service', 'product'], name='uniq_service_item'),
            models.CheckConstraint(condition=models.Q(quantity__gt=0), name='service_product_quantity_positive'),
        ]

    def __str__(self):
        return f'{self.service} uses {self.quantity} x {self.product}'


class Package(models.Model):
    name = models.CharField(max_length=120, unique=True, validators=TEXT_SANITIZERS)
    description = models.TextField(blank=True, validators=TEXT_SANITIZERS)
    price_usd = usd_field(default=Decimal('0'))
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class PackageService(models.Model):
    package = models.ForeignKey(Package, on_delete=models.CASCADE, related_name='package_services')
    service = models.ForeignKey('customers.Service', on_delete=models.CASCADE, related_name='packages')

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['package', 'service'], name='uniq_package_service'),
        ]

    def __str__(self):
        return f'{self.package} includes {self.service}'


class PackageItem(models.Model):
    package = models.ForeignKey(Package, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey('inventory.Product', on_delete=models.CASCADE, related_name='package_usages')
    quantity = models.DecimalField(
        max_digits=10, decimal_places=3, default=Decimal('1'),
        validators=[MinValueValidator(Decimal('0'))],
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['package', 'product'], name='uniq_package_item'),
        ]

    def __str__(self):
        return f'{self.package} uses {self.quantity} x {self.product}'


class ProductUsage(models.Model):
    product = models.ForeignKey('inventory.Product', on_delete=models.CASCADE, related_name='usages')
    visit = models.ForeignKey(
        'customers.Visit', on_delete=models.SET_NULL, null=True, blank=True, related_name='product_usages',
    )
    service = models.ForeignKey(
        'customers.Service', on_delete=models.SET_NULL, null=True, blank=True, related_name='product_usages',
    )
    package_sale = models.ForeignKey(
        'finance.Sale', on_delete=models.SET_NULL, null=True, blank=True, related_name='product_usages',
    )
    quantity = models.DecimalField(
        max_digits=10, decimal_places=3, default=Decimal('1'),
        validators=[MinValueValidator(Decimal('0'))],
    )
    unit_cost_usd_snapshot = usd_field(default=Decimal('0'))
    total_cost_usd_snapshot = usd_field(default=Decimal('0'))
    exchange_rate_snapshot = rate_field(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['visit', 'created_at']),
            models.Index(fields=['package_sale', 'created_at']),
            models.Index(fields=['created_at']),
        ]

    def __str__(self):
        return f'{self.quantity} x {self.product} @ {self.unit_cost_usd_snapshot}'


class Sale(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        PAID = 'paid', 'Paid'
        REFUNDED = 'refunded', 'Refunded'
        PARTIALLY_REFUNDED = 'partially_refunded', 'Partially Refunded'
        CANCELLED = 'cancelled', 'Cancelled'

    customer = models.ForeignKey('customers.Customer', on_delete=models.CASCADE, related_name='sales')
    visit = models.ForeignKey(
        'customers.Visit', on_delete=models.SET_NULL, null=True, blank=True, related_name='sales',
    )
    package = models.ForeignKey(
        Package, on_delete=models.SET_NULL, null=True, blank=True, related_name='sales',
    )
    payment = models.ForeignKey(
        'customers.Payment', on_delete=models.SET_NULL, null=True, blank=True, related_name='sales',
    )
    amount_usd = usd_field(default=Decimal('0'))
    discount_usd = usd_field(default=Decimal('0'))
    exchange_rate = rate_field(null=True, blank=True)
    amount_toman = toman_field(default=Decimal('0'))
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    idempotency_key = models.CharField(max_length=64, unique=True, null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status', 'created_at']),
            models.Index(fields=['customer', 'created_at']),
            models.Index(fields=['visit']),
            models.Index(fields=['package']),
        ]

    def __str__(self):
        return f'Sale {self.id} {self.amount_usd} ({self.status})'


class PaymentComponent(models.Model):
    class Method(models.TextChoices):
        CASH = 'cash', 'Cash'
        CARD = 'card', 'Card'
        WALLET = 'wallet', 'Wallet'

    sale = models.ForeignKey(Sale, on_delete=models.CASCADE, related_name='components')
    method = models.CharField(max_length=20, choices=Method.choices)
    amount_usd = usd_field(default=Decimal('0'))
    wallet_transaction = models.ForeignKey(
        WalletTransaction, on_delete=models.SET_NULL, null=True, blank=True, related_name='payment_components',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['id']
        indexes = [models.Index(fields=['sale', 'method'])]

    def __str__(self):
        return f'{self.method} {self.amount_usd}'


class ExpenseCategory(models.Model):
    name = models.CharField(max_length=120, unique=True, validators=TEXT_SANITIZERS)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['name']
        verbose_name_plural = 'expense categories'

    def __str__(self):
        return self.name


class Expense(models.Model):
    class Status(models.TextChoices):
        DRAFT = 'draft', 'Draft'
        SUBMITTED = 'submitted', 'Submitted'
        APPROVED = 'approved', 'Approved'
        REJECTED = 'rejected', 'Rejected'
        PAID = 'paid', 'Paid'
        CANCELLED = 'cancelled', 'Cancelled'

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='expenses',
    )
    category = models.ForeignKey(ExpenseCategory, on_delete=models.PROTECT, related_name='expenses')
    amount_usd = usd_field(default=Decimal('0'))
    exchange_rate_snapshot = rate_field(null=True, blank=True)
    amount_toman = toman_field(default=Decimal('0'))
    description = models.TextField(blank=True, validators=TEXT_SANITIZERS)
    vendor = models.CharField(max_length=200, blank=True, validators=TEXT_SANITIZERS)
    expense_date = models.DateField()
    receipt = models.FileField(upload_to='expenses/%Y/%m/', null=True, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='approved_expenses',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-expense_date', '-created_at']
        indexes = [
            models.Index(fields=['status', 'expense_date']),
            models.Index(fields=['category', 'expense_date']),
            models.Index(fields=['created_by', 'expense_date']),
        ]

    def __str__(self):
        return f'Expense {self.id} {self.amount_usd} ({self.status})'


class ProductPurchase(models.Model):
    product = models.ForeignKey('inventory.Product', on_delete=models.PROTECT, related_name='purchases')
    quantity = models.DecimalField(
        max_digits=12, decimal_places=3, validators=[MinValueValidator(Decimal('0'))],
    )
    unit_cost_usd = usd_field(default=Decimal('0'))
    total_cost_usd = usd_field(default=Decimal('0'))
    supplier = models.CharField(max_length=200, blank=True, validators=TEXT_SANITIZERS)
    purchase_date = models.DateField()
    exchange_rate_snapshot = rate_field(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-purchase_date', '-created_at']
        indexes = [models.Index(fields=['product', 'purchase_date'])]

    def __str__(self):
        return f'Purchase {self.quantity} x {self.product} @ {self.unit_cost_usd}'
