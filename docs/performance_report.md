# Sefro Clinic — Performance Report

**Phase:** `run`
**Metrics collected:** 48
**Data directory:** `C:\Users\Dani\Desktop\Sefro_Clinic\tests\performance\reports\data\run`

## Endpoint Benchmarks

| Endpoint | p50 (ms) | p95 (ms) | p99 (ms) | RPS | Errors |
|----------|----------|----------|----------|-----|--------|
| auth_login | 102.34 | 149.41 | 199.81 | - | - |
| auth_me | 1.09 | 2.02 | 7.8 | 662.6 | 0.0 |
| auth_refresh | 3.1 | 6.83 | 19.64 | - | - |
| crud_customer_detail | 5.25 | 6.99 | 13.26 | 179.5 | 0.0 |
| crud_customer_list | 11.95 | 19.96 | 28.04 | 72.9 | 0.0 |
| crud_customer_search | 18.21 | 21.55 | 22.44 | 53.3 | 0.0 |
| crud_payment_by_service | 88.9 | 244.29 | 302.31 | 9.3 | 0.0 |
| crud_payment_list | 8.99 | 15.08 | 27.62 | 98.7 | 0.0 |
| crud_service_list | 11.59 | 20.92 | 112.41 | 63.3 | 0.0 |
| crud_visit_list | 15.5 | 25.39 | 28.52 | 59.2 | 0.0 |
| dashboard | 8.16 | 13.75 | 14.17 | 109.5 | 0.0 |
| finance_checkout | 14.82 | 36.95 | 36.95 | - | - |
| finance_exchange_dollar | 3.67 | 4.31 | 11.3 | 243.1 | 0.0 |
| finance_expense_list | 4.31 | 7.64 | 19.5 | 187.3 | 0.0 |
| finance_financial_summary | 23.25 | 33.87 | 55.51 | 38.0 | 0.0 |
| finance_operating_expense_category_list | 4.36 | 5.21 | 16.17 | 199.1 | 0.0 |
| finance_operating_expense_list | 3.61 | 7.02 | 18.07 | 223.5 | 0.0 |
| finance_operating_expense_summary | 7.52 | 8.64 | 14.48 | 124.2 | 0.0 |
| finance_wallet_list | 5.01 | 14.09 | 18.16 | 160.6 | 0.0 |
| inventory_product_create | 5.63 | 6.38 | 14.46 | - | - |
| inventory_product_detail | 3.25 | 6.4 | 10.1 | 257.5 | 0.0 |
| inventory_product_list | 6.09 | 9.59 | 140.13 | 91.4 | 0.0 |
| inventory_product_list_size | - | - | - | - | - |
| inventory_product_search | 8.89 | 15.23 | 16.94 | 104.0 | 0.0 |
| reports_all | 108.94 | 122.2 | 122.2 | 9.3 | 0.0 |
| reports_customers | 10.81 | 16.64 | 16.72 | 85.8 | 0.0 |
| reports_daily | 6.83 | 11.54 | 20.61 | 117.8 | 0.0 |
| reports_monthly | 7.51 | 12.63 | 14.55 | 109.6 | 0.0 |
| reports_referral | 4.77 | 9.18 | 18.04 | 168.8 | 0.0 |
| reports_summary | 93.49 | 121.18 | 149.79 | 10.3 | 0.0 |
| reports_weekly | 6.31 | 9.45 | 13.4 | 147.3 | 0.0 |

## Database Performance

### scale_1000_customers
```json
{
  "n": 15,
  "min_ms": 21.07,
  "p50_ms": 59.34,
  "p75_ms": 77.31,
  "p90_ms": 118.14,
  "p95_ms": 118.14,
  "p99_ms": 156.0,
  "max_ms": 156.0,
  "mean_ms": 63.89,
  "url": "/api/customers/",
  "method": "GET",
  "iterations": 15,
  "errors": 0,
  "error_rate": 0.0,
  "throughput_rps": 15.7,
  "avg_response_bytes": 11346,
  "max_response_bytes": 11346
}
```

### scale_1000_product_search
```json
{
  "n": 10,
  "min_ms": 9.95,
  "p50_ms": 11.18,
  "p75_ms": 12.71,
  "p90_ms": 13.89,
  "p95_ms": 16.36,
  "p99_ms": 16.36,
  "max_ms": 16.36,
  "mean_ms": 11.81,
  "url": "/api/inventory/products/?search=\u0645\u062d\u0635\u0648\u0644",
  "method": "GET",
  "iterations": 10,
  "errors": 0,
  "error_rate": 0.0,
  "throughput_rps": 84.6,
  "avg_response_bytes": 5825,
  "max_response_bytes": 5825
}
```

### scale_1000_products
```json
{
  "n": 15,
  "min_ms": 5.64,
  "p50_ms": 6.22,
  "p75_ms": 7.21,
  "p90_ms": 11.53,
  "p95_ms": 11.53,
  "p99_ms": 13.01,
  "max_ms": 13.01,
  "mean_ms": 7.27,
  "url": "/api/inventory/products/",
  "method": "GET",
  "iterations": 15,
  "errors": 0,
  "error_rate": 0.0,
  "throughput_rps": 137.6,
  "avg_response_bytes": 5700,
  "max_response_bytes": 5700
}
```

### scale_100_customers
```json
{
  "n": 15,
  "min_ms": 10.38,
  "p50_ms": 14.43,
  "p75_ms": 30.76,
  "p90_ms": 45.03,
  "p95_ms": 45.03,
  "p99_ms": 67.7,
  "max_ms": 67.7,
  "mean_ms": 22.92,
  "url": "/api/customers/",
  "method": "GET",
  "iterations": 15,
  "errors": 0,
  "error_rate": 0.0,
  "throughput_rps": 43.6,
  "avg_response_bytes": 11273,
  "max_response_bytes": 11273
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
- P95: 48.1 ms
- Aggregate RPS: 52.4

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
    "max_ms": 0.06,
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
  "min_ms": 0.06,
  "p50_ms": 0.09,
  "p75_ms": 0.1,
  "p90_ms": 0.13,
  "p95_ms": 0.14,
  "p99_ms": 0.15,
  "max_ms": 0.15,
  "mean_ms": 0.09
}
```

## Background Tasks

- **background_probe**: {"celery_configured": false, "broker_configured": false, "finding": "NO Celery/broker in project. All work is synchronous in-request.", "recommendation": "For long-running report generation or bulk operations, consider adding Celery with Redis broker in production."}
- **blocking_io_check**: {"/api/dashboard/": {"time_s": 0.007, "status": 401}, "/api/reports/": {"time_s": 0.001, "status": 401}, "/api/customers/": {"time_s": 0.001, "status": 401}}

## Response Sizes

```json
{
  "bytes": 5620
}
```
```json
{
  "/api/customers/": 11298,
  "/api/visits/": 5470,
  "/api/payments/": 4412,
  "/api/services/": 6207,
  "/api/inventory/products/": 5666,
  "/api/dashboard/": 109,
  "/api/reports/": 5706,
  "/api/finance/operating-expenses/": 52,
  "/api/finance/operating-expenses/summary/": 173,
  "/api/finance/operating-expense-categories/": 2060
}
```

---
*Report generated automatically by the performance test suite.*