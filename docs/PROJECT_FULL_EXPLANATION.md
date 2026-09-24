# Sefro Clinic — Complete Project Explanation

> **Audience:** developers, operators, and anyone onboarding onto this codebase.
> **Method:** this document was produced by a full evidence-based audit of the codebase
> (per `skills/django_api_full_audit_skill.md`): every statement below is traced from
> executable code — URLConfs → views → serializers → services → models → settings.
> Nothing is inferred from filenames alone.

---

## Table of Contents

1. [What This Project Is](#1-what-this-project-is)
2. [Technology Stack & Project Layout](#2-technology-stack--project-layout)
3. [Configuration & Environment](#3-configuration--environment)
4. [Authentication, Authorization & Security Model](#4-authentication-authorization--security-model)
5. [Data Model Reference](#5-data-model-reference)
6. [Complete API Endpoint Reference](#6-complete-api-endpoint-reference)
7. [Customer Workflow (End-to-End)](#7-customer-workflow-end-to-end)
8. [Financial Workflows (Checkout, Wallet, Refunds, Expenses, Payouts)](#8-financial-workflows)
9. [The Shamsi (Jalali) Calendar System](#9-the-shamsi-jalali-calendar-system)
10. [Audit Logging](#10-audit-logging)
11. [Testing, CI/CD & Deployment](#11-testing-cicd--deployment)
12. [Architectural Notes & Known Design Decisions](#12-architectural-notes--known-design-decisions)

---

## 1. What This Project Is

**Sefro Clinic** (سیستم مدیریت کلینیک زیبایی) is a production-grade REST backend for a beauty
clinic, built with **Django 5.2 + Django REST Framework**. It manages the complete business of
a clinic:

- **CRM** — customer records (with Persian national ID, mobile, Shamsi birthday)
- **Scheduling** — visits/appointments with overlap prevention and a lifecycle state machine
- **Service catalog** — services, categories, product "recipes" per service, packages
- **Finance** — dual-currency (USD authoritative + Toman derived) sales ledger, split
  payments, customer wallets with a rewards program, refunds, expenses with an approval
  pipeline, staff commission payouts
- **Inventory** — products, stock counts, purchase history, consumption tracking with
  historical cost snapshots
- **Exchange rates** — USD→Toman rate management with DB cache, optional external provider
  (Tindex) and backup provider (BrsApi.ir)
- **Public website API (v2)** — read-only catalog + contact intake for the clinic's public site
- **Audit trail** — automatic create/update/delete logging of every model change

There are **two parallel API surfaces**:

| Surface | Base path | Purpose | Docs |
|---|---|---|---|
| **Dashboard API (v1 "legacy")** | `/api/` | The internal clinic management dashboard (the main frontend consumes this) | `/api/docs/` |
| **Site API (v2)** | `/api/v2/` | Public website (barancliniccenter.com): catalog, team, testimonials, contact | `/api/v2/docs/` |

---

## 2. Technology Stack & Project Layout

### Stack

| Layer | Technology |
|---|---|
| Framework | Django 5.2, Django REST Framework ≥3.16 |
| Auth | `djangorestframework-simplejwt` (JWT in **HttpOnly cookies**, refresh rotation + blacklist) |
| API docs | `drf-spectacular` + sidecar (Swagger UI at `/api/docs/` and `/api/v2/docs/`) |
| Database | PostgreSQL 16 (via `psycopg2-binary`); `db.sqlite3` exists only as a local artifact |
| Password hashing | **Argon2id** (primary), PBKDF2 fallbacks |
| Calendar | `jdatetime` — the business runs on the **Shamsi (Jalali/Persian) calendar** |
| Server | gunicorn + whitenoise; Docker + docker-compose |
| Time zone / locale | `Asia/Tehran`, `fa-ir`, `USE_TZ=True` |

### Repository layout

```
Sefro_Clinic/
├── Sefro_Clinic/          # Project package (settings, root URLs, shared utils)
│   ├── settings.py        # All configuration (env-driven; refuses to boot without secrets)
│   ├── urls.py            # Root URLConf → mounts api_legacy + api_v2 + 2 schema/doc pairs
│   ├── api_legacy.py      # /api/ → accounts + customers + inventory + finance + logs
│   ├── api_v2.py          # /api/v2/ → public website API (website app)
│   ├── docs.py            # Schema/Swagger views gated by DocsAccessPermission
│   ├── fields.py          # ShamsiDateField / ShamsiDateTimeField serializer fields
│   └── validators.py      # TEXT_SANITIZERS (NUL-byte + Unicode-surrogate rejection)
├── accounts/              # ClinicUser, auth endpoints, permissions, bootstrap admin
├── customers/             # Customer, ServiceCategory, Service, Visit, Payment + legacy reports
├── finance/               # Sale/PaymentComponent, Wallet ledger, Expenses, Packages,
│   │                      #   ExchangeRate, StaffCompensation, ProductUsage/Purchase/CostHistory
│   └── services/          # Business-logic layer (checkout, wallet, accounting, reporting, ...)
├── inventory/             # Product catalog + stock count
├── logs/                  # AuditLog model, signals, thread-local user middleware
├── website/               # Public site models (SiteService, SitePackage, TeamMember, ...)
├── tests/                 # unit / integration / e2e / security / performance suites
├── docs/                  # This documentation (RUN_PROJECT.txt, SECURITY_TEST_MAP.md, ...)
├── skills/                # Agent skill definitions used for audits
├── Dockerfile, docker-compose.yml
└── requirements.txt / requirements-dev.txt
```

### App dependency graph

```
accounts  ──────────────► (auth, roles, permissions)
customers ──────────────► accounts (staff FK on Visit)
inventory ──────────────► (standalone Product)
finance   ──────────────► customers + inventory + accounts
logs      ──────────────► accounts (user FK, CookieJWTAuthentication)
website   ──────────────► (standalone, public site)
```

---

## 3. Configuration & Environment

`settings.py` is **fully env-driven** and fails fast: the app *refuses to start* without
`DJANGO_SECRET_KEY`, `CLINIC_ADMIN_USERNAME`, and `CLINIC_ADMIN_PASSWORD` (no insecure defaults).
Copy `.env.example` → `.env`. Key variables:

| Variable | Default | Purpose |
|---|---|---|
| `DJANGO_SECRET_KEY` | — (required) | Django secret |
| `DJANGO_DEBUG` | `False` | Debug mode (local only) |
| `DJANGO_ALLOWED_HOSTS` | `127.0.0.1,localhost` | Hosts |
| `DJANGO_SECURE_SSL_REDIRECT` | `False` | Enables HTTPS redirect + HSTS (1 year) + Secure cookies |
| `POSTGRES_DB/USER/PASSWORD/HOST/PORT` | `sefro_clinic` / `postgres` / — / `127.0.0.1` / `5432` | Database |
| `CLINIC_ADMIN_USERNAME` / `CLINIC_ADMIN_PASSWORD` | — (required) | **Bootstrap admin**, created once on first `migrate` (post-migrate signal); password must pass the full Django password policy |
| `JWT_ACCESS_TOKEN_LIFETIME` | `900` (15 min) | Access-token lifetime (seconds) |
| `JWT_REFRESH_TOKEN_LIFETIME` | `604800` (7 days) | Refresh-token lifetime |
| `DJANGO_JWT_COOKIE_SECURE` | follows SSL redirect | `Secure` flag on JWT cookies |
| `DJANGO_RETURN_TOKENS_IN_BODY` | `False` | If `True`, login/refresh also return tokens in the JSON body (dev/Swagger convenience) |
| `THROTTLE_AUTH_RATE` / `THROTTLE_CONTACT_RATE` / `THROTTLE_ANON_RATE` / `THROTTLE_USER_RATE` | `10/min` / `5/min` / `60/min` / `600/min` | DRF throttling (effectively disabled during tests) |
| `DJANGO_DOCS_PUBLIC` | `False` | If `True`, anonymous users may read API docs; otherwise login required |
| `CORS_ALLOWED_ORIGINS` / `CORS_ALLOW_ALL_ORIGINS` / `CSRF_TRUSTED_ORIGINS` | empty | CORS/CSRF; credentials allowed |
| `FINANCE_DEFAULT_USD_TO_TOMAN_RATE` | `100000` | Fallback exchange rate if no DB row exists (also seeded on first migrate) |
| `EXCHANGE_RATE_PROVIDER` | `database` | `database` = DB cache only; `external` = HTTP fetch (Tindex) + DB cache |
| `EXCHANGE_RATE_API_URL/API_KEY/TIMEOUT/CACHE_TTL` | Tindex URL / — / 5s / 3600s | Primary external provider config |
| `EXCHANGE_RATE_BACKUP_API_URL/API_KEY` | BrsApi URL / — | Backup provider (BrsApi.ir) |


---

## 4. Authentication, Authorization & Security Model

### 4.1 Users & roles

`accounts.ClinicUser` (extends `AbstractUser`) has exactly **two roles**:

| Role | Code | Capabilities |
|---|---|---|
| **Admin** | `admin` | Everything: employee management, catalog writes, finance config, expense approval, wallet adjustments, audit logs, all reports |
| **Employee** | `employee` | Day-to-day operations: customers, visits, checkout, consumption, own expenses, read most finance data |

Hard rules enforced in code (`ClinicUser.clean()`):
- **Only the configured bootstrap username** (`CLINIC_ADMIN_USERNAME`) may hold the admin role —
  you cannot promote another account to admin through any API.
- Employee endpoints (`/api/auth/employees/…`) query only `role=employee` rows, so the admin
  account is **hidden** from the employee API surface.
- Passwords are validated with Django's full validator chain and hashed with **Argon2id**.

### 4.2 JWT in HttpOnly cookies

Login (`POST /api/auth/token/`) returns SimpleJWT tokens and stores them in cookies:

| Cookie | Content | Flags |
|---|---|---|
| `access_token` | JWT access token (default 15 min) | `HttpOnly`, `SameSite=Lax`, `Path=/`, `Secure` when TLS enabled |
| `refresh_token` | JWT refresh token (default 7 days) | same |
| `csrftoken` | CSRF token (issued at login so SPA can send `X-CSRFToken`) | Django default |

`CookieJWTAuthentication` (`accounts/authentication.py`) authenticates in this order:
1. `Authorization: Bearer …` header (standard JWT), else
2. `access_token` cookie — and for **unsafe methods (POST/PUT/PATCH/DELETE) it enforces CSRF**
   via Django's `CsrfViewMiddleware` before accepting the cookie token.

Refresh tokens **rotate** (`ROTATE_REFRESH_TOKENS=True`) and the old one is **blacklisted**
(`BLACKLIST_AFTER_ROTATION=True`), so replay of a used refresh token is rejected. Logout
blacklists the presented/cookie refresh token and clears both cookies. Logout is deliberately
`AllowAny` so an expired session can always log out cleanly.

### 4.3 Permission classes (who can call what)

Defined in `accounts/permissions.py` + `finance/permissions.py`:

| Class | Rule |
|---|---|
| `IsAdmin` | authenticated **and** role = admin |
| `IsAdminOrReadOnly` | authenticated; safe methods for everyone, writes only for admin |
| `IsAdminOrEmployee` | authenticated admin or employee (used for Customers) |
| `IsEmployeeOrAdmin` (finance) | any authenticated staff user |
| `CanManageVisits` | any authenticated user (defined; visit endpoints currently use plain `IsAuthenticated`) |

### 4.4 Other security controls (all verified in code)

- **Throttling:** scoped `auth` rate on login/refresh (default 10/min/IP) against brute force;
  `contact` scope (5/min) on the public contact form; global anon 60/min and user 600/min.
- **Input sanitization:** every free-text model field uses `TEXT_SANITIZERS` = NUL-byte
  prohibition + Unicode surrogate rejection.
- **Docs gating:** `/api/docs/` and `/api/v2/docs/` require login unless `DJANGO_DOCS_PUBLIC=True`.
- **Transport:** `X_FRAME_OPTIONS='DENY'`, referrer policy `same-origin`; HSTS + SSL redirect +
  secure cookies when `DJANGO_SECURE_SSL_REDIRECT=True` (behind a TLS-terminating proxy,
  `SECURE_PROXY_SSL_HEADER` honors `X-Forwarded-Proto`).
- **Secrets:** nothing hard-coded; CI runs gitleaks + a secrets-hygiene test; `bandit` SAST and
  `pip-audit` dependency audit run in the Security workflow.
- **Pagination:** global `PageNumberPagination`, page size 20 (all list endpoints bounded).


---

## 5. Data Model Reference

Money design: **USD is the authoritative currency** for the financial system; **Toman** values
are derived using an exchange-rate snapshot stored on each record (`exchange_rate`,
`exchange_rate_snapshot`). Legacy display fields (`Service.price`, `Payment.amount`) are in
Toman for backward compatibility with the old dashboard.

### 5.1 accounts — `ClinicUser`

| Field | Notes |
|---|---|
| `username` | unique, sanitized |
| `role` | `admin` \| `employee` (only the configured bootstrap username may be admin) |
| `phone_number`, `first_name`, `last_name` | sanitized text |
| inherits | `password` (Argon2id), `is_active`, `date_joined`, … |

### 5.2 customers app

**`ServiceCategory`** — grouping for the service menu: `name` (unique), `slug` (unique),
`description`, `is_active`, `sort_order`.

**`Service`** — a bookable clinic service:
`name` (unique), `description`, `price` (legacy Toman display), **`price_usd` (authoritative)**,
`time` (duration minutes), `is_active`, `category` FK→ServiceCategory (SET_NULL),
`compensation_role` (`none`/`doctor`/`facial`/`laser`) — drives commission payouts.

**`Customer`** — the clinic client:
`first_name`, `last_name`, **`mobile_number` (unique)**, **`national_id` (unique)**,
`bitmoji_code` (unique, optional), `file_sys_id` (unique 40-char external file id, optional),
`birthday` (Shamsi date via API), `satisfaction` (1–5), `notes`, `created_at`.
Computed properties: `visit_count`, `is_new_customer` (0 visits), `is_loyal_customer` (≥5 visits),
`total_payments`, `last_visit_date` (Shamsi).

**`Visit`** — an appointment:
`customer` FK (CASCADE), `staff` FK→ClinicUser (SET_NULL), `services` M2M→Service,
`start_at`/`end_at`, `status` (`pending`→`confirmed`→`completed`, or `canceled`), `notes`.
Indexed for overlap checks (`customer, start_at, end_at`).

**`Payment`** — legacy payment record (Toman `amount` + optional `amount_usd`/`exchange_rate`
snapshots): `customer` FK, `visit` FK (SET_NULL), `payment_method`
(`cash`/`card`/`transfer`/`wallet`/`mixed`), `paid_at`, `notes`.
The checkout flow *also* writes here so old dashboard reports keep working.

### 5.3 inventory — `Product`

`name`, `sku` (unique, optional), `description`, `unit_price`, **`cost_usd`** (current
acquisition cost; history in `ProductCostHistory`), `count` (stock), `status`
(`available`/`less`/`finished`), `unit`.

### 5.4 finance app

| Model | Purpose / key fields |
|---|---|
| **`ExchangeRate`** | `currency_from→currency_to` (USD→TOMAN), `rate`, `effective_at`, `source`, `is_active`. Latest active row ≤ now wins |
| **`Wallet`** | One per customer (`OneToOne`). `balance` (USD) with **DB check constraint `balance ≥ 0`** |
| **`WalletTransaction`** | Immutable ledger entry: signed `amount`, `balance_after`, `transaction_type` (`reward`, `payment`, `refund`, `manual_credit`, `manual_debit`, `adjustment`, `expiration`, `reward_reverse`), `reference_type`+`reference_id` link to source. Constraints: amount ≠ 0, balance_after ≥ 0, **unique reward per reference**, **unique reward_reverse per reference** |
| **`WalletRewardRule`** | Cashback config: `rule_type` (`percentage`/`fixed`), `value`, `min_base_amount_usd`, validity `start_date`/`end_date`, `is_active` |
| **`ProductCostHistory`** | Time-ranged cost per product (`effective_from`/`effective_to`) for historical costing |
| **`ServiceItem`** | "Recipe": which `product` + `quantity` a service consumes (unique per service+product, qty > 0) |
| **`Package`** | Bundle sold at `price_usd`; contains services via `PackageService` and products via `PackageItem` |
| **`ProductUsage`** | Actual consumption record with `unit_cost_usd_snapshot`, `total_cost_usd_snapshot`, `exchange_rate_snapshot`; linked to visit/service/package_sale |
| **`Sale`** | Financial sale: `customer`, optional `visit`/`package`/`payment` FKs, `amount_usd`, `discount_usd`, `exchange_rate`, `amount_toman`, `status` (`pending`/`paid`/`refunded`/`partially_refunded`/`cancelled`), **`idempotency_key` (unique)** |
| **`PaymentComponent`** | Split payment line of a Sale: `method` (`cash`/`card`/`wallet`), `amount_usd`, optional `wallet_transaction` link |
| **`ExpenseCategory`** / **`Expense`** | Expense with approval pipeline: `status` (`draft`→`submitted`→`approved`/`rejected`→`paid`, or `cancelled`), `created_by`, `approved_by`, `amount_usd`/`amount_toman` snapshot, `receipt` file |
| **`ProductPurchase`** | Restock record; updates `Product.cost_usd` + `count` and closes/opens cost-history range |
| **`StaffCompensationRule`** | Per-role commission config (unique `role`): `calculation_type` (`percent_profit`/`fixed_per_session`/`monthly_salary`), `payout_type` (`cash`/`product`/`hybrid`), percent/fixed amounts, transport allowance, commission product+qty |
| **`StaffPayout`** | Generated per (visit, staff, service) — **unique constraint**; snapshots revenue/cost/profit in USD+Toman, cash and/or product payout, `status` (`pending`/`approved`/`paid`/`cancelled`), `payout_mode`, approval fields |

### 5.5 logs — `AuditLog`

`user` (SET_NULL), `action` (`CREATE`/`UPDATE`/`DELETE`), `model_name`, `object_id`,
`object_repr`, `changes` (JSON snapshot of all concrete fields except the PK and `password`),
`timestamp`. See §10.

### 5.6 website app (public site, API v2)

| Model | Purpose |
|---|---|
| **`SiteService`** | Public service catalog: `slug`, `category` (`face`/`skin`/`hair`/`body`), `price`, `duration_label`, `image_url`, `is_active`, `sort_order` |
| **`SitePackage`** | Public bundles: `tier` (`base`/`standard`/`special`), `price`/`original_price` → computed `discount_percent`, `free_service_count`, M2M `services` |
| **`SiteProduct`** | Public skincare product catalog |
| **`TeamMember`** / **`Testimonial`** | Specialists and customer testimonials |
| **`ContactMessage`** | Public consultation intake: `full_name`, `phone` (Iranian mobile `^09\d{9}$`), `message`, `is_handled` |


---

## 6. Complete API Endpoint Reference

Conventions: all list endpoints are paginated (20/page, `?page=`). Unless noted, auth = JWT
cookie (`access_token`) or `Authorization: Bearer <token>`. **All dates accepted/returned by the
dashboard API are Shamsi (Jalali) strings** unless marked *Gregorian*.

### 6.1 API documentation & schema

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/api/schema/` | Login (or public if `DJANGO_DOCS_PUBLIC=True`) | OpenAPI 3 JSON for the dashboard API |
| GET | `/api/docs/` | same | Swagger UI for the dashboard API |
| GET | `/api/v2/schema/` | same | OpenAPI 3 JSON for the site API |
| GET | `/api/v2/docs/` | same | Swagger UI for the site API |

### 6.2 Authentication & employees — `/api/auth/`

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/api/auth/token/` | Public, throttled (`auth` scope) | Login `{username, password}` → sets `access_token`/`refresh_token` HttpOnly cookies + `csrftoken`; body tokens only if `DJANGO_RETURN_TOKENS_IN_BODY=True` |
| POST | `/api/auth/token/refresh/` | Public (refresh cookie/body), throttled | Rotates tokens; old refresh blacklisted; cookies re-set |
| POST | `/api/auth/logout/` | Public | Blacklists refresh token, clears cookies → `{"detail": "Logged out."}` |
| GET | `/api/auth/me/` | Any staff | Current user `{id, username, role, date_joined(Shamsi)}` |
| POST | `/api/auth/employees/` | **Admin** | Create employee `{username, password, first_name, last_name, phone_number}` (password policy enforced; role forced to `employee`) |
| GET | `/api/auth/employees/list/` | **Admin** | List employees (admin account never appears) |
| GET | `/api/auth/employees/{id}/` | Any staff | Employee detail |
| PUT/PATCH | `/api/auth/employees/{id}/` | **Admin** | Update employee incl. optional password reset |
| DELETE | `/api/auth/employees/{id}/` | **Admin** | Delete employee |

### 6.3 Dashboard & legacy reports — `/api/` (customers app)

All require authentication. `date_from`/`date_to` query params are **Shamsi** `YYYY-MM-DD`.

| Method | Path | Description |
|---|---|---|
| GET | `/api/dashboard/` | KPI cards: `customer_count`, `loyal_customer_count` (≥5 visits), `today_sales` (Toman), `today_visits`, `new_customers` — "today" = current Shamsi day |
| GET | `/api/reports/` | Combined report: sales charts bucketed by Shamsi **daily/weekly/monthly/quarterly/yearly** + `total_sales`, `avg_satisfaction`, `service_popularity`, `total_visits`, `customer_breakdown` |
| GET | `/api/reports/daily/` | Current Shamsi day: per-day sales chart, total, visit count |
| GET | `/api/reports/weekly/` | Current Shamsi week (Saturday-start): per-day chart, total, visits |
| GET | `/api/reports/monthly/` | Current Shamsi month: per-day chart, total, visits |
| GET | `/api/reports/quarterly/` | Current Shamsi quarter (`YYYY-Qn`): per-month chart, total, visits |
| GET | `/api/reports/yearly/` | Current Shamsi year: per-month chart, total, visits |
| GET | `/api/reports/all/` | All-time: full 5-bucket sales chart, totals, satisfaction avg, service popularity, visit-status breakdown |
| GET | `/api/reports/visits/` | Visit count in range + previous equal-length period + `change_percent` |
| GET | `/api/reports/customers/` | `by_visit_status`, `new_customers` (0 visits), `loyal_customers` (≥5), `total` |
| GET | `/api/reports/referral/` | `total_visits`, `total_customers`, `returning_customers` (≥2 visits), `referral_rate` % |
| GET | `/api/reports/exchange-dollar/` | Current USD→Toman rate (+optional `?usd=` / `?amount=` conversion). 503 if no rate configured |
| GET | `/api/reports/backup-exchange/` | Same, but fetched live from the **BrsApi backup provider** |

### 6.4 Customers — `/api/customers/` (IsAdminOrEmployee)

| Method | Path | Description |
|---|---|---|
| GET | `/api/customers/` | List; `?search=` across name/mobile/national_id/bitmoji/file_sys_id; `?ordering=first_name,last_name,created_at,num_visits`. Rows annotated with `visit_number`, `total_payments`, `last_visit_date`, `is_new_customer`, `is_loyal_customer` |
| POST | `/api/customers/` | Create: `first_name, last_name, mobile_number*, national_id* (*unique), birthday (Shamsi), bitmoji_code, file_sys_id, satisfaction (1-5), notes` |
| GET/PUT/PATCH/DELETE | `/api/customers/{id}/` | Retrieve / update / delete |

### 6.5 Service catalog — `/api/service-categories/`, `/api/services/`

| Method | Path | Auth | Description |
|---|---|---|---|
| GET/POST | `/api/service-categories/` | read: staff / write: **admin** | Category list+create; search `name,slug,description`; ordering incl. `sort_order` |
| GET/PUT/PATCH/DELETE | `/api/service-categories/{id}/` | same | Delete is **blocked (400)** while services exist in the category — deactivate instead |
| GET/POST | `/api/services/` | any staff | Service catalog. Filters: `?category=<id or slug>`, `?is_active=true/false`, `?search=` (name/description/category). Response adds computed fields: `price_toman`, `exchange_rate`, `products[]` (recipe with unit costs), `estimated_cost_usd/toman`, `estimated_gross_profit_usd/toman`, `estimated_margin_percent` |
| GET/PUT/PATCH/DELETE | `/api/services/{id}/` | any staff | Detail; writable fields incl. `price_usd`, `time`, `compensation_role`, `category_id` |


### 6.6 Visits — `/api/visits/` (any authenticated staff)

| Method | Path | Description |
|---|---|---|
| GET | `/api/visits/` | List. Filters: `?status=pending/confirmed/completed/canceled`, `?year=&month=` (Shamsi), `?date_from=&date_to=` (Shamsi); `?search=` across customer name/mobile, notes, status |
| POST | `/api/visits/` | Create visit `{customer, services[], start_at, end_at (Shamsi "YYYY-MM-DD HH:MM"), notes}`. Validation: `end_at ≥ start_at`; **overlap check** — same customer cannot have two visits whose time ranges intersect while status is pending/confirmed/completed |
| GET/PUT/PATCH/DELETE | `/api/visits/{id}/` | Retrieve / update (same overlap validation) / delete |
| POST | `/api/visits/{id}/confirm/` | `pending → confirmed` |
| POST | `/api/visits/{id}/complete/` | `→ completed` **and auto-generates staff commission payouts** (see §8.5) |
| POST | `/api/visits/{id}/cancel/` | `→ canceled` |
| POST | `/api/visits/reserve/` | Simplified booking: `{customer: id, services: [ids], date: "Shamsi YYYY-MM-DD", time: "HH:MM", notes?}` → creates a **pending** visit whose `end_at = start_at + Σ service.time` |

### 6.7 Payments (legacy) — `/api/payments/`

| Method | Path | Description |
|---|---|---|
| GET | `/api/payments/` | List; search customer name/id/mobile; ordering `paid_at, amount, payment_method` |
| POST | `/api/payments/` | Record a payment directly `{customer, visit?, amount (Toman), payment_method, paid_at (Shamsi), notes}` |
| GET/PUT/PATCH/DELETE | `/api/payments/{id}/` | Retrieve / update / delete |
| GET | `/api/payments/by_service/` | Aggregate payment totals per service; `?date_from=&date_to=` (Shamsi) |

### 6.8 Inventory — `/api/inventory/products/` (any authenticated staff)

| Method | Path | Description |
|---|---|---|
| GET | `/api/inventory/products/` | List; `?search=` by name |
| POST | `/api/inventory/products/` | Create `{name, sku?, description, unit_price, cost_usd, count, status, unit}` |
| GET/PUT/PATCH | `/api/inventory/products/{id}/` | Retrieve / update |
| DELETE | `/api/inventory/products/{id}/` | 400 if the product is referenced by a service recipe (ProtectedError → "Deactivate it instead") |

### 6.9 Finance — `/api/finance/`

**Actions**

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/api/finance/checkout/` | staff | **The cash register.** Body: `{customer, amount_usd, components: [{method: cash\|card\|wallet, amount_usd}...], discount_usd?, visit?, package?, idempotency_key?, description?}`. Components must sum exactly to `amount_usd`. Atomically creates the `Sale` (+ components, + legacy `Payment` rows for cash/card, + wallet debit, + reward credit). Idempotent via `idempotency_key`. See §8.1 |
| POST | `/api/finance/visits/{id}/record-consumption/` | staff | Record actual product consumption for a visit; optional `{selected_products: {"<service_id>": [[product_id, qty], ...]}}`; falls back to each service's configured `ServiceItem` recipe. Returns created `ProductUsage` rows with cost snapshots |
| POST | `/api/finance/sales/{id}/refund/` | staff | Refund a **paid** sale: `{refund_amount_usd?, reason?}` (default = full). Creates a negative refund `Sale`, refunds the wallet portion to the wallet, reverses the unspent part of the reward. Exactly one refund per sale. See §8.3 |
| POST | `/api/finance/wallets/{id}/adjust/` | **admin** | Manual wallet adjustment `{amount_usd, direction: credit\|debit, transaction_type: manual_credit\|manual_debit\|adjustment, description?}` |

**Finance reports** (all staff; `start_date`/`end_date` are **Gregorian** `YYYY-MM-DD`; `period`
shortcut: `today`, `this_week`, `this_month`, `prev_month`):

| Method | Path | Description |
|---|---|---|
| GET | `/api/finance/reports/financial-summary/` | Revenue, product cost, gross/net profit (USD+Toman), expenses, avg transaction, payment-method breakdown, wallet totals; filters `service, package, product, personnel` |
| GET | `/api/finance/reports/profit-by-service/` | Profit & margin per service |
| GET | `/api/finance/reports/profit-by-package/` | Profit & margin per package |
| GET | `/api/finance/reports/profit-by-staff/` | Revenue/cost/profit per staff member across completed visits |
| GET | `/api/finance/reports/wallet-summary/` | Wallet liability, rewards issued/reversed, wallet payments/refunds |
| GET | `/api/finance/reports/staff-payout-summary/` | Payout totals; filters `staff`, `role` |
| GET | `/api/finance/reports/dashboard/` | The finance dashboard: sales summary, expenses, net profit, payout totals, wallet summary, operational metrics (completed visits, new customers, avg ticket), payment-method breakdown |


**Finance CRUD viewsets** (all under `/api/finance/`)

| Resource | Type | Auth | Notes |
|---|---|---|---|
| `exchange-rates/` | CRUD | read: staff / write: **admin** | Configure USD→TOMAN rates; latest active `effective_at ≤ now` wins |
| `reward-rules/` | CRUD | read: staff / write: **admin** | Wallet cashback rules |
| `packages/` | CRUD | read: staff / write: **admin** | Response includes `price_toman`, `exchange_rate`, `services[]`, `items[]` |
| `service-items/` | CRUD | read: staff / write: **admin** | Service→product recipe; qty > 0; rejects `finished` products |
| `package-items/` | CRUD | read: staff / write: **admin** | Package→product lines |
| `package-services/` | CRUD | read: staff / write: **admin** | Package→service lines |
| `product-cost-history/` | read-only | staff | Historical product costs |
| `product-usages/` | read-only | staff | Filters: `?visit=`, `?service=`, `?product=`, `?package_sale=` |
| `wallets/` | read-only + `adjust` | staff (adjust: admin) | Search by customer name/mobile |
| `wallet-transactions/` | read-only | staff | Ledger; `?wallet=` filter |
| `sales/` | read-only + `refund` | staff | Filters: `?customer=`, `?status=`, `?package=` |
| `expense-categories/` | CRUD | read: staff / write: **admin** | |
| `expenses/` | CRUD + workflow | staff | **Employees only see their own expenses**; create ⇒ `draft`. Actions below |
| `product-purchases/` | CRUD | read: staff / write: **admin** | Creating a purchase updates `Product.cost_usd` + `count` and rolls `ProductCostHistory` |
| `staff-compensation-rules/` | CRUD | **admin only** | Commission rules per role |
| `staff-payouts/` | read-only | staff | Filters `?staff= ?role= ?status= ?visit=`; plus `GET staff-payouts/summary/` and `GET staff-payouts/detail_report/` |

**Expense workflow actions** (on `/api/finance/expenses/{id}/`):

| Action | Auth | Transition |
|---|---|---|
| `POST …/submit/` | staff (owner) | `draft → submitted` |
| `POST …/approve/` | **admin** (cannot approve own) | `submitted → approved` |
| `POST …/reject/` | **admin** (cannot reject own) | `submitted → rejected` |
| `POST …/pay/` | **admin** | `approved → paid` |
| `POST …/cancel/` | owner or admin | any non-paid state → `cancelled` |

### 6.10 Audit logs — `/api/logs/`

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/api/logs/` | **admin** | Audit trail; `?search=` across `model_name, action, object_repr, user__username`; `?ordering=timestamp` |
| GET | `/api/logs/{id}/` | **admin** | Single entry |

### 6.11 Site API v2 — `/api/v2/` (public website)

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/api/v2/site/info/` | staff | `{name, version}` health/info probe |
| GET | `/api/v2/services/` | **public** | Active site services; `?category=face\|skin\|hair\|body` |
| GET | `/api/v2/services/{slug}/` | **public** | Service detail (slug lookup) |
| GET | `/api/v2/packages/` + `/{slug}/` | **public** | Active packages incl. nested services + `discount_percent` |
| GET | `/api/v2/products/` + `/{slug}/` | **public** | Active skincare products |
| GET | `/api/v2/team/` | **public** | Active team members (unpaginated) |
| GET | `/api/v2/testimonials/` | **public** | Active testimonials (unpaginated) |
| POST | `/api/v2/contact/` | **public**, throttled (`contact` scope, 5/min) | Consultation intake `{full_name, phone (Iranian mobile 09xxxxxxxxx), message}` |

> DRF `DefaultRouter` also exposes API-root index views at `/api/`, `/api/finance/`,
> `/api/inventory/`, and `/api/v2/`.


---

## 7. Customer Workflow (End-to-End)

This is the full journey of a customer through the clinic, and the exact API calls behind each
step. Actors: **Admin** (owner) and **Employee** (front desk / practitioner).

### Phase 0 — Staff onboarding (one-time, Admin)

```
Admin: POST /api/auth/token/           → login (cookies set)
Admin: POST /api/auth/employees/       → create each employee account
```

The bootstrap admin itself is created automatically on the first `migrate` from
`CLINIC_ADMIN_USERNAME`/`CLINIC_ADMIN_PASSWORD` (password policy enforced).

### Phase 1 — Catalog setup (Admin)

```
Admin: POST /api/service-categories/         → e.g. "پوست" (skin), "مو" (hair)
Admin: POST /api/services/                   → name, price_usd, time (minutes),
                                               compensation_role (doctor/facial/laser/none)
Admin: POST /api/inventory/products/         → products with cost_usd and stock count
Admin: POST /api/finance/service-items/      → "recipe": service X consumes qty of product Y
Admin: POST /api/finance/packages/ (+ package-services/, package-items/)  → bundles
```

### Phase 2 — Finance setup (Admin)

```
Admin: POST /api/finance/exchange-rates/             → current USD→Toman rate
Admin: POST /api/finance/reward-rules/               → wallet cashback rule (e.g. 5% over $50)
Admin: POST /api/finance/staff-compensation-rules/   → per-role commission config
Admin: POST /api/finance/expense-categories/         → rent, supplies, ...
```

### Phase 3 — Customer registration (Employee or Admin)

```
POST /api/customers/
{ "first_name": "...", "last_name": "...", "mobile_number": "0912...",
  "national_id": "...", "birthday": "1375-06-15" (Shamsi), "notes": "..." }
```
Uniqueness is enforced on `mobile_number`, `national_id`, `bitmoji_code`, `file_sys_id`.

### Phase 4 — Booking a visit

Two paths:
```
Simple:  POST /api/visits/reserve/
         { "customer": 12, "services": [3, 7], "date": "1404-07-01", "time": "14:30" }
         → end time auto-computed from total service minutes; status = pending

Full:    POST /api/visits/  { customer, services[], start_at, end_at (Shamsi), notes }
```
Double-booking the **same customer** in an overlapping time range is rejected with a Persian
validation message: «این بازه زمانی با ویزیت دیگری از همین مشتری تداخل دارد.»

### Phase 5 — Visit lifecycle (state machine)

```
pending ──confirm()──► confirmed ──complete()──► completed
   │                      │
   └──────cancel()────────┴────────────────────► canceled
```
- `POST /api/visits/{id}/confirm/` — front desk confirms attendance.
- `POST /api/visits/{id}/complete/` — service delivered. **Side effect:**
  `staff_compensation.generate_visit_payouts()` runs — for each service with a non-`none`
  `compensation_role` and a matching active `StaffCompensationRule`, a `StaffPayout`
  (`pending`) is created (idempotent via `update_or_create` + unique constraint). For
  `product`/`hybrid` rules, the commission product is also recorded as consumed stock.
- `POST /api/visits/{id}/cancel/` — cancels at any point.
- Note: the actions set the status directly; there is no transition guard rejecting e.g.
  `canceled → confirmed` — discipline is procedural.

### Phase 6 — Consumption recording (cost tracking)

```
POST /api/finance/visits/{id}/record-consumption/
{ "selected_products": { "3": [[5, 1.5]] } }   # optional override
```
Creates `ProductUsage` rows with **historical cost snapshots** (from `ProductCostHistory`).
Default = the service's configured recipe. (Stock `count` is decremented only for
commission-type usage and by purchases; see §8.6.)

### Phase 7 — Checkout / payment

```
POST /api/finance/checkout/
{ "customer": 12, "visit": 88, "amount_usd": "120.00",
  "components": [{"method": "cash", "amount_usd": "70"},
                 {"method": "wallet", "amount_usd": "50"}],
  "idempotency_key": "visit-88-checkout" }
```
Everything happens in **one DB transaction** (see §8.1). The customer may split payment
across cash/card/wallet. Wallet rewards are credited automatically.

### Phase 8 — After the sale

- **Refund:** `POST /api/finance/sales/{id}/refund/` (full or partial, once per sale).
- **Wallet top-up/deduction:** `POST /api/finance/wallets/{id}/adjust/` (admin).
- **Expenses:** employees submit, admin approves/pays (§8.4).
- **Payouts:** admin reviews generated `StaffPayout` rows (API is read-only; status changes
  happen via the Django admin panel) and reports via `staff-payouts/summary/`.
- **Reporting:** legacy Shamsi reports under `/api/reports/*` and finance (Gregorian) reports
  under `/api/finance/reports/*`.

### Public-website journey (no login)

```
Visitor: GET /api/v2/services/ (?category=face)  → browses catalog
         GET /api/v2/packages/                    → sees bundles & discounts
         GET /api/v2/products/  /team/  /testimonials/
         POST /api/v2/contact/ {full_name, phone 09xxxxxxxxx, message}  → consultation request
Staff:   reads ContactMessage rows via the Django admin (no API exposure) and calls back
```


---

## 8. Financial Workflows

The `finance/services/` package is the business-logic layer; views stay thin and delegate.

### 8.1 Checkout (`finance/services/payments.py::checkout`) — atomic sale

`@transaction.atomic`, exact sequence:

1. **Validate** — `amount_usd ≥ 0`, at least one component, `Σ components == amount_usd`.
2. **Resolve rate** — explicit or latest active `ExchangeRate` (fallback: `FINANCE_DEFAULT_USD_TO_TOMAN_RATE`).
3. **Idempotency** — if `idempotency_key` matches an existing `Sale`, return it unchanged
   (unique constraint on the column). Safe against double-clicks/retries.
4. **Wallet pre-check** — if a `wallet` component exists, the wallet row is locked with
   `SELECT … FOR UPDATE` and `InsufficientFunds` raised if balance < required.
5. **Create `Sale`** (status `paid`, USD + Toman snapshot at the resolved rate).
6. **Per component:** `wallet` → wallet `debit()` (ledger txn `payment`, linked);
   `cash`/`card` → also writes a **legacy `customers.Payment`** row (Toman `amount`,
   USD + rate snapshot) so old dashboard reports remain consistent. Then a
   `PaymentComponent` row per component.
7. **Reward** — `grant_reward()` evaluates active `WalletRewardRule`s (percentage or fixed,
   min-base threshold, validity dates) and credits the wallet (ledger txn `reward`,
   unique per sale → never double-granted).

### 8.2 Wallet ledger (`finance/services/wallet.py`)

- `credit()` / `debit()` / `manual_adjust()` all funnel into `_apply()`, which locks the wallet
  row (`select_for_update`), computes `balance_after`, enforces non-negativity, and writes an
  immutable `WalletTransaction`.
- **DB-level invariants:** balance ≥ 0, txn amount ≠ 0, balance_after ≥ 0, one reward and one
  reward-reversal per (reference_type, reference_id).
- `reverse_reward()` only claws back the **unspent** portion of a reward, preserving ledger
  integrity when the customer already spent part of it.

### 8.3 Refunds (`payments.py::refund_sale`)

- Only `paid` sales are refundable, and **exactly once**: a partially refunded sale becomes
  `partially_refunded` and can never enter the refund path again (refund sales carry no
  back-reference, so cumulative totals couldn't be recomputed safely — this is a deliberate
  guard documented in the code).
- Creates a **negative `Sale`** (`amount_usd = -refund`, status `refunded`).
- Wallet portion (up to the refund amount) is credited back to the wallet (txn `refund`);
  the sale's reward is reversed for its unspent portion (txn `reward_reverse`).
- Original sale becomes `refunded` (full) or `partially_refunded`.

### 8.4 Expense pipeline (`finance/services/expenses.py`)

```
draft ──submit──► submitted ──approve──► approved ──pay──► paid
   │                  │                      │
   │                  └────reject────────► rejected
   └────────────── cancel (from any non-paid state) ──► cancelled
```
Guards: transitions validated by `_require_status`; **self-approval/rejection blocked**
(`You cannot approve your own expense`); cancel forbidden once `paid`. Employees' list view is
scoped to their own expenses; admins see all. Only `approved`/`paid` expenses count in reports.

### 8.5 Staff compensation (`finance/services/staff_compensation.py`)

- Triggered by visit completion. `calculate_visit_profit()` sums service `price_usd` minus
  recipe product costs (current `cost_usd`), converted with the current rate.
- `calculate_service_payout()` applies the role's rule: `percent_profit` (% of visit profit)
  or `fixed_per_session` (USD or Toman), plus transport allowance; `product`/`hybrid` rules add
  a product payout whose value is snapshotted and whose stock is decremented as commission usage.
- `StaffPayout` rows are idempotent per (visit, staff, service). Lifecycle
  `pending → approved → paid` (or `cancelled`) is managed via the Django admin panel; the API
  exposes read/report endpoints only.
- Reports: `staff_payout_summary()` (totals per period/staff/role) and `staff_payout_detail()`
  (per-payout rows).

### 8.6 Inventory costing (`finance/services/inventory.py`)

- `record_product_purchase()` — atomic: creates `ProductPurchase`, sets `Product.cost_usd` to
  the new unit cost, increments `Product.count`, closes the open `ProductCostHistory` range and
  opens a new one effective from the purchase date.
- `record_product_usage()` — snapshots `current_cost()` (from cost history, else current cost)
  into `ProductUsage`. Stock `count` is decremented **only** for commission payouts
  (`is_commission=True`, floored at 0); treatment consumption is tracked for costing without
  mutating the retail stock counter.

### 8.7 Exchange rates (`finance/services/exchange_rates.py`)

- `get_rate()` — legacy: latest active DB row ≤ now, else `FINANCE_DEFAULT_USD_TO_TOMAN_RATE`
  (validated positive; hard floor 100000).
- `get_current_usd_to_toman_rate()` — DB cache; when `EXCHANGE_RATE_PROVIDER=external` and the
  cache is stale (`CACHE_TTL`), fetches the primary provider (Tindex), then the **BrsApi backup**,
  caching successful results as new `ExchangeRate` rows. Returns `None` if everything fails
  (callers expose `null`/503 rather than a wrong rate).
- A `post_migrate` signal seeds a default rate row on first migrate.


---

## 9. The Shamsi (Jalali) Calendar System

The clinic operates on the Persian calendar (`jdatetime`, `TIME_ZONE=Asia/Tehran`).
**Two date dialects exist — do not mix them:**

| Surface | Format | Where |
|---|---|---|
| Dashboard/customer-facing API | **Shamsi** strings | `birthday`, `Visit.start_at/end_at`, `Payment.paid_at`, `Customer.created_at`, audit `timestamp`, all `/api/reports/*` params & buckets, `/api/visits/` filters, `/api/customers/` payloads |
| Finance reports | **Gregorian** `YYYY-MM-DD` | `/api/finance/reports/*` (`start_date`/`end_date`, or `period=today/this_week/this_month/prev_month`) |

Mechanics (`Sefro_Clinic/fields.py`):
- `ShamsiDateField` / `ShamsiDateTimeField` convert inbound Shamsi → aware Gregorian datetimes
  for storage, and outbound Gregorian → Shamsi strings (`%Y-%m-%d`, `%Y-%m-%d %H:%M`).
- Report bucketing (`_shamsi_period_key`, `_shamsi_period_range`, `_build_sales_chart`)
  converts each payment's `paid_at` to Shamsi and buckets by day / Saturday-start week /
  month / quarter (`YYYY-Qn`) / year.

## 10. Audit Logging

- `logs/signals.py` listens to **`post_save` and `post_delete` for every model** (except
  `AuditLog` itself and SimpleJWT token bookkeeping tables) and writes an `AuditLog` row:
  user, action, `app.model`, object id, repr, and a JSON snapshot of all concrete field values
  (PK and `password` excluded — credentials never enter the audit trail).
- The acting user comes from `RequestUserMiddleware`, which resolves the caller per request
  (session or `CookieJWTAuthentication`) into a thread-local. System/migration writes are
  recorded with `user = NULL` (shown as `system` in the API).
- Audit writes are fail-safe: during migrations (table not yet created, PG code `42P01`) they
  are skipped silently; other errors go to stderr, never breaking the business operation.
- Reading the trail: `GET /api/logs/` (admin only), searchable & ordered by timestamp.

## 11. Testing, CI/CD & Deployment

### Test suites (`python manage.py test --noinput`)

| Suite | Location | Covers |
|---|---|---|
| Unit | `tests/unit/` | Shamsi conversion, period keys, currency, service pricing, exchange-rate helpers |
| Integration | `tests/integration/` | reports, dashboard, payment aggregation, DB constraints, visit overlap |
| E2E | `tests/e2e/` | full visit cycle: reserve → confirm → complete → pay → audit-trail integrity |
| Security | `tests/security/` | auth (forgery/replay/brute-force), authorization/IDOR, CSRF, headers/cookies, injection/XSS, secrets hygiene, docs gating |
| Performance | `tests/performance/` | smoke/stress/spike (only with `SEFRO_PERF=1`) |

Coverage gate: `--fail-under=90`. `docs/SECURITY_TEST_MAP.md` maps every OWASP Top-10 category
to its tests and records three **owner-accepted risks**: plaintext PII at rest, employee read
access to payment aggregates, and optional tokens-in-body (disable via
`DJANGO_RETURN_TOKENS_IN_BODY=False` once the frontend is cookie-only).

### CI/CD (GitHub Actions)

- **Tests workflow:** ruff lint → full suite on PostgreSQL 16 → coverage ≥ 90% → Docker build.
- **Security workflow:** bandit (SAST), pip-audit (dependencies), gitleaks (secrets), weekly.

### Deployment

- `Dockerfile` + `docker-compose.yml`: `postgres:16` (healthchecked) + `web` (gunicorn,
  whitenoise statics), bound to `127.0.0.1:8000` — put nginx/Caddy with TLS in front and set
  `DJANGO_SECURE_SSL_REDIRECT=True` + `DJANGO_JWT_COOKIE_SECURE=True`.
- Local run: see `docs/RUN_PROJECT.txt` (`py manage.py migrate && runserver`, then
  `/api/docs/`).


---

## 12. Architectural Notes & Known Design Decisions

These are deliberate (or simply factual) characteristics discovered during the audit — useful
to know before extending the system:

1. **Dual payment representation.** Checkout writes both the financial ledger
   (`Sale` + `PaymentComponent`, USD-authoritative) *and* the legacy `customers.Payment` table
   (Toman) for backward compatibility with the old dashboard reports. Payments created directly
   via `POST /api/payments/` do **not** create a `Sale` — the two write paths are asymmetric.
2. **Two dashboards.** `/api/dashboard/` (Shamsi, customer-centric KPIs, Toman) and
   `/api/finance/reports/dashboard/` (Gregorian, USD+Toman financial aggregates) serve different
   frontends.
3. **Two calendars.** Dashboard = Shamsi; finance reports = Gregorian (see §9). Period math for
   the Shamsi reports is done in Python (`jdatetime`), not SQL.
4. **Visit status transitions are not guarded** — `confirm`/`complete`/`cancel` set the status
   unconditionally; business discipline is procedural. Payout generation *is* guarded
   (`generate_visit_payouts` no-ops unless status is `completed`).
5. **Staff payout approval has no API** — `StaffPayoutViewSet` is read-only; approve/pay via
   Django admin. Contact messages are likewise admin-panel-only (write-only public intake).
6. **Stock count vs. consumption** — `Product.count` changes only on purchases and commission
   payouts; visit consumption is cost-tracked via `ProductUsage` snapshots without decrementing
   the counter.
7. **Legacy price field.** `Service.price` (Toman) is kept as a display value; `price_usd` is
   authoritative for all finance math.
8. **Rate fallback policy.** If no exchange rate is configured, the system uses
   `FINANCE_DEFAULT_USD_TO_TOMAN_RATE` (default 100000) and seeds it on migrate — reports
   remain computable, but you should configure a real rate.
9. **Admin uniqueness by policy** — there is exactly one admin (the configured bootstrap
   account); the model layer rejects any other admin-role assignment.
10. **No outbound HTTP except exchange rates** — the only network egress is the optional
    exchange-rate providers, so SSRF surface is minimal (OWASP A10 marked N/A).

---

*Document generated from a full source audit (routing → views → serializers → services →
models → settings → tests). Last verified against branch `master`.*

