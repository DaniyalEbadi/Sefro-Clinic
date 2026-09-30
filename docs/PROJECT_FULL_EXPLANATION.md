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
- **Welcome packs** — product gift bundles issued to customers with immutable cost snapshots
- **Operating expenses** — direct clinic running costs (rent, supplies, …), a separate domain
  from the employee expense-claim pipeline
- **Face AI Analyzer** — public face-photo analysis (aesthetic scores, attributes, beauty
  suggestions, regenerable skin-care plan) + staff analysis history
- **Public website API (v2)** — read-only catalog + contact intake for the clinic's public site
- **Audit trail** — automatic create/update/delete logging of every model change

There are **three parallel API surfaces**:

| Surface | Base path | Purpose | Docs |
|---|---|---|---|
| **Dashboard API (v1 "legacy")** | `/api/` | The internal clinic management dashboard (the main frontend consumes this) | `/api/docs/` |
| **Site API (v2)** | `/api/v2/` | Public website (barancliniccenter.com): catalog, team, testimonials, contact | `/api/v2/docs/` |
| **Face AI Analyzer API (v3)** | `/api/v3/` | Public face analysis + skin-care plans; staff analysis history | `/api/v3/docs/` |

> The Django admin site is **not installed and not routed** (`django.contrib.admin` is absent
> from `INSTALLED_APPS`, no `admin/` URL exists — a security test asserts `/admin/` → 404).
> Everything is operated through the three API surfaces above.

---

## 2. Technology Stack & Project Layout

### Stack

| Layer | Technology |
|---|---|
| Framework | Django 5.2, Django REST Framework ≥3.16 |
| Auth | `djangorestframework-simplejwt` (JWT in **HttpOnly cookies**, refresh rotation + blacklist) |
| API docs | `drf-spectacular` + sidecar (Swagger UI at `/api/docs/`, `/api/v2/docs/`, `/api/v3/docs/`) |
| Database | PostgreSQL 16 (via `psycopg2-binary`); `db.sqlite3` exists only as a local artifact |
| Password hashing | **Argon2id** (primary), PBKDF2 fallbacks |
| Calendar | `jdatetime` — the business runs on the **Shamsi (Jalali/Persian) calendar** |
| Face AI | MediaPipe local pipeline (default) or an external HTTP analyzer; skin-care tips rule-based (default) or LLM (OpenAI/Anthropic) |
| Server | gunicorn + whitenoise; Docker + docker-compose |
| Time zone / locale | `Asia/Tehran`, `fa-ir`, `USE_TZ=True` |

### Repository layout

```
Sefro_Clinic/
├── Sefro_Clinic/          # Project package (settings, root URLs, shared utils)
│   ├── settings.py        # All configuration (env-driven; refuses to boot without secrets)
│   ├── urls.py            # Root URLConf → mounts api_legacy + api_v2 + face_analyzer (v3) + 3 schema/doc pairs
│   ├── api_legacy.py      # /api/ → accounts + customers + inventory + finance + logs
│   ├── api_v2.py          # /api/v2/ → public website API (website app)
│   ├── api_v3.py          # OpenAPI urlconf for /api/v3/ (face_analyzer) — docs only
│   ├── docs.py            # Schema/Swagger views gated by DocsAccessPermission
│   ├── fields.py          # ShamsiDateField / ShamsiDateTimeField serializer fields
│   └── validators.py      # TEXT_SANITIZERS (NUL-byte + Unicode-surrogate rejection)
├── accounts/              # ClinicUser, auth endpoints, permissions, bootstrap admin
├── customers/             # Customer, ServiceCategory, Service, Visit, Payment + legacy reports
├── finance/               # Sale/PaymentComponent, Wallet ledger, Expenses, Packages,
│   │                      #   WelcomePacks, OperatingExpenses, ExchangeRate,
│   │                      #   StaffCompensation, ProductUsage/Purchase/CostHistory
│   └── services/          # Business-logic layer (checkout, wallet, accounting, reporting, ...)
├── inventory/             # Product catalog + stock count
├── face_analyzer/         # Face AI Analyzer (API v3): models, MediaPipe/external backends,
│   │                      #   skin-care plan generators (rule-based or LLM)
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
face_analyzer ──────────► accounts (user FK) + customers (Service FK on tips)
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
| `JWT_LEEWAY` | `30` | Clock-skew tolerance (seconds) so a just-issued token is not rejected as expired |
| `DJANGO_JWT_COOKIE_SECURE` | follows SSL redirect | `Secure` flag on JWT cookies |
| `DJANGO_RETURN_TOKENS_IN_BODY` | `False` | If `True`, login/refresh also return tokens in the JSON body (dev/Swagger convenience) |
| `THROTTLE_AUTH_RATE` / `THROTTLE_CONTACT_RATE` / `THROTTLE_ANON_RATE` / `THROTTLE_USER_RATE` | `10/min` / `5/min` / `60/min` / `600/min` | DRF throttling (effectively disabled during tests) |
| `DJANGO_DOCS_PUBLIC` | `False` | If `True`, anonymous users may read API docs; otherwise login required |
| `CORS_ALLOWED_ORIGINS` / `CORS_ALLOW_ALL_ORIGINS` / `CSRF_TRUSTED_ORIGINS` | empty | CORS/CSRF; credentials allowed |
| `FINANCE_DEFAULT_USD_TO_TOMAN_RATE` | `100000` | Fallback exchange rate if no DB row exists (also seeded on first migrate) |
| `EXCHANGE_RATE_PROVIDER` | `database` | `database` = DB cache only; `external` = HTTP fetch (Tindex) + DB cache |
| `EXCHANGE_RATE_API_URL/API_KEY/TIMEOUT/CACHE_TTL` | Tindex URL / — / 5s / 3600s | Primary external provider config |
| `EXCHANGE_RATE_BACKUP_API_URL/API_KEY` | BrsApi URL / — | Backup provider (BrsApi.ir) |
| `FACE_ANALYZER_MODEL_PROVIDER` | `local` | `local` = MediaPipe pipeline; `external` = HTTP analyzer (`FACE_ANALYZER_EXTERNAL_API_URL` + `_API_KEY`) |
| `FACE_ANALYZER_MAX_IMAGE_MB` | `5` | Upload size cap for `POST /api/v3/face/analyze/` (JPEG/PNG/WebP, magic-byte + Pillow verified) |
| `FACE_ANALYZER_ENABLE_HISTORY` | `True` | When `False`, the v3 history endpoints return 404 |
| `FACE_ANALYZER_THROTTLE_RATE` | `5/min` (prod), `100000/min` (tests) | Scoped `face_analyzer` throttle on analyze + tips |
| `FACE_ANALYZER_TIPS_PROVIDER` | `rule_based` | `rule_based` or `llm` skin-care plan generator |
| `FACE_ANALYZER_LLM_PROVIDER/LLM_API_KEY/LLM_MODEL/LLM_TIMEOUT` | `openai` / — / `gpt-4o-mini` / `30` | LLM tips settings; any failure falls back to the rule engine |


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
(`BLACKLIST_AFTER_ROTATION=True`), so replay of a used refresh token is rejected. Refresh is
401-loop proof by design: if the presented token fails but the `refresh_token` cookie holds a
different (rotated) token, the request **retries once with the cookie**; if the session is
definitively dead, the failure response **deletes both cookies** so the client gets a clean
logged-out state instead of replaying a blacklisted token forever. Logout has
`authentication_classes = []` (an expired access token can never 401 it), blacklists the
presented/cookie refresh token, and clears both cookies — an expired session can always log
out cleanly. Token verification allows `JWT_LEEWAY` (default 30 s) of clock skew.

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
  `contact` scope (5/min) on the public contact form; `face_analyzer` scope (5/min) on
  `POST /api/v3/face/analyze/` and `POST /api/v3/face/{id}/tips/`; global anon 60/min and
  user 600/min.
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
| **`PurchaseOrder`** | **Buying products (purchase order) workflow**: `supplier`, `status` (`draft`→`ordered`→`received` / `cancelled`), `order_date` (Gregorian, defaults to today), `received_date`, `notes`, `created_by`, `total_cost_usd`, `exchange_rate_snapshot` + `total_cost_toman` (written **only on receive**), `idempotency_key` (unique). Indexes on `status+order_date`, `supplier`. Draft/ordered rows are pure paperwork — no stock, cost or ledger effect |
| **`PurchaseOrderItem`** | Product line of an order (`order` CASCADE `items`, `product` **PROTECT** `purchase_order_items`): `quantity` (> 0, ≤ 3 decimals), `unit_cost_usd`, computed `total_cost_usd`, receive-time `unit_cost_toman`/`total_cost_toman` snapshots. Unique per order+product (duplicate lines are also rejected in the service layer) |
| **`StaffCompensationRule`** | Per-role commission config (unique `role`): `calculation_type` (`percent_profit`/`fixed_per_session`/`monthly_salary`), `payout_type` (`cash`/`product`/`hybrid`), percent/fixed amounts, transport allowance, commission product+qty |
| **`StaffPayout`** | Generated per (visit, staff, service) — **unique constraint**; snapshots revenue/cost/profit in USD+Toman, cash and/or product payout, `status` (`pending`/`approved`/`paid`/`cancelled`), `payout_mode`, approval fields |
| **`WelcomePack`** | Named gift-bundle definition: `name` (unique), `description`, `is_active`, `created_by`. Creating it has **no** financial effect |
| **`WelcomePackItem`** | Product line inside a pack (`welcome_pack` + `product` unique, `quantity` > 0) |
| **`WelcomePackUsage`** | The financial event: pack issued to a `customer` (optional `visit`, `issued_by`); snapshots `total_cost_usd_snapshot`, `exchange_rate_snapshot`, `total_cost_toman_snapshot` at issue time. `PROTECT` on pack/customer; immutable, read-only API |
| **`OperatingExpenseCategory`** | Categories for **direct clinic operating costs** (هزینه‌های جاری): `name` (unique), `slug` (unique), `description`, `is_active`, `sort_order`. Seeded by migration; delete blocked while expenses exist |
| **`OperatingExpense`** | Direct clinic spend paid with clinic money: `category` (PROTECT), `title`, `amount_usd` (≥ 0), `exchange_rate`/`amount_toman` snapshots, `expense_date` (**Gregorian**), `payment_method` (`cash`/`card`/`bank_transfer`/`other`), `vendor`, `receipt`, `notes`, `created_by`, **`idempotency_key` (unique)**. Never touches Wallet/Sale/PaymentComponent |

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

### 5.7 face_analyzer app (Face AI API v3)

| Model | Purpose |
|---|---|
| **`FaceAnalysis`** | Immutable record of one run: nullable `user` FK (SET_NULL; anonymous uploads are allowed and unowned), `image` (uploaded to `face_analyses/%Y/%m/`), five 0–10 scores (`overall_score`, `symmetry_score`, `skin_clarity_score`, `youthfulness_score`, `harmony_score`), `detected_attributes` (JSON), `suggestions` (JSON list), `raw_model_output` (JSON), `provider` (`local`/`external`), `model_version`, Shamsi `created_at`. Indexed on `(user, -created_at)` and `created_at` |
| **`SkinCarePlan`** | One-to-one per analysis (`related_name=skin_plan`): `summary`, `skin_type` (`oily`/`dry`/`combination`/`normal`), `primary_concerns` (JSON), `recommended_frequency`, `provider` (`rule_based`/`llm`), `model_used`, `created_at` (`auto_now` so regeneration refreshes the timestamp) |
| **`SkinCareTip`** | Actionable tip rows on a plan: `period` (`morning`/`evening`/`weekly`/`lifestyle`/`professional`), `sort_order`, `title`, `description`, `priority` (`low`/`medium`/`high`), `category` (cleanser, toner, serum, moisturizer, sunscreen, exfoliant, mask, eye_care, treatment, lifestyle, diet, in_clinic), `key_ingredients`/`avoid_ingredients` (JSON), `related_service_slug` + optional `related_service` FK→`customers.Service` (SET_NULL) linking the tip to a sellable clinic service |


---

## 6. Complete API Endpoint Reference

Conventions: all list endpoints are paginated (20/page, `?page=`). Unless noted, auth = JWT
cookie (`access_token`) or `Authorization: Bearer <token>`. **All dates accepted/returned by the
dashboard API are Shamsi (Jalali) strings** unless marked *Gregorian*. Router-managed routes also
accept DRF **format suffixes** (`/api/customers/1.json`, …). Every path below was verified
against a live dump of the Django URL resolver.

### 6.1 API documentation & schema

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/api/schema/` | Login (or public if `DJANGO_DOCS_PUBLIC=True`) | OpenAPI 3 JSON for the dashboard API |
| GET | `/api/docs/` | same | Swagger UI for the dashboard API |
| GET | `/api/v2/schema/` | same | OpenAPI 3 JSON for the site API |
| GET | `/api/v2/docs/` | same | Swagger UI for the site API |
| GET | `/api/v3/schema/` | same | OpenAPI 3 JSON for the Face AI Analyzer API |
| GET | `/api/v3/docs/` | same | Swagger UI for the Face AI Analyzer API |

### 6.2 Authentication & employees — `/api/auth/`

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/api/auth/token/` | Public, throttled (`auth` scope) | Login `{username, password}` → sets `access_token`/`refresh_token` HttpOnly cookies + `csrftoken`; body tokens only if `DJANGO_RETURN_TOKENS_IN_BODY=True` |
| POST | `/api/auth/token/refresh/` | Public (refresh cookie/body), throttled | Rotates tokens; old refresh blacklisted; cookies re-set; retries once with the cookie if the body token is stale; dead session ⇒ both cookies deleted |
| POST | `/api/auth/logout/` | Public (never authenticated) | Blacklists refresh token, clears cookies → `{"detail": "Logged out."}` — works even with an expired access token |
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
| GET/PUT/PATCH/DELETE | `/api/visits/{id}/` | Retrieve / update (same overlap validation) / delete. Every response embeds the visit's payments (`payments: [{id, customer, customer_name, amount, amount_usd, exchange_rate, payment_method, paid_at}]`), the denormalized `customer_name` and `total_paid` (sum of `payments.amount`); payments are fetched with one prefetch query for the list endpoint |
| POST | `/api/visits/{id}/confirm/` | `pending → confirmed` |
| POST | `/api/visits/{id}/complete/` | `→ completed` **and auto-generates staff commission payouts** (see §8.5) |
| POST | `/api/visits/{id}/cancel/` | `→ canceled` |
| POST | `/api/visits/reserve/` | Simplified booking: `{customer: id, services: [ids], date: "Shamsi YYYY-MM-DD", time: "HH:MM", notes?}` → creates a **pending** visit whose `end_at = start_at + Σ service.time` |

### 6.7 Payments (legacy) — `/api/payments/`

| Method | Path | Description |
|---|---|---|
| GET | `/api/payments/` | List; search customer name/id/mobile; ordering `paid_at, amount, payment_method`; filters `?visit={id}` and `?customer={id}` |
| POST | `/api/payments/` | Record a payment directly `{customer?, visit?, amount (Toman), payment_method, paid_at (Shamsi), notes}`. When `visit` is given and `customer` is omitted, the customer is **inherited from the visit**; a `customer` that does not match the visit's customer is rejected with `400` |
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
shortcut: `today`, `this_week`, `this_month`, `prev_month`, `this_year`; falls back to *today*
when no usable range is supplied):

| Method | Path | Description |
|---|---|---|
| GET | `/api/finance/reports/financial-summary/` | Revenue, product cost, gross/net profit (USD+Toman), expenses, avg transaction, payment-method breakdown, wallet totals; filters `service, package, product, personnel` |
| GET | `/api/finance/reports/profit-by-service/` | Profit & margin per service |
| GET | `/api/finance/reports/profit-by-package/` | Profit & margin per package |
| GET | `/api/finance/reports/profit-by-staff/` | Revenue/cost/profit per staff member across completed visits |
| GET | `/api/finance/reports/wallet-summary/` | Wallet liability, rewards issued/reversed, wallet payments/refunds |
| GET | `/api/finance/reports/staff-payout-summary/` | Payout totals; filters `staff`, `role` |
| GET | `/api/finance/reports/dashboard/` | The finance dashboard: sales summary, expenses, net profit, payout totals, wallet summary, operational metrics (completed visits, new customers, avg ticket), payment-method breakdown |
| GET | `/api/finance/reports/welcome-packs/` | Welcome-pack issuance & cost summary: `total_usage_count`, `total_packs_issued`, `total_cost_usd/toman`, `by_pack[]` |
| GET | `/api/finance/reports/product-purchases/` | **Received purchase orders** (buying products): `order_count`, `line_count`, `total_quantity`, `total_cost_usd/toman`, `by_product[]`, `by_supplier[]`. Filters `product`, `supplier`, plus the standard `start_date`/`end_date`/`period` range (applied to `received_date`) |


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
| `product-purchases/` | CRUD | read: staff / write: **admin** | **Legacy one-shot restock**: creating a purchase updates `Product.cost_usd` + `count` and rolls `ProductCostHistory` immediately. Prefer `purchase-orders/` for a staged workflow |
| `purchase-orders/` | CRUD + workflow | read: staff / write: **admin** | **Buying products with approval-style flow** (see §8.10). Nested writable `items[]` (`product`, `quantity`, `unit_cost_usd`); server computes `total_cost_usd`, converts `total_cost_toman` live while open and switches to stored snapshots once `received`. Filters `?status= ?supplier= ?product= ?date_from= ?date_to=` (Gregorian), search `supplier,notes,items__product__name`, `POST` idempotent via `idempotency_key`. **Delete blocked (400) once received** |
| `staff-compensation-rules/` | CRUD | **admin only** | Commission rules per role |
| `staff-payouts/` | read-only | staff | Filters `?staff= ?role= ?status= ?visit=`; plus `GET staff-payouts/summary/` and `GET staff-payouts/detail_report/` |
| `operating-expense-categories/` | CRUD | staff (admin **and** employee) | Direct operating-cost categories; search `name,slug,description`; ordering `name,slug,sort_order,is_active`; **delete blocked (400)** while expenses reference the category |
| `operating-expenses/` | CRUD + `summary` | staff (admin **and** employee) | Direct clinic spend; filters `?category= ?payment_method= ?created_by= ?date_from= ?date_to=` (Gregorian); search `title,description,vendor,notes,category__name`; `POST` is idempotent via `idempotency_key`; `GET …/summary/` for period totals |
| `welcome-packs/` | CRUD + `issue` | staff (admin **and** employee) | Pack definitions (`?is_active=true\|false`, search `name,description`); nested `items` accepted on create/update; `POST /api/finance/welcome-packs/{id}/issue/` = the financial event (see below) |
| `welcome-pack-items/` | CRUD | staff | Granular pack→product lines (unique per pack+product, qty > 0) |
| `welcome-pack-usages/` | read-only | staff | Immutable issuance history; filters `?welcome_pack= ?customer= ?visit= ?date_from= ?date_to=` (Gregorian), search pack/customer name |

**Welcome-pack issuance action**

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/api/finance/welcome-packs/{id}/issue/` | staff | Issue a pack: `{customer, quantity?=1, visit?}`. Validates customer/visit existence and that the visit belongs to that customer; creates a `WelcomePackUsage` with USD/rate/Toman cost snapshots → **201** |

**Expense workflow actions** (on `/api/finance/expenses/{id}/`):

| Action | Auth | Transition |
|---|---|---|
| `POST …/submit/` | staff (owner) | `draft → submitted` |
| `POST …/approve/` | **admin** (cannot approve own) | `submitted → approved` |
| `POST …/reject/` | **admin** (cannot reject own) | `submitted → rejected` |
| `POST …/pay/` | **admin** | `approved → paid` |
| `POST …/cancel/` | owner or admin | any non-paid state → `cancelled` |

**Purchase-order lifecycle actions** (on `/api/finance/purchase-orders/{id}/`, **admin only**;
everything else on the resource follows read: staff / write: admin):

| Action | Auth | Transition & effect |
|---|---|---|
| `POST …/mark-ordered/` | **admin** | `draft → ordered`. Still pure paperwork: no stock, cost or Toman snapshot |
| `POST …/receive/` | **admin** | `draft/ordered → received`. **The only step that moves money**: locks each product, sets `Product.cost_usd`, increments `count`, closes/opens `ProductCostHistory`, then writes `exchange_rate_snapshot` + per-line and order-level Toman totals |
| `POST …/cancel/` | **admin** | any state except `received → cancelled` (a received order is immutable — it already changed stock) |

### 6.10 Face AI Analyzer — `/api/v3/` (`face_analyzer` app)

Own URLConf (`Sefro_Clinic/api_v3.py`) with its own Swagger/schema. Analysis is **public**;
history is staff-only and scoped to the caller.

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/api/v3/face/analyze/` | **public**, throttled (`face_analyzer`, 5/min) | `multipart/form-data` with `image` (JPEG/PNG/WebP; ≤ `FACE_ANALYZER_MAX_IMAGE_MB`, MIME + magic-byte + Pillow verified). Runs the analyzer (`local` MediaPipe or `external` HTTP), persists a `FaceAnalysis` + generated `SkinCarePlan`/`SkinCareTip`s and returns `{id, overall_score, symmetry_score, skin_clarity_score, youthfulness_score, harmony_score, detected_attributes, suggestions, skin_plan, created_at (Shamsi), provider, model_version}`. Logged-in staff callers get the analysis linked to their user. Errors: **400** invalid/too-large image, no face detected, analysis failed; **429** throttled |
| POST | `/api/v3/face/{pk}/tips/` | **public**, throttled (`face_analyzer`, 5/min) | Regenerate the skin-care plan for an existing analysis → `SkinCarePlanSerializer` (`summary`, `skin_type`, `primary_concerns`, `recommended_frequency`, `provider`, `model_used`, plus `morning/evening/weekly/lifestyle/professional` tip arrays). **404** if the analysis does not exist |
| GET | `/api/v3/face/history/` | Any staff | Paginated (20/page) list of the caller's own analyses (`id`, five scores, `created_at` Shamsi, `skin_plan {summary, skin_type}`). Admin-role users see **all** analyses; other staff see only their own. **404** when `FACE_ANALYZER_ENABLE_HISTORY=False`. Anonymous rows are nobody's history (they never appear for employees) |
| GET | `/api/v3/face/history/{pk}/` | Any staff | Full detail (`FaceAnalysisResponseSerializer`, same shape as analyze). **404** for records owned by another non-admin user (queryset-scoped); admin role may read any |

Notes: there is **no** create/update/delete API for analyses or tips — the only write path is
`analyze`. `tips` regeneration runs `generate_and_store_plan()` atomically: it **upserts** the
one-to-one plan and **replaces** all its tips (delete + bulk-create), resolving each tip's
`related_service_slug` to a live `customers.Service`. `FaceAnalysis` rows own their plan and
tips, which cascade if an analysis is deleted (ORM/shell only).

### 6.11 Audit logs — `/api/logs/`

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/api/logs/` | **admin** | Audit trail; `?search=` across `model_name, action, object_repr, user__username`; `?ordering=timestamp` |
| GET | `/api/logs/{id}/` | **admin** | Single entry |

### 6.12 Site API v2 — `/api/v2/` (public website)

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
> `/api/inventory/`, and `/api/v2/`. There is **no** root index under `/api/v3/`
> (plain `path()` routes only).


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
Admin: POST /api/finance/operating-expense-categories/ → direct running-cost categories
                                                        (seeded by migration, extendable)
Any staff: POST /api/finance/welcome-packs/ (+ welcome-pack-items/) → gift bundles
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
- **Welcome pack:** `POST /api/finance/welcome-packs/{id}/issue/` → immutable cost snapshot
  (`WelcomePackUsage`); reported by `/api/finance/reports/welcome-packs/` and the dashboard.
- **Expenses:** employees submit, admin approves/pays (§8.4). Direct clinic running costs go
  through `/api/finance/operating-expenses/` instead (no approval workflow, any staff).
- **Payouts:** admin reviews generated `StaffPayout` rows and reports via
  `staff-payouts/summary/`. The API is **read-only** and there is no Django admin site, so
  `pending → approved → paid` transitions must be done through the ORM/shell (or a future
  endpoint) — see §12.
- **Face analysis:** staff can run `POST /api/v3/face/analyze/` during a consultation and
  revisit their own records under `/api/v3/face/history/`.
- **Reporting:** legacy Shamsi reports under `/api/reports/*` and finance (Gregorian) reports
  under `/api/finance/reports/*`.

### Public-website journey (no login)

```
Visitor: GET /api/v2/services/ (?category=face)  → browses catalog
         GET /api/v2/packages/                    → sees bundles & discounts
         GET /api/v2/products/  /team/  /testimonials/
         POST /api/v2/contact/ {full_name, phone 09xxxxxxxxx, message}  → consultation request
         POST /api/v3/face/analyze/ (multipart image)  → scores + skin-care plan (5/min)
         POST /api/v3/face/{id}/tips/                  → regenerate the plan
Staff:   reads ContactMessage rows through the ORM/shell (no list API, no admin site mounted)
         and calls back; browses own analyses at GET /api/v3/face/history/
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
  `pending → approved → paid` (or `cancelled`) has **no API and no admin site** — the API
  exposes read/report endpoints only, so status changes are made through the ORM/shell.
- Reports: `staff_payout_summary()` (totals per period/staff/role) and `staff_payout_detail()`
  (per-payout rows).

### 8.6 Inventory costing (`finance/services/inventory.py`)

- `record_product_purchase()` — atomic: creates `ProductPurchase`, sets `Product.cost_usd` to
  the new unit cost, increments `Product.count`, closes the open `ProductCostHistory` range and
  opens a new one effective from the purchase date.
- `apply_purchase_receipt(product, quantity, unit_cost_usd, purchase_date)` — the shared,
  lock-protected core of that mutation (lock product → set cost → increment count → roll
  cost history). Used by **both** the one-shot `ProductPurchase` ledger and the
  purchase-order `receive` step (§8.10) so stock/cost semantics stay identical.
  It creates **no ledger row** of its own.
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

### 8.8 Welcome packs (`finance/services/welcome_pack.py`)

- **Definition vs. event.** `WelcomePack` + `WelcomePackItem` are just configuration — creating
  or editing them moves no money. The financial event is `POST …/welcome-packs/{id}/issue/`.
- `issue_welcome_pack(pack, customer, quantity, visit, issued_by)` computes the pack cost from
  current `Product.cost_usd` (`calculate_welcome_pack_cost_usd`), converts with the current
  rate, and writes one `WelcomePackUsage` holding `total_cost_usd_snapshot`,
  `exchange_rate_snapshot` and `total_cost_toman_snapshot`. Historical reports read only these
  snapshots — never today's costs or rate.
- Pack/customer are `PROTECT`ed, so a pack that has ever been issued cannot be deleted;
  usages are read-only through the API (`welcome-pack-usages/`).
- Nested `items` payloads on pack create/update go through `validate_welcome_pack_items`
  (unique product per pack, quantity > 0) and replace the item set atomically.
- Cost flows into the finance dashboard (`welcome_pack_cost_usd/toman`, subtracted before
  gross profit) and into `/api/finance/reports/welcome-packs/`.

### 8.9 Operating expenses (`finance/services/operating_expenses.py`)

- **Separate domain** from `Expense` (employee reimbursement claims): no
  draft→submitted→approved→paid pipeline, no self-approval guard, no per-owner scoping —
  any authenticated staff has full CRUD (owner decision recorded in the view docstrings).
- `create_operating_expense()` validates `amount_usd ≥ 0` and that the category is active,
  snapshots `exchange_rate` + `amount_toman` at creation, and is **idempotent** on
  `idempotency_key` (repeat submissions return the original record).
- `update_operating_expense()` re-validates amount/category; `expense_date` is **Gregorian**
  (finance convention). Category deletion is blocked (400) while expenses reference it.
- Reported separately from employee expenses so the two domains can be combined explicitly:
  `GET /api/finance/operating-expenses/summary/` (period totals) and
  `reporting.operating_expense_summary()`. It never touches `Wallet`, `Sale` or
  `PaymentComponent`.

### 8.10 Buying products — purchase orders (`finance/services/purchases.py`)

Buying stock is a **separate, staged workflow** from the legacy one-shot
`product-purchases/` endpoint, and deliberately writes no `ProductPurchase` rows (one purchase →
one restock event in the ledger; two ledgers would double-count).

- **Lifecycle:** `draft → ordered → received`, with `cancelled` reachable from any state except
  `received`. Only drafts/ordered rows can be edited (`update_purchase_order`).
- **Paperwork vs. money.** `create_purchase_order` / `mark_ordered` / `cancel_purchase_order`
  change nothing in inventory or profit — no stock, no `Product.cost_usd`, no
  `ProductCostHistory`. Validation lives in `normalize_items`: ≥ 1 line, unique product per
  order, quantity > 0 with ≤ 3 decimals, unit cost ≥ 0, unknown products rejected.
- **Receiving is the event.** `receive_purchase_order` (atomic) loads the lines, resolves the
  current USD→Toman rate, then for each line (locked in `product_id` order to avoid deadlocks)
  calls `apply_purchase_receipt()` — set cost, add stock, roll cost history — and stores
  `unit_cost_toman`/`total_cost_toman` snapshots on the line. It then marks the order
  `received`, stamps `received_date`, `exchange_rate_snapshot`, `total_cost_usd` and
  `total_cost_toman`, and refreshes the instance so the API response renders fresh items.
  Re-receiving, receiving a cancelled order, or receiving without a usable rate all raise
  `PurchaseOrderError` → HTTP 400. An already-received order can be neither edited, cancelled
  nor deleted (400) — it is the audit trail.
- **Profit stays correct by construction.** Receiving only *builds* stock and opens a new
  cost-history range; the cost reaches the P&L later, when the product is consumed
  (`ProductUsage` / COGS). So restocking never dilutes today's margin.
- **USD/Toman convention.** `total_cost_usd` is authoritative. Toman is a *live conversion*
  while the order is open (serializer converts at the current rate) and becomes a *stored
  snapshot* (`exchange_rate_snapshot`, line-level `unit_cost_toman`/`total_cost_toman`) once
  received — same rule as sales, welcome packs and operating expenses.
- **Idempotency & concurrency.** Creates are keyed on `idempotency_key` (repeat calls return the
  original order, HTTP 201); `Product` rows are `select_for_update()`ed during receive.
- **Reporting.** `purchase_summary(start, end, product_id, supplier)` powers
  `GET /api/finance/reports/product-purchases/`: totals in USD **and** Toman plus `by_product[]`
  and `by_supplier[]`, filtered on `received_date` (Gregorian, same `_resolve_range` /
   `period=` helpers as every other finance report).

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
| Unit | `tests/unit/` | Shamsi conversion, period keys, currency, service pricing, exchange-rate helpers, face-analyzer services |
| Integration | `tests/integration/` | reports, dashboard, payment aggregation, DB constraints, visit overlap, welcome-pack, operating-expense & **purchase-order** APIs, **face-analyzer API** |
| E2E | `tests/e2e/` | full visit cycle: reserve → confirm → complete → pay → audit-trail integrity |
| Domain/feature | `tests/finance/`, `tests/accounts/`, `tests/customers/`, `tests/website/`, `tests/logs/`, `tests/api/`, `tests/logic/` | wallets, staff compensation, welcome packs, operating expenses, **purchase-order service workflow** (`tests/finance/test_purchase_orders.py`), auth serializers/permissions, public site, audit log, API versioning |
| Security | `tests/security/` | auth (forgery/replay/brute-force), authorization/IDOR, CSRF, headers/cookies, injection/XSS, secrets hygiene, docs gating (incl. `/admin/` → 404) |
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
5. **Staff payout approval has no API** — `StaffPayoutViewSet` is read-only, and there is **no
   Django admin site** (`django.contrib.admin` is not installed; `/admin/` → 404 by test), so
   payout status changes require direct ORM/shell access or a new endpoint. Contact messages
   are likewise read via the ORM only (write-only public intake, no list endpoint).
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
10. **Outbound HTTP is limited to three providers** — exchange-rate feeds (Tindex/BrsApi), the
    optional external face-analyzer backend, and the optional LLM tips provider. The default
    configuration (`FACE_ANALYZER_MODEL_PROVIDER=local`, `FACE_ANALYZER_TIPS_PROVIDER=rule_based`)
    makes face analysis fully offline, keeping the SSRF surface minimal (OWASP A10 near N/A).
11. **Three API surfaces, three schemas.** `/api/` (v1 dashboard), `/api/v2/` (public site) and
    `/api/v3/` (face AI) each have their own OpenAPI urlconf + Swagger UI and are documented
    independently; the v3 surface is not included in the v1/v2 schemas.
12. **Face analysis is public but cheap-by-default-throttled.** `POST /api/v3/face/analyze/` is
    `AllowAny` (anonymous rows have `user = NULL`), protected by the scoped `face_analyzer`
    throttle; image input is size-capped, MIME- and magic-byte-checked and Pillow-verified
    before any model runs. History endpoints are `IsAuthenticated` and queryset-scoped to the
    caller unless the caller has the `admin` role.
13. **Two expense domains.** `Expense` = employee reimbursement with an approval pipeline and
    owner-scoped reads; `OperatingExpense` = direct clinic spend with full CRUD for all staff,
    idempotent creation and Gregorian dates. Reports keep them separate so totals can be
    combined explicitly.
14. **Welcome packs snapshot cost at issue time.** `WelcomePackUsage` stores USD/rate/Toman
    snapshots, so historical welcome-pack cost reports never drift when product costs or the
    exchange rate change later.

---

*Document generated from a full source audit (routing → views → serializers → services →
models → settings → tests). Last verified against branch `master`.*

