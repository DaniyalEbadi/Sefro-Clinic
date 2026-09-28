# Service Layer Overview

## Architecture

All business logic lives in `services/` modules within each Django app. Views and serializers call these functions; they never touch models directly for writes. Every mutating function is wrapped in `@transaction.atomic`.

**Money convention:** USD is the authoritative currency. Toman is derived at the moment of creation using the current exchange rate and snapshotted on the row. Historical rows are never repriced.

---

## finance/services/

### accounting.py — Visit Consumption

| Symbol | Type | Purpose |
|---|---|---|
| `ConsumptionError` | Exception | User-correctable validation failure |
| `_parse_quantity(value)` | Internal | Validates Decimal: finite, > 0, max 3 decimal places |
| `_normalise_selected_products(selected, service_ids)` | Internal | Validates untrusted `{service_id: [[product_id, qty]]}` payload |
| `record_visit_consumption(visit, *, selected_products, at, rate)` | Public | Atomically consume a visit recipe and snapshot product costs |

**Key behaviors:**
- Locks the `Visit` row (`select_for_update`) to prevent double-consumption.
- Idempotency guard: raises if a non-commission `ProductUsage` already exists for the visit.
- Mandatory items (no `selection_group`) are consumed automatically; explicit selection overrides quantity.
- Selection groups require exactly one product selected.
- Locks all involved `Product` rows, validates stock, then calls `record_product_usage` with `decrement_stock=True`.

---

### wallet.py — Customer Wallet

| Symbol | Type | Purpose |
|---|---|---|
| `WalletError` | Exception | Base wallet error |
| `InsufficientFunds` | Exception | Balance would go negative |
| `get_or_create_wallet(customer)` | Public | Fetch or create a wallet |
| `current_balance(customer)` | Public | Return current balance (0 if no wallet) |
| `_apply(wallet, amount, txn_type, ...)` | Internal | Core credit/debit with row locking |
| `credit(customer, amount, txn_type, **kw)` | Public | Add funds |
| `debit(customer, amount, txn_type, **kw)` | Public | Remove funds |
| `manual_adjust(wallet, amount, txn_type, **kw)` | Public | Admin adjustment (always locks) |
| `compute_reward(base_amount_usd, at)` | Public | Calculate reward from active rules |
| `grant_reward(customer, base_amount_usd, *, reference_type, reference_id, ...)` | Public | Credit reward if rules match |
| `reverse_reward(customer, *, reference_type, reference_id, original_reward, ...)` | Public | Reverse only the unspent portion |
| `wallet_transactions(customer, *, limit)` | Public | List transactions |

**Key behaviors:**
- `_apply` locks the wallet row, checks balance >= 0 after debit, creates `WalletTransaction` with `balance_after`.
- `reverse_reward` only reverses `min(original_reward, available_balance)` to prevent negative balance.
- `grant_reward` silently returns `None` on `IntegencyError` (idempotency).

---

### inventory.py — Product Stock & Cost

| Symbol | Type | Purpose |
|---|---|---|
| `InventoryError` | Exception | User-correctable inventory failure |
| `_valid_quantity(value)` | Internal | Same validation as accounting |
| `current_cost(product, at)` | Public | Historical cost from `ProductCostHistory` |
| `apply_purchase_receipt(*, product, quantity, unit_cost_usd, purchase_date)` | Public | Lock product, update cost/count, roll cost history |
| `record_product_purchase(*, product, quantity, unit_cost_usd, supplier, ...)` | Public | Create `ProductPurchase` + call `apply_purchase_receipt` |
| `record_product_usage(*, product, quantity, visit, service, package_sale, ...)` | Public | Create `ProductUsage` snapshot; optionally decrement stock |
| `total_product_cost_usd(usages)` | Public | Sum of `total_cost_usd_snapshot` |

**Key behaviors:**
- `apply_purchase_receipt` is shared by one-shot purchases and purchase-order receive steps.
- `record_product_usage` snapshots `unit_cost_usd` and `total_cost_usd` at the time of usage.
- Stock decrement only happens when `decrement_stock=True` or `is_commission=True`.

---

### pricing.py — Service & Package Price Conversion

| Symbol | Type | Purpose |
|---|---|---|
| `service_price_toman(service, at, rate)` | Public | Convert service USD price to Toman |
| `package_price_toman(package, at, rate)` | Public | Convert package USD price to Toman |
| `service_pricing_payload(service, at)` | Public | Dict with `price_usd`, `price_toman`, `exchange_rate` |
| `package_pricing_payload(package, at)` | Public | Same for packages |

Simple conversion helpers — no cost/margin logic here.

---

### reporting.py — Financial Reports

| Symbol | Type | Purpose |
|---|---|---|
| `financial_summary(start, end, *, service_id, package_id, ...)` | Public | Full P&L: revenue, costs, gross/net profit, payment breakdown, wallet stats, counts |
| `profit_by_service(start, end)` | Public | Per-service revenue, cost, profit, margin % |
| `profit_by_package(start, end)` | Public | Per-package revenue, cost, profit, margin % |
| `wallet_summary()` | Public | Total liability, rewards issued/reversed, payments, refunds |
| `operating_expense_summary(start, end)` | Public | OperatingExpense totals by category and payment method |

**Key behaviors:**
- Revenue includes PAID, REFUNDED, and PARTIALLY_REFUNDED sales.
- Product cost Toman is computed per-usage using each row's `exchange_rate_snapshot`.
- Welcome Pack costs come from immutable `WelcomePackUsage` snapshots.
- `operating_expense_summary` is deliberately separate from employee `Expense` claims.

---

### expenses.py — Employee Expense Claims

| Symbol | Type | Purpose |
|---|---|---|
| `ExpenseError` | Exception | Expense workflow error |
| `create_expense(*, created_by, category, amount_usd, expense_date, ...)` | Public | Create DRAFT expense |
| `submit_expense(expense)` | Public | DRAFT → SUBMITTED |
| `approve_expense(expense, approved_by)` | Public | SUBMITTED → APPROVED (cannot approve own) |
| `reject_expense(expense, approved_by)` | Public | SUBMITTED → REJECTED (cannot reject own) |
| `pay_expense(expense, approved_by)` | Public | APPROVED → PAID |
| `cancel_expense(expense)` | Public | Cancel if not PAID/CANCELLED |

State machine: `DRAFT → SUBMITTED → APPROVED → PAID` (or `REJECTED`/`CANCELLED`).

---

### welcome_pack.py — Welcome Pack Issuance

| Symbol | Type | Purpose |
|---|---|---|
| `WelcomePackError` | Exception | Validation or issuance failure |
| `calculate_welcome_pack_cost_usd(welcome_pack, at)` | Public | Sum of item costs from product cost history |
| `calculate_welcome_pack_cost_toman(welcome_pack, at, rate)` | Public | Convert USD cost to Toman |
| `issue_welcome_pack(*, welcome_pack, customer, quantity, visit, ...)` | Public | Create `WelcomePackUsage` snapshot (only financial impact) |
| `validate_welcome_pack_items(items_data, instance)` | Public | Validate items for create/update |
| `create_welcome_pack_with_items(*, name, items_data, ...)` | Public | Create pack + items atomically |
| `update_welcome_pack_with_items(pack, *, items_data, ...)` | Public | Update pack; optionally replace all items |
| `get_welcome_pack_usage_summary(start, end)` | Public | Aggregated usage report |

**Key behaviors:**
- Only `issue_welcome_pack` has financial impact. Creating/editing a pack definition does not.
- Costs are frozen at issuance time in `WelcomePackUsage`.

---

### operating_expenses.py — Direct Clinic Costs

| Symbol | Type | Purpose |
|---|---|---|
| `OperatingExpenseError` | Exception | Validation failure |
| `resolve_operating_expense_rate(rate)` | Public | Explicit rate or fallback to `get_rate` |
| `create_operating_expense(*, created_by, category, title, amount_usd, ...)` | Public | Create with idempotency key support |
| `update_operating_expense(expense, **fields)` | Public | Edit fields; recompute Toman using ORIGINAL rate |
| `delete_operating_expense(expense)` | Public | Delete (audit signals handle logging) |

**Key behaviors:**
- Distinct from employee expense claims — paid with clinic money, never touches Wallet/Sale.
- Toman is always derived from the expense's original `exchange_rate` snapshot, never repriced.
- Supports `idempotency_key` for safe retries.

---

## customers/services/

### pricing.py — Service Cost & Margin

| Symbol | Type | Purpose |
|---|---|---|
| `calculate_service_cost_usd(service)` | Public | Estimated cost from current `Product.cost_usd` × item quantities |
| `calculate_service_gross_profit_usd(service)` | Public | `price_usd - estimated_cost` |
| `calculate_service_margin_percent(service)` | Public | `gross / price × 100` (0 if price is 0) |
| `service_pricing_breakdown(service, rate)` | Public | Full dict for serializer: price, cost, gross, margin, Toman conversions |

**Key behaviors:**
- Uses **current** `Product.cost_usd`, not historical snapshots.
- Supports prefetched `items__product` to avoid N+1 queries.
- Negative profit is supported (not clamped).

---

## Shared Patterns

| Pattern | Where Used |
|---|---|
| `select_for_update()` row locking | wallet, inventory, accounting |
| `@transaction.atomic` | All mutating functions |
| `Decimal` with `quantize(Decimal('0.01'))` | All money calculations |
| Exchange rate snapshot on creation | All models with `exchange_rate_snapshot` |
| Idempotency guards | wallet (`IntegrityError` catch), accounting (duplicate check), operating_expenses (key) |
| Custom exception per module | `ConsumptionError`, `WalletError`, `InventoryError`, `ExpenseError`, `WelcomePackError`, `OperatingExpenseError` |
