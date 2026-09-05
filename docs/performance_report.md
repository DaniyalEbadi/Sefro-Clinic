# Sefro Clinic — Performance Report

**Phase:** `run`
**Metrics collected:** 45
**Data directory:** `C:\Users\Dani\Desktop\Sefro_Clinic\tests\performance\reports\data\run`

## Endpoint Benchmarks

| Endpoint | p50 (ms) | p95 (ms) | p99 (ms) | RPS | Errors |
|----------|----------|----------|----------|-----|--------|
| auth_login | 134.56 | 200.64 | 202.61 | - | - |
| auth_me | 1.26 | 2.12 | 10.9 | 566.2 | 0.0 |
| auth_refresh | 3.55 | 5.04 | 24.9 | - | - |
| crud_customer_detail | 5.47 | 8.26 | 19.37 | 161.6 | 0.0 |
| crud_customer_list | 13.28 | 16.91 | 22.46 | 71.4 | 0.0 |
| crud_customer_search | 19.63 | 27.19 | 31.6 | 48.1 | 0.0 |
| crud_payment_by_service | 85.2 | 198.56 | 205.38 | 9.7 | 0.0 |
| crud_payment_list | 8.62 | 13.17 | 15.54 | 107.0 | 0.0 |
| crud_service_list | 12.81 | 19.16 | 39.12 | 67.3 | 0.0 |
| crud_visit_list | 13.26 | 17.99 | 22.35 | 71.1 | 0.0 |
| dashboard | 10.87 | 17.96 | 18.5 | 79.9 | 0.0 |
| finance_checkout | 14.97 | 45.6 | 45.6 | - | - |
| finance_exchange_dollar | 3.25 | 6.07 | 9.66 | 263.6 | 0.0 |
| finance_expense_list | 3.0 | 4.5 | 19.66 | 246.5 | 0.0 |
| finance_financial_summary | 18.48 | 23.46 | 38.54 | 49.7 | 0.0 |
| finance_wallet_list | 4.34 | 9.23 | 15.35 | 190.2 | 0.0 |
| inventory_product_create | 4.99 | 7.77 | 11.69 | - | - |
| inventory_product_detail | 2.45 | 5.23 | 9.32 | 332.9 | 0.0 |
| inventory_product_list | 5.32 | 8.41 | 13.74 | 168.0 | 0.0 |
| inventory_product_list_size | - | - | - | - | - |
| inventory_product_search | 7.54 | 10.39 | 13.78 | 124.5 | 0.0 |
| reports_all | 76.09 | 92.75 | 92.75 | 12.9 | 0.0 |
| reports_customers | 7.56 | 10.48 | 13.86 | 121.2 | 0.0 |
| reports_daily | 6.48 | 11.02 | 13.15 | 133.9 | 0.0 |
| reports_monthly | 18.95 | 30.45 | 31.5 | 47.7 | 0.0 |
| reports_referral | 4.14 | 7.42 | 12.07 | 195.5 | 0.0 |
| reports_summary | 70.96 | 79.96 | 87.62 | 13.7 | 0.0 |
| reports_weekly | 8.26 | 11.22 | 16.44 | 113.1 | 0.0 |

## Database Performance

### scale_1000_customers
```json
{
  "n": 15,
  "min_ms": 14.86,
  "p50_ms": 16.9,
  "p75_ms": 17.58,
  "p90_ms": 18.49,
  "p95_ms": 18.49,
  "p99_ms": 25.56,
  "max_ms": 25.56,
  "mean_ms": 17.42,
  "url": "/api/customers/",
  "method": "GET",
  "iterations": 15,
  "errors": 0,
  "error_rate": 0.0,
  "throughput_rps": 57.4,
  "avg_response_bytes": 10965,
  "max_response_bytes": 10965
}
```

### scale_1000_product_search
```json
{
  "n": 10,
  "min_ms": 9.55,
  "p50_ms": 11.43,
  "p75_ms": 15.7,
  "p90_ms": 17.82,
  "p95_ms": 18.97,
  "p99_ms": 18.97,
  "max_ms": 18.97,
  "mean_ms": 13.01,
  "url": "/api/inventory/products/?search=\u0645\u062d\u0635\u0648\u0644",
  "method": "GET",
  "iterations": 10,
  "errors": 0,
  "error_rate": 0.0,
  "throughput_rps": 76.9,
  "avg_response_bytes": 4989,
  "max_response_bytes": 4989
}
```

### scale_1000_products
```json
{
  "n": 15,
  "min_ms": 4.46,
  "p50_ms": 5.39,
  "p75_ms": 5.66,
  "p90_ms": 7.11,
  "p95_ms": 7.11,
  "p99_ms": 12.86,
  "max_ms": 12.86,
  "mean_ms": 5.9,
  "url": "/api/inventory/products/",
  "method": "GET",
  "iterations": 15,
  "errors": 0,
  "error_rate": 0.0,
  "throughput_rps": 169.4,
  "avg_response_bytes": 4862,
  "max_response_bytes": 4862
}
```

### scale_100_customers
```json
{
  "n": 15,
  "min_ms": 9.17,
  "p50_ms": 11.39,
  "p75_ms": 11.77,
  "p90_ms": 14.38,
  "p95_ms": 14.38,
  "p99_ms": 24.92,
  "max_ms": 24.92,
  "mean_ms": 12.17,
  "url": "/api/customers/",
  "method": "GET",
  "iterations": 15,
  "errors": 0,
  "error_rate": 0.0,
  "throughput_rps": 82.2,
  "avg_response_bytes": 10899,
  "max_response_bytes": 10899
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
- P95: 54.32 ms
- Aggregate RPS: 63.8

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
    "p99_ms": 0.01,
    "max_ms": 0.04,
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
  "min_ms": 0.05,
  "p50_ms": 0.07,
  "p75_ms": 0.09,
  "p90_ms": 0.13,
  "p95_ms": 0.18,
  "p99_ms": 0.23,
  "max_ms": 0.23,
  "mean_ms": 0.09
}
```

## Background Tasks

- **background_probe**: {"celery_configured": false, "broker_configured": false, "finding": "NO Celery/broker in project. All work is synchronous in-request.", "recommendation": "For long-running report generation or bulk operations, consider adding Celery with Redis broker in production."}
- **blocking_io_check**: {"/api/dashboard/": {"time_s": 0.007, "status": 401}, "/api/reports/": {"time_s": 0.001, "status": 401}, "/api/customers/": {"time_s": 0.001, "status": 401}}

## Response Sizes

```json
{
  "bytes": 4834
}
```
```json
{
  "/api/customers/": 10893,
  "/api/visits/": 5381,
  "/api/payments/": 4384,
  "/api/services/": 5787,
  "/api/inventory/products/": 4908,
  "/api/dashboard/": 108,
  "/api/reports/": 5728
}
```

---
*Report generated automatically by the performance test suite.*