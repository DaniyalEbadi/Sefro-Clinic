# Sefro Clinic — Performance Report

**Phase:** `run`
**Metrics collected:** 48
**Data directory:** `C:\Users\Dani\Desktop\Sefro_Clinic\tests\performance\reports\data\run`

## Endpoint Benchmarks

| Endpoint | p50 (ms) | p95 (ms) | p99 (ms) | RPS | Errors |
|----------|----------|----------|----------|-----|--------|
| auth_login | 139.42 | 194.87 | 199.47 | - | - |
| auth_me | 1.18 | 2.71 | 7.62 | 611.8 | 0.0 |
| auth_refresh | 3.69 | 6.01 | 25.18 | - | - |
| crud_customer_detail | 5.77 | 12.9 | 24.53 | 132.8 | 0.0 |
| crud_customer_list | 16.26 | 22.3 | 31.0 | 59.3 | 0.0 |
| crud_customer_search | 21.98 | 29.95 | 34.08 | 43.0 | 0.0 |
| crud_payment_by_service | 110.72 | 270.07 | 319.34 | 7.7 | 0.0 |
| crud_payment_list | 8.98 | 14.39 | 19.14 | 100.6 | 0.0 |
| crud_service_list | 12.8 | 21.62 | 54.89 | 64.6 | 0.0 |
| crud_visit_list | 24.0 | 47.98 | 262.42 | 29.2 | 0.0 |
| dashboard | 9.02 | 16.17 | 17.01 | 100.1 | 0.0 |
| finance_checkout | 17.16 | 41.28 | 41.28 | - | - |
| finance_exchange_dollar | 4.25 | 9.41 | 11.03 | 194.6 | 0.0 |
| finance_expense_list | 4.49 | 11.45 | 18.08 | 181.1 | 0.0 |
| finance_financial_summary | 27.98 | 42.62 | 62.91 | 31.7 | 0.0 |
| finance_operating_expense_category_list | 5.21 | 9.14 | 19.96 | 158.5 | 0.0 |
| finance_operating_expense_list | 4.75 | 17.83 | 24.2 | 139.5 | 0.0 |
| finance_operating_expense_summary | 8.96 | 15.15 | 15.77 | 103.7 | 0.0 |
| finance_wallet_list | 5.74 | 9.5 | 15.62 | 150.5 | 0.0 |
| inventory_product_create | 6.96 | 13.27 | 27.16 | - | - |
| inventory_product_detail | 4.03 | 8.12 | 12.98 | 200.5 | 0.0 |
| inventory_product_list | 7.47 | 12.93 | 14.8 | 121.9 | 0.0 |
| inventory_product_list_size | - | - | - | - | - |
| inventory_product_search | 9.62 | 17.09 | 30.65 | 87.5 | 0.0 |
| reports_all | 98.38 | 120.37 | 120.37 | 9.8 | 0.0 |
| reports_customers | 10.76 | 18.03 | 18.13 | 88.0 | 0.0 |
| reports_daily | 6.84 | 7.85 | 13.51 | 139.1 | 0.0 |
| reports_monthly | 11.64 | 16.68 | 26.89 | 77.4 | 0.0 |
| reports_referral | 5.14 | 5.96 | 15.02 | 172.7 | 0.0 |
| reports_summary | 104.84 | 136.54 | 180.97 | 8.9 | 0.0 |
| reports_weekly | 10.0 | 16.56 | 16.6 | 87.9 | 0.0 |

## Database Performance

### scale_1000_customers
```json
{
  "n": 15,
  "min_ms": 25.05,
  "p50_ms": 38.49,
  "p75_ms": 56.31,
  "p90_ms": 100.38,
  "p95_ms": 100.38,
  "p99_ms": 203.78,
  "max_ms": 203.78,
  "mean_ms": 58.4,
  "url": "/api/customers/",
  "method": "GET",
  "iterations": 15,
  "errors": 0,
  "error_rate": 0.0,
  "throughput_rps": 17.1,
  "avg_response_bytes": 11347,
  "max_response_bytes": 11347
}
```

### scale_1000_product_search
```json
{
  "n": 10,
  "min_ms": 14.2,
  "p50_ms": 15.18,
  "p75_ms": 15.66,
  "p90_ms": 15.95,
  "p95_ms": 36.97,
  "p99_ms": 36.97,
  "max_ms": 36.97,
  "mean_ms": 17.23,
  "url": "/api/inventory/products/?search=\u0645\u062d\u0635\u0648\u0644",
  "method": "GET",
  "iterations": 10,
  "errors": 0,
  "error_rate": 0.0,
  "throughput_rps": 58.0,
  "avg_response_bytes": 5813,
  "max_response_bytes": 5813
}
```

### scale_1000_products
```json
{
  "n": 15,
  "min_ms": 9.07,
  "p50_ms": 10.06,
  "p75_ms": 10.69,
  "p90_ms": 15.55,
  "p95_ms": 15.55,
  "p99_ms": 29.56,
  "max_ms": 29.56,
  "mean_ms": 11.96,
  "url": "/api/inventory/products/",
  "method": "GET",
  "iterations": 15,
  "errors": 0,
  "error_rate": 0.0,
  "throughput_rps": 83.6,
  "avg_response_bytes": 5717,
  "max_response_bytes": 5717
}
```

### scale_100_customers
```json
{
  "n": 15,
  "min_ms": 18.2,
  "p50_ms": 19.27,
  "p75_ms": 21.42,
  "p90_ms": 25.65,
  "p95_ms": 25.65,
  "p99_ms": 39.75,
  "max_ms": 39.75,
  "mean_ms": 21.34,
  "url": "/api/customers/",
  "method": "GET",
  "iterations": 15,
  "errors": 0,
  "error_rate": 0.0,
  "throughput_rps": 46.9,
  "avg_response_bytes": 11276,
  "max_response_bytes": 11276
}
```

### scale_500_query_count
```json
{
  "count": 2
}
```

## Load / Concurrency

### concurrency_smoke_4w
- Workers: 4
- Requests executed: 20
- Error rate: 0.0
- P95: 57.15 ms
- Aggregate RPS: 47.5

## Database Plan Analysis

- **explain_customer_search**: uses_index=unknown
- **explain_payments_range**: uses_index=False
- **explain_visit_overlap**: uses_index=True
- **explain_visits_window**: uses_index=True

## Cache Performance

### cache_dashboard_queries
```json
{
  "uncached": 5,
  "cached": 5
}
```

### cache_raw_latency
```json
{
  "set": {
    "n": 100,
    "min_ms": 0.01,
    "p50_ms": 0.01,
    "p75_ms": 0.01,
    "p90_ms": 0.01,
    "p95_ms": 0.01,
    "p99_ms": 0.02,
    "max_ms": 0.05,
    "mean_ms": 0.01
  },
  "get": {
    "n": 100,
    "min_ms": 0.01,
    "p50_ms": 0.01,
    "p75_ms": 0.01,
    "p90_ms": 0.01,
    "p95_ms": 0.01,
    "p99_ms": 0.02,
    "max_ms": 0.04,
    "mean_ms": 0.01
  }
}
```

### cache_stampede
```json
{
  "n": 20,
  "min_ms": 0.1,
  "p50_ms": 0.14,
  "p75_ms": 0.16,
  "p90_ms": 0.21,
  "p95_ms": 0.26,
  "p99_ms": 0.36,
  "max_ms": 0.36,
  "mean_ms": 0.16
}
```

## Background Tasks

- **background_probe**: {"celery_configured": false, "broker_configured": false, "finding": "NO Celery/broker in project. All work is synchronous in-request.", "recommendation": "For long-running report generation or bulk operations, consider adding Celery with Redis broker in production."}
- **blocking_io_check**: {"/api/dashboard/": {"time_s": 0.01, "status": 401}, "/api/reports/": {"time_s": 0.001, "status": 401}, "/api/customers/": {"time_s": 0.001, "status": 401}}

## Response Sizes

```json
{
  "bytes": 5717
}
```
```json
{
  "/api/customers/": 11294,
  "/api/visits/": 10795,
  "/api/payments/": 4423,
  "/api/services/": 6207,
  "/api/inventory/products/": 5691,
  "/api/dashboard/": 109,
  "/api/reports/": 5746,
  "/api/finance/operating-expenses/": 52,
  "/api/finance/operating-expenses/summary/": 173,
  "/api/finance/operating-expense-categories/": 2060
}
```

---
*Report generated automatically by the performance test suite.*