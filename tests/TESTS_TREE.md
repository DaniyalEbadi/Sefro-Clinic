# Tests Directory Structure

```
tests/
├── __init__.py
├── helpers.py                              # Shared test utilities (make_admin, make_employee, admin_client, employee_client)
│
├── accounts/                               # Accounts app tests
│   ├── __init__.py
│   ├── e2e/
│   │   ├── __init__.py
│   │   └── test_endpoints.py              # Auth endpoint E2E tests
│   ├── integration/
│   │   ├── __init__.py
│   │   └── test_views.py                  # Auth view integration tests
│   └── unit/
│       ├── __init__.py
│       ├── test_models.py                 # ClinicUser model tests
│       ├── test_permissions.py            # Permission class tests
│       └── test_serializers.py            # Auth serializer tests
│
├── api/                                    # API-level tests
│   ├── __init__.py
│   └── test_versioning.py                 # API versioning tests
│
├── customers/                              # Customers app tests
│   ├── __init__.py
│   ├── e2e/
│   │   ├── __init__.py
│   │   └── test_endpoints.py             # Customer endpoint E2E tests
│   ├── integration/
│   │   ├── __init__.py
│   │   ├── test_views.py                 # Customer view integration tests
│   │   └── test_visit_past_dates.py      # Visit past-date validation tests
│   └── unit/
│       ├── __init__.py
│       ├── test_models.py                # Customer/Service/Visit model tests
│       └── test_serializers.py           # Customer serializer tests
│
├── e2e/                                    # End-to-end workflow tests
│   ├── __init__.py
│   ├── test_clinic_workflow.py            # Full clinic workflow E2E
│   └── test_critical_e2e_journeys.py     # Critical user journey E2E
│
├── finance/                                # Finance app tests
│   ├── __init__.py
│   ├── test_finance.py                    # Finance API & checkout tests
│   ├── test_models.py                     # Finance model constraint tests
│   ├── test_operating_expenses.py         # OperatingExpense domain tests (38 tests)
│   ├── test_services.py                   # Finance service layer tests
│   ├── test_staff_compensation.py         # Staff compensation/payout tests
│   └── test_wallets.py                    # Wallet & transaction tests
│
├── integration/                            # Cross-app integration tests
│   ├── __init__.py
│   ├── test_constraints.py                # DB constraint integration tests
│   ├── test_customer_visit_expense_exchange_integration.py
│   ├── test_dashboard.py                  # Dashboard endpoint integration tests
│   ├── test_finance_endpoints_api.py      # Finance endpoint API tests
│   ├── test_finance_reports_api.py        # Finance reports API tests
│   ├── test_inventory_api.py              # Inventory endpoint API tests
│   ├── test_payments_by_service.py        # Payment aggregation tests
│   ├── test_reports_api.py                # Reports API integration tests
│   ├── test_service_category_and_pricing_api.py
│   ├── test_visit_overlap.py             # Visit overlap prevention tests
│   └── test_wallet_checkout_integration.py # Wallet + checkout integration tests
│
├── logic/                                  # Business logic permission tests
│   ├── __init__.py
│   ├── admin/
│   │   ├── __init__.py
│   │   └── test_admin_permissions.py     # Admin-only permission tests
│   └── employee/
│       ├── __init__.py
│       └── test_employee_permissions.py   # Employee permission boundary tests
│
├── logs/                                   # Audit logging tests
│   ├── __init__.py
│   └── test_audit_log.py                 # AuditLog model & signal tests
│
├── performance/                            # Performance test suite (opt-in: SEFRO_PERF=1)
│   ├── __init__.py
│   ├── conftest.py                        # Performance test fixtures
│   ├── test_smoke_performance.py          # Smoke test thresholds
│   ├── api/
│   │   ├── __init__.py
│   │   └── test_api_benchmarks.py        # API endpoint benchmarks
│   ├── background/
│   │   ├── __init__.py
│   │   └── test_background_probe.py      # Background task probe tests
│   ├── benchmarks/
│   │   ├── __init__.py
│   │   └── (empty)
│   ├── cache/
│   │   ├── __init__.py
│   │   └── test_cache_effectiveness.py   # Cache hit/miss tests
│   ├── database/
│   │   ├── __init__.py
│   │   ├── test_explain_plans.py         # Query plan analysis
│   │   └── test_query_regressions.py     # Query budget regression tests
│   ├── endurance/
│   │   ├── __init__.py
│   │   └── test_endurance_soak.py        # Sustained load tests
│   ├── factories/
│   │   ├── __init__.py
│   │   └── models.py                     # Test data factories
│   ├── fixtures/
│   │   ├── __init__.py
│   │   └── datasets.py                   # Test dataset generators
│   ├── load/
│   │   ├── __init__.py
│   │   └── test_concurrent_endpoints.py  # Concurrent reader/writer tests
│   ├── reports/
│   │   ├── __init__.py
│   │   ├── test_report_generation.py     # Report generation perf tests
│   │   └── data/
│   │       └── run/                      # Benchmark result snapshots (JSON)
│   │           ├── auth_login.json
│   │           ├── auth_me.json
│   │           ├── auth_refresh.json
│   │           ├── blocking_io_check.json
│   │           ├── cache_raw_latency.json
│   │           ├── cache_stampede.json
│   │           ├── concurrency_smoke_4w.json
│   │           ├── crud_customer_detail.json
│   │           ├── crud_customer_list.json
│   │           ├── crud_customer_search.json
│   │           ├── crud_payment_by_service.json
│   │           ├── crud_payment_list.json
│   │           ├── crud_service_list.json
│   │           ├── crud_visit_list.json
│   │           ├── dashboard.json
│   │           ├── explain_customer_search.json
│   │           ├── explain_payments_range.json
│   │           ├── finance_checkout.json
│   │           ├── finance_exchange_dollar.json
│   │           ├── finance_expense_list.json
│   │           ├── finance_financial_summary.json
│   │           ├── finance_wallet_list.json
│   │           ├── inventory_product_create.json
│   │           ├── inventory_product_detail.json
│   │           ├── inventory_product_list.json
│   │           ├── inventory_product_list_size.json
│   │           ├── inventory_product_search.json
│   │           ├── pagination_latency_by_page.json
│   │           ├── reports_all.json
│   │           ├── reports_customers.json
│   │           ├── reports_daily.json
│   │           ├── reports_monthly.json
│   │           ├── reports_referral.json
│   │           ├── reports_summary.json
│   │           ├── reports_weekly.json
│   │           ├── response_sizes.json
│   │           ├── scale_1000_customers.json
│   │           ├── scale_1000_product_search.json
│   │           ├── scale_1000_products.json
│   │           └── scale_100_customers.json
│   ├── scalability/
│   │   ├── __init__.py
│   │   └── test_dataset_scaling.py       # Dataset scaling tests
│   ├── spike/
│   │   ├── __init__.py
│   │   └── test_traffic_spike.py         # Traffic spike tests
│   └── stress/
│       ├── __init__.py
│       └── test_stress_rampup.py         # Stress rampup tests
│
├── security/                               # Security test suite
│   ├── __init__.py
│   ├── test_audit_and_input_hardening.py  # Audit logging & input sanitization
│   ├── test_auth_security.py              # Auth: brute force, tokens, cookies
│   ├── test_authorization_security.py     # Authorization: IDOR, escalation, mass assignment
│   ├── test_csrf_security.py              # CSRF protection tests
│   ├── test_docs_admin_security.py        # API docs gating & error disclosure
│   ├── test_headers_cookies.py            # Security headers & cookie flags
│   ├── test_input_validation_security.py  # SQL injection, XSS, boundary validation
│   ├── test_owasp_monitoring.py           # OWASP auth event monitoring
│   └── test_secrets_hygiene.py            # Secrets/credentials hygiene
│
├── unit/                                   # Unit tests
│   ├── __init__.py
│   ├── test_currency.py                   # Currency validation tests
│   ├── test_exchange_rate_helpers.py      # Exchange rate provider & conversion tests
│   ├── test_period_keys.py               # Shamsi period key & range tests
│   ├── test_service_pricing.py           # Service cost/profit calculation tests
│   └── test_shamsi_fields.py            # Shamsi/Jalali date field tests
│
└── website/                                # Website (public v2) tests
    ├── __init__.py
    ├── test_contact_intake.py             # Contact form validation tests
    ├── test_models.py                     # Website model behavior tests
    ├── test_public_catalog.py             # Public catalog access tests
    ├── test_seeded_catalog.py             # Seeded catalog data tests
    └── test_visitor_journey.py            # Anonymous visitor E2E tests
```

## Test Categories Summary

| Category | Location | Test Count | Description |
|---|---|---|---|
| **Unit** | `tests/unit/` | ~50 | Currency, exchange rates, Shamsi dates, pricing, period keys |
| **Integration** | `tests/integration/` | ~100 | API endpoints, constraints, dashboard, reports, wallet+checkout |
| **E2E** | `tests/e2e/` + `*/e2e/` | ~30 | Full workflow journeys: reserve → confirm → complete → pay → audit |
| **Security** | `tests/security/` | ~60 | Auth, authorization, CSRF, headers, injection, XSS, secrets hygiene |
| **Finance** | `tests/finance/` | ~80 | Checkout, wallet, expenses, operating expenses, staff compensation |
| **Performance** | `tests/performance/` | ~40 | Smoke, stress, spike, endurance, scalability, cache, query plans |
| **Accounts** | `tests/accounts/` | ~20 | User model, permissions, serializers, auth endpoints |
| **Customers** | `tests/customers/` | ~20 | Customer model, serializers, visit validation |
| **Logic** | `tests/logic/` | ~10 | Admin/employee permission boundary tests |
| **Logs** | `tests/logs/` | ~5 | AuditLog model & signal tests |
| **Website** | `tests/website/` | ~15 | Public catalog, contact intake, visitor journey |
| **API** | `tests/api/` | ~3 | API versioning tests |

**Total: 815 tests** (15 performance tests skipped unless `SEFRO_PERF=1`)

## Running Tests

```bash
# Full suite
py manage.py test --noinput

# Specific category
py manage.py test tests.finance --noinput
py manage.py test tests.security --noinput
py manage.py test tests.unit --noinput

# Specific file
py manage.py test tests.finance.test_operating_expenses --noinput

# Performance (opt-in)
SEFRO_PERF=1 py manage.py test tests.performance --noinput
```
