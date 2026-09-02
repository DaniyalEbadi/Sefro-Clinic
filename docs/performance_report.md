# Sefro Clinic — Performance Report

**Phase:** `run`
**Metrics collected:** 40
**Data directory:** `C:\Users\Dani\Desktop\Sefro_Clinic\tests\performance\reports\data\run`

## Endpoint Benchmarks

| Endpoint | p50 (ms) | p95 (ms) | p99 (ms) | RPS | Errors |
|----------|----------|----------|----------|-----|--------|
| auth_login | 188.2 | 290.46 | 313.5 | - | - |
| auth_me | 3.49 | 6.28 | 15.96 | 244.4 | 0.0 |
| auth_refresh | 7.9 | 13.23 | 41.84 | - | - |
| crud_customer_detail | 8.02 | 11.14 | 26.02 | 112.7 | 0.0 |
| crud_customer_list | 24.01 | 30.78 | 39.55 | 39.0 | 0.0 |
| crud_customer_search | 31.53 | 38.52 | 45.92 | 30.9 | 0.0 |
| crud_payment_by_service | 216.82 | 350.62 | 440.19 | 4.2 | 0.0 |
| crud_payment_list | 16.57 | 20.78 | 36.5 | 56.9 | 0.0 |
| crud_service_list | 21.14 | 34.72 | 254.76 | 32.8 | 0.0 |
| crud_visit_list | 28.44 | 38.97 | 40.18 | 32.9 | 0.0 |
| dashboard | 13.22 | 25.79 | 26.25 | 65.0 | 0.0 |
| inventory_product_create | 9.59 | 15.39 | 23.76 | - | - |
| inventory_product_detail | 5.75 | 9.21 | 18.97 | 153.4 | 0.0 |
| inventory_product_list | 9.78 | 13.06 | 22.73 | 94.9 | 0.0 |
| inventory_product_list_size | - | - | - | - | - |
| inventory_product_search | 11.54 | 22.81 | 49.22 | 70.3 | 0.0 |
| reports_all | 203.34 | 339.62 | 339.62 | 4.5 | 0.0 |
| reports_customers | 15.89 | 21.99 | 28.42 | 57.9 | 0.0 |
| reports_daily | 11.04 | 16.3 | 27.82 | 79.6 | 0.0 |
| reports_monthly | 24.99 | 34.79 | 46.92 | 35.6 | 0.0 |
| reports_referral | 77.54 | 276.99 | 295.54 | 8.0 | 0.0 |
| reports_summary | 219.85 | 315.3 | 331.47 | 4.1 | 0.0 |
| reports_weekly | 19.27 | 25.43 | 33.55 | 48.1 | 0.0 |

## Database Performance

### scale_1000_customers
```json
{
  "n": 15,
  "min_ms": 16.79,
  "p50_ms": 20.14,
  "p75_ms": 22.59,
  "p90_ms": 25.17,
  "p95_ms": 25.17,
  "p99_ms": 40.52,
  "max_ms": 40.52,
  "mean_ms": 21.56,
  "url": "/api/customers/",
  "method": "GET",
  "iterations": 15,
  "errors": 0,
  "error_rate": 0.0,
  "throughput_rps": 46.4,
  "avg_response_bytes": 10649,
  "max_response_bytes": 10649
}
```

### scale_1000_product_search
```json
{
  "n": 10,
  "min_ms": 9.3,
  "p50_ms": 10.01,
  "p75_ms": 10.31,
  "p90_ms": 10.41,
  "p95_ms": 16.73,
  "p99_ms": 16.73,
  "max_ms": 16.73,
  "mean_ms": 10.58,
  "url": "/api/inventory/products/?search=\u0645\u062d\u0635\u0648\u0644",
  "method": "GET",
  "iterations": 10,
  "errors": 0,
  "error_rate": 0.0,
  "throughput_rps": 94.5,
  "avg_response_bytes": 4965,
  "max_response_bytes": 4965
}
```

### scale_1000_products
```json
{
  "n": 15,
  "min_ms": 5.85,
  "p50_ms": 6.98,
  "p75_ms": 7.73,
  "p90_ms": 10.08,
  "p95_ms": 10.08,
  "p99_ms": 13.91,
  "max_ms": 13.91,
  "mean_ms": 7.6,
  "url": "/api/inventory/products/",
  "method": "GET",
  "iterations": 15,
  "errors": 0,
  "error_rate": 0.0,
  "throughput_rps": 131.6,
  "avg_response_bytes": 4898,
  "max_response_bytes": 4898
}
```

### scale_100_customers
```json
{
  "n": 15,
  "min_ms": 10.03,
  "p50_ms": 13.32,
  "p75_ms": 14.08,
  "p90_ms": 21.31,
  "p95_ms": 21.31,
  "p99_ms": 25.06,
  "max_ms": 25.06,
  "mean_ms": 14.3,
  "url": "/api/customers/",
  "method": "GET",
  "iterations": 15,
  "errors": 0,
  "error_rate": 0.0,
  "throughput_rps": 69.9,
  "avg_response_bytes": 10581,
  "max_response_bytes": 10581
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
- P95: 108.37 ms
- Aggregate RPS: 24.2

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
    "min_ms": 0.02,
    "p50_ms": 0.02,
    "p75_ms": 0.02,
    "p90_ms": 0.03,
    "p95_ms": 0.04,
    "p99_ms": 0.07,
    "max_ms": 0.08,
    "mean_ms": 0.02
  },
  "get": {
    "n": 100,
    "min_ms": 0.02,
    "p50_ms": 0.02,
    "p75_ms": 0.02,
    "p90_ms": 0.02,
    "p95_ms": 0.03,
    "p99_ms": 0.04,
    "max_ms": 0.06,
    "mean_ms": 0.02
  }
}
```

### cache_stampede
```json
{
  "n": 20,
  "min_ms": 0.11,
  "p50_ms": 0.18,
  "p75_ms": 0.21,
  "p90_ms": 0.23,
  "p95_ms": 0.24,
  "p99_ms": 0.33,
  "max_ms": 0.33,
  "mean_ms": 0.19
}
```

## Background Tasks

- **background_probe**: {"celery_configured": false, "broker_configured": false, "finding": "NO Celery/broker in project. All work is synchronous in-request.", "recommendation": "For long-running report generation or bulk operations, consider adding Celery with Redis broker in production."}
- **blocking_io_check**: {"/api/dashboard/": {"time_s": 0.019, "status": 401}, "/api/reports/": {"time_s": 0.002, "status": 401}, "/api/customers/": {"time_s": 0.002, "status": 401}}

## Response Sizes

```json
{
  "bytes": 4910
}
```
```json
{
  "/api/customers/": 10571,
  "/api/visits/": 5465,
  "/api/payments/": 4396,
  "/api/services/": 5802,
  "/api/inventory/products/": 4923,
  "/api/dashboard/": 109,
  "/api/reports/": 5743
}
```

---
*Report generated automatically by the performance test suite.*