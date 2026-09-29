# Sefro Clinic — Performance Report

**Phase:** `run`
**Metrics collected:** 48
**Data directory:** `C:\Users\Dani\Desktop\Sefro_Clinic\tests\performance\reports\data\run`

## Endpoint Benchmarks

| Endpoint | p50 (ms) | p95 (ms) | p99 (ms) | RPS | Errors |
|----------|----------|----------|----------|-----|--------|
| auth_login | 147.96 | 226.94 | 279.9 | - | - |
| auth_me | 1.14 | 3.18 | 8.33 | 563.3 | 0.0 |
| auth_refresh | 4.92 | 7.96 | 24.81 | - | - |
| crud_customer_detail | 9.95 | 15.23 | 18.68 | 96.7 | 0.0 |
| crud_customer_list | 45.16 | 54.02 | 59.79 | 21.8 | 0.0 |
| crud_customer_search | 89.25 | 155.21 | 156.38 | 10.0 | 0.0 |
| crud_payment_by_service | 100.05 | 286.46 | 352.13 | 8.0 | 0.0 |
| crud_payment_list | 10.06 | 16.47 | 20.93 | 89.2 | 0.0 |
| crud_service_list | 13.97 | 20.35 | 38.84 | 64.2 | 0.0 |
| crud_visit_list | 29.08 | 71.96 | 106.41 | 26.1 | 0.0 |
| dashboard | 13.3 | 43.12 | 78.3 | 41.8 | 0.0 |
| finance_checkout | 19.22 | 62.11 | 62.11 | - | - |
| finance_exchange_dollar | 4.04 | 5.85 | 13.75 | 207.7 | 0.0 |
| finance_expense_list | 4.43 | 5.55 | 20.24 | 187.8 | 0.0 |
| finance_financial_summary | 27.5 | 38.16 | 67.17 | 33.1 | 0.0 |
| finance_operating_expense_category_list | 5.73 | 11.08 | 21.75 | 147.0 | 0.0 |
| finance_operating_expense_list | 4.92 | 11.79 | 20.91 | 155.4 | 0.0 |
| finance_operating_expense_summary | 8.88 | 13.05 | 21.98 | 101.1 | 0.0 |
| finance_wallet_list | 5.98 | 13.79 | 15.06 | 141.0 | 0.0 |
| inventory_product_create | 5.93 | 7.89 | 16.78 | - | - |
| inventory_product_detail | 3.17 | 4.81 | 9.92 | 265.1 | 0.0 |
| inventory_product_list | 7.55 | 10.43 | 14.42 | 122.8 | 0.0 |
| inventory_product_list_size | - | - | - | - | - |
| inventory_product_search | 9.82 | 19.74 | 29.46 | 84.2 | 0.0 |
| reports_all | 100.24 | 154.91 | 154.91 | 9.3 | 0.0 |
| reports_customers | 34.62 | 67.14 | 86.75 | 29.1 | 0.0 |
| reports_daily | 7.81 | 15.84 | 16.87 | 109.7 | 0.0 |
| reports_monthly | 13.0 | 17.69 | 19.09 | 74.5 | 0.0 |
| reports_referral | 6.85 | 15.88 | 25.61 | 114.4 | 0.0 |
| reports_summary | 95.99 | 128.67 | 138.93 | 10.0 | 0.0 |
| reports_weekly | 12.47 | 24.35 | 50.25 | 61.6 | 0.0 |

## Database Performance

### scale_1000_customers
```json
{
  "n": 15,
  "min_ms": 60.01,
  "p50_ms": 100.06,
  "p75_ms": 104.6,
  "p90_ms": 154.47,
  "p95_ms": 154.47,
  "p99_ms": 365.29,
  "max_ms": 365.29,
  "mean_ms": 113.28,
  "url": "/api/customers/",
  "method": "GET",
  "iterations": 15,
  "errors": 0,
  "error_rate": 0.0,
  "throughput_rps": 8.8,
  "avg_response_bytes": 14079,
  "max_response_bytes": 14079
}
```

### scale_1000_product_search
```json
{
  "n": 10,
  "min_ms": 10.7,
  "p50_ms": 11.71,
  "p75_ms": 12.99,
  "p90_ms": 13.45,
  "p95_ms": 19.8,
  "p99_ms": 19.8,
  "max_ms": 19.8,
  "mean_ms": 12.52,
  "url": "/api/inventory/products/?search=\u0645\u062d\u0635\u0648\u0644",
  "method": "GET",
  "iterations": 10,
  "errors": 0,
  "error_rate": 0.0,
  "throughput_rps": 79.9,
  "avg_response_bytes": 5792,
  "max_response_bytes": 5792
}
```

### scale_1000_products
```json
{
  "n": 15,
  "min_ms": 6.26,
  "p50_ms": 8.02,
  "p75_ms": 8.41,
  "p90_ms": 12.27,
  "p95_ms": 12.27,
  "p99_ms": 15.49,
  "max_ms": 15.49,
  "mean_ms": 8.35,
  "url": "/api/inventory/products/",
  "method": "GET",
  "iterations": 15,
  "errors": 0,
  "error_rate": 0.0,
  "throughput_rps": 119.8,
  "avg_response_bytes": 5727,
  "max_response_bytes": 5727
}
```

### scale_100_customers
```json
{
  "n": 15,
  "min_ms": 45.82,
  "p50_ms": 59.08,
  "p75_ms": 62.01,
  "p90_ms": 70.02,
  "p95_ms": 70.02,
  "p99_ms": 85.79,
  "max_ms": 85.79,
  "mean_ms": 60.02,
  "url": "/api/customers/",
  "method": "GET",
  "iterations": 15,
  "errors": 0,
  "error_rate": 0.0,
  "throughput_rps": 16.7,
  "avg_response_bytes": 14020,
  "max_response_bytes": 14020
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
- P95: 67.49 ms
- Aggregate RPS: 39.3

## Database Plan Analysis

- **explain_customer_search**: uses_index=unknown
- **explain_payments_range**: uses_index=False
- **explain_visit_overlap**: uses_index=True
- **explain_visits_window**: uses_index=False

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
    "p99_ms": 0.01,
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
    "max_ms": 0.03,
    "mean_ms": 0.01
  }
}
```

### cache_stampede
```json
{
  "n": 20,
  "min_ms": 0.05,
  "p50_ms": 0.14,
  "p75_ms": 0.17,
  "p90_ms": 0.18,
  "p95_ms": 0.19,
  "p99_ms": 0.61,
  "max_ms": 0.61,
  "mean_ms": 0.15
}
```

## Background Tasks

- **background_probe**: {"celery_configured": false, "broker_configured": false, "finding": "NO Celery/broker in project. All work is synchronous in-request.", "recommendation": "For long-running report generation or bulk operations, consider adding Celery with Redis broker in production."}
- **blocking_io_check**: {"/api/dashboard/": {"time_s": 0.009, "status": 401}, "/api/reports/": {"time_s": 0.001, "status": 401}, "/api/customers/": {"time_s": 0.001, "status": 401}}

## Response Sizes

```json
{
  "bytes": 5691
}
```
```json
{
  "/api/customers/": 14035,
  "/api/visits/": 10394,
  "/api/payments/": 4400,
  "/api/services/": 6207,
  "/api/inventory/products/": 5714,
  "/api/dashboard/": 109,
  "/api/reports/": 5746,
  "/api/finance/operating-expenses/": 52,
  "/api/finance/operating-expenses/summary/": 173,
  "/api/finance/operating-expense-categories/": 2060
}
```

---
*Report generated automatically by the performance test suite.*