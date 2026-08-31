# Sefro Clinic — Performance Report

**Phase:** `run`
**Metrics collected:** 40
**Data directory:** `C:\Users\Dani\Desktop\Sefro_Clinic\tests\performance\reports\data\run`

## Endpoint Benchmarks

| Endpoint | p50 (ms) | p95 (ms) | p99 (ms) | RPS | Errors |
|----------|----------|----------|----------|-----|--------|
| auth_login | 131.7 | 172.79 | 186.16 | - | - |
| auth_me | 1.52 | 2.89 | 8.2 | 535.1 | 0.0 |
| auth_refresh | 5.52 | 6.91 | 25.29 | - | - |
| crud_customer_detail | 4.83 | 6.44 | 13.35 | 192.5 | 0.0 |
| crud_customer_list | 14.16 | 18.37 | 21.28 | 70.3 | 0.0 |
| crud_customer_search | 19.19 | 22.03 | 31.32 | 50.3 | 0.0 |
| crud_payment_by_service | 82.98 | 222.58 | 316.71 | 9.8 | 0.0 |
| crud_payment_list | 8.27 | 9.83 | 16.85 | 114.3 | 0.0 |
| crud_service_list | 5.28 | 7.92 | 14.95 | 165.5 | 0.0 |
| crud_visit_list | 16.87 | 20.36 | 27.71 | 57.1 | 0.0 |
| dashboard | 8.51 | 11.6 | 16.28 | 109.0 | 0.0 |
| inventory_product_create | 5.22 | 6.11 | 14.33 | - | - |
| inventory_product_detail | 2.17 | 3.47 | 9.83 | 350.1 | 0.0 |
| inventory_product_list | 4.9 | 6.05 | 12.09 | 192.7 | 0.0 |
| inventory_product_list_size | - | - | - | - | - |
| inventory_product_search | 6.98 | 9.26 | 13.37 | 133.8 | 0.0 |
| reports_all | 73.85 | 87.87 | 87.87 | 13.2 | 0.0 |
| reports_customers | 13.38 | 14.73 | 18.69 | 77.5 | 0.0 |
| reports_daily | 9.18 | 13.02 | 17.82 | 103.1 | 0.0 |
| reports_monthly | 10.23 | 12.66 | 16.93 | 92.6 | 0.0 |
| reports_referral | 4.67 | 7.56 | 10.87 | 182.9 | 0.0 |
| reports_summary | 82.87 | 90.98 | 94.12 | 12.1 | 0.0 |
| reports_weekly | 8.5 | 10.95 | 14.29 | 113.5 | 0.0 |

## Database Performance

### scale_1000_customers
```json
{
  "n": 15,
  "min_ms": 21.0,
  "p50_ms": 24.38,
  "p75_ms": 26.32,
  "p90_ms": 30.99,
  "p95_ms": 30.99,
  "p99_ms": 34.74,
  "max_ms": 34.74,
  "mean_ms": 25.23,
  "url": "/api/customers/",
  "method": "GET",
  "iterations": 15,
  "errors": 0,
  "error_rate": 0.0,
  "throughput_rps": 39.6,
  "avg_response_bytes": 10645,
  "max_response_bytes": 10645
}
```

### scale_1000_product_search
```json
{
  "n": 10,
  "min_ms": 10.91,
  "p50_ms": 11.49,
  "p75_ms": 12.28,
  "p90_ms": 12.32,
  "p95_ms": 23.32,
  "p99_ms": 23.32,
  "max_ms": 23.32,
  "mean_ms": 12.79,
  "url": "/api/inventory/products/?search=\u0645\u062d\u0635\u0648\u0644",
  "method": "GET",
  "iterations": 10,
  "errors": 0,
  "error_rate": 0.0,
  "throughput_rps": 78.2,
  "avg_response_bytes": 4982,
  "max_response_bytes": 4982
}
```

### scale_1000_products
```json
{
  "n": 15,
  "min_ms": 7.44,
  "p50_ms": 8.03,
  "p75_ms": 8.56,
  "p90_ms": 9.92,
  "p95_ms": 9.92,
  "p99_ms": 19.43,
  "max_ms": 19.43,
  "mean_ms": 9.01,
  "url": "/api/inventory/products/",
  "method": "GET",
  "iterations": 15,
  "errors": 0,
  "error_rate": 0.0,
  "throughput_rps": 111.0,
  "avg_response_bytes": 4890,
  "max_response_bytes": 4890
}
```

### scale_100_customers
```json
{
  "n": 15,
  "min_ms": 16.86,
  "p50_ms": 17.92,
  "p75_ms": 19.64,
  "p90_ms": 20.59,
  "p95_ms": 20.59,
  "p99_ms": 38.05,
  "max_ms": 38.05,
  "mean_ms": 19.71,
  "url": "/api/customers/",
  "method": "GET",
  "iterations": 15,
  "errors": 0,
  "error_rate": 0.0,
  "throughput_rps": 50.7,
  "avg_response_bytes": 10580,
  "max_response_bytes": 10580
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
- P95: 64.91 ms
- Aggregate RPS: 68.1

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
  "min_ms": 0.04,
  "p50_ms": 0.06,
  "p75_ms": 0.08,
  "p90_ms": 0.09,
  "p95_ms": 0.09,
  "p99_ms": 0.1,
  "max_ms": 0.1,
  "mean_ms": 0.07
}
```

## Background Tasks

- **background_probe**: {"celery_configured": false, "broker_configured": false, "finding": "NO Celery/broker in project. All work is synchronous in-request.", "recommendation": "For long-running report generation or bulk operations, consider adding Celery with Redis broker in production."}
- **blocking_io_check**: {"/api/dashboard/": {"time_s": 0.009, "status": 401}, "/api/reports/": {"time_s": 0.001, "status": 401}, "/api/customers/": {"time_s": 0.001, "status": 401}}

## Response Sizes

```json
{
  "bytes": 4920
}
```
```json
{
  "/api/customers/": 10570,
  "/api/visits/": 5459,
  "/api/payments/": 4375,
  "/api/services/": 2832,
  "/api/inventory/products/": 4901,
  "/api/dashboard/": 108,
  "/api/reports/": 5743
}
```

---
*Report generated automatically by the performance test suite.*