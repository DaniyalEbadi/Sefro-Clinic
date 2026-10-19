# AGENTS.md — guidelines for AI agents (and new devs)

Sefro Clinic: Django 5.2 + DRF backend for a beauty clinic.
Everything money-related is formula-driven and cross-checked by tests.
Read this before changing finance code. Deeper reading is listed at the bottom — do not duplicate it here.

## Commands

Python is always the project venv (Windows):

```powershell
& "venv\Scripts\python.exe" manage.py runserver
& "venv\Scripts\python.exe" manage.py check
& "venv\Scripts\python.exe" manage.py makemigrations --check   # must stay clean
& "venv\Scripts\python.exe" -m ruff check .
```

### Tests — run in three batches

A single full run exceeds a ~15-minute command timeout. These three batches each finish in time
(counts drift; trust the runner, not the numbers):

```powershell
# batch 1 (~772 tests, ~7 min)
& "venv\Scripts\python.exe" manage.py test tests.finance tests.integration --noinput

# batch 2 (~518 tests)
& "venv\Scripts\python.exe" manage.py test tests.security tests.accounts tests.customers tests.api tests.unit tests.logic --noinput

# batch 3 (~146 tests; performance tests skip unless SEFRO_PERF=1)
& "venv\Scripts\python.exe" manage.py test tests.logs tests.performance tests.website tests.e2e --noinput
```

- Expected result: everything passes except **one known flaky test**:
  `tests.finance.test_wallets.WalletConcurrencyTests.test_concurrent_wallet_spend`
  (threaded DB race; fails intermittently as an IntegrityError or a balance assertion).
  Pre-existing. Do not chase it, do not "fix" it, do not count it against your change.
- If a run is interrupted, orphaned connections hold the test database and the next run
  fails on `DROP DATABASE`. Kill them first:

  ```powershell
  & "venv\Scripts\python.exe" "$env:TEMP\opencode\kill_test_sessions.py"
  ```

- Test DB: `test_sefro_clinic` on `127.0.0.1:5432` (dev DB `sefro_clinic`).
- Performance budgets/queries live in `tests/performance/conftest.py` (`BUDGETS`).

## Money invariants — never break these

The authoritative formula is implemented once, in `finance/services/financials.py :: build_report`:

```
gross        = revenue − product_cost − welcome_pack_cost
below_line   = staff_compensation + operating_expenses + claims
net_profit   = gross − below_line
clinic_share = revenue − product_cost − welcome_pack_cost − staff_compensation
```

- All report endpoints (financial-summary, dashboard, profit-by-service/staff/package,
  monthly-close, payout summaries, welcome-pack report) are thin wrappers over
  `build_report` / `calculate_visit_financials`. **Never re-derive revenue, cost or profit
  in a view.** If two endpoints disagree, the bug is always outside `financials.py`.
- Revenue = the Sale ledger (money actually collected), never list price.
- Product cost = `ProductUsage.total_cost_usd_snapshot` recorded at consumption time.
  `finance/services/inventory.py :: record_product_usage` decrements `Product.count`
  (row-locked; insufficient stock raises `InventoryError`).
- Welcome-pack cost comes only from `WelcomePackUsage` snapshots — never recomputed live.
- Staff pay is per-service, per-operator: the operator of each service is
  `VisitService.staff` (explicitly assigned, else auto-resolved from unique
  `compensation_role` holders), with primary `Visit.staff` as the fallback.
  A percent rule pays that percentage of **that service's own revenue**.
- Operating expenses and staff claims bucket by `expense_date`; both are below the line
  (they reduce net profit, never gross).
- A compensable visit that cannot resolve an operator for every role-tagged service is
  rejected at completion (400) and its status restored. Completion via
  `PATCH {"status": "completed"}` runs the same guards.
- Completion ALSO requires recorded consumption for every service with a recipe:
  `missing_recipe_services(visit)` → 400 with the offending service names
  (`customers/views.py`, `_missing_consumption_message`). Record consumption first
  (`POST /api/finance/visits/<id>/record-consumption/`); services without recipes are
  exempt; explicitly not consuming a recipe product requires a `zero_reason` on the
  usage; repeat recording is rejected (400) so stock never double-deducts.
- Changing pricing or compensation math is a business decision — never do it to make a
  test pass.

## Accounts and the role axes

There are exactly **two kinds of accounts**: `admin` and `employee` (`ClinicUser.role`,
`accounts/models.py`). There is no third kind, ever. `Customer` is not an account at
all — no login, no password, portal-side data model only.

Money routing inside the employees is a single admin-set tag on the employee record,
`ClinicUser.compensation_role` (doctor / facial / laser / **none**). It exists only so a
role-tagged service knows which employee its payout goes to. Admin sets it on the
admin-gated employee endpoints; it is not a user type and not a permission.

All Staff Compensation is defined in its own endpoints — nowhere else:

- rules: `/api/finance/staff-compensation-rules/` — **admin-only** writes (how each role is paid)
- payouts + summaries: `/api/finance/staff-payouts/...` and
  `/api/finance/reports/staff-payout-summary/` — **read-only** for employees and admins alike

The service side mirrors the same four values: `Service.compensation_role` and
`StaffCompensationRule.role` must stay value-identical to `accounts.CompensationRole`
(accounts mirrors the choices because it cannot import customers/finance). A service
tagged `none` pays nothing and never blocks completion (`staff_compensation.py` skips
it); an employee tagged `none` is simply never paid by the payout engine (sole
exception: the primary-staff fallback when nobody holds that service's role).

## Dates and report windows (Shamsi)

- The clinic runs on the Shamsi (Jalali) calendar. Visit `start_at` / `end_at` inputs are
  Shamsi strings, format `%Y-%m-%d %H:%M` (`Sefro_Clinic.fields.greg_to_shamsi_dt`);
  anything else is a 400.
- `_resolve_range(request)` (`finance/views.py`) resolves every finance-report window, in order:
  `?year=&month=` → `?period=` → `?start_date=&end_date=` → **default: the current Shamsi day**.
- Bucket anchors differ by design: sales by `created_at`, visits by `start_at`,
  payouts by `created_at`, expenses by `expense_date`. Activity reports
  (`/api/reports/daily|weekly|monthly|...|all/`) count the Sale ledger in Toman.

## API gotchas

- DRF auto-generates **read-only** fields for m2m relations that have an explicit
  `through` model. `VisitSerializer.services` (through `VisitService`) must stay an
  explicitly declared `PrimaryKeyRelatedField(many=True, required=False)` — if it is ever
  removed, visit creates silently drop their services.
- JSON money fields are stringified (`_stringify`); some quantities come back as
  3-decimal strings like `'4.000'`. Parse with `Decimal(...)`, never `int(...)`.
- Typical visit flow, all via API:
  `POST /api/visits/` → `.../confirm/` → `POST /api/finance/visits/<id>/record-consumption/`
  → optional `POST /api/finance/welcome-packs/<id>/issue/` → `POST /api/finance/checkout/`
  → `.../complete/` (generates payouts).

## Where things live

- `finance/services/financials.py` — owns ALL money math (build_report, calculate_visit_financials).
- `finance/services/staff_compensation.py` — payout engine, rules, payout summaries.
- `finance/services/inventory.py` — consumption and stock decrements.
- `finance/views.py` — report endpoints (thin), `_resolve_range`, checkout, record-consumption.
- `customers/views.py` — VisitViewSet (+ confirm/complete/cancel actions) and the Activity reports.
- `customers/serializers.py` — VisitSerializer (services, service_operators write / operators read).
- The `customers.VisitService` migration was hand-written; read it before touching the through model.

## Deeper reading (single sources of truth — don't copy their content around)

- `docs/PROJECT_FULL_EXPLANATION.md` — full domain walkthrough
- `skills/integration.md`, `skills/e2e.md` — test-suite skills
- `tests/TESTS_TREE.md` — what each test module covers
- `docs/SPEC_Doctor_Fixed_Payment_Per_Visit.md` — compensation spec
