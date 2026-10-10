# Sefro Clinic — Performance Report

**Phase:** `run`
**Metrics collected:** 48
**Data directory:** `C:\Users\Dani\Desktop\Sefro_Clinic\tests\performance\reports\data\run`

## Endpoint Benchmarks

| Endpoint | p50 (ms) | p95 (ms) | p99 (ms) | RPS | Errors |
|----------|----------|----------|----------|-----|--------|
| auth_login | 253.65 | 539.24 | 596.19 | - | - |
| auth_me | 1.61 | 5.32 | 16.07 | 360.1 | 0.0 |
| auth_refresh | 13.7 | 18.03 | 22.07 | - | - |
| crud_customer_detail | 10.31 | 14.14 | 25.68 | 87.2 | 0.0 |
| crud_customer_list | 22.66 | 120.24 | 230.19 | 21.4 | 0.0 |
| crud_customer_search | 30.28 | 100.76 | 121.85 | 23.0 | 0.0 |
| crud_payment_by_service | 124.16 | 310.9 | 423.08 | 6.6 | 0.0 |
| crud_payment_list | 9.46 | 11.2 | 17.17 | 102.0 | 0.0 |
| crud_service_list | 13.35 | 19.22 | 50.3 | 65.7 | 0.0 |
| crud_visit_list | 25.4 | 39.43 | 416.27 | 25.1 | 0.0 |
| dashboard | 9.9 | 15.83 | 17.1 | 91.5 | 0.0 |
| finance_checkout | 18.89 | 45.33 | 45.33 | - | - |
| finance_exchange_dollar | 4.2 | 7.6 | 11.39 | 204.1 | 0.0 |
| finance_expense_list | 5.03 | 7.81 | 20.69 | 167.1 | 0.0 |
| finance_financial_summary | 41.34 | 60.82 | 97.74 | 21.6 | 0.0 |
| finance_operating_expense_category_list | 4.95 | 14.22 | 20.12 | 155.1 | 0.0 |
| finance_operating_expense_list | 4.14 | 5.66 | 13.08 | 211.8 | 0.0 |
| finance_operating_expense_summary | 8.31 | 12.28 | 19.2 | 107.8 | 0.0 |
| finance_wallet_list | 5.1 | 7.02 | 17.07 | 165.9 | 0.0 |
| inventory_product_create | 6.69 | 11.73 | 16.63 | - | - |
| inventory_product_detail | 3.55 | 4.88 | 13.82 | 240.8 | 0.0 |
| inventory_product_list | 6.66 | 8.37 | 14.71 | 138.9 | 0.0 |
| inventory_product_list_size | - | - | - | - | - |
| inventory_product_search | 9.1 | 11.04 | 24.23 | 98.0 | 0.0 |
| reports_all | 94.27 | 206.03 | 206.03 | 9.0 | 0.0 |
| reports_customers | 11.36 | 16.88 | 22.14 | 79.6 | 0.0 |
| reports_daily | 7.61 | 11.02 | 20.04 | 111.8 | 0.0 |
| reports_monthly | 16.0 | 19.28 | 24.46 | 61.6 | 0.0 |
| reports_referral | 5.11 | 11.05 | 12.5 | 157.4 | 0.0 |
| reports_summary | 95.43 | 133.99 | 148.52 | 9.6 | 0.0 |
| reports_weekly | 11.46 | 17.02 | 42.94 | 75.9 | 0.0 |

## Database Performance

### scale_1000_customers
```json
{
  "n": 15,
  "min_ms": 13.93,
  "p50_ms": 16.33,
  "p75_ms": 17.69,
  "p90_ms": 23.18,
  "p95_ms": 23.18,
  "p99_ms": 23.56,
  "max_ms": 23.56,
  "mean_ms": 17.15,
  "url": "/api/customers/",
  "method": "GET",
  "iterations": 15,
  "errors": 0,
  "error_rate": 0.0,
  "throughput_rps": 58.3,
  "avg_response_bytes": 14105,
  "max_response_bytes": 14105
}
```

### scale_1000_product_search
```json
{
  "n": 10,
  "min_ms": 10.81,
  "p50_ms": 11.49,
  "p75_ms": 12.35,
  "p90_ms": 12.46,
  "p95_ms": 18.27,
  "p99_ms": 18.27,
  "max_ms": 18.27,
  "mean_ms": 12.21,
  "url": "/api/inventory/products/?search=\u0645\u062d\u0635\u0648\u0644",
  "method": "GET",
  "iterations": 10,
  "errors": 0,
  "error_rate": 0.0,
  "throughput_rps": 81.9,
  "avg_response_bytes": 5760,
  "max_response_bytes": 5760
}
```

### scale_1000_products
```json
{
  "n": 15,
  "min_ms": 4.81,
  "p50_ms": 6.07,
  "p75_ms": 6.3,
  "p90_ms": 8.96,
  "p95_ms": 8.96,
  "p99_ms": 14.4,
  "max_ms": 14.4,
  "mean_ms": 6.72,
  "url": "/api/inventory/products/",
  "method": "GET",
  "iterations": 15,
  "errors": 0,
  "error_rate": 0.0,
  "throughput_rps": 148.8,
  "avg_response_bytes": 5731,
  "max_response_bytes": 5731
}
```

### scale_100_customers
```json
{
  "n": 15,
  "min_ms": 13.18,
  "p50_ms": 15.91,
  "p75_ms": 17.43,
  "p90_ms": 23.18,
  "p95_ms": 23.18,
  "p99_ms": 34.44,
  "max_ms": 34.44,
  "mean_ms": 17.32,
  "url": "/api/customers/",
  "method": "GET",
  "iterations": 15,
  "errors": 0,
  "error_rate": 0.0,
  "throughput_rps": 57.7,
  "avg_response_bytes": 14030,
  "max_response_bytes": 14030
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
- P95: 65.66 ms
- Aggregate RPS: 31.5

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
    "max_ms": 0.02,
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
  "p75_ms": 0.22,
  "p90_ms": 0.79,
  "p95_ms": 2.13,
  "p99_ms": 2.65,
  "max_ms": 2.65,
  "mean_ms": 0.42
}
```

## Background Tasks

- **background_probe**: {"celery_configured": false, "broker_configured": false, "finding": "NO Celery/broker in project. All work is synchronous in-request.", "recommendation": "For long-running report generation or bulk operations, consider adding Celery with Redis broker in production."}
- **blocking_io_check**: {"/api/dashboard/": {"time_s": 0.01, "status": 401}, "/api/reports/": {"time_s": 0.002, "status": 401}, "/api/customers/": {"time_s": 0.001, "status": 401}}

## Response Sizes

```json
{
  "bytes": 5700
}
```
```json
{
  "/api/customers/": 14028,
  "/api/visits/": 11184,
  "/api/payments/": 4404,
  "/api/services/": 6207,
  "/api/inventory/products/": 5688,
  "/api/dashboard/": 108,
  "/api/reports/": 5750,
  "/api/finance/operating-expenses/": 52,
  "/api/finance/operating-expenses/summary/": 173,
  "/api/finance/operating-expense-categories/": 2060
}
```

---
*Report generated automatically by the performance test suite.*