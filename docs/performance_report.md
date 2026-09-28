# Sefro Clinic — Performance Report

**Phase:** `run`
**Metrics collected:** 48
**Data directory:** `C:\Users\Dani\Desktop\Sefro_Clinic\tests\performance\reports\data\run`

## Endpoint Benchmarks

| Endpoint | p50 (ms) | p95 (ms) | p99 (ms) | RPS | Errors |
|----------|----------|----------|----------|-----|--------|
| auth_login | 142.07 | 188.5 | 222.03 | - | - |
| auth_me | 1.34 | 2.94 | 10.8 | 525.2 | 0.0 |
| auth_refresh | 3.49 | 8.4 | 28.79 | - | - |
| crud_customer_detail | 6.41 | 9.83 | 16.58 | 140.0 | 0.0 |
| crud_customer_list | 13.87 | 23.02 | 25.94 | 65.5 | 0.0 |
| crud_customer_search | 17.68 | 26.9 | 31.35 | 52.3 | 0.0 |
| crud_payment_by_service | 99.28 | 274.09 | 384.73 | 7.9 | 0.0 |
| crud_payment_list | 9.62 | 16.14 | 33.46 | 89.3 | 0.0 |
| crud_service_list | 12.09 | 29.65 | 165.45 | 53.4 | 0.0 |
| crud_visit_list | 16.74 | 24.23 | 241.47 | 40.0 | 0.0 |
| dashboard | 7.9 | 8.95 | 15.49 | 120.2 | 0.0 |
| finance_checkout | 17.71 | 41.48 | 41.48 | - | - |
| finance_exchange_dollar | 4.52 | 12.31 | 19.27 | 167.0 | 0.0 |
| finance_expense_list | 4.39 | 6.58 | 20.03 | 188.3 | 0.0 |
| finance_financial_summary | 29.85 | 36.09 | 72.18 | 30.8 | 0.0 |
| finance_operating_expense_category_list | 5.33 | 8.73 | 20.44 | 153.5 | 0.0 |
| finance_operating_expense_list | 4.26 | 18.67 | 21.32 | 159.3 | 0.0 |
| finance_operating_expense_summary | 9.46 | 18.06 | 19.01 | 89.5 | 0.0 |
| finance_wallet_list | 6.0 | 15.41 | 25.2 | 129.6 | 0.0 |
| inventory_product_create | 5.82 | 7.58 | 14.55 | - | - |
| inventory_product_detail | 3.58 | 4.95 | 15.53 | 242.2 | 0.0 |
| inventory_product_list | 6.4 | 8.44 | 13.4 | 146.9 | 0.0 |
| inventory_product_list_size | - | - | - | - | - |
| inventory_product_search | 8.77 | 13.93 | 18.59 | 104.4 | 0.0 |
| reports_all | 102.62 | 128.19 | 128.19 | 9.4 | 0.0 |
| reports_customers | 10.95 | 18.59 | 30.04 | 78.3 | 0.0 |
| reports_daily | 7.66 | 9.28 | 16.9 | 119.9 | 0.0 |
| reports_monthly | 9.92 | 17.47 | 17.69 | 89.9 | 0.0 |
| reports_referral | 5.38 | 6.24 | 13.8 | 168.0 | 0.0 |
| reports_summary | 106.68 | 159.52 | 178.06 | 9.1 | 0.0 |
| reports_weekly | 9.01 | 10.69 | 22.56 | 99.7 | 0.0 |

## Database Performance

### scale_1000_customers
```json
{
  "n": 15,
  "min_ms": 17.15,
  "p50_ms": 21.43,
  "p75_ms": 23.86,
  "p90_ms": 26.56,
  "p95_ms": 26.56,
  "p99_ms": 33.08,
  "max_ms": 33.08,
  "mean_ms": 21.92,
  "url": "/api/customers/",
  "method": "GET",
  "iterations": 15,
  "errors": 0,
  "error_rate": 0.0,
  "throughput_rps": 45.6,
  "avg_response_bytes": 11344,
  "max_response_bytes": 11344
}
```

### scale_1000_product_search
```json
{
  "n": 10,
  "min_ms": 10.5,
  "p50_ms": 11.26,
  "p75_ms": 14.06,
  "p90_ms": 15.78,
  "p95_ms": 18.56,
  "p99_ms": 18.56,
  "max_ms": 18.56,
  "mean_ms": 12.7,
  "url": "/api/inventory/products/?search=\u0645\u062d\u0635\u0648\u0644",
  "method": "GET",
  "iterations": 10,
  "errors": 0,
  "error_rate": 0.0,
  "throughput_rps": 78.7,
  "avg_response_bytes": 5806,
  "max_response_bytes": 5806
}
```

### scale_1000_products
```json
{
  "n": 15,
  "min_ms": 5.77,
  "p50_ms": 6.55,
  "p75_ms": 6.82,
  "p90_ms": 7.83,
  "p95_ms": 7.83,
  "p99_ms": 14.3,
  "max_ms": 14.3,
  "mean_ms": 7.08,
  "url": "/api/inventory/products/",
  "method": "GET",
  "iterations": 15,
  "errors": 0,
  "error_rate": 0.0,
  "throughput_rps": 141.2,
  "avg_response_bytes": 5752,
  "max_response_bytes": 5752
}
```

### scale_100_customers
```json
{
  "n": 15,
  "min_ms": 10.0,
  "p50_ms": 12.35,
  "p75_ms": 13.96,
  "p90_ms": 19.62,
  "p95_ms": 19.62,
  "p99_ms": 27.25,
  "max_ms": 27.25,
  "mean_ms": 14.03,
  "url": "/api/customers/",
  "method": "GET",
  "iterations": 15,
  "errors": 0,
  "error_rate": 0.0,
  "throughput_rps": 71.3,
  "avg_response_bytes": 11278,
  "max_response_bytes": 11278
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
- P95: 53.85 ms
- Aggregate RPS: 81.3

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
  "min_ms": 0.08,
  "p50_ms": 0.14,
  "p75_ms": 0.16,
  "p90_ms": 0.34,
  "p95_ms": 1.27,
  "p99_ms": 3.31,
  "max_ms": 3.31,
  "mean_ms": 0.36
}
```

## Background Tasks

- **background_probe**: {"celery_configured": false, "broker_configured": false, "finding": "NO Celery/broker in project. All work is synchronous in-request.", "recommendation": "For long-running report generation or bulk operations, consider adding Celery with Redis broker in production."}
- **blocking_io_check**: {"/api/dashboard/": {"time_s": 0.009, "status": 401}, "/api/reports/": {"time_s": 0.001, "status": 401}, "/api/customers/": {"time_s": 0.001, "status": 401}}

## Response Sizes

```json
{
  "bytes": 5665
}
```
```json
{
  "/api/customers/": 11295,
  "/api/visits/": 5479,
  "/api/payments/": 4416,
  "/api/services/": 6207,
  "/api/inventory/products/": 5680,
  "/api/dashboard/": 108,
  "/api/reports/": 5743,
  "/api/finance/operating-expenses/": 52,
  "/api/finance/operating-expenses/summary/": 173,
  "/api/finance/operating-expense-categories/": 2060
}
```

---
*Report generated automatically by the performance test suite.*