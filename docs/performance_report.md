# Sefro Clinic — Performance Report

**Phase:** `run`
**Metrics collected:** 40
**Data directory:** `C:\Users\Dani\Desktop\Sefro_Clinic\tests\performance\reports\data\run`

## Endpoint Benchmarks

| Endpoint | p50 (ms) | p95 (ms) | p99 (ms) | RPS | Errors |
|----------|----------|----------|----------|-----|--------|
| auth_login | 127.85 | 204.89 | 281.05 | - | - |
| auth_me | 1.99 | 4.83 | 15.12 | 338.9 | 0.0 |
| auth_refresh | 7.72 | 11.62 | 34.46 | - | - |
| crud_customer_detail | 7.43 | 8.88 | 23.64 | 127.1 | 0.0 |
| crud_customer_list | 17.55 | 24.71 | 97.35 | 46.1 | 0.0 |
| crud_customer_search | 24.93 | 30.47 | 36.72 | 38.4 | 0.0 |
| crud_payment_by_service | 144.71 | 208.91 | 254.28 | 6.6 | 0.0 |
| crud_payment_list | 13.35 | 16.89 | 22.43 | 72.1 | 0.0 |
| crud_service_list | 8.27 | 10.13 | 23.84 | 112.1 | 0.0 |
| crud_visit_list | 26.74 | 37.79 | 40.63 | 34.4 | 0.0 |
| dashboard | 14.08 | 21.6 | 22.7 | 64.9 | 0.0 |
| inventory_product_create | 8.75 | 13.55 | 21.06 | - | - |
| inventory_product_detail | 5.0 | 8.57 | 20.0 | 159.6 | 0.0 |
| inventory_product_list | 11.66 | 15.88 | 19.43 | 86.7 | 0.0 |
| inventory_product_list_size | - | - | - | - | - |
| inventory_product_search | 10.5 | 13.68 | 25.49 | 85.4 | 0.0 |
| reports_all | 153.85 | 174.51 | 174.51 | 6.3 | 0.0 |
| reports_customers | 15.05 | 18.8 | 27.63 | 64.1 | 0.0 |
| reports_daily | 10.68 | 13.79 | 22.46 | 87.8 | 0.0 |
| reports_monthly | 20.61 | 23.86 | 31.88 | 47.2 | 0.0 |
| reports_referral | 7.15 | 8.76 | 21.55 | 122.2 | 0.0 |
| reports_summary | 145.37 | 174.63 | 231.48 | 6.7 | 0.0 |
| reports_weekly | 12.64 | 14.9 | 21.46 | 75.4 | 0.0 |

## Database Performance

### scale_1000_customers
```json
{
  "n": 15,
  "min_ms": 14.87,
  "p50_ms": 17.93,
  "p75_ms": 18.31,
  "p90_ms": 19.87,
  "p95_ms": 19.87,
  "p99_ms": 23.19,
  "max_ms": 23.19,
  "mean_ms": 18.13,
  "url": "/api/customers/",
  "method": "GET",
  "iterations": 15,
  "errors": 0,
  "error_rate": 0.0,
  "throughput_rps": 55.2,
  "avg_response_bytes": 10707,
  "max_response_bytes": 10707
}
```

### scale_1000_product_search
```json
{
  "n": 10,
  "min_ms": 7.3,
  "p50_ms": 8.92,
  "p75_ms": 9.3,
  "p90_ms": 10.78,
  "p95_ms": 14.18,
  "p99_ms": 14.18,
  "max_ms": 14.18,
  "mean_ms": 9.41,
  "url": "/api/inventory/products/?search=\u0645\u062d\u0635\u0648\u0644",
  "method": "GET",
  "iterations": 10,
  "errors": 0,
  "error_rate": 0.0,
  "throughput_rps": 106.3,
  "avg_response_bytes": 4974,
  "max_response_bytes": 4974
}
```

### scale_1000_products
```json
{
  "n": 15,
  "min_ms": 4.38,
  "p50_ms": 5.09,
  "p75_ms": 5.59,
  "p90_ms": 6.46,
  "p95_ms": 6.46,
  "p99_ms": 11.87,
  "max_ms": 11.87,
  "mean_ms": 5.63,
  "url": "/api/inventory/products/",
  "method": "GET",
  "iterations": 15,
  "errors": 0,
  "error_rate": 0.0,
  "throughput_rps": 177.6,
  "avg_response_bytes": 4917,
  "max_response_bytes": 4917
}
```

### scale_100_customers
```json
{
  "n": 15,
  "min_ms": 9.47,
  "p50_ms": 13.16,
  "p75_ms": 14.41,
  "p90_ms": 16.31,
  "p95_ms": 16.31,
  "p99_ms": 24.19,
  "max_ms": 24.19,
  "mean_ms": 13.69,
  "url": "/api/customers/",
  "method": "GET",
  "iterations": 15,
  "errors": 0,
  "error_rate": 0.0,
  "throughput_rps": 73.1,
  "avg_response_bytes": 10641,
  "max_response_bytes": 10641
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
- P95: 99.42 ms
- Aggregate RPS: 50.0

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
    "p90_ms": 0.02,
    "p95_ms": 0.02,
    "p99_ms": 0.06,
    "max_ms": 0.13,
    "mean_ms": 0.02
  },
  "get": {
    "n": 100,
    "min_ms": 0.02,
    "p50_ms": 0.02,
    "p75_ms": 0.02,
    "p90_ms": 0.02,
    "p95_ms": 0.02,
    "p99_ms": 0.03,
    "max_ms": 0.04,
    "mean_ms": 0.02
  }
}
```

### cache_stampede
```json
{
  "n": 20,
  "min_ms": 0.08,
  "p50_ms": 0.08,
  "p75_ms": 0.09,
  "p90_ms": 0.13,
  "p95_ms": 0.14,
  "p99_ms": 0.16,
  "max_ms": 0.16,
  "mean_ms": 0.09
}
```

## Background Tasks

- **background_probe**: {"celery_configured": false, "broker_configured": false, "finding": "NO Celery/broker in project. All work is synchronous in-request.", "recommendation": "For long-running report generation or bulk operations, consider adding Celery with Redis broker in production."}
- **blocking_io_check**: {"/api/dashboard/": {"time_s": 0.013, "status": 401}, "/api/reports/": {"time_s": 0.003, "status": 401}, "/api/customers/": {"time_s": 0.002, "status": 401}}

## Response Sizes

```json
{
  "bytes": 4861
}
```
```json
{
  "/api/customers/": 10571,
  "/api/visits/": 5462,
  "/api/payments/": 4391,
  "/api/services/": 2832,
  "/api/inventory/products/": 4915,
  "/api/dashboard/": 108,
  "/api/reports/": 5746
}
```

---
*Report generated automatically by the performance test suite.*