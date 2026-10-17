# Sefro Clinic — Performance Report

**Phase:** `run`
**Metrics collected:** 48
**Data directory:** `C:\Users\Dani\Desktop\Sefro_Clinic\tests\performance\reports\data\run`

## Endpoint Benchmarks

| Endpoint | p50 (ms) | p95 (ms) | p99 (ms) | RPS | Errors |
|----------|----------|----------|----------|-----|--------|
| auth_login | 155.12 | 199.91 | 281.05 | - | - |
| auth_me | 1.15 | 1.76 | 9.31 | 681.0 | 0.0 |
| auth_refresh | 11.42 | 14.98 | 25.55 | - | - |
| crud_customer_detail | 8.69 | 10.77 | 17.46 | 108.6 | 0.0 |
| crud_customer_list | 14.66 | 19.59 | 32.63 | 63.9 | 0.0 |
| crud_customer_search | 18.78 | 22.01 | 25.11 | 52.1 | 0.0 |
| crud_payment_by_service | 84.55 | 204.78 | 243.03 | 10.0 | 0.0 |
| crud_payment_list | 8.0 | 10.07 | 13.78 | 117.4 | 0.0 |
| crud_service_list | 10.39 | 16.95 | 32.5 | 87.2 | 0.0 |
| crud_visit_list | 24.14 | 29.32 | 39.44 | 39.8 | 0.0 |
| dashboard | 6.35 | 9.01 | 13.45 | 141.2 | 0.0 |
| finance_checkout | 19.51 | 45.74 | 45.74 | - | - |
| finance_exchange_dollar | 4.54 | 7.66 | 12.29 | 190.0 | 0.0 |
| finance_expense_list | 4.49 | 11.9 | 24.4 | 163.7 | 0.0 |
| finance_financial_summary | 32.72 | 40.36 | 105.77 | 26.1 | 0.0 |
| finance_operating_expense_category_list | 2.65 | 3.76 | 18.88 | 286.2 | 0.0 |
| finance_operating_expense_list | 2.67 | 3.49 | 8.82 | 327.0 | 0.0 |
| finance_operating_expense_summary | 6.13 | 7.02 | 14.92 | 148.6 | 0.0 |
| finance_wallet_list | 4.22 | 10.56 | 24.82 | 169.5 | 0.0 |
| inventory_product_create | 5.99 | 7.65 | 14.07 | - | - |
| inventory_product_detail | 3.24 | 4.67 | 10.92 | 269.1 | 0.0 |
| inventory_product_list | 6.28 | 8.18 | 16.68 | 139.4 | 0.0 |
| inventory_product_list_size | - | - | - | - | - |
| inventory_product_search | 7.65 | 10.03 | 18.52 | 119.6 | 0.0 |
| reports_all | 13.32 | 39.04 | 39.04 | 63.2 | 0.0 |
| reports_customers | 11.16 | 18.27 | 154.61 | 47.5 | 0.0 |
| reports_daily | 5.61 | 9.18 | 10.96 | 167.1 | 0.0 |
| reports_monthly | 5.73 | 9.04 | 14.83 | 149.6 | 0.0 |
| reports_referral | 3.59 | 5.22 | 12.61 | 231.9 | 0.0 |
| reports_summary | 7.53 | 8.61 | 14.45 | 123.9 | 0.0 |
| reports_weekly | 6.29 | 10.37 | 11.46 | 141.5 | 0.0 |

## Database Performance

### scale_1000_customers
```json
{
  "n": 15,
  "min_ms": 14.95,
  "p50_ms": 17.74,
  "p75_ms": 18.72,
  "p90_ms": 22.74,
  "p95_ms": 22.74,
  "p99_ms": 22.82,
  "max_ms": 22.82,
  "mean_ms": 17.73,
  "url": "/api/customers/",
  "method": "GET",
  "iterations": 15,
  "errors": 0,
  "error_rate": 0.0,
  "throughput_rps": 56.4,
  "avg_response_bytes": 13755,
  "max_response_bytes": 13755
}
```

### scale_1000_product_search
```json
{
  "n": 10,
  "min_ms": 8.75,
  "p50_ms": 9.56,
  "p75_ms": 11.56,
  "p90_ms": 13.79,
  "p95_ms": 16.85,
  "p99_ms": 16.85,
  "max_ms": 16.85,
  "mean_ms": 10.94,
  "url": "/api/inventory/products/?search=\u0645\u062d\u0635\u0648\u0644",
  "method": "GET",
  "iterations": 10,
  "errors": 0,
  "error_rate": 0.0,
  "throughput_rps": 91.4,
  "avg_response_bytes": 5814,
  "max_response_bytes": 5814
}
```

### scale_1000_products
```json
{
  "n": 15,
  "min_ms": 5.09,
  "p50_ms": 6.61,
  "p75_ms": 7.21,
  "p90_ms": 14.55,
  "p95_ms": 14.55,
  "p99_ms": 16.24,
  "max_ms": 16.24,
  "mean_ms": 7.54,
  "url": "/api/inventory/products/",
  "method": "GET",
  "iterations": 15,
  "errors": 0,
  "error_rate": 0.0,
  "throughput_rps": 132.6,
  "avg_response_bytes": 5663,
  "max_response_bytes": 5663
}
```

### scale_100_customers
```json
{
  "n": 15,
  "min_ms": 12.55,
  "p50_ms": 14.91,
  "p75_ms": 16.35,
  "p90_ms": 20.16,
  "p95_ms": 20.16,
  "p99_ms": 27.56,
  "max_ms": 27.56,
  "mean_ms": 16.05,
  "url": "/api/customers/",
  "method": "GET",
  "iterations": 15,
  "errors": 0,
  "error_rate": 0.0,
  "throughput_rps": 62.3,
  "avg_response_bytes": 13706,
  "max_response_bytes": 13706
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
- P95: 72.22 ms
- Aggregate RPS: 48.2

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
    "p95_ms": 0.02,
    "p99_ms": 0.03,
    "max_ms": 0.07,
    "mean_ms": 0.01
  },
  "get": {
    "n": 100,
    "min_ms": 0.01,
    "p50_ms": 0.01,
    "p75_ms": 0.01,
    "p90_ms": 0.01,
    "p95_ms": 0.02,
    "p99_ms": 0.03,
    "max_ms": 0.03,
    "mean_ms": 0.01
  }
}
```

### cache_stampede
```json
{
  "n": 20,
  "min_ms": 0.05,
  "p50_ms": 0.06,
  "p75_ms": 0.07,
  "p90_ms": 0.08,
  "p95_ms": 0.1,
  "p99_ms": 0.1,
  "max_ms": 0.1,
  "mean_ms": 0.07
}
```

## Background Tasks

- **background_probe**: {"celery_configured": false, "broker_configured": false, "finding": "NO Celery/broker in project. All work is synchronous in-request.", "recommendation": "For long-running report generation or bulk operations, consider adding Celery with Redis broker in production."}
- **blocking_io_check**: {"/api/dashboard/": {"time_s": 0.009, "status": 401}, "/api/reports/": {"time_s": 0.001, "status": 401}, "/api/customers/": {"time_s": 0.002, "status": 401}}

## Response Sizes

```json
{
  "bytes": 5683
}
```
```json
{
  "/api/customers/": 13701,
  "/api/visits/": 10306,
  "/api/payments/": 4423,
  "/api/services/": 6222,
  "/api/inventory/products/": 5670,
  "/api/dashboard/": 108,
  "/api/reports/": 1116,
  "/api/finance/operating-expenses/": 52,
  "/api/finance/operating-expenses/summary/": 148,
  "/api/finance/operating-expense-categories/": 52
}
```

---
*Report generated automatically by the performance test suite.*