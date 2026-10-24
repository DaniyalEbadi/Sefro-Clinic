# Sefro Clinic — Performance Report

**Phase:** `run`
**Metrics collected:** 49
**Data directory:** `C:\Users\Dani\Desktop\Sefro_Clinic\tests\performance\reports\data\run`

## Endpoint Benchmarks

| Endpoint | p50 (ms) | p95 (ms) | p99 (ms) | RPS | Errors |
|----------|----------|----------|----------|-----|--------|
| auth_login | 407.35 | 656.49 | 793.61 | - | - |
| auth_me | 1.91 | 3.66 | 13.2 | 374.6 | 0.0 |
| auth_refresh | 30.77 | 54.72 | 66.59 | - | - |
| crud_customer_detail | 10.26 | 22.85 | 31.02 | 73.7 | 0.0 |
| crud_customer_list | 16.95 | 30.06 | 260.13 | 37.6 | 0.0 |
| crud_customer_search | 19.23 | 34.36 | 39.05 | 46.8 | 0.0 |
| crud_payment_by_service | 2.12 | 10.19 | 16.92 | 297.2 | 1.0 |
| crud_payment_list | 2.19 | 4.48 | 8.01 | 386.8 | 1.0 |
| crud_sale_list | 12.66 | 18.26 | 34.37 | 70.6 | 0.0 |
| crud_service_list | 16.97 | 31.34 | 50.72 | 50.8 | 0.0 |
| crud_visit_list | 38.49 | 70.63 | 73.21 | 22.6 | 0.0 |
| dashboard | 7.55 | 17.69 | 18.51 | 111.2 | 0.0 |
| finance_checkout | 13.63 | 39.66 | 39.66 | - | - |
| finance_exchange_dollar | 4.39 | 7.32 | 13.65 | 199.0 | 0.0 |
| finance_expense_list | 6.28 | 10.26 | 17.76 | 150.5 | 0.0 |
| finance_financial_summary | 51.66 | 59.46 | 155.59 | 17.8 | 0.0 |
| finance_operating_expense_category_list | 6.04 | 9.31 | 22.33 | 139.0 | 0.0 |
| finance_operating_expense_list | 4.21 | 9.18 | 12.23 | 194.7 | 0.0 |
| finance_operating_expense_summary | 7.96 | 11.29 | 15.81 | 113.0 | 0.0 |
| finance_wallet_list | 5.03 | 8.71 | 18.16 | 171.6 | 0.0 |
| inventory_product_create | 6.43 | 8.5 | 16.27 | - | - |
| inventory_product_detail | 3.73 | 5.61 | 10.58 | 250.6 | 0.0 |
| inventory_product_list | 6.54 | 10.18 | 14.72 | 140.1 | 0.0 |
| inventory_product_list_size | - | - | - | - | - |
| inventory_product_search | 10.3 | 12.99 | 21.01 | 92.7 | 0.0 |
| reports_all | 184.66 | 390.79 | 390.79 | 4.5 | 0.0 |
| reports_customers | 10.35 | 20.55 | 23.22 | 82.1 | 0.0 |
| reports_daily | 8.95 | 22.07 | 36.51 | 86.0 | 0.0 |
| reports_monthly | 10.88 | 22.55 | 24.78 | 78.4 | 0.0 |
| reports_referral | 6.26 | 9.29 | 15.8 | 140.9 | 0.0 |
| reports_summary | 109.4 | 132.57 | 150.63 | 8.6 | 0.0 |
| reports_weekly | 7.54 | 12.45 | 15.63 | 117.9 | 0.0 |

## Database Performance

### scale_1000_customers
```json
{
  "n": 15,
  "min_ms": 17.15,
  "p50_ms": 19.98,
  "p75_ms": 36.15,
  "p90_ms": 93.96,
  "p95_ms": 93.96,
  "p99_ms": 103.42,
  "max_ms": 103.42,
  "mean_ms": 34.4,
  "url": "/api/customers/",
  "method": "GET",
  "iterations": 15,
  "errors": 0,
  "error_rate": 0.0,
  "throughput_rps": 29.1,
  "avg_response_bytes": 13704,
  "max_response_bytes": 13704
}
```

### scale_1000_product_search
```json
{
  "n": 10,
  "min_ms": 8.13,
  "p50_ms": 9.71,
  "p75_ms": 10.15,
  "p90_ms": 10.4,
  "p95_ms": 15.93,
  "p99_ms": 15.93,
  "max_ms": 15.93,
  "mean_ms": 10.17,
  "url": "/api/inventory/products/?search=\u0645\u062d\u0635\u0648\u0644",
  "method": "GET",
  "iterations": 10,
  "errors": 0,
  "error_rate": 0.0,
  "throughput_rps": 98.3,
  "avg_response_bytes": 5779,
  "max_response_bytes": 5779
}
```

### scale_1000_products
```json
{
  "n": 15,
  "min_ms": 5.79,
  "p50_ms": 7.43,
  "p75_ms": 8.46,
  "p90_ms": 9.07,
  "p95_ms": 9.07,
  "p99_ms": 15.01,
  "max_ms": 15.01,
  "mean_ms": 7.83,
  "url": "/api/inventory/products/",
  "method": "GET",
  "iterations": 15,
  "errors": 0,
  "error_rate": 0.0,
  "throughput_rps": 127.7,
  "avg_response_bytes": 5744,
  "max_response_bytes": 5744
}
```

### scale_100_customers
```json
{
  "n": 15,
  "min_ms": 16.87,
  "p50_ms": 20.29,
  "p75_ms": 20.45,
  "p90_ms": 24.48,
  "p95_ms": 24.48,
  "p99_ms": 34.01,
  "max_ms": 34.01,
  "mean_ms": 20.65,
  "url": "/api/customers/",
  "method": "GET",
  "iterations": 15,
  "errors": 0,
  "error_rate": 0.0,
  "throughput_rps": 48.4,
  "avg_response_bytes": 13629,
  "max_response_bytes": 13629
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
- P95: 64.3 ms
- Aggregate RPS: 68.7

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
    "p90_ms": 0.02,
    "p95_ms": 0.03,
    "p99_ms": 0.07,
    "max_ms": 0.08,
    "mean_ms": 0.01
  },
  "get": {
    "n": 100,
    "min_ms": 0.01,
    "p50_ms": 0.01,
    "p75_ms": 0.01,
    "p90_ms": 0.02,
    "p95_ms": 0.02,
    "p99_ms": 0.05,
    "max_ms": 0.08,
    "mean_ms": 0.01
  }
}
```

### cache_stampede
```json
{
  "n": 20,
  "min_ms": 0.07,
  "p50_ms": 0.15,
  "p75_ms": 0.19,
  "p90_ms": 0.54,
  "p95_ms": 0.56,
  "p99_ms": 1.22,
  "max_ms": 1.22,
  "mean_ms": 0.24
}
```

## Background Tasks

- **background_probe**: {"celery_configured": false, "broker_configured": false, "finding": "NO Celery/broker in project. All work is synchronous in-request.", "recommendation": "For long-running report generation or bulk operations, consider adding Celery with Redis broker in production."}
- **blocking_io_check**: {"/api/dashboard/": {"time_s": 0.01, "status": 401}, "/api/reports/": {"time_s": 0.201, "status": 401}, "/api/customers/": {"time_s": 0.002, "status": 401}}

## Response Sizes

```json
{
  "bytes": 5672
}
```
```json
{
  "/api/customers/": 13620,
  "/api/visits/": 18375,
  "/api/finance/sales/": 4446,
  "/api/services/": 6192,
  "/api/inventory/products/": 5691,
  "/api/dashboard/": 109,
  "/api/reports/": 5732,
  "/api/finance/operating-expenses/": 52,
  "/api/finance/operating-expenses/summary/": 148,
  "/api/finance/operating-expense-categories/": 1740
}
```

---
*Report generated automatically by the performance test suite.*