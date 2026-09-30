# Sefro Clinic — Performance Report

**Phase:** `run`
**Metrics collected:** 48
**Data directory:** `C:\Users\Dani\Desktop\Sefro_Clinic\tests\performance\reports\data\run`

## Endpoint Benchmarks

| Endpoint | p50 (ms) | p95 (ms) | p99 (ms) | RPS | Errors |
|----------|----------|----------|----------|-----|--------|
| auth_login | 141.45 | 164.01 | 245.47 | - | - |
| auth_me | 1.96 | 4.51 | 9.98 | 388.0 | 0.0 |
| auth_refresh | 15.45 | 23.35 | 26.39 | - | - |
| crud_customer_detail | 8.75 | 14.75 | 23.29 | 99.6 | 0.0 |
| crud_customer_list | 20.26 | 25.94 | 28.97 | 47.3 | 0.0 |
| crud_customer_search | 24.43 | 36.89 | 45.56 | 37.0 | 0.0 |
| crud_payment_by_service | 95.05 | 245.5 | 354.1 | 8.4 | 0.0 |
| crud_payment_list | 8.39 | 10.49 | 15.37 | 111.6 | 0.0 |
| crud_service_list | 11.31 | 20.36 | 34.2 | 75.9 | 0.0 |
| crud_visit_list | 22.05 | 29.64 | 37.72 | 41.8 | 0.0 |
| dashboard | 80.14 | 198.75 | 476.44 | 9.0 | 0.0 |
| finance_checkout | 14.14 | 37.74 | 37.74 | - | - |
| finance_exchange_dollar | 3.3 | 3.79 | 11.37 | 265.4 | 0.0 |
| finance_expense_list | 3.76 | 4.36 | 16.57 | 225.7 | 0.0 |
| finance_financial_summary | 22.41 | 32.87 | 55.9 | 38.9 | 0.0 |
| finance_operating_expense_category_list | 4.52 | 5.66 | 16.78 | 191.0 | 0.0 |
| finance_operating_expense_list | 3.49 | 4.59 | 27.16 | 210.9 | 0.0 |
| finance_operating_expense_summary | 7.57 | 8.41 | 15.4 | 124.0 | 0.0 |
| finance_wallet_list | 4.69 | 5.97 | 13.92 | 188.1 | 0.0 |
| inventory_product_create | 5.34 | 6.45 | 14.15 | - | - |
| inventory_product_detail | 3.21 | 4.34 | 9.9 | 273.7 | 0.0 |
| inventory_product_list | 5.72 | 7.56 | 12.57 | 160.3 | 0.0 |
| inventory_product_list_size | - | - | - | - | - |
| inventory_product_search | 8.34 | 18.37 | 313.86 | 40.2 | 0.0 |
| reports_all | 103.73 | 124.48 | 124.48 | 9.6 | 0.0 |
| reports_customers | 161.12 | 237.42 | 273.42 | 5.8 | 0.0 |
| reports_daily | 6.13 | 8.55 | 22.48 | 135.1 | 0.0 |
| reports_monthly | 10.91 | 12.89 | 18.2 | 87.0 | 0.0 |
| reports_referral | 111.82 | 197.04 | 209.82 | 8.1 | 0.0 |
| reports_summary | 109.19 | 130.74 | 152.69 | 9.1 | 0.0 |
| reports_weekly | 10.4 | 13.92 | 17.07 | 89.3 | 0.0 |

## Database Performance

### scale_1000_customers
```json
{
  "n": 15,
  "min_ms": 26.19,
  "p50_ms": 47.76,
  "p75_ms": 61.28,
  "p90_ms": 104.16,
  "p95_ms": 104.16,
  "p99_ms": 118.66,
  "max_ms": 118.66,
  "mean_ms": 54.99,
  "url": "/api/customers/",
  "method": "GET",
  "iterations": 15,
  "errors": 0,
  "error_rate": 0.0,
  "throughput_rps": 18.2,
  "avg_response_bytes": 14107,
  "max_response_bytes": 14107
}
```

### scale_1000_product_search
```json
{
  "n": 10,
  "min_ms": 10.28,
  "p50_ms": 10.78,
  "p75_ms": 12.02,
  "p90_ms": 18.92,
  "p95_ms": 21.79,
  "p99_ms": 21.79,
  "max_ms": 21.79,
  "mean_ms": 12.87,
  "url": "/api/inventory/products/?search=\u0645\u062d\u0635\u0648\u0644",
  "method": "GET",
  "iterations": 10,
  "errors": 0,
  "error_rate": 0.0,
  "throughput_rps": 77.7,
  "avg_response_bytes": 5763,
  "max_response_bytes": 5763
}
```

### scale_1000_products
```json
{
  "n": 15,
  "min_ms": 6.16,
  "p50_ms": 7.75,
  "p75_ms": 7.87,
  "p90_ms": 12.44,
  "p95_ms": 12.44,
  "p99_ms": 14.7,
  "max_ms": 14.7,
  "mean_ms": 8.15,
  "url": "/api/inventory/products/",
  "method": "GET",
  "iterations": 15,
  "errors": 0,
  "error_rate": 0.0,
  "throughput_rps": 122.8,
  "avg_response_bytes": 5675,
  "max_response_bytes": 5675
}
```

### scale_100_customers
```json
{
  "n": 15,
  "min_ms": 15.97,
  "p50_ms": 19.63,
  "p75_ms": 20.69,
  "p90_ms": 27.07,
  "p95_ms": 27.07,
  "p99_ms": 38.0,
  "max_ms": 38.0,
  "mean_ms": 21.38,
  "url": "/api/customers/",
  "method": "GET",
  "iterations": 15,
  "errors": 0,
  "error_rate": 0.0,
  "throughput_rps": 46.8,
  "avg_response_bytes": 14024,
  "max_response_bytes": 14024
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
- P95: 63.6 ms
- Aggregate RPS: 63.5

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
    "p99_ms": 0.03,
    "max_ms": 0.03,
    "mean_ms": 0.01
  },
  "get": {
    "n": 100,
    "min_ms": 0.01,
    "p50_ms": 0.01,
    "p75_ms": 0.01,
    "p90_ms": 0.01,
    "p95_ms": 0.01,
    "p99_ms": 0.01,
    "max_ms": 0.02,
    "mean_ms": 0.01
  }
}
```

### cache_stampede
```json
{
  "n": 20,
  "min_ms": 0.06,
  "p50_ms": 0.11,
  "p75_ms": 0.13,
  "p90_ms": 0.15,
  "p95_ms": 0.19,
  "p99_ms": 0.19,
  "max_ms": 0.19,
  "mean_ms": 0.11
}
```

## Background Tasks

- **background_probe**: {"celery_configured": false, "broker_configured": false, "finding": "NO Celery/broker in project. All work is synchronous in-request.", "recommendation": "For long-running report generation or bulk operations, consider adding Celery with Redis broker in production."}
- **blocking_io_check**: {"/api/dashboard/": {"time_s": 0.008, "status": 401}, "/api/reports/": {"time_s": 0.001, "status": 401}, "/api/customers/": {"time_s": 0.001, "status": 401}}

## Response Sizes

```json
{
  "bytes": 5691
}
```
```json
{
  "/api/customers/": 14032,
  "/api/visits/": 11203,
  "/api/payments/": 4417,
  "/api/services/": 6207,
  "/api/inventory/products/": 5647,
  "/api/dashboard/": 109,
  "/api/reports/": 5749,
  "/api/finance/operating-expenses/": 52,
  "/api/finance/operating-expenses/summary/": 173,
  "/api/finance/operating-expense-categories/": 2060
}
```

---
*Report generated automatically by the performance test suite.*