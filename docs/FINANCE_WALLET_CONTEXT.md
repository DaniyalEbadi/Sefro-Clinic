# Sefro Clinic — Wallet & Finance Subsystem Context

---

## 1. Overview

The **Wallet & Finance** subsystem is the financial core of Sefro Clinic. It handles:

- **Customer wallets** (USD balances, immutable transaction ledger)
- **Sales & checkout** (idempotent, split payments, rewards)
- **Refunds** (wallet restoration, reward reversal)
- **Expenses** (approval workflow, self-approval forbidden)
- **Product inventory accounting** (purchase cost history, usage snapshots)
- **Reporting** (P&L, profit by service/package, wallet summary)

All financial values use `Decimal` (USD: 14 digits, 2 decimal places). Toman snapshots stored via exchange rate at transaction time.

---

## 2. Core Models (Source of Truth)

### Wallet
```python
class Wallet(models.Model):
    customer = OneToOneField(Customer, related_name='wallet')
    currency = CharField(default='USD')
    balance = DecimalField(default=0)  # CheckConstraint: balance >= 0
```
- One wallet per customer, created on first credit via `get_or_create_wallet()`.
- Balance **only modified** through `wallet._apply()` (see Services).

### WalletTransaction (Immutable Ledger)
```python
class WalletTransaction(models.Model):
    class Type(TextChoices):
        REWARD = 'reward'
        PAYMENT = 'payment'
        REFUND = 'refund'
        MANUAL_CREDIT = 'manual_credit'
        MANUAL_DEBIT = 'manual_debit'
        ADJUSTMENT = 'adjustment'
        EXPIRATION = 'expiration'
        REWARD_REVERSE = 'reward_reverse'

    wallet = FK(Wallet, related_name='transactions')
    transaction_type = CharField(choices=Type.choices)
    amount = DecimalField()  # Signed: positive=credit, negative=debit
    balance_after = DecimalField()  # Wallet balance AFTER this txn
    reference_type = CharField()  # 'sale', 'sale_refund', 'spend', etc.
    reference_id = PositiveIntegerField()
    exchange_rate_snapshot = DecimalField()
```
- **Append-only** — never updated/deleted.
- `balance_after` enables point-in-time balance reconstruction.
- Unique constraint on `(reference_type, reference_id, transaction_type)` for `reward` and `reward_reverse` prevents duplicate rewards.

### Sale
```python
class Sale(models.Model):
    class Status(TextChoices):
        PENDING, PAID, REFUNDED, PARTIALLY_REFUNDED, CANCELLED

    customer = FK(Customer)
    visit = FK(Visit, null=True)
    package = FK(Package, null=True)
    payment = FK(Payment, null=True)
    amount_usd = DecimalField()
    discount_usd = DecimalField()
    exchange_rate = DecimalField()  # USD→TOMAN at sale time
    amount_toman = DecimalField()   # Snapshot
    status = CharField(choices=Status.choices)
    idempotency_key = CharField(unique=True, null=True)  # Prevents double-charge
```
- Created by `checkout()` — **idempotent** via `idempotency_key`.
- Links to `PaymentComponent` for payment method breakdown.

### PaymentComponent
```python
class PaymentComponent(models.Model):
    class Method(TextChoices):
        CASH, CARD, WALLET

    sale = FK(Sale, related_name='components')
    method = CharField(choices=Method.choices)
    amount_usd = DecimalField()
    wallet_transaction = FK(WalletTransaction, null=True)  # Only for wallet method
```
- Splits a sale into method portions.
- Wallet portion links to its `WalletTransaction`.

### Expense
```python
class Expense(models.Model):
    class Status(TextChoices):
        DRAFT, SUBMITTED, APPROVED, REJECTED, PAID, CANCELLED

    created_by = FK(User)
    category = FK(ExpenseCategory)
    amount_usd = DecimalField()
    exchange_rate_snapshot = DecimalField()
    amount_toman = DecimalField()
    status = CharField(choices=Status.choices)
    approved_by = FK(User, null=True)
```
- State machine: `DRAFT → SUBMITTED → APPROVED/REJECTED → PAID/CANCELLED`.
- **Self-approval forbidden** (enforced in `approve_expense`/`reject_expense`).

### ProductUsage (Cost Snapshot)
```python
class ProductUsage(models.Model):
    product = FK(Product)
    visit = FK(Visit, null=True)
    service = FK(Service, null=True)
    package_sale = FK(Sale, null=True)
    quantity = DecimalField()
    unit_cost_usd_snapshot = DecimalField()    # Cost at time of use
    total_cost_usd_snapshot = DecimalField()   # quantity × unit_cost
    exchange_rate_snapshot = DecimalField()
```
- **Preserves historical cost** — future purchase price changes don't affect past usage.
- Used by reporting for accurate COGS.

### ProductCostHistory
```python
class ProductCostHistory(models.Model):
    product = FK(Product)
    cost_usd = DecimalField()
    effective_from = DateTimeField()
    effective_to = DateTimeField(null=True)  # None = current
```
- Time-series of product acquisition costs.
- Updated by `record_product_purchase()`.

---

## 3. Service Layer (Business Logic)

All services in `finance/services/` use `@transaction.atomic` and `Decimal.quantize(Decimal('0.01'))`.

### wallet.py — Ledger Operations
```python
def _apply(wallet, amount, txn_type, *, reference_type, reference_id, rate, lock=True):
    # 1. Lock wallet row (select_for_update)
    # 2. Compute new_balance = balance + amount
    # 3. Check new_balance >= 0 (raise InsufficientFunds)
    # 4. Update wallet.balance
    # 5. Create WalletTransaction with balance_after=new_balance
    # 6. Return transaction
```

| Function | Purpose |
|----------|---------|
| `credit(customer, amount, txn_type, ...)` | Positive amount → wallet credit |
| `debit(customer, amount, txn_type, ...)` | Negative amount → wallet debit |
| `grant_reward(customer, base_amount_usd, reference_type, reference_id, ...)` | Computes reward via active rules, creates REWARD txn |
| `reverse_reward(customer, reference_type, reference_id, original_reward, ...)` | Reverses **unspent portion only** (clamps to wallet.balance) |
| `manual_adjust(wallet, amount, txn_type, ...)` | Admin-only manual credit/debit/adjustment |
| `compute_reward(base_amount_usd)` | Evaluates active `WalletRewardRule` (percentage or fixed) |

**Key invariants:**
- Wallet row locked during `_apply` (prevents race conditions).
- `balance_after` always matches wallet balance after txn.
- Reward uniqueness enforced by DB constraint + `IntegrityError` catch.

### payments.py — Checkout & Refund
```python
@transaction.atomic
def checkout(customer, amount_usd, components, ..., idempotency_key=None):
    # 1. Validate components sum to amount_usd
    # 2. If idempotency_key exists → return existing Sale
    # 3. Lock wallet, check sufficient balance for wallet portion
    # 4. Create Sale (status=PAID)
    # 5. For each component:
    #    - wallet: debit() → WalletTransaction → PaymentComponent
    #    - cash/card: create Payment record
    # 6. grant_reward(customer, amount_usd, reference_type='sale', reference_id=sale.id)
    # 7. Return Sale
```

```python
@transaction.atomic
def refund_sale(sale, refund_amount_usd=None):
    # 1. Validate sale not already refunded
    # 2. Calculate wallet_portion from PaymentComponents
    # 3. Create refund Sale (negative amount_usd, status=REFUNDED)
    # 4. If wallet_portion > 0: credit() wallet_refund → REFUND txn
    # 5. Reverse reward for original sale (unspent portion only)
    # 6. Update original sale status
```

**Idempotency:** Same `idempotency_key` returns existing `Sale` without side effects.

### expenses.py — Approval Workflow
```python
def create_expense(created_by, category, amount_usd, expense_date, ...) -> Expense:
    # Creates Expense(status=DRAFT)

def submit_expense(expense):        # DRAFT → SUBMITTED
def approve_expense(expense, approved_by):  # SUBMITTED → APPROVED (self-approval forbidden)
def reject_expense(expense, approved_by):   # SUBMITTED → REJECTED (self-approval forbidden)
def pay_expense(expense):           # APPROVED → PAID
def cancel_expense(expense):        # DRAFT/SUBMITTED/APPROVED/REJECTED → CANCELLED (not PAID)
```

**Self-approval check:**
```python
if approved_by is not None and approved_by == expense.created_by:
    raise ExpenseError('You cannot approve your own expense.')
```

### inventory.py — Product Cost & Usage
```python
def record_product_purchase(product, quantity, unit_cost_usd, purchase_date, ...):
    # 1. Create ProductPurchase
    # 2. Update Product.cost_usd = unit_cost_usd, Product.count += quantity
    # 3. Close previous ProductCostHistory (set effective_to)
    # 4. Create new ProductCostHistory(effective_from=purchase_date, effective_to=None)
```

```python
def record_product_usage(product, quantity, visit=None, service=None, package_sale=None, at=None):
    # 1. unit_cost = current_cost(product, at=at)  # Looks up ProductCostHistory
    # 2. Create ProductUsage with:
    #    - unit_cost_usd_snapshot = unit_cost
    #    - total_cost_usd_snapshot = unit_cost × quantity
    # 3. Return usage
```

**Cost basis:** Uses **latest purchase cost** (current_cost) at time of usage. Historical usage snapshots never change.

### reporting.py — Aggregations
```python
def financial_summary(start, end, ...):
    # Revenue: Sale.amount_usd (PAID/REFUNDED/PARTIALLY_REFUNDED)
    # Product Cost: ProductUsage.total_cost_usd_snapshot
    # Expenses: Expense.amount_usd (APPROVED/PAID)
    # Wallet: rewards_issued, wallet_payments, refunds
    # Returns dict with USD + Toman (using snapshots)

def profit_by_service(start, end):
    # Groups ProductUsage by service
    # Revenue = sum(Service.price_usd per usage)
    # Cost = sum(ProductUsage.total_cost_usd_snapshot)

def profit_by_package(start, end):
    # Groups Sales by package
    # Revenue = sum(Sale.amount_usd)
    # Cost = sum(ProductUsage via package_sale)

def wallet_summary():
    # Liability = sum(Wallet.balance)
    # Rewards issued = sum(WalletTransaction.amount where type=REWARD)
    # Reward reversals = sum(type=REWARD_REVERSE)
    # Wallet payments = abs(sum(type=PAYMENT))
    # Refunds = sum(type=REFUND)
```

---

## 4. Critical Invariants & Rules

| Rule | Enforcement |
|------|-------------|
| **Wallet balance never negative** | DB `CheckConstraint(balance >= 0)` + `InsufficientFunds` in `_apply()` |
| **All wallet changes via ledger** | No direct `Wallet.balance` writes; only `credit()`, `debit()`, `manual_adjust()` |
| **Idempotent checkout** | `idempotency_key` unique on `Sale`; returns existing |
| **Self-approval forbidden** | `approve_expense`/`reject_expense` check `approved_by == created_by` |
| **Reward uniqueness** | DB `UniqueConstraint(reference_type, reference_id, type='reward')` |
| **Reward reversal clamps** | `min(original_reward, wallet.balance)` — never negative balance |
| **Historical cost preserved** | `ProductUsage` snapshots `unit_cost_usd_snapshot` at consumption |
| **Decimal precision** | All financial `Decimal.quantize(Decimal('0.01'))` |
| **Toman snapshots** | `amount_toman = amount_usd × exchange_rate` at transaction time |

---

## 5. API Endpoints (Finance)

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/finance/checkout/` | POST | Create sale (idempotent) |
| `/api/finance/sales/{id}/refund/` | POST | Refund sale (wallet + reward reversal) |
| `/api/finance/wallets/{id}/adjust/` | POST | Admin manual credit/debit/adjustment |
| `/api/finance/exchange-rates/` | CRUD | USD→TOMAN rates (admin write) |
| `/api/finance/expenses/` | CRUD | Expense lifecycle |
| `/api/finance/expenses/{id}/submit/` | POST | DRAFT → SUBMITTED |
| `/api/finance/expenses/{id}/approve/` | POST | SUBMITTED → APPROVED (admin, not self) |
| `/api/finance/expenses/{id}/reject/` | POST | SUBMITTED → REJECTED (admin, not self) |
| `/api/finance/expenses/{id}/pay/` | POST | APPROVED → PAID |
| `/api/finance/expenses/{id}/cancel/` | POST | Cancel (not PAID) |
| `/api/finance/reward-rules/` | CRUD | Wallet reward rules (admin) |
| `/api/finance/packages/` | CRUD | Packages + items/services |
| `/api/finance/product-purchases/` | CRUD | Record purchase (updates cost history) |
| `/api/finance/visits/{id}/record-consumption/` | POST | Create ProductUsage from visit |
| `/api/finance/reports/financial-summary/` | GET | P&L for period |
| `/api/finance/reports/profit-by-service/` | GET | Per-service profitability |
| `/api/finance/reports/profit-by-package/` | GET | Per-package profitability |
| `/api/finance/reports/wallet-summary/` | GET | Liability, rewards, payments, refunds |

---

## 6. Testing Patterns

**Wallet tests** (`tests/finance/test_wallets.py`):
- Fresh customer + wallet per test (`make_customer()` + `Wallet.objects.create()`)
- Test credit, debit, insufficient funds, reward grant/reverse, concurrency

**Finance service tests** (`tests/finance/test_services.py`):
- Isolated customers per test class
- Reward rule created in `setUp` for reward tests
- `test_cost_history_and_snapshot` verifies snapshot immutability
- `test_wallet_refund_restores_balance` verifies full wallet restoration

**Key test utilities** (`tests/helpers.py`):
```python
make_admin()          # Creates/returns admin user
make_employee()       # Creates/returns employee user
admin_client()        # Authenticated APIClient as admin
employee_client()     # Authenticated APIClient as employee
```

---

## 7. Common Pitfalls for AI Agents

| Pitfall | Correct Approach |
|---------|------------------|
| Modifying `Wallet.balance` directly | Use `wallet_service.credit/debit/manual_adjust` |
| Creating `Sale` without `idempotency_key` | Always support idempotency; test duplicate calls |
| Forgetting `quantize(Decimal('0.01'))` | Every financial `Decimal` operation |
| Allowing self-approval in expense tests | Use different users for creator vs approver |
| Sharing wallet across tests | Create fresh `Customer` + `Wallet` per test |
| Using float for money | Always `Decimal` |
| Updating `ProductUsage` snapshots | Snapshots are write-once; never modify after creation |
| Bypassing `select_for_update` | All wallet balance changes need row locking |

---

## 8. Files to Inspect First

| File | Purpose |
|------|---------|
| `finance/models.py` | All financial models with constraints |
| `finance/services/wallet.py` | Ledger core (`_apply`, credit, debit, reward, reverse) |
| `finance/services/payments.py` | Checkout, refund, idempotency |
| `finance/services/expenses.py` | Approval workflow, self-approval check |
| `finance/services/inventory.py` | Cost history, usage snapshots |
| `finance/services/reporting.py` | Financial aggregations |
| `finance/views.py` | ViewSets + APIViews (thin, delegate to services) |
| `finance/urls.py` | Router + custom paths |
| `tests/finance/test_wallets.py` | Wallet isolation patterns |
| `tests/finance/test_services.py` | Service test patterns |
| `tests/helpers.py` | Test factories |