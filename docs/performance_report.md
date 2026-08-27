# Sefro Clinic — Performance Report

**Phase:** `run`
**Metrics collected:** 40
**Data directory:** `C:\Users\Dani\Desktop\Sefro_Clinic\tests\performance\reports\data\run`

## Endpoint Benchmarks

| Endpoint | p50 (ms) | p95 (ms) | p99 (ms) | RPS | Errors |
|----------|----------|----------|----------|-----|--------|
| auth_login | 183.74 | 293.97 | 310.9 | - | - |
| auth_me | 1.92 | 3.44 | 6.24 | 445.3 | 0.0 |
| auth_refresh | 6.09 | 10.9 | 20.48 | - | - |
| crud_customer_detail | 5.79 | 7.18 | 8.62 | 167.3 | 0.0 |
| crud_customer_list | 15.39 | 19.78 | 75.28 | 58.3 | 0.0 |
| crud_customer_search | 21.63 | 27.77 | 32.19 | 44.2 | 0.0 |
| crud_payment_by_service | 77.78 | 122.81 | 229.25 | 11.0 | 0.0 |
| crud_payment_list | 7.89 | 9.54 | 12.26 | 122.2 | 0.0 |
| crud_service_list | 4.8 | 5.86 | 7.83 | 204.9 | 0.0 |
| crud_visit_list | 16.66 | 22.73 | 36.0 | 56.6 | 0.0 |
| dashboard | 10.47 | 13.43 | 14.95 | 96.8 | 0.0 |
| inventory_product_create | 6.23 | 8.54 | 9.63 | - | - |
| inventory_product_detail | 3.24 | 4.66 | 6.54 | 292.0 | 0.0 |
| inventory_product_list | 5.48 | 7.04 | 9.31 | 178.7 | 0.0 |
| inventory_product_list_size | - | - | - | - | - |
| inventory_product_search | 8.08 | 10.66 | 11.9 | 119.9 | 0.0 |
| reports_all | 80.13 | 184.46 | 184.46 | 10.7 | 0.0 |
| reports_customers | 7.82 | 9.61 | 9.79 | 124.6 | 0.0 |
| reports_daily | 5.47 | 7.37 | 121.41 | 75.5 | 0.0 |
| reports_monthly | 14.3 | 17.03 | 17.64 | 68.9 | 0.0 |
| reports_referral | 8.27 | 10.4 | 10.71 | 121.8 | 0.0 |
| reports_summary | 93.79 | 112.18 | 117.07 | 10.5 | 0.0 |
| reports_weekly | 8.16 | 10.5 | 11.75 | 119.5 | 0.0 |

## Database Performance

### scale_1000_customers
```json
{
  "n": 15,
  "min_ms": 989.94,
  "p50_ms": 1126.53,
  "p75_ms": 1192.01,
  "p90_ms": 1263.88,
  "p95_ms": 1263.88,
  "p99_ms": 1270.09,
  "max_ms": 1270.09,
  "mean_ms": 1121.86,
  "url": "/api/customers/",
  "method": "GET",
  "iterations": 15,
  "errors": 0,
  "error_rate": 0.0,
  "throughput_rps": 0.9,
  "avg_response_bytes": 10702,
  "max_response_bytes": 10702
}
```

### scale_1000_product_search
```json
{
  "n": 10,
  "min_ms": 9.45,
  "p50_ms": 10.2,
  "p75_ms": 11.3,
  "p90_ms": 11.31,
  "p95_ms": 11.76,
  "p99_ms": 11.76,
  "max_ms": 11.76,
  "mean_ms": 10.48,
  "url": "/api/inventory/products/?search=\u0645\u062d\u0635\u0648\u0644",
  "method": "GET",
  "iterations": 10,
  "errors": 0,
  "error_rate": 0.0,
  "throughput_rps": 95.4,
  "avg_response_bytes": 4609,
  "max_response_bytes": 4609
}
```

### scale_1000_products
```json
{
  "n": 15,
  "min_ms": 4.97,
  "p50_ms": 6.48,
  "p75_ms": 7.29,
  "p90_ms": 8.39,
  "p95_ms": 8.39,
  "p99_ms": 8.75,
  "max_ms": 8.75,
  "mean_ms": 6.53,
  "url": "/api/inventory/products/",
  "method": "GET",
  "iterations": 15,
  "errors": 0,
  "error_rate": 0.0,
  "throughput_rps": 153.1,
  "avg_response_bytes": 4559,
  "max_response_bytes": 4559
}
```

### scale_100_customers
```json
{
  "n": 15,
  "min_ms": 15.64,
  "p50_ms": 21.42,
  "p75_ms": 22.69,
  "p90_ms": 24.22,
  "p95_ms": 24.22,
  "p99_ms": 27.78,
  "max_ms": 27.78,
  "mean_ms": 21.13,
  "url": "/api/customers/",
  "method": "GET",
  "iterations": 15,
  "errors": 0,
  "error_rate": 0.0,
  "throughput_rps": 47.3,
  "avg_response_bytes": 10637,
  "max_response_bytes": 10637
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
- P95: 36.57 ms
- Aggregate RPS: 85.1

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
  "min_ms": 0.06,
  "p50_ms": 0.06,
  "p75_ms": 0.07,
  "p90_ms": 0.07,
  "p95_ms": 0.08,
  "p99_ms": 0.11,
  "max_ms": 0.11,
  "mean_ms": 0.07
}
```

## Background Tasks

- **background_probe**: {"celery_configured": false, "broker_configured": false, "finding": "NO Celery/broker in project. All work is synchronous in-request.", "recommendation": "For long-running report generation or bulk operations, consider adding Celery with Redis broker in production."}
- **blocking_io_check**: {"/api/dashboard/": {"time_s": 0.002, "status": 401}, "/api/reports/": {"time_s": 0.001, "status": 401}, "/api/customers/": {"time_s": 0.001, "status": 401}}

## Response Sizes

```json
{
  "bytes": 4610
}
```
```json
{
  "/api/customers/": 10633,
  "/api/visits/": 5386,
  "/api/payments/": 3618,
  "/api/services/": 1767,
  "/api/inventory/products/": 4596,
  "/api/dashboard/": 108,
  "/api/reports/": 5690
}
```

---
*Report generated automatically by the performance test suite.*