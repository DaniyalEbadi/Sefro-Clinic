# Sefro Clinic — Performance Report

**Phase:** `run`
**Metrics collected:** 45
**Data directory:** `C:\Users\Dani\Desktop\Sefro_Clinic\tests\performance\reports\data\run`

## Endpoint Benchmarks

| Endpoint | p50 (ms) | p95 (ms) | p99 (ms) | RPS | Errors |
|----------|----------|----------|----------|-----|--------|
| auth_login | 144.21 | 236.15 | 245.84 | - | - |
| auth_me | 1.36 | 2.27 | 9.18 | 574.6 | 0.0 |
| auth_refresh | 5.79 | 8.36 | 25.6 | - | - |
| crud_customer_detail | 4.41 | 5.41 | 12.08 | 210.8 | 0.0 |
| crud_customer_list | 12.54 | 17.64 | 21.9 | 73.2 | 0.0 |
| crud_customer_search | 18.82 | 23.91 | 24.92 | 51.9 | 0.0 |
| crud_payment_by_service | 104.52 | 283.72 | 288.56 | 8.3 | 0.0 |
| crud_payment_list | 8.0 | 9.08 | 13.77 | 120.7 | 0.0 |
| crud_service_list | 9.98 | 14.35 | 27.41 | 93.1 | 0.0 |
| crud_visit_list | 16.61 | 24.8 | 34.44 | 55.6 | 0.0 |
| dashboard | 10.05 | 14.87 | 16.7 | 100.7 | 0.0 |
| finance_checkout | 15.21 | 36.05 | 36.05 | - | - |
| finance_exchange_dollar | 3.25 | 4.16 | 10.34 | 265.9 | 0.0 |
| finance_expense_list | 3.56 | 8.05 | 15.95 | 213.8 | 0.0 |
| finance_financial_summary | 20.36 | 31.94 | 59.43 | 42.7 | 0.0 |
| finance_wallet_list | 5.25 | 12.87 | 26.86 | 148.4 | 0.0 |
| inventory_product_create | 9.34 | 13.34 | 20.88 | - | - |
| inventory_product_detail | 4.47 | 5.54 | 10.52 | 214.2 | 0.0 |
| inventory_product_list | 8.17 | 14.39 | 23.39 | 107.0 | 0.0 |
| inventory_product_list_size | - | - | - | - | - |
| inventory_product_search | 7.94 | 10.14 | 17.23 | 115.5 | 0.0 |
| reports_all | 81.56 | 130.29 | 130.29 | 10.5 | 0.0 |
| reports_customers | 8.08 | 9.87 | 13.63 | 118.1 | 0.0 |
| reports_daily | 5.74 | 7.3 | 13.09 | 158.9 | 0.0 |
| reports_monthly | 24.64 | 30.88 | 31.93 | 38.4 | 0.0 |
| reports_referral | 5.1 | 7.07 | 14.51 | 171.9 | 0.0 |
| reports_summary | 71.95 | 83.5 | 84.33 | 13.5 | 0.0 |
| reports_weekly | 12.73 | 13.46 | 20.52 | 78.7 | 0.0 |

## Database Performance

### scale_1000_customers
```json
{
  "n": 15,
  "min_ms": 15.64,
  "p50_ms": 19.92,
  "p75_ms": 20.79,
  "p90_ms": 22.69,
  "p95_ms": 22.69,
  "p99_ms": 27.49,
  "max_ms": 27.49,
  "mean_ms": 19.73,
  "url": "/api/customers/",
  "method": "GET",
  "iterations": 15,
  "errors": 0,
  "error_rate": 0.0,
  "throughput_rps": 50.7,
  "avg_response_bytes": 11346,
  "max_response_bytes": 11346
}
```

### scale_1000_product_search
```json
{
  "n": 10,
  "min_ms": 8.96,
  "p50_ms": 10.48,
  "p75_ms": 12.39,
  "p90_ms": 12.69,
  "p95_ms": 17.03,
  "p99_ms": 17.03,
  "max_ms": 17.03,
  "mean_ms": 11.22,
  "url": "/api/inventory/products/?search=\u0645\u062d\u0635\u0648\u0644",
  "method": "GET",
  "iterations": 10,
  "errors": 0,
  "error_rate": 0.0,
  "throughput_rps": 89.1,
  "avg_response_bytes": 5001,
  "max_response_bytes": 5001
}
```

### scale_1000_products
```json
{
  "n": 15,
  "min_ms": 5.51,
  "p50_ms": 6.56,
  "p75_ms": 7.1,
  "p90_ms": 8.1,
  "p95_ms": 8.1,
  "p99_ms": 13.49,
  "max_ms": 13.49,
  "mean_ms": 7.15,
  "url": "/api/inventory/products/",
  "method": "GET",
  "iterations": 15,
  "errors": 0,
  "error_rate": 0.0,
  "throughput_rps": 139.8,
  "avg_response_bytes": 4914,
  "max_response_bytes": 4914
}
```

### scale_100_customers
```json
{
  "n": 15,
  "min_ms": 9.58,
  "p50_ms": 11.64,
  "p75_ms": 12.79,
  "p90_ms": 14.08,
  "p95_ms": 14.08,
  "p99_ms": 26.48,
  "max_ms": 26.48,
  "mean_ms": 12.63,
  "url": "/api/customers/",
  "method": "GET",
  "iterations": 15,
  "errors": 0,
  "error_rate": 0.0,
  "throughput_rps": 79.2,
  "avg_response_bytes": 11282,
  "max_response_bytes": 11282
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
- P95: 48.2 ms
- Aggregate RPS: 67.3

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
  "min_ms": 0.07,
  "p50_ms": 0.08,
  "p75_ms": 0.09,
  "p90_ms": 0.1,
  "p95_ms": 0.11,
  "p99_ms": 0.15,
  "max_ms": 0.15,
  "mean_ms": 0.08
}
```

## Background Tasks

- **background_probe**: {"celery_configured": false, "broker_configured": false, "finding": "NO Celery/broker in project. All work is synchronous in-request.", "recommendation": "For long-running report generation or bulk operations, consider adding Celery with Redis broker in production."}
- **blocking_io_check**: {"/api/dashboard/": {"time_s": 0.009, "status": 401}, "/api/reports/": {"time_s": 0.001, "status": 401}, "/api/customers/": {"time_s": 0.002, "status": 401}}

## Response Sizes

```json
{
  "bytes": 4917
}
```
```json
{
  "/api/customers/": 11271,
  "/api/visits/": 5463,
  "/api/payments/": 4405,
  "/api/services/": 5802,
  "/api/inventory/products/": 4869,
  "/api/dashboard/": 108,
  "/api/reports/": 5743
}
```

---
*Report generated automatically by the performance test suite.*