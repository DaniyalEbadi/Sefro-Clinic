# Sefro Clinic — Project Context for AI Coding Agents

---

## 1. Project Overview

**Sefro Clinic** is a Django 5.2 / Django REST Framework backend API for beauty clinic management. It handles the full operational workflow: customer management, service catalogs with categories and product-cost pricing, visit scheduling, payments, wallet/loyalty system, product inventory, financial accounting, expense tracking, exchange-rate conversion, and reporting.

The system supports two API surfaces:
- **Legacy Dashboard API** (`/api/...`) — authenticated internal dashboard for clinic staff
- **Site API v2** (`/api/v2/...`) — public-facing website API for services, packages, products, team, testimonials, and contact forms

Key technologies: Django 5.2, DRF, PostgreSQL, JWT (cookie + header auth, 15 min access), drf-spectacular for OpenAPI/Swagger, Argon2 password hashing, provider-based USD→TOMAN conversion (Tindex + BrsApi backup).

---

## 2. Technology Stack

| Category | Technology |
|----------|------------|
| Backend | Django 5.2, Django REST Framework 3.16 |
| Database | PostgreSQL 16 (psycopg2) |
| Auth | JWT via `djangorestframework-simplejwt` (access 15 min / refresh 7 days, rotation + blacklist). Transport: HttpOnly cookies (`access_token`, `refresh_token`) + `Authorization: Bearer` header. Cookie-only by default (`DJANGO_RETURN_TOKENS_IN_BODY=False`). |
| Permissions | Custom DRF permission classes (`IsAdmin`, `IsAdminOrReadOnly`, `IsEmployeeOrAdmin`/`IsFinanceAdmin`, `CanManageVisits`) — see §7 |
| API Docs | drf-spectacular + sidecar (Swagger UI, ReDoc) — two isolated schemas (`api_legacy` + `api_v2`) |
| Validation | Custom text sanitizers, Shamsi (Jalali) date handling via `jdatetime` |
| Exchange Rates | Provider abstraction: `DatabaseExchangeRateProvider` (default), `ExternalExchangeRateProvider` (Tindex `tindex.app`), `BrsApiExchangeRateProvider` (BrsApi.ir backup). Stdlib `urllib` + DB cache with TTL |
| Pricing | `customers/services/pricing.py` (cost/gross/margin) + `finance/services/pricing.py` (Toman display) via current `Product.cost_usd` |
| Caching | None currently (no Redis) — rate cache is DB row + TTL check |
| Task Queue | None currently |
| Containerization | Docker (gunicorn 3 workers, `--timeout 60`), docker-compose for Postgres + web (binds `127.0.0.1:8000`) |
| Web Server | gunicorn (3 workers, timeout 60) |
| Static Files | WhiteNoise |
| Testing | Django TestCase, `coverage --branch` (80% threshold), `ruff` linting |
| Security | bandit SAST, pip-audit (requirements + dev), gitleaks secret scanning |
| CI/CD | GitHub Actions (tests.yml, security.yml, performance.yml) |

---

## 3. Repository Structure

```
Sefro_Clinic/
├── Sefro_Clinic/           # Project config (settings, urls, docs, wsgi/asgi, validators, fields)
│   ├── settings.py         # DB, auth, DRF, Spectacular, CORS, throttling, JWT lifetimes, exchange-rate providers
│   ├── urls.py             # Root routing: api/schema+docs (legacy) + api/v2/schema+docs (SiteSchemaView)
│   ├── api_legacy.py       # Dashboard API includes (customers, accounts, finance, inventory, logs)
│   ├── api_v2.py           # Site API includes (website)
│   └── docs.py             # DocsAccessPermission + EnUsJSONSchemaView / SwaggerUIView
├── accounts/               # Custom user model (ClinicUser), JWT cookie auth, permissions
├── customers/              # Customer, ServiceCategory, Service, Visit, Payment + views/serializers
│   ├── services/pricing.py # Service cost/gross/margin breakdown (current Product.cost_usd)
│   └── migrations/         # 0012_add_service_category_and_service_product, 0013_add_service_performance_indexes
├── finance/                # Core financial domain (models, services, views)
│   ├── models.py           # Wallet, WalletTransaction, Sale, Expense, Package, ProductUsage, ServiceItem, etc.
│   ├── services/           # Business logic: wallet, payments, expenses, inventory, reporting, accounting, exchange_rates, pricing
│   │   ├── wallet.py       # Ledger (_apply, credit, debit, grant_reward, reverse_reward, manual_adjust)
│   │   ├── payments.py     # checkout, refund_sale (idempotent)
│   │   ├── expenses.py     # Expense state machine
│   │   ├── inventory.py    # Product purchase/usage with cost snapshots
│   │   ├── reporting.py    # financial_summary, profit_by_service/package, wallet_summary (personnel/product filters)
│   │   ├── accounting.py   # record_visit_consumption (selected_products override)
│   │   ├── exchange_rates.py # _validate_rate, get_rate, get_current_usd_to_toman_rate + 3 Providers + convert helpers
│   │   └── pricing.py      # service_price_toman, package_price_toman
│   ├── views.py            # ViewSets + APIViews (ExchangeRateReportView etc.)
│   ├── serializers.py      # ServiceItem validation (quantity>0, FINISHED guard), Package toman
│   └── urls.py             # Router (13 viewsets) + 5 custom paths
├── inventory/              # Product catalog (name, cost_usd, count, status, sku, unit)
├── logs/                   # AuditLog model + middleware + signals
├── website/                # Public site models (SiteService, SitePackage, SiteProduct, TeamMember, Testimonial, ContactMessage)
├── tests/                  # Comprehensive test suite (90 files)
│   ├── unit/               # Shamsi dates, report keys, currency (_validate_rate, convert, get_rate, provider mocking), service_pricing
│   ├── integration/        # Reports, dashboard, payment aggregation, DB constraints, visit_overlap, inventory_api, service_category_and_pricing_api
│   ├── e2e/                # Full visit→payment→audit cycle
│   ├── security/           # Auth (900s lifetime), authorization/IDOR (incl. service-category), input validation (category XSS/SQLi, quantity, duplicate), headers/cookies, CSRF, OWASP
│   ├── finance/            # Models, services (wallet, payments, expenses, reporting), wallets, currency
│   ├── api/                # Versioning, schema isolation (legacy vs v2)
│   ├── logic/              # Role-based logic (admin vs employee)
│   ├── performance/        # Fast regression (opt-in) + heavy suite (scheduled) — 15 sub-suites
│   ├── accounts/ customers/ website/ logs/ # App-level tests
│   └── helpers.py          # make_admin, make_employee, admin_client, employee_client
├── .github/workflows/      # tests.yml, security.yml, performance.yml
├── docs/                   # PROJECT_CONTEXT.md, FINANCE_WALLET_CONTEXT.md, PROJECT_EXPLANATION.md, SECURITY_TEST_MAP.md, API_GUIDE_FA.md, performance_report.md
├── docker-compose.yml      # Postgres + web (env drift note: EXCHANGE_RATE_* not yet forwarded)
├── Dockerfile              # python:3.12-slim, gunicorn
├── requirements.txt        # Production deps
├── requirements-dev.txt    # Dev deps (coverage, ruff, bandit, pip-audit)
├── .env.example            # Template (59 lines incl. exchange-rate + JWT vars)
└── manage.py
```

---

## 4. Architecture

```
Request
  ↓
URL Router (Sefro_Clinic.urls → api_legacy.py / api_v2.py → app urls)
  ↓  docs gated by DocsAccessPermission, Schemas isolated (EnUsJSONSchemaView vs SiteSchemaView)
View / ViewSet (DRF, @extend_schema tags)
  ↓
Serializer (validation, ShamsiDateField, pricing breakdown, sanitizers)
  ↓
Service Layer (finance/services/*.py, customers/services/pricing.py)  ← Business logic lives HERE
  ↓
Models / Database (PostgreSQL)
  ↓
Transaction.atomic() + select_for_update() for financial operations
```

**Key Architectural Rules:**
- **Business logic in services**, not views or models. Services are pure functions/classes using `@transaction.atomic`.
- **Models are data + constraints** (CheckConstraints, UniqueConstraints, indexes).
- **Serializers handle I/O transformation** (ShamsiDateField, nested serializers, toman pricing via cached rate).
- **Views are thin** — delegate to services, handle HTTP concerns only. Prefetch `items__product` to avoid N+1.
- **Financial values use `Decimal`** everywhere (USD_MAX_DIGITS=14, USD_DECIMAL_PLACES=2, `quantize(Decimal('0.01'))`).
- **Wallet changes ONLY via `wallet.py` service** (`credit`, `debit`, `grant_reward`, `reverse_reward`, `manual_adjust` → `_apply` with `select_for_update`).
- **Checkout is idempotent** via `idempotency_key` on `Sale`.
- **Product usage snapshots historical cost** at time of consumption (`unit_cost_usd_snapshot`, `total_cost_usd_snapshot`); service pricing estimate uses *current* `Product.cost_usd` (distinct concepts).
- **Exchange rate via provider abstraction** (`get_current_usd_to_toman_rate()` with TTL + backup fallback; `get_rate()` legacy helper with `FINANCE_DEFAULT_USD_TO_TOMAN_RATE` fallback).
- **Exchange-rate validation** via `_validate_rate()` (positive Decimal, returns None if invalid).

---

## 5. Core Domain / Business Logic

| Concept | Purpose |
|---------|---------|
| **ClinicUser** | Custom user model: `ADMIN` or `EMPLOYEE` role. `clean()` prevents non-configured admin (`settings.CLINIC_ADMIN['username']`). Fields: `username` (sanitized), `role`, `phone_number`. |
| **ServiceCategory** | Grouping for services: `name`/`slug` unique, `description`, `is_active`, `sort_order`. Index `svc_cat_sort_idx`. Delete protected if services exist (ViewSet returns 400). |
| **Service** | Clinic service: `name` unique, `price` (legacy 10,2), `price_usd` (authoritative 14,2 USD), `time` (minutes), `is_active`, `category` FK `SET_NULL` `related_name='services'`. Indexes `svc_category_active_idx` (partial `is_active=True`), `svc_name_idx`. Pricing fields computed via `customers/services/pricing.py` + `finance/services/exchange_rates.py`. |
| **Product** | Inventory item: `name`, `sku`, `description`, `unit_price`, `cost_usd` (current acquisition cost, updated on purchase), `count`, `status` (`available`/`less`/`finished`), `unit`. Historical costs via `ProductCostHistory`. |
| **ServiceItem** | Join: `service` `CASCADE` + `product` `PROTECT` + `quantity` (12,3, `>0` CheckConstraint, `uniq_service_item`). Serializer rejects `quantity<=0` and `product.status==FINISHED`. |
| **Customer** | Clinic client: `first_name`, `last_name`, `mobile_number` unique, `national_id` unique, `birthday` nullable Shamsi `YYYY-MM-DD` (`customers/models.py:birthday` DateField, `customers/serializers.py:birthday` ShamsiDateField), `bitmoji_code` unique nullable, `satisfaction` 1-5, `notes`. Annotated `num_visits`, `sum_payments`, `last_visit_at`. Properties: `is_new_customer`, `is_loyal_customer` (5+ visits), `visit_count`, `total_payments`, `last_visit_date` (Shamsi). Has wallet OneToOne. |
| **Visit** | Appointment: `customer`, `staff` (nullable), `services` M2M, `start_at`/`end_at`, `status` (pending/confirmed/completed/canceled). Indexes `visits_start_at_idx`, `visit_overlap_idx`. Overlap validation in `VisitSerializer` (pending/confirmed/completed). Shamsi year/month + `status`/`date_from`/`date_to` filters. |
| **Payment** | Legacy payment: `customer`, `visit` nullable, `amount` + `amount_usd` nullable, `exchange_rate` nullable, `payment_method` (`cash`/`card`/`transfer`/`wallet`/`mixed`), `paid_at`, `notes`. Indexes `payments_paid_at_idx`, `payments_paid_at_customer_idx`. |
| **Wallet** | OneToOne per customer. `currency` default USD, `balance` non-negative constraint. Created via `get_or_create_wallet()`. |
| **WalletTransaction** | Immutable ledger (types: reward/payment/refund/manual_credit/manual_debit/adjustment/expiration/reward_reverse). Signed `amount` (non-zero), `balance_after`, `reference_type`/`reference_id`, `exchange_rate_snapshot`. Indexes `wallet/-created_at`, `reference_type/reference_id`. Partial uniques `uniq_reward_per_reference` + `uniq_reward_reverse_per_reference`. |
| **WalletRewardRule** | Percentage or fixed USD reward on payments. Fields: `name`, `rule_type`, `value`, `min_base_amount_usd`, `applies_to`, `is_active`, `start_date`/`end_date`. |
| **Sale** | Financial sale (status: pending/paid/refunded/partially_refunded/cancelled). `amount_usd`, `discount_usd`, `exchange_rate`, `amount_toman` snapshots, `idempotency_key` unique nullable, `customer`/`visit`/`package`/`payment` FKs. Indexes `status/created_at`, `customer/created_at`, `visit`, `package`. |
| **PaymentComponent** | Split of sale by method (cash/card/wallet). `amount_usd`, `wallet_transaction` FK for wallet portion. Index `sale/method`. |
| **Package** | Bundle of services + products: `name` unique, `description`, `price_usd`, `is_active`. Serializer exposes `price_toman`, `exchange_rate`, `services` (ids), `items` (`product`+`quantity`). |
| **PackageService** | Many-to-many `package`/`service` (`uniq_package_service`). |
| **PackageItem** | Many-to-many `package`/`product` + `quantity` (`uniq_package_item`). |
| **ProductCostHistory** | Time-series of product costs: `product`, `cost_usd`, `effective_from` → `effective_to` (null=current). Index `product/-effective_from`, ordering `-effective_from`. Updated by `record_product_purchase()` (closes previous). |
| **ProductUsage** | Consumption: `product`, `visit`/`service`/`package_sale` nullable, `quantity`, `unit_cost_usd_snapshot` + `total_cost_usd_snapshot` + `exchange_rate_snapshot`. Indexes `visit/created_at`, `package_sale/created_at`, `created_at`. |
| **ProductPurchase** | Purchase order: `product` PROTECT, `quantity`, `unit_cost_usd`, `total_cost_usd`, `supplier`, `purchase_date`, `exchange_rate_snapshot`. Creates `ProductCostHistory`, updates `Product.cost_usd`+`count`. |
| **ExpenseCategory** | Categorization for expenses (`name` unique, `is_active`). |
| **Expense** | Operational expense (draft→submitted→approved/rejected→paid/cancelled, `cancel` from non-PAID). Fields: `created_by`, `category` PROTECT, `amount_usd`, `exchange_rate_snapshot`, `amount_toman`, `vendor`, `expense_date`, `receipt`, `status`, `approved_by`. Self-approval forbidden. Employee queryset filtered to own expenses. |
| **ExchangeRate** | USD→TOMAN rate: `currency_from`/`currency_to`, `rate` (18,6), `effective_at`, `source`, `is_active`. Indexes `currency_from/currency_to/-effective_at` and `currency_from/currency_to/is_active`. |
| **Service Pricing** | Not a model: computed in `customers/services/pricing.py` (`calculate_service_cost_usd` = Σ `Product.cost_usd×quantity`, `calculate_service_gross_profit_usd`, `calculate_service_margin_percent`, `service_pricing_breakdown` → `price_usd`, `estimated_cost_usd`, `estimated_gross_profit_usd`, `estimated_margin_percent`, `price_toman`, `estimated_cost_toman`, `estimated_gross_profit_toman`, `exchange_rate`). Uses current `Product.cost_usd`, not snapshots. |
| **Reporting** | Financial summary (with `personnel_id`/`product_id` filters), profit by service/package, wallet summary, exchange-rate report (`?usd`/`amount`/`amount_usd` → `503` if unavailable). |
| **AuditLog** | Generic change tracking (`user` SET_NULL, `model_name`, `object_id`, `object_repr`, `changes` JSONField, `timestamp` index) via `RequestUserMiddleware` + signals. |

---

## 6. Critical Business Rules

- **Self-approval forbidden**: `approve_expense`/`reject_expense` raise `ExpenseError` if `approved_by == created_by` (`finance/services/expenses.py:1-86`).
- **Wallet integrity**: All balance changes via `wallet._apply()` with `select_for_update()`; `balance >=0` CheckConstraint; `balance_after` preserved per txn; `amount !=0` constraint.
- **Idempotent checkout**: Same `idempotency_key` returns existing `Sale` without double-charging (`finance/services/payments.py:64-74`).
- **Decimal precision**: All financial calcs `Decimal.quantize(Decimal('0.01'))`.
- **Historical cost preservation**: `ProductUsage` snapshots `unit_cost_usd_snapshot` at consumption; future `Product.cost_usd` changes don't affect past usage.
- **Service pricing estimate** uses *current* `Product.cost_usd` (`customers/services/pricing.py:24-43`) — distinct from `ProductUsage` snapshots.
- **Reward uniqueness**: One reward + one reward_reverse per `(reference_type, reference_id)` via two partial UniqueConstraints (`finance/models.py:119-128`).
- **Reward reversal clamps**: `min(original_reward, wallet.balance)` — never negative balance.
- **Expense state machine**: `DRAFT → SUBMITTED → APPROVED/REJECTED → PAID/CANCELLED`; `CANCELLED` allowed from DRAFT/SUBMITTED/APPROVED/REJECTED (not PAID); `pay_expense(expense, approved_by)` called with `request.user` (`finance/views.py:357-363`).
- **Admin-only actions**: Wallet manual adjust (`/wallets/{id}/adjust/` `IsAdmin` action, `transaction_type` must be `manual_credit|manual_debit|adjustment`), expense approve/reject/pay (`IsAdmin`), exchange-rate write (`IsAdminOrReadOnly`), package/service-item/category write (`IsAdminOrReadOnly`).
- **Employee restrictions**: Expenses filtered to `created_by=user` (`finance/views.py:304-305`); `cancel` checks `is_admin or created_by==user` else 403; cannot access admin endpoints.
- **ServiceItem guards**: `quantity >0` CheckConstraint + serializer `validate_quantity`; `product.status==FINISHED` rejected (`finance/serializers.py:110-114`); `PROTECT` on product delete.
- **ServiceCategory delete guard**: `destroy` returns `400 "Cannot delete category with existing services. Deactivate it instead."` (`customers/views.py:445-451`).
- **Visit overlap**: `VisitSerializer.validate` rejects overlapping `PENDING/CONFIRMED/COMPLETED` visits for same customer (`customers/serializers.py:142-152`); index `visit_overlap_idx`.
- **Shamsi dates**: API accepts/returns Jalali via `ShamsiDateField`/`ShamsiDateTimeField`; filters `date_from`/`date_to` converted via `shamsi_to_greg_date`.
- **Exchange-rate validation**: `_validate_rate()` positive Decimal only; `get_rate()` falls back to `FINANCE_DEFAULT_USD_TO_TOMAN_RATE=100000` (still validated, defaults to 100000 if fallback invalid); `get_current_usd_to_toman_rate()` returns `None` → `503` in `ExchangeRateReportView`.
- **API docs gated**: `/api/docs/` and `/api/schema/` require auth unless `DJANGO_DOCS_PUBLIC=True` (`Sefro_Clinic/docs.py:8-14`).
- **N+1 guard**: `ServiceViewSet.get_queryset()` prefetches `items__product`; `ServiceSerializer` caches `pricing_breakdown` per `id` and reuses `_exchange_rate_cached` across list; tested via `CaptureQueriesContext <15`.

---

## 7. Authentication & Permissions

| Aspect | Implementation |
|--------|----------------|
| **Auth mechanism** | JWT (access 15 min via `JWT_ACCESS_TOKEN_LIFETIME=900`, refresh 7 days `604800`, rotation + blacklist). Transport: HttpOnly cookies (`access_token`, `refresh_token`) + `Authorization: Bearer` header. Header takes precedence (`accounts/authentication.py:18-19`). |
| **Cookie JWT auth** | `accounts.authentication.CookieJWTAuthentication` — reads `request.COOKIES[settings.JWT_AUTH_COOKIE]`, enforces CSRF on unsafe methods via `_CsrfChecker` (`:26-27`). `SESSION_COOKIE_SECURE`/`CSRF_COOKIE_SECURE` follow `SECURE_SSL_REDIRECT`. `JWT_AUTH_COOKIE_SAMESITE='Lax'`, `HTTP_ONLY=True`, `JWT_AUTH_COOKIE_SECURE` env. |
| **Token in body** | `DJANGO_RETURN_TOKENS_IN_BODY=False` by default (prod cookie-only, XSS-proof). Set `True` for dev/Swagger. |
| **Default permission** | `IsAuthenticated` globally (`REST_FRAMEWORK.DEFAULT_PERMISSION_CLASSES`). |
| **Permission classes** | `accounts/permissions.py`: `IsAdmin` (authenticated+admin), `IsAdminOrReadOnly` (read for any authenticated, write admin-only), `CanManageVisits` (any authenticated, returns True). `finance/permissions.py`: `IsEmployeeOrAdmin` (misleading name — actually `is_authenticated` any role, `finance/permissions.py:6-8`), `IsFinanceAdmin = IsAdmin` alias. |
| **Admin vs Employee** | Admin: full access, wallet adjust, expense approve/reject/pay, exchange-rate/category/package write. Employee: own expenses only, read finance reports, cannot call admin-only actions. |
| **Public endpoints** | `/api/v2/` site catalog (`AllowAny`), `/api/auth/token/`, `/api/auth/token/refresh/`, `/api/v2/contact/` (throttled). `/api/v2/site/info/` is **authenticated** (`IsAuthenticated`, version `v2`). |
| **Docs access** | `DocsAccessPermission` checks `settings.DOCS_PUBLIC` (`DJANGO_DOCS_PUBLIC`, default `False` → 401). `EnUsJSONSchemaView` forces `translation.override('en-us')`. |
| **Throttling** | Scoped: `auth` login/refresh, `contact` contact form, `anon`, `user`. In tests expanded to `100000/min` via `TESTING` flag (`settings.py:182-188`). Env overrides `THROTTLE_AUTH_RATE` (default `10/min`), `THROTTLE_CONTACT_RATE` (`5/min`), etc. |

---

## 8. API Structure

```
# Dashboard API (authenticated, IsAuthenticated default)
# Auth
/api/auth/token/           # POST login → sets HttpOnly cookies (body tokens only if DJANGO_RETURN_TOKENS_IN_BODY=True)
/api/auth/token/refresh/   # POST refresh (cookie or body)
/api/auth/logout/          # POST clears cookies
/api/auth/me/              # GET current user
/api/auth/employees/       # POST create employee (admin), GET list

# Legacy financial + inventory + logs (api_legacy)
# Customers app
/api/customers/            # CRUD incl. birthday Shamsi YYYY-MM-DD (nullable), search (first_name, last_name, mobile, national_id, bitmoji_code, birthday), ordering num_visits/created_at; birthday via ShamsiDateField (customers/serializers.py:birthday)
/api/service-categories/   # CRUD (IsAdminOrReadOnly), Search+Ordering, DELETE guarded (400 if has services)
/api/services/             # CRUD (IsAuthenticated), Search (name, description, category__name/slug), Ordering (name, price_usd, time, category__name)
                           # Query: ?category=<id|slug>&is_active=<bool>&search=<text>
                           # Response includes 8 pricing fields: price_toman, exchange_rate, products[], estimated_cost_usd/toman,
                           #   estimated_gross_profit_usd/toman, estimated_margin_percent (via customers/services/pricing.py)
/api/visits/               # CRUD, reserve (POST /visits/reserve/), confirm/complete/cancel, filters ?status & Shamsi ?year & month & date_from/date_to
/api/payments/             # CRUD, by_service (GET /payments/by_service/?date_from&date_to)
/api/visits/<id>/record-consumption/  # POST finance → ProductUsage from visit (supports {selected_products: {service_id: [[product_id,qty]]}} override)
# Dashboard/reports (customers/views.py)
 /api/dashboard/           # GET summary (customer_count, loyal, today_sales, today_visits, new_customers)
/api/reports/              # GET Shamsi chart (date_from/date_to)
/api/reports/daily|weekly|monthly|quarterly|yearly|all|visits|customers|referral  # Period reports + visits/customers breakdown

# Inventory
/api/inventory/products/   # CRUD (IsAuthenticated), status low-stock derived

# Finance (IsEmployeeOrAdmin read, IsAdmin write where noted)
 /api/finance/checkout/                    # POST CheckoutSerializer (customer, amount_usd, components[cash|card|wallet], visit, package, idempotency_key)
 /api/finance/sales/                       # Read-only + ?customer & ?status & ?package, Search, Ordering; POST /sales/{id}/refund/ (IsEmployeeOrAdmin)
 /api/finance/exchange-rates/              # CRUD (IsAdminOrReadOnly)
 /api/finance/expense-categories/          # CRUD (IsAdminOrReadOnly)
 /api/finance/expenses/                    # CRUD (IsEmployeeOrAdmin, employee sees own) + submit/approve/reject/pay/cancel actions
 /api/finance/packages/                    # CRUD (IsAdminOrReadOnly), exposes price_toman, exchange_rate, services[], items[]
 /api/finance/service-items/               # CRUD (IsAdminOrReadOnly) Search (service__name, product__name), Ordering; quantity>0 + FINISHED guard
 /api/finance/package-items/               # CRUD (IsAdminOrReadOnly)
 /api/finance/package-services/            # CRUD (IsAdminOrReadOnly)
 /api/finance/product-cost-history/        # Read-only (IsEmployeeOrAdmin)
 /api/finance/product-usages/              # Read-only (IsEmployeeOrAdmin) filters ?visit & ?service & ?product & ?package_sale
 /api/finance/product-purchases/           # CRUD (IsAdminOrReadOnly) → triggers cost history (POST via record_product_purchase)
 /api/finance/reward-rules/                # CRUD (IsAdminOrReadOnly)
 /api/finance/wallets/                     # Read-only + Search+Ordering + POST /wallets/{id}/adjust/ (IsAdmin, transaction_type manual_credit|manual_debit|adjustment)
 /api/finance/wallet-transactions/         # Read-only, filter ?wallet
 /api/finance/reports/financial-summary/   # GET ?start_date&end_date&period&service&package&product&personnel (personnel filters visit__staff)
 /api/finance/reports/profit-by-service/   # GET ?start_date&end_date&period
 /api/finance/reports/profit-by-package/   # GET ?start_date&end_date&period
 /api/finance/reports/wallet-summary/      # GET liability, rewards_issued/reversed, payments, refunds
 /api/reports/exchange-dollar/             # GET ?usd|amount|amount_usd → {rate, rate_toman_per_usd, effective_at, source, amount_usd, amount_toman}; 503 if unavailable (customers/urls.py:44, finance/views.py:ExchangeRateReportView)
 /api/reports/backup-exchange/             # GET backup rate via BrsApi (BrsApiExchangeRateProvider) ?usd|amount|amount_usd → {rate, source:brsapi, provider:BrsApi.ir}; 503 if EXCHANGE_RATE_BACKUP_API_KEY missing (customers/urls.py:45, finance/views.py:BackupExchangeRateReportView)
 /api/logs/                                # Audit logs (via logs.urls mounted at /api/ root, no prefix)

# Site API v2 (public, AllowAny except /site/info/)
/api/v2/services/       # List/retrieve (filter by category)
/api/v2/packages/       # List/retrieve (with services, tier base|standard|special, discount_percent)
/api/v2/products/       # List/retrieve
/api/v2/team/           # List
/api/v2/testimonials/   # List
/api/v2/contact/        # Create (throttled via THROTTLE_CONTACT_RATE)
/api/v2/site/info/      # GET authenticated health/version {name, version: v2}

# Documentation (two isolated schemas)
 /api/schema/              # OpenAPI JSON (legacy, gated)
/api/docs/                 # Swagger UI legacy (gated)
 /api/v2/schema/           # OpenAPI JSON site (SiteSchemaView TAGS: Site Services/Packages/Products/Team/Testimonials/Contact/Site)
/api/v2/docs/              # Swagger UI site
```

---

## 9. Database & Financial Data

**Key Financial Models (Source of Truth):**

| Model | Role |
|-------|------|
| `Wallet` | Current balance per customer (USD). Updated atomically via service. |
| `WalletTransaction` | **Immutable ledger** — every credit/debit. Source of truth for wallet history, rewards, refunds. Partial uniques for reward/reverse. |
| `Sale` | Financial sale record. Links visit, package, payment. Idempotency key prevents duplicates. |
| `PaymentComponent` | Breaks sale into method portions (cash/card/wallet). Links wallet portion to WalletTransaction. |
| `Expense` | Operational spending with approval workflow (receipt FileField optional). |
| `ProductUsage` | **Cost snapshot** — preserves `unit_cost_usd_snapshot` and `total_cost_usd_snapshot` at consumption time. |
| `ProductCostHistory` | Time-series of product acquisition costs. |
| `ProductPurchase` | Purchase records that update Product.cost_usd+count and create ProductCostHistory. |
| `ServiceItem` | Product quantity required per service (PROTECT, quantity>0). Current estimate source. |
| `ExchangeRate` | USD→TOMAN rate rows (is_active, effective_at, source). |

**Exchange-Rate Provider Layer (`finance/services/exchange_rates.py:1-383`):**

| Component | Detail |
|-----------|--------|
| `_validate_rate(value)` | Positive Decimal only, else None |
| `_get_cached_rate()` / `get_rate()` | DB lookup `is_active + effective_at<=when`; `get_rate` fallback `FINANCE_DEFAULT_USD_TO_TOMAN_RATE` (validated) |
| `get_current_usd_to_toman_rate()` | If `EXCHANGE_RATE_PROVIDER=='external'` and cache stale (> `EXCHANGE_RATE_CACHE_TTL` 3600s) → try `ExternalExchangeRateProvider` → on `None` log + try `BrsApiExchangeRateProvider` → cache success to DB (`source='external'`) → return; else return cached/validated or fallback; returns `None` → caller 503 |
| `DatabaseExchangeRateProvider` | Thin wrapper around `get_current_usd_to_toman_rate()` |
| `ExternalExchangeRateProvider` | Tindex default `https://tindex.app/api/public/indicators/Foreign-Currency/USD-EXCHANGE-RATE`. Handles `Authorization: Bearer` + `X-API-Key`, validates URL scheme, respects `429 Retry-After`, parses shapes: `data: [{key, rate|price}]`, `data.rows`, single `price|rate|value|result`, `current.price`, generic `rate|USD_TOMAN` etc. |
| `BrsApiExchangeRateProvider` | Backup `https://Api.BrsApi.ir/Market/Gold_Currency.php?key=<key>` with `User-Agent Mozilla`, `Referer https://brsapi.ir/`, requires `EXCHANGE_RATE_BACKUP_API_KEY` else None. Parses `currency: [{symbol USD, price}]`, supports `best_buy|best_sell` fallback keys. |
| `convert_usd_to_toman` / `to_toman` / `to_usd` / `usd_to_toman` / `set_rate` | Quantized helpers; `to_toman` without rate uses `get_rate` legacy fallback; `usd_to_toman` returns `Optional` (None if no rate) |
| **Env** | `EXCHANGE_RATE_PROVIDER` (`database`| `external`), `EXCHANGE_RATE_API_URL`, `EXCHANGE_RATE_API_KEY`, `EXCHANGE_RATE_TIMEOUT` (5), `EXCHANGE_RATE_CACHE_TTL` (3600), `EXCHANGE_RATE_BACKUP_API_URL`, `EXCHANGE_RATE_BACKUP_API_KEY` — note `docker-compose.yml` does **not** yet forward these (drift) |

**Snapshot Models (Historical/Audit):**
- `WalletTransaction` — append-only ledger
- `ProductUsage` — cost at time of use
- `Sale` — exchange_rate, amount_toman snapshots
- `Payment` — amount_usd, exchange_rate snapshots
- `Expense` — exchange_rate_snapshot, amount_toman snapshots
- `ProductCostHistory` — cost timeline
- `AuditLog` — generic model change tracking (via middleware + signals, index `auditlog_timestamp_idx`)

**Service Pricing (Estimate, not snapshot):**
- `customers/services/pricing.py`: `calculate_service_cost_usd` Σ `qty×cost_usd` quantized `0.01`, `calculate_service_gross_profit_usd` (`price_usd - cost`), `calculate_service_margin_percent` (`gross/price*100`, zero-price→0), `service_pricing_breakdown` (+ Toman via `convert_usd_to_toman` if rate available else None), `finance/services/pricing.py`: `service_price_toman`/`package_price_toman` via `to_toman`+`get_rate` fallback.
- `ServiceSerializer` caches per-request exchange rate in `context['_exchange_rate_cached']` and per-id pricing in `_pricing_cache` to avoid N+1.

---

## 10. Testing Architecture

| Test Type | Location | Focus |
|-----------|----------|-------|
| Unit | `tests/unit/test_shamsi_fields.py`, `test_period_keys.py`, `test_currency.py` (174 lines, _validate_rate/convert/get_rate/caching/provider mocking), `test_service_pricing.py` (101 lines, cost/gross/margin) | Date conversion, period keys, currency, pricing math |
| Integration | `tests/integration/test_dashboard.py`, `test_reports_api.py`, `test_payments_by_service.py`, `test_inventory_api.py`, `test_constraints.py`, `test_visit_overlap.py`, `test_service_category_and_pricing_api.py` (252 lines, category CRUD, filtering, ServiceItem relations, pricing Toman payload, N+1 guard `CaptureQueriesContext <15`) | Reports, dashboard, payment aggregation, DB constraints, overlap, category/pricing |
| E2E | `tests/e2e/test_clinic_workflow.py` | Full visit → payment → audit log cycle |
| Security | `tests/security/test_auth_security.py` (900s lifetime, tokens not in body), `test_authorization_security.py` (service-category IDOR 93-126), `test_input_validation_security.py` (category XSS/SQLi, quantity, duplicate, exchange-rate key leakage 173-216), `test_headers_cookies.py` (max-age 86400), plus CSRF, secrets, OWASP, etc. (9 files) | Auth, permissions/IDOR, CSRF, headers/cookies, input validation, secrets, OWASP |
| Finance | `tests/finance/test_wallets.py`, `test_services.py`, `test_models.py`, `test_finance.py` (376 lines) + unit currency | Models, services (wallet, payments, expenses, reporting, currency) |
| API Versioning | `tests/api/test_versioning.py` | Legacy vs v2 schema isolation (TAGS `Site Services…` vs Finance/Wallet/…), docs gating |
| Logic | `tests/logic/admin/`, `tests/logic/employee/` (87 tests) | Role-based permission logic |
| Performance | `tests/performance/api/`, `background/`, `benchmarks/`, `cache/`, `database/`, `endurance/`, `load/`, `reports/`, `scalability/`, `spike/`, `stress/` (15 suites) — fast mode default, heavy via `SEFRO_PERF_HEAVY=1` / `SEFRO_PERF=1` opt-in | Regression, explain plans, cache effectiveness, load/spike/endurance |
| App-level | `tests/accounts/`, `tests/customers/`, `tests/website/` (4 files), `tests/logs/` | Unit/integration/e2e per app |
| Helpers | `tests/helpers.py` | `make_admin()`, `make_employee()`, `admin_client()`, `employee_client()` — fresh customers/wallets per test |

**Conventions:**
- Tests use `TestCase` (DB transaction rollback per test).
- `tests.helpers`: `make_admin()`, `make_employee()`, `admin_client()`, `employee_client()`.
- Financial tests create fresh customers/wallets per test (isolation).
- Coverage: `coverage run --branch --source=accounts,customers,finance,inventory,logs,Sefro_Clinic,website manage.py test --parallel 1 --noinput` ; CI enforces `--fail-under=80` (README mentions 90% aspirational, CI is 80% — trust CI).
- Lint: `ruff check .` (CI enforces).
- Security: `bandit -q -r accounts customers finance inventory logs Sefro_Clinic website -x "**/migrations/*" -ll` (CI includes finance/inventory/website added at 23e852c; test scan skips B105/B106/B101/B404/B603/B607), `pip-audit -r requirements.txt` + `requirements-dev.txt`, `gitleaks` (weekly + PR/push).
- Performance: `SEFRO_PERF=1 python manage.py test tests.performance` fast; `SEFRO_PERF_HEAVY=1` heavy (scheduled weekly).

---

## 11. Environment & Configuration

| Variable | Purpose | Default |
|----------|---------|---------|
| `DJANGO_SECRET_KEY` | Required | — (app fails fast if missing) |
| `DJANGO_DEBUG` | Debug mode | `False` |
| `DJANGO_ALLOWED_HOSTS` | Comma-separated hosts | `127.0.0.1,localhost` |
| `DJANGO_SECURE_SSL_REDIRECT` | HTTPS redirect | `False` |
| `DJANGO_JWT_COOKIE_SECURE` | Secure cookies | follows `SECURE_SSL_REDIRECT` (env `DJANGO_JWT_COOKIE_SECURE`) |
| `DJANGO_RETURN_TOKENS_IN_BODY` | Include tokens in JSON (dev/Swagger) | `False` (prod cookie-only) |
| `DJANGO_DOCS_PUBLIC` | Public API docs | `False` |
| `CORS_ALLOWED_ORIGINS` | CORS origins | — |
| `CORS_ALLOW_ALL_ORIGINS` | Allow all origins | `False` |
| `CSRF_TRUSTED_ORIGINS` | CSRF trusted origins | — |
| `THROTTLE_AUTH_RATE` | Login rate limit | `10/min` |
| `THROTTLE_CONTACT_RATE` | Contact form rate | `5/min` |
| `THROTTLE_ANON_RATE` | Anon throttle | `60/min` |
| `THROTTLE_USER_RATE` | User throttle | `600/min` |
| `JWT_ACCESS_TOKEN_LIFETIME` | Access token seconds | `900` (15 min) |
| `JWT_REFRESH_TOKEN_LIFETIME` | Refresh token seconds | `604800` (7 days) |
| `POSTGRES_DB/USER/PASSWORD/HOST/PORT` | Database | `sefro_clinic`/`postgres`/``/127.0.0.1/5432 |
| `CLINIC_ADMIN_USERNAME/PASSWORD` | Bootstrap admin (required) | — |
| `FINANCE_DEFAULT_USD_TO_TOMAN_RATE` | Fallback rate when no DB row | `100000` (validated; returns 100000 if invalid) |
| `EXCHANGE_RATE_PROVIDER` | Provider: `database` or `external` | `database` |
| `EXCHANGE_RATE_API_URL` | Primary provider URL (Tindex) | `https://tindex.app/api/public/indicators/Foreign-Currency/USD-EXCHANGE-RATE` |
| `EXCHANGE_RATE_API_KEY` | Primary provider key | — |
| `EXCHANGE_RATE_TIMEOUT` | HTTP timeout seconds | `5` |
| `EXCHANGE_RATE_CACHE_TTL` | Seconds cache considered fresh | `3600` |
| `EXCHANGE_RATE_BACKUP_API_URL` | Backup provider URL (BrsApi) | `https://Api.BrsApi.ir/Market/Gold_Currency.php` |
| `EXCHANGE_RATE_BACKUP_API_KEY` | Backup provider key (required for backup) | — |
| `DJANGO_LOG_LEVEL` | Log level | `INFO` |

**Environments:**
- **Development**: `.env` with `DJANGO_DEBUG=True`, `DJANGO_DOCS_PUBLIC=True`, `DJANGO_RETURN_TOKENS_IN_BODY=True` for Swagger, local Postgres or docker-compose. Tindex free plan: 1 req/min, 100/day; `EXCHANGE_RATE_CACHE_TTL=3600` keeps you inside limits.
- **Test**: CI sets test values; `TESTING` flag in settings disables throttling (`100000/min`).
- **Production**: `DJANGO_DEBUG=False`, `SECURE_SSL_REDIRECT=True`, `DJANGO_DOCS_PUBLIC=False`, `DJANGO_RETURN_TOKENS_IN_BODY=False`, `DJANGO_JWT_COOKIE_SECURE=True`, real secrets, Postgres, `EXCHANGE_RATE_PROVIDER=external` with keys, TLS termination at host (nginx/Caddy).

---

## 12. Development & Testing Commands

```bash
# Setup
pip install -r requirements-dev.txt
cp .env.example .env   # fill in values (incl. JWT lifetimes + exchange-rate vars)

# Run server
python manage.py runserver

# Docker (binds 127.0.0.1:8000, expects reverse proxy)
docker-compose up --build

# Tests
python manage.py test --noinput --parallel 1              # All tests
python manage.py test tests.finance --parallel 1           # Finance only
python manage.py test tests.security --parallel 1          # Security only
python manage.py test tests.unit --parallel 1              # Unit only
python manage.py test tests.integration --parallel 1       # Integration only
python manage.py test tests.e2e --parallel 1               # E2E only
python manage.py test tests.logic --parallel 1             # Role-based logic
SEFRO_PERF=1 python manage.py test tests.performance --parallel 1  # Performance fast
SEFRO_PERF_HEAVY=1 python manage.py test tests.performance --parallel 1 -v 2  # Heavy

# Coverage (CI uses this exact --branch flag)
coverage run --branch --source=accounts,customers,finance,inventory,logs,Sefro_Clinic,website manage.py test --parallel 1 --noinput
coverage report --fail-under=80
coverage xml -o coverage.xml
coverage html

# Lint & Security (CI bandit includes finance/inventory/website)
ruff check .
ruff check --fix .
bandit -q -r accounts customers finance inventory logs Sefro_Clinic website -x "**/migrations/*" -ll
bandit -q -r accounts customers finance inventory logs Sefro_Clinic website -x "**/migrations/*" -ll --skip B105,B106,B101,B404,B603,B607  # test-safe variant
pip-audit -r requirements.txt --no-deps
pip-audit -r requirements-dev.txt --no-deps

# Django
python manage.py check
python manage.py check --deploy
python manage.py makemigrations --check --dry-run  # CI enforces (tests.yml:75)
python manage.py migrate
python manage.py collectstatic --noinput  # CI verifies (tests.yml:87)
```

---

## 13. CI/CD & Deployment

**GitHub Actions Workflows:**

| Workflow | File | Trigger | Jobs / Steps |
|----------|------|---------|--------------|
| **Tests** | `.github/workflows/tests.yml` | `pull_request` + `push` (all branches) | `lint` ruff check → `test` Postgres 16 service (verify migrations committed `makemigrations --check`, `coverage run --branch` with `accounts,customers,finance,inventory,logs,Sefro_Clinic,website`, `--fail-under=80`, verify `collectstatic`, upload `coverage.xml`) → `logic` role-based tests (`tests.logic --parallel 1`) → `performance` fast regression (`tests.performance --parallel 1 -v 0`, artifacts `tests/performance/reports/data/`) → `build` Docker (needs `[lint,test,logic,performance]`, only on `push` to `master`; login + push `se-clinic-api:latest`+`${{github.sha}}` if secrets present, else build-only) |
| **Security** | `.github/workflows/security.yml` | `pull_request` + `push` + weekly Mon 04:00 UTC | `bandit` SAST prod (`-q -r accounts customers finance inventory logs Sefro_Clinic website -x "**/migrations/*" -ll` fails on medium+) + test-safe variant `--skip B105,B106,B101,B404,B603,B607` → `pip-audit` on `requirements.txt` + `requirements-dev.txt` → `security` test suite (`tests.security`) → `gitleaks` secret scan (scheduled) |
| **Performance (scheduled)** | `.github/workflows/performance.yml` | `schedule 0 3 * * 1` (Mon 03:00 UTC) + `workflow_dispatch` | `heavy-performance` with `SEFRO_PERF_HEAVY=1`: `python manage.py test tests.performance --parallel 1 -v 2 \| tee performance-output.log`, artifacts `tests/performance/reports/data/` + `performance-output.log` |

**Deployment:**
- Docker image built on push to `master` only if `DOCKERHUB_USERNAME`/`DOCKERHUB_TOKEN` secrets configured; otherwise build-only (no push).
- `docker-compose` for local/prod: Postgres 16 + web (gunicorn `python manage.py migrate --noinput && collectstatic --noinput && exec gunicorn ... --workers 3 --timeout 60` on `127.0.0.1:8000`).
- Host should run TLS termination (nginx/Caddy) in front. `SECURE_PROXY_SSL_HEADER` respects `X-Forwarded-Proto: https`.
- **Env drift**: `docker-compose.yml` environment forwards only 13 vars (`DJANGO_SECRET_KEY`, `DJANGO_DEBUG`, `DJANGO_ALLOWED_HOSTS`, `DJANGO_SECURE_SSL_REDIRECT`, `DJANGO_JWT_COOKIE_SECURE`, `DJANGO_DOCS_PUBLIC`, `CORS_ALLOWED_ORIGINS`, `CSRF_TRUSTED_ORIGINS`, `THROTTLE_AUTH_RATE`, `POSTGRES_*`, `CLINIC_ADMIN_*`) — missing `EXCHANGE_RATE_*` (+ `JWT_*`, `DJANGO_RETURN_TOKENS_IN_BODY`). Configure host override or compose `env_file`.

---

## 14. Important Files

| File | Purpose |
|------|---------|
| `Sefro_Clinic/settings.py` | All configuration (DB, auth, DRF, Spectacular TAGS, CORS, throttling, JWT lifetimes 900/604800, exchange-rate provider, logging). `TESTING` auto-detected via `sys.argv`. |
| `Sefro_Clinic/urls.py` | Root routing — `EnUsJSONSchemaView(urlconf='Sefro_Clinic.api_legacy')` + `SiteSchemaView` (7 TAGS: Site Services…Site Contact/Site), Swagger. |
| `Sefro_Clinic/api_legacy.py` | Dashboard API includes + `logs.urls` at `/api/` root. |
| `Sefro_Clinic/api_v2.py` | Site API includes, `SiteInfoAPIView` (`IsAuthenticated`, `{name, version:'v2'}`). |
| `Sefro_Clinic/docs.py` | `DocsAccessPermission`, `EnUsJSONSchemaView` (en-us), `SwaggerUIView`. |
| `Sefro_Clinic/fields.py` | `ShamsiDateField`, `ShamsiDateTimeField`, `greg_to_shamsi_date`. |
| `finance/models.py` | All financial models (14 models: ExchangeRate, Wallet, WalletTransaction with two partial uniques, ProductCostHistory, ServiceItem with PROTECT, Package/PackageService/PackageItem, ProductUsage, Sale with idempotency, PaymentComponent, ExpenseCategory, Expense, ProductPurchase). |
| `finance/services/wallet.py` | Ledger (`_apply` with `select_for_update`, `quantize`, `get_or_create_wallet`, `credit/debit/grant_reward/reverse_reward/manual_adjust`, `compute_reward` ordered by `id`). |
| `finance/services/payments.py` | Checkout (components sum validate, wallet lock, cash/card Payment, wallet debit, grant_reward), refund (negative Sale, wallet restore, reward reversal). |
| `finance/services/expenses.py` | State machine (`create/submit/approve/reject/pay/cancel`), self-approval guard. `pay_expense(expense, approved_by)` signature. |
| `finance/services/inventory.py` | `current_cost(product, at)`, `record_product_purchase` (closes history), `record_product_usage`. |
| `finance/services/exchange_rates.py` | Provider abstraction — `_validate_rate`, `_get_cached_rate`, `get_rate` (fallback), `get_current_usd_to_toman_rate` (TTL+backup caching), `Database/External/BrsApi` providers, `convert_usd_to_toman`, `to_toman`, `to_usd`, `set_rate`. |
| `finance/services/pricing.py` | `service_price_toman`, `package_price_toman`, `service_pricing_payload`/`package_pricing_payload` (via `get_rate`). |
| `customers/services/pricing.py` | Estimated cost engine — `calculate_service_cost_usd`, `calculate_service_gross_profit_usd`, `calculate_service_margin_percent`, `service_pricing_breakdown` (+ toman via `convert_usd_to_toman`). Prefetch-aware. |
| `finance/services/reporting.py` | `financial_summary(start,end,service_id,package_id,product_id,personnel_id)`, `profit_by_service`, `profit_by_package`, `wallet_summary`. |
| `finance/services/accounting.py` | `record_visit_consumption(visit, selected_products=None, at, rate)` per-service product override → `ProductUsage`. |
| `finance/serializers.py` | `ServiceItemSerializer` (quantity>0, FINISHED guard), `PackageSerializer` (price_toman, exchange_rate), `CheckoutSerializer` (method enum, sum), `RefundSerializer`. |
| `finance/views.py` | 13 ViewSets + `CheckoutView`, `RecordConsumptionView`, `FinancialSummaryView`, `ProfitByService/PackageView`, `WalletSummaryView`, `ExchangeRateReportView` (503 if None, 400 if invalid amount). All with `@extend_schema(tags=[...])` matching `SPECTACULAR_SETTINGS.TAGS` (Authentication, Employees, Dashboard, Customers, Services, Visits, Payments, Products, Finance, Wallet, Exchange Rates, Packages, Expenses, Reports). |
| `finance/urls.py` | Router + custom paths (`checkout/`, `reports/*`, `visits/<id>/record-consumption/`). |
| `finance/permissions.py` | `IsEmployeeOrAdmin` (actually any authenticated), `IsFinanceAdmin` alias. |
| `customers/models.py` | `ServiceCategory` + `Service` (category FK SET_NULL, dual price, indexes) + `Customer` (birthday nullable Shamsi DateField `customers/migrations/0014_add_customer_birthday`) + `Visit` (overlap indexes) + `Payment`. |
| `customers/views.py` | `ServiceCategoryViewSet` (delete guard), `ServiceViewSet` (category/id|slug + is_active filters, prefetch, Search/Ordering), `VisitViewSet` (Shamsi year/month/date_from/date_to filters, reserve with overlap check via serializer). |
| `customers/serializers.py` | `ServiceSerializer` (8 pricing fields via `service_pricing_breakdown`, cached rate, products breakdown) + `VisitSerializer` (overlap check) + `CustomerSerializer` (birthday ShamsiDateField nullable, annotated visit counts/payments). |
| `inventory/models.py` | `Product` (cost_usd current cost, count, status AVAILABLE/LESS/FINISHED, sku, unit). |
| `accounts/models.py` | `ClinicUser` (ADMIN/EMPLOYEE, phone_number, sanitized username, `clean()` admin guard, `full_clean()` in `save()`). |
| `accounts/authentication.py` | `CookieJWTAuthentication` (header precedence, CSRF on unsafe). |
| `accounts/permissions.py` | `IsAdmin`, `IsAdminOrReadOnly`, `CanManageVisits`. |
| `tests/helpers.py` | `make_admin()`, `make_employee()`, `admin_client()`, `employee_client()` — per-test isolation. |
| `.env.example` | Required env template (59 lines, includes `EXCHANGE_RATE_*` + `JWT_*` + `DJANGO_RETURN_TOKENS_IN_BODY`). |
| `docker-compose.yml` / `Dockerfile` | Container setup (gunicorn 3 workers, timeout 60). |
| `docs/FINANCE_WALLET_CONTEXT.md` | Wallet & Finance deep-dive (ledger, checkout/refund, expenses, inventory, reporting, API table, pitfalls). |

---

## 15. AI Coding Rules

**Before changing code:**
1. Read this `PROJECT_CONTEXT.md` + `FINANCE_WALLET_CONTEXT.md` if touching finance.
2. Inspect the relevant existing implementation (models, services, views, tests) — pay attention to `select_for_update`, `quantize`, `_validate_rate`, prefetch patterns.
3. Follow existing architecture: business logic in `services/`, thin views, `Decimal` for money, provider pattern for exchange rates.
4. Do not invent duplicate business logic — reuse `wallet.*`, `payments.*`, `exchange_rates.*`, `customers/services/pricing.py`.
5. Do not weaken security/permissions to make tests pass (note `IsEmployeeOrAdmin` name is misleading but intentional — any authenticated).
6. Do not modify unrelated code (models, serializers, other apps); keep changes minimal.
7. Preserve financial integrity: `transaction.atomic`, `select_for_update`, CheckConstraints, idempotency_key, snapshot immutability.
8. Use `Decimal` with `.quantize(Decimal('0.01'))` for all financial calculations; use `_validate_rate` for rates.
9. Keep tests isolated: fresh customers/wallets per test; no shared mutable state; mock external HTTP (Tindex/BrsApi) in unit tests.
10. Add regression tests for bug fixes; cover both DB and external provider paths.
11. Never expose secrets in code, logs, or commit history (`logger.warning` must not log API keys).
12. Prefer minimal, maintainable changes over refactoring. Reuse `context['_exchange_rate_cached']` for pricing N+1 avoidance.
13. Run `ruff check .` and relevant tests before considering done (`--parallel 1`).
14. Validate quantity>0 and FINISHED guard for ServiceItem; protect ServiceCategory delete; check visit overlap serialization.
15. Ensure exchange-rate fallback returns valid Decimal; `ExchangeRateReportView` must return 503 if `get_current_usd_to_toman_rate() is None`.

---

## 16. Known Issues / Important Notes

- **API docs require auth by default** — set `DJANGO_DOCS_PUBLIC=True` in `.env` for local dev; two schemas: legacy `api/schema/` (dashboard) + `api/v2/schema/` (site, 7 TAGS `Site Services…Site Contact`).
- **JWT access is 15 min (900s)** — not 1 day. Configure `JWT_ACCESS_TOKEN_LIFETIME`/`JWT_REFRESH_TOKEN_LIFETIME` per env. Prod default `DJANGO_RETURN_TOKENS_IN_BODY=False` (cookie-only); set `True` for Swagger dev convenience. Tests assert 900s and no body tokens by default (`tests/security/test_auth_security.py:127-145`).
- **Exchange-rate providers**: default `database` (DB row + `FINANCE_DEFAULT_USD_TO_TOMAN_RATE=100000` fallback); set `EXCHANGE_RATE_PROVIDER=external` to enable Tindex primary + BrsApi backup. Free Tindex limits: 1 req/min, 100/day — `EXCHANGE_RATE_CACHE_TTL=3600` prevents excess. Backup requires `EXCHANGE_RATE_BACKUP_API_KEY` else silently skipped (`BrsApi backup: no API key configured`). `get_current_usd_to_toman_rate()` returns `None` → `503` at `/api/reports/exchange-dollar/`; backup endpoint `/api/reports/backup-exchange/` (BrsApi) also `503` if key missing. Former route `/api/reports/exchange-rate/` renamed to `exchange-dollar`; `finance/` duplicate removed — only `/api/reports/*` now. Docker env drift: `docker-compose.yml` not yet forwarding `EXCHANGE_RATE_*`/`JWT_*`/`DJANGO_RETURN_TOKENS_IN_BODY` — configure on host.
- **Service pricing vs snapshots**: `customers/services/pricing.py` estimate uses *current* `Product.cost_usd` (not `ProductCostHistory`/`ProductUsage` snapshots). Future purchase price changes affect Service's `estimated_cost_usd` but not past `ProductUsage.total_cost_usd_snapshot` reporting.
- **Dual price on Service**: `price` (legacy 10,2 display) + `price_usd` (14,2 authoritative financial). `ServiceSerializer` exposes both plus derived Toman. `Search` scans `category__name`/`slug`.
- **ServiceItem uses `PROTECT`** on product delete (not `CASCADE` like `PackageItem`); `quantity` `>0` + FINISHED guard enforced at serializer + DB constraint.
- **Root URL `/` returns 404** — API-only; no landing page (expected).
- **No Redis/cache layer** — all queries hit Postgres directly; rate cache is DB row.
- **No background task queue** — all operations synchronous.
- **Shamsi handling** uses `jdatetime`; serializers convert to/from Gregorian; `ShamsiDateTimeField` on `Visit.start_at/end_at`, `Payment.paid_at`.
- **Visit overlap** checked for same customer, status in pending/confirmed/completed (`customers/serializers.py:142-148`); index `visit_overlap_idx`.
- **Performance indexes** added: `svc_category_active_idx` (partial), `svc_name_idx`, `svc_cat_sort_idx`, `visits_start_at_idx`, `payments_paid_at_idx`/`payments_paid_at_customer_idx`, `auditlog_timestamp_idx`.
- **Finance serializers now validate** inactive product assign, duplicate ServiceItem via `uniq_service_item`, and `TOMAN` pricing via single `get_rate` per request.
- **Security tests expect** `ServiceItemViewSet` Search/Ordering, `WalletViewSet.adjust` `permission_classes=[IsAdmin]` per-action, `ExpenseViewSet.cancel` 403 for non-owner non-admin.
- **Coverage threshold** CI `80` (`tests.yml:81` `coverage report --fail-under=80` with `--branch`); README aspirational 90% differs — trust CI.
- **Performance suite**: fast regression runs in PR (`tests.yml:performance`); heavy suite (`SEFRO_PERF_HEAVY=1`, load/stress/spike/endurance) scheduled Mon 03:00 UTC (`performance.yml`). Artifacts `tests/performance/reports/data/`.
- **Two API schemas isolated** (`api/schema/` vs `api/v2/schema/`) — v2 excludes legacy endpoints (tested `tests/api/test_versioning.py`).
- **Docker binds to 127.0.0.1:8000** — expects host reverse proxy for TLS; `SECURE_PROXY_SSL_HEADER` respects `X-Forwarded-Proto`.
