# Sefro Clinic — Project Context for AI Coding Agents

---

## 1. Project Overview

**Sefro Clinic** is a Django 5.2 / Django REST Framework backend API for beauty clinic management. It handles the full operational workflow: customer management, service catalogs, visit scheduling, payments, wallet/loyalty system, product inventory, financial accounting, expense tracking, and reporting.

The system supports two API surfaces:
- **Legacy Dashboard API** (`/api/...`) — authenticated internal dashboard for clinic staff
- **Site API v2** (`/api/v2/...`) — public-facing website API for services, packages, products, team, testimonials, and contact forms

Key technologies: Django 5.2, DRF, PostgreSQL, JWT (cookie + header auth), drf-spectacular for OpenAPI/Swagger, Argon2 password hashing.

---

## 2. Technology Stack

| Category | Technology |
|----------|------------|
| Backend | Django 5.2, Django REST Framework 3.16 |
| Database | PostgreSQL 16 (psycopg2) |
| Auth | JWT via `djangorestframework-simplejwt` (access/refresh tokens in HttpOnly cookies + Bearer header), Argon2 |
| Permissions | Custom DRF permission classes (`IsAdmin`, `IsAdminOrReadOnly`, `IsEmployeeOrAdmin`) |
| API Docs | drf-spectacular + sidecar (Swagger UI, ReDoc) |
| Validation | Custom text sanitizers, Shamsi (Jalali) date handling via `jdatetime` |
| Caching | None currently (no Redis) |
| Task Queue | None currently |
| Containerization | Docker (gunicorn), docker-compose for Postgres + web |
| Web Server | gunicorn (3 workers) |
| Static Files | WhiteNoise |
| Testing | Django TestCase, `coverage` (80% threshold), `ruff` linting |
| Security | bandit SAST, pip-audit, gitleaks secret scanning |
| CI/CD | GitHub Actions (tests.yml, security.yml) |

---

## 3. Repository Structure

```
Sefro_Clinic/
├── Sefro_Clinic/           # Project config (settings, urls, docs, wsgi/asgi)
├── accounts/               # Custom user model (ClinicUser), JWT cookie auth, permissions
├── customers/              # Customer, Service, Visit, Payment models + views
├── finance/                # Core financial domain (models, services, views)
│   ├── models.py           # Wallet, WalletTransaction, Sale, Expense, Package, ProductUsage, etc.
│   ├── services/           # Business logic: wallet, payments, expenses, inventory, reporting
│   ├── views.py            # ViewSets + APIViews for all finance endpoints
│   └── urls.py             # Router + custom paths
├── inventory/              # Product catalog (simple CRUD)
├── logs/                   # AuditLog model + middleware
├── website/                # Public site models (SiteService, SitePackage, SiteProduct, etc.)
├── tests/                  # Comprehensive test suite
│   ├── unit/               # Unit tests (Shamsi dates, report keys)
│   ├── integration/        # Integration tests
│   ├── e2e/                # Full visit→payment→audit cycle
│   ├── security/           # Auth, permissions, CSRF, headers, secrets, OWASP
│   ├── finance/            # Finance-specific tests (models, services, wallets)
│   ├── api/                # Versioning, schema isolation tests
│   ├── logic/              # Role-based logic tests
│   ├── performance/        # Performance regression (opt-in via SEFRO_PERF=1)
│   └── helpers.py          # Test utilities (make_admin, make_employee, clients)
├── .github/workflows/      # CI: tests.yml, security.yml
├── docker-compose.yml      # Postgres + web (bound to 127.0.0.1:8000)
├── Dockerfile              # python:3.12-slim, gunicorn
├── requirements.txt        # Production deps
├── requirements-dev.txt    # Dev deps (coverage, ruff, bandit, pip-audit)
├── .env.example            # Template for environment variables
└── manage.py
```

---

## 4. Architecture

```
Request
  ↓
URL Router (Sefro_Clinic.urls → api_legacy.py / api_v2.py → app urls)
  ↓
View / ViewSet (DRF)
  ↓
Serializer (validation, Shamsi date fields)
  ↓
Service Layer (finance/services/*.py)  ← Business logic lives HERE
  ↓
Models / Database (PostgreSQL)
  ↓
Transaction.atomic() for financial operations
```

**Key Architectural Rules:**
- **Business logic in services**, not views or models. Services are pure functions/classes using `@transaction.atomic`.
- **Models are data + constraints** (CheckConstraints, UniqueConstraints, indexes).
- **Serializers handle I/O transformation** (ShamsiDateField, nested serializers).
- **Views are thin** — delegate to services, handle HTTP concerns only.
- **Financial values use `Decimal`** everywhere (USD_MAX_DIGITS=14, USD_DECIMAL_PLACES=2).
- **Wallet changes ONLY via `wallet.py` service** (`credit`, `debit`, `grant_reward`, `reverse_reward`, `manual_adjust`).
- **Checkout is idempotent** via `idempotency_key` on `Sale`.
- **Product usage snapshots historical cost** at time of consumption (`unit_cost_usd_snapshot`, `total_cost_usd_snapshot`).

---

## 5. Core Domain / Business Logic

| Concept | Purpose |
|---------|---------|
| **ClinicUser** | Custom user model: `ADMIN` or `EMPLOYEE` role. Only configured system admin can have admin role. |
| **Customer** | Clinic client. Has wallet (OneToOne), visits, payments, sales. Properties: `is_new_customer`, `is_loyal_customer` (5+ visits). |
| **Service** | Clinic service (name, price_usd, duration). Used in visits and packages. |
| **Visit** | Customer appointment (status: pending/confirmed/completed/canceled). Links customer, staff, services. |
| **Payment** | Legacy payment record (cash/card/transfer/wallet/mixed). Has `amount_usd` snapshot. |
| **Wallet** | OneToOne per customer. Balance in USD (non-negative constraint). |
| **WalletTransaction** | Immutable ledger entry (type: reward/payment/refund/manual_credit/manual_debit/adjustment/expiration/reward_reverse). Signed amount, balance_after, reference tracking. |
| **WalletRewardRule** | Percentage or fixed USD reward on payments. Configurable min base amount, date range, active flag. |
| **Sale** | Financial sale record (status: pending/paid/refunded/partially_refunded/cancelled). Idempotency key. Links visit, package, payment. |
| **PaymentComponent** | Split of a sale by method (cash/card/wallet). Links to WalletTransaction for wallet portion. |
| **Package** | Bundle of services + products with package price. |
| **PackageService / PackageItem** | Many-to-many links for services/products in a package. |
| **Product** | Inventory item (name, cost_usd, count, status). Current cost updated on purchase. |
| **ProductPurchase** | Purchase order (quantity, unit_cost_usd, supplier). Creates ProductCostHistory. |
| **ProductCostHistory** | Time-series of product costs (effective_from → effective_to). |
| **ProductUsage** | Consumption of product during visit/service/package_sale. Snapshots `unit_cost_usd_snapshot` and `total_cost_usd_snapshot` at time of use. |
| **Expense** | Operational expense (draft→submitted→approved/rejected→paid/cancelled). Self-approval forbidden. |
| **ExpenseCategory** | Categorization for expenses. |
| **ExchangeRate** | USD→TOMAN rate with effective_at. Used for Toman snapshots. |
| **Reporting** | Financial summary, profit by service/package, wallet summary. |

---

## 6. Critical Business Rules

- **Self-approval forbidden**: A user cannot approve/reject their own expense (`expense_svc.approve_expense` raises `ExpenseError`).
- **Wallet integrity**: All balance changes go through `wallet._apply()` with `select_for_update()` locking. Balance never negative (DB CheckConstraint).
- **Idempotent checkout**: Same `idempotency_key` returns existing `Sale` without double-charging.
- **Decimal precision**: All financial calculations use `Decimal` with `.quantize(Decimal('0.01'))`.
- **Historical cost preservation**: `ProductUsage` snapshots `unit_cost_usd_snapshot` at consumption time; future purchase price changes do not affect past usage.
- **Reward uniqueness**: One reward per `(reference_type, reference_id)` via DB UniqueConstraint.
- **Reward reversal clamps**: Only unspent portion of reward can be reversed (prevents negative balance).
- **Expense state machine**: `DRAFT → SUBMITTED → APPROVED/REJECTED → PAID/CANCELLED`. No transitions from PAID/CANCELLED.
- **Admin-only actions**: Wallet manual adjust, expense approve/reject/pay, exchange rate write.
- **Employee restrictions**: Employees see only their own expenses; cannot access admin endpoints.
- **Shamsi dates**: API accepts/returns Persian (Jalali) dates via `ShamsiDateField` / `ShamsiDateTimeField`.
- **API docs gated**: `/api/docs/` and `/api/schema/` require authentication unless `DJANGO_DOCS_PUBLIC=True`.

---

## 7. Authentication & Permissions

| Aspect | Implementation |
|--------|----------------|
| **Auth mechanism** | JWT (access 1d, refresh 7d, rotation + blacklist). Transport: HttpOnly cookies (`access_token`, `refresh_token`) + `Authorization: Bearer` header. |
| **Cookie JWT auth** | `accounts.authentication.CookieJWTAuthentication` — reads from cookie, enforces CSRF on unsafe methods. |
| **Default permission** | `IsAuthenticated` globally (`REST_FRAMEWORK.DEFAULT_PERMISSION_CLASSES`). |
| **Permission classes** | `IsAdmin` (admin only), `IsAdminOrReadOnly` (read for all authenticated, write for admin), `IsEmployeeOrAdmin` (finance views), `CanManageVisits` (all authenticated). |
| **Admin vs Employee** | Admin: full access, wallet adjust, expense approve. Employee: own expenses only, no admin endpoints. |
| **Public endpoints** | `/api/v2/` site API (AllowAny), `/api/auth/token/`, `/api/auth/token/refresh/`, `/api/v2/contact/` (throttled). |
| **Docs access** | `DocsAccessPermission` — checks `settings.DOCS_PUBLIC` (env `DJANGO_DOCS_PUBLIC`). Default: private (401). |
| **Throttling** | Scoped: `auth` (login/refresh), `contact` (contact form), `anon`, `user`. High limits in tests. |

---

## 8. API Structure

```
# Dashboard API (authenticated)
/api/auth/              # Login, refresh, me, employee management
/api/customers/         # CRUD, search
/api/services/          # CRUD
/api/visits/            # CRUD, reserve, confirm, complete, cancel
/api/payments/          # CRUD, by_service
/api/dashboard/         # Summary stats
/api/reports/           # daily/weekly/monthly/quarterly/yearly/all/customers/visits/referral
/api/inventory/products/# CRUD
/api/finance/           # All finance endpoints:
    /checkout/                    # Idempotent sale creation
    /exchange-rates/              # CRUD (admin write)
    /expense-categories/          # CRUD
    /expenses/                    # CRUD + submit/approve/reject/pay/cancel
    /packages/                    # CRUD + service-items/package-items/package-services
    /product-cost-history/        # Read-only
    /product-purchases/           # CRUD (triggers cost history)
    /product-usages/              # Read-only (filterable)
    /reward-rules/                # CRUD (admin)
    /sales/                       # Read-only + refund
    /service-items/               # CRUD
    /wallets/                     # Read-only + adjust (admin)
    /wallet-transactions/         # Read-only
    /reports/financial-summary/   # Aggregated P&L
    /reports/profit-by-service/   # Per-service profitability
    /reports/profit-by-package/   # Per-package profitability
    /reports/wallet-summary/      # Liability, rewards, payments, refunds
    /visits/<id>/record-consumption/  # Product usage from visit

# Site API v2 (public)
/api/v2/services/       # List/retrieve (filter by category)
/api/v2/packages/       # List/retrieve (with services)
/api/v2/products/       # List/retrieve
/api/v2/team/           # List
/api/v2/testimonials/   # List
/api/v2/contact/        # Create (throttled)
/api/v2/site/info/      # Authenticated health/version

# Documentation
/api/docs/              # Swagger UI (gated by DOCS_PUBLIC)
/api/schema/            # OpenAPI JSON (gated)
/api/v2/docs/           # Site API Swagger UI
/api/v2/schema/         # Site API OpenAPI JSON
```

---

## 9. Database & Financial Data

**Key Financial Models (Source of Truth):**

| Model | Role |
|-------|------|
| `Wallet` | Current balance per customer (USD). Updated atomically via service. |
| `WalletTransaction` | **Immutable ledger** — every credit/debit. Source of truth for wallet history, rewards, refunds. |
| `Sale` | Financial sale record. Links visit, package, payment. Idempotency key prevents duplicates. |
| `PaymentComponent` | Breaks sale into method portions (cash/card/wallet). Links wallet portion to WalletTransaction. |
| `Expense` | Operational spending with approval workflow. |
| `ProductUsage` | **Cost snapshot** — preserves `unit_cost_usd_snapshot` and `total_cost_usd_snapshot` at consumption time. |
| `ProductCostHistory` | Time-series of product acquisition costs. |
| `ProductPurchase` | Purchase records that update Product.cost_usd and create ProductCostHistory. |

**Snapshot Models (Historical/Audit):**
- `WalletTransaction` — append-only ledger
- `ProductUsage` — cost at time of use
- `Sale` — exchange_rate, amount_toman snapshots
- `Payment` — amount_usd, exchange_rate snapshots
- `Expense` — exchange_rate_snapshot, amount_toman snapshots
- `ProductCostHistory` — cost timeline
- `AuditLog` — generic model change tracking (via middleware)

---

## 10. Testing Architecture

| Test Type | Location | Focus |
|-----------|----------|-------|
| Unit | `tests/unit/` | Shamsi date conversion, report period keys |
| Integration | `tests/integration/` | Reports, dashboard, payment aggregation, DB constraints |
| E2E | `tests/e2e/` | Full visit → payment → audit log cycle |
| Security | `tests/security/` | Auth, permissions (IDOR), CSRF, headers, input validation, secrets, OWASP |
| Finance | `tests/finance/` | Models, services (wallet, payments, expenses, reporting), wallets |
| API Versioning | `tests/api/test_versioning.py` | Legacy vs v2 schema isolation, docs gating |
| Logic | `tests/logic/` | Role-based permission logic |
| Performance | `tests/performance/` | Opt-in via `SEFRO_PERF=1` |

**Conventions:**
- Tests use `TestCase` (DB transaction rollback per test).
- `tests.helpers`: `make_admin()`, `make_employee()`, `admin_client()`, `employee_client()`.
- Financial tests create fresh customers/wallets per test (isolation).
- Coverage threshold: 80% (CI enforces `--fail-under=80`).
- Lint: `ruff check .` (CI enforces).
- Security: `bandit` (SAST), `pip-audit`, `gitleaks` (CI).

---

## 11. Environment & Configuration

| Variable | Purpose | Default |
|----------|---------|---------|
| `DJANGO_SECRET_KEY` | Required | — |
| `DJANGO_DEBUG` | Debug mode | `False` |
| `DJANGO_ALLOWED_HOSTS` | Comma-separated hosts | `127.0.0.1,localhost` |
| `DJANGO_SECURE_SSL_REDIRECT` | HTTPS redirect | `False` |
| `DJANGO_JWT_COOKIE_SECURE` | Secure cookies | follows SSL redirect |
| `DJANGO_DOCS_PUBLIC` | Public API docs | `False` |
| `CORS_ALLOWED_ORIGINS` | CORS origins | — |
| `CORS_ALLOW_ALL_ORIGINS` | Allow all origins | `False` |
| `CSRF_TRUSTED_ORIGINS` | CSRF trusted origins | — |
| `THROTTLE_AUTH_RATE` | Login rate limit | `10/min` |
| `POSTGRES_DB/USER/PASSWORD/HOST/PORT` | Database | `sefro_clinic`/`postgres`/``/127.0.0.1/5432 |
| `CLINIC_ADMIN_USERNAME/PASSWORD` | Bootstrap admin | — |
| `FINANCE_DEFAULT_USD_TO_TOMAN_RATE` | Fallback rate | `100000` |
| `DJANGO_LOG_LEVEL` | Log level | `INFO` |

**Environments:**
- **Development**: `.env` with `DJANGO_DEBUG=True`, `DJANGO_DOCS_PUBLIC=True`, local Postgres or docker-compose.
- **Test**: CI sets test values; `TESTING` flag in settings disables throttling.
- **Production**: `DJANGO_DEBUG=False`, `SECURE_SSL_REDIRECT=True`, `DJANGO_DOCS_PUBLIC=False`, real secrets, Postgres, TLS termination at host (nginx/Caddy).

---

## 12. Development & Testing Commands

```bash
# Setup
pip install -r requirements-dev.txt
cp .env.example .env   # fill in values

# Run server
python manage.py runserver

# Docker
docker-compose up --build

# Tests
python manage.py test --noinput              # All tests
python manage.py test tests.finance          # Finance only
python manage.py test tests.security         # Security only
python manage.py test tests.unit             # Unit only
python manage.py test tests.integration      # Integration only
python manage.py test tests.e2e              # E2E only
SEFRO_PERF=1 python manage.py test tests.performance  # Performance

# Coverage
coverage run --source=accounts,customers,finance,inventory,logs,Sefro_Clinic,website manage.py test --noinput
coverage report --fail-under=80
coverage html

# Lint & Security
ruff check .
ruff check --fix .
bandit -q -r accounts customers finance inventory logs Sefro_Clinic website -x "**/migrations/*" -ll
pip-audit -r requirements.txt --no-deps

# Django
python manage.py check
python manage.py check --deploy
python manage.py makemigrations --check --dry-run
python manage.py migrate
python manage.py collectstatic --noinput
```

---

## 13. CI/CD & Deployment

**GitHub Actions Workflows:**

| Workflow | Trigger | Steps |
|----------|---------|-------|
| `tests.yml` | PR, push | ruff lint → full test suite on Postgres 16 (coverage ≥80%) → collectstatic → Docker build (push on master with secrets) |
| `security.yml` | PR, push, weekly (Mon 04:00) | bandit SAST (fails on medium+) → pip-audit → security test suite → gitleaks secret scan |

**Deployment:**
- Docker image built on push to `master` if `DOCKERHUB_USERNAME`/`DOCKERHUB_TOKEN` secrets configured.
- `docker-compose` for local/prod: Postgres + web (gunicorn on 127.0.0.1:8000).
- Host should run TLS termination (nginx/Caddy) in front.

---

## 14. Important Files

| File | Purpose |
|------|---------|
| `Sefro_Clinic/settings.py` | All configuration (DB, auth, DRF, Spectacular, CORS, throttling, logging) |
| `Sefro_Clinic/urls.py` | Root URL routing (legacy + v2 API, docs) |
| `Sefro_Clinic/docs.py` | Docs gating permission, English schema views |
| `finance/models.py` | All financial models (Wallet, Sale, Expense, ProductUsage, etc.) |
| `finance/services/wallet.py` | Wallet ledger operations (credit, debit, reward, reverse) |
| `finance/services/payments.py` | Checkout, refund, idempotency |
| `finance/services/expenses.py` | Expense state machine (self-approval forbidden) |
| `finance/services/inventory.py` | Product purchase/usage with cost snapshots |
| `finance/services/reporting.py` | Financial summary, profit by service/package, wallet summary |
| `finance/urls.py` | Finance API routes |
| `customers/models.py` | Customer, Service, Visit, Payment |
| `accounts/models.py` | ClinicUser (ADMIN/EMPLOYEE) |
| `accounts/authentication.py` | CookieJWTAuthentication (CSRF on unsafe methods) |
| `accounts/permissions.py` | IsAdmin, IsAdminOrReadOnly, CanManageVisits |
| `tests/helpers.py` | Test factories (make_admin, make_employee, clients) |
| `.env.example` | Required environment variables template |
| `docker-compose.yml` / `Dockerfile` | Container setup |

---

## 15. AI Coding Rules

**Before changing code:**
1. Read this `PROJECT_CONTEXT.md`.
2. Inspect the relevant existing implementation (models, services, views, tests).
3. Follow existing architecture: business logic in `services/`, thin views, Decimal for money.
4. Do not invent duplicate business logic — reuse service functions.
5. Do not weaken security/permissions to make tests pass.
6. Do not modify unrelated code (models, serializers, other apps).
7. Preserve financial integrity: `transaction.atomic`, `select_for_update`, DB constraints.
8. Use `Decimal` with `.quantize(Decimal('0.01'))` for all financial calculations.
9. Keep tests isolated: fresh customers/wallets per test; no shared mutable state.
10. Add regression tests for bug fixes.
11. Never expose secrets in code, logs, or commit history.
12. Prefer minimal, maintainable changes over refactoring.
13. Run `ruff check .` and relevant tests before considering done.

---

## 16. Known Issues / Important Notes

- **API docs require auth by default** — set `DJANGO_DOCS_PUBLIC=True` in `.env` for local development.
- **Root URL `/` returns 404** — project is API-only; no landing page defined (expected).
- **No Redis/cache layer** — all queries hit Postgres directly.
- **No background task queue** — all operations synchronous.
- **Shamsi date handling** uses `jdatetime`; serializers convert to/from Gregorian.
- **Two API schemas** (legacy + v2) are isolated; v2 schema excludes legacy endpoints (tested).
- **Finance ViewSets now have explicit `@extend_schema(tags=[...])`** matching `SPECTACULAR_SETTINGS.TAGS` (Finance, Wallet, Exchange Rates, Packages, Expenses, Reports).
- **Performance tests opt-in** via `SEFRO_PERF=1` env var.
- **Docker binds to 127.0.0.1:8000** — expects host reverse proxy for TLS.