# Endpoint Audit Report

Generated from live Django URL resolver. Total: **223 URL patterns** (all under `/api/`, including format-suffix variants).

## Summary

| Category | Count |
|---|---|
| **Total endpoints** | 223 |
| **Unique base paths** (format suffixes collapsed) | ~150 |
| **Flagged for review** | 14 groups |

> Report only — no endpoints were deleted. Recommendations below are for a future cleanup pass.

---

## 1. Intentional Duplicates (Known, Acceptable)

| Endpoint A | Endpoint B | Reason |
|---|---|---|
| `/api/finance/staff-payouts/summary/` | `/api/finance/reports/staff-payout-summary/` | Same view (`_staff_payout_summary_payload`), two routes for API organization. Kept for backward compatibility. |

---

## 2. Redundant / Mergeable Pairs

### 2.1 Exchange Rate Reports (Legacy Customers App)
| Endpoint | Issue | Recommendation |
|---|---|---|
| `/api/reports/exchange-dollar/` | Returns current USD→Toman rate; 503 if no rate | **Merge into finance** — same data as `GET /api/finance/exchange-rates/` (latest active). The legacy report is a read-only subset. |
| `/api/reports/backup-exchange/` | Same but forces BrsApi backup fetch | **Remove** — backup provider is already tried by `get_current_usd_to_toman_rate()` when cache is stale. No need for a separate endpoint. |

### 2.2 Wallet Summary
| Endpoint | Issue | Recommendation |
|---|---|---|
| `/api/finance/reports/wallet-summary/` | Returns wallet liability, rewards issued, wallet payments | **Merge into `/api/finance/reports/financial-summary/`** — the financial summary already includes `wallet` block with identical data. The standalone endpoint adds no new information. |

### 2.3 Profit by Staff / Coverage
| Endpoint | Issue | Recommendation |
|---|---|---|
| `/api/finance/reports/profit-by-staff/` | Revenue/cost/profit per staff | **Merge `coverage` into main** — `/profit-by-staff/coverage/` returns the same rows with an extra `coverage_percent` field. One endpoint with `?include_coverage=true` is cleaner. |
| `/api/finance/reports/profit-by-staff/coverage/` | Same data + coverage % | See above. |

---

## 3. Legacy Reports Hardcoded to Current Period (Customers App)

These endpoints **only work for the current Shamsi period** — no `year`/`month`/`date_from`/`date_to` parameters accepted. They cannot be used for historical analysis.

| Endpoint | Period | Data | Recommendation |
|---|---|---|---|
| `/api/reports/daily/` | Current Shamsi day | Sales chart, total, visits | **Deprecate** — use `/api/finance/reports/financial-summary/?period=today` |
| `/api/reports/weekly/` | Current Shamsi week (Sat-start) | Per-day chart, total, visits | **Deprecate** — use `?period=this_week` |
| `/api/reports/monthly/` | Current Shamsi month | Per-day chart, total, visits | **Deprecate** — use `?period=this_month` + Shamsi `year`/`month` |
| `/api/reports/quarterly/` | Current Shamsi quarter | Per-month chart, total, visits | **Deprecate** — use `?period=this_year` + quarter math client-side |
| `/api/reports/yearly/` | Current Shamsi year | Per-month chart, total, visits | **Implemented: now answers 410 Gone** with a pointer to `/api/finance/reports/monthly-close/?year=<shamsi_year>`; marked `deprecated=True` in the OpenAPI schema |
| `/api/reports/all/` | All time | 5-bucket chart, totals | **Keep** (no finance equivalent for all-time) |

**Note:** `/api/reports/` (combined) is also current-period only.

---

## 4. Two Dashboards Serving Different Frontends (By Design)

| Endpoint | Calendar | Currency | Audience |
|---|---|---|---|
| `/api/dashboard/` | Shamsi | Toman (legacy) | Internal clinic dashboard (v1) |
| `/api/finance/reports/dashboard/` | Shamsi (date params) | USD + Toman | Finance team / reporting |

**Verdict:** Keep both. They serve different consumers. Both take Shamsi date parameters —
one calendar on the wire across the whole app (stored finance `DateField`s stay Gregorian).

---

## 5. Finance Reports: Old vs New

### Monthly Close (New — Comprehensive)
- `/api/finance/reports/monthly-close/?year=1405[&month=7]` — **12 months of Shamsi year**, each with full P&L, purchases, operators, payouts, year_total.
- `POST /api/finance/reports/monthly-close/close/` — **explicit closing** of a past Shamsi month (`{year, month}`, staff/admin): freezes the month's full payload into a `MonthlyClose` row; the report then serves the frozen snapshot (`is_closed`, `closed_at`, `close_note`, …). Outstanding payouts are informational, never a blocker. Idempotent re-close keeps the first snapshot.
- `POST /api/finance/reports/monthly-close/reopen/` — `{year, month, reason}` (reason required): row → `reopened`, month back to live data (`was_reopened`).
- **Enforcement:** in a closed month, refunds, expense/opex mutations, payout cancels/re-pricing, backdated purchases, and admin saves/deletes are refused with **409** + a `BLOCKED:*` AuditLog entry until reopened.

### Financial Summary (Existing — Single Period)
- `/api/finance/reports/financial-summary/?period=today|this_week|this_month|prev_month|this_year` — **one bucket**, all Shamsi windows of *now* (`this_week` is Saturday-start).
- `?year=<shamsi_year>&month=<1-12>` navigates any Shamsi month; `?start_date=&end_date=` accept Shamsi `YYYY-MM-DD` (Gregorian dates → 400; garbage → falls back to the current Shamsi day).

**Observation:** Monthly close supersedes the need for multiple single-period calls. Consider adding `period=` support to monthly-close for single-month convenience (already supports `?month=`).

---

## 6. Low-Value / Questionable Endpoints

| Endpoint | Issue | Recommendation |
|---|---|---|
| `/api/reports/visits/` | Visit count + change % vs previous period | **Move to finance** or deprecate — finance reports don't expose visit counts. Could be added to monthly-close. |
| `/api/reports/customers/` | New/loyal/total customers | **Move to finance** — same logic, just customer dimension. |
| `/api/reports/referral/` | Returning customer rate | **Low value** — business metric, not financial. Keep if marketing uses it. |
| `/api/payments/by_service/` | Aggregate payment totals per service | **Redundant** — `/api/finance/reports/profit-by-service/` has richer data (cost, margin). Deprecate. |
| `/api/finance/reports/welcome-packs/` | Welcome pack issuance cost summary | **Niche** — only 8 tests. Could be merged into monthly-close `by_pack` breakdown. |

---

## 7. CRUD Endpoints with No Write Path in API (Read-Only by Design)

These are **intentional** — status transitions happen via ORM/shell, not API.

| Resource | Read-Only Endpoints | Write Actions (Missing from API) |
|---|---|---|
| `StaffPayout` | `/api/finance/staff-payouts/`, `/summary/`, `/detail_report/` | `pending → approved → paid` transitions (no API) |
| `Expense` | `/api/finance/expenses/` | Workflow actions exist: `/submit/`, `/approve/`, `/pay/`, `/reject/`, `/cancel/` ✓ |
| `PurchaseOrder` | `/api/finance/purchase-orders/` | Workflow actions exist: `/mark-ordered/`, `/receive/`, `/cancel/` ✓ |
| `WelcomePackUsage` | `/api/finance/welcome-pack-usages/` | Write via `/welcome-packs/{id}/issue/` ✓ |

**Verdict:** StaffPayout status transitions are the only gap. Documented in ARCHITECTURAL_NOTES.md #5.

---

## 8. Format Suffix Noise

Every router-registered endpoint has a duplicate with format suffix (`.json`, `.api`). This is DRF `DefaultRouter` behavior.

**Count:** ~72 suffix variants that could be suppressed with `format_suffix_patterns=False` on routers if not needed.

---

## 9. v3 Face Analyzer — Clean

| Endpoint | Auth | Notes |
|---|---|---|
| `/api/v3/face/analyze/` | Public (throttled) | Core feature |
| `/api/v3/face/{pk}/tips/` | Public (throttled) | Regenerate plan |
| `/api/v3/face/history/` | Staff (scoped) | Own analyses; admin sees all |
| `/api/v3/face/history/{pk}/` | Staff (scoped) | Detail |

**No issues** — dedicated surface, own schema, no overlap.

---

## 10. v2 Public Website — Clean

| Endpoint | Auth | Notes |
|---|---|---|
| `/api/v2/services/`, `/packages/`, `/products/`, `/team/`, `/testimonials/` | Public | Read-only catalog |
| `/api/v2/contact/` | Public (throttled) | Write-only intake |
| `/api/v2/site/info/` | Staff | Health probe |

**No issues** — separate surface, public-first.

---

## Action Items (Prioritized)

| Priority | Action | Effort |
|---|---|---|
| **High** | Deprecate `/api/reports/exchange-dollar/` and `/backup-exchange/`; point to `/api/finance/exchange-rates/` | Low |
| **High** | Deprecate `/api/finance/reports/wallet-summary/`; use `financial-summary.wallet` | Low |
| **Medium** | Merge `profit-by-staff/coverage/` into main with `?include_coverage=true` | Low |
| **Medium** | Deprecate legacy Shamsi reports (`/api/reports/daily|weekly|monthly|quarterly|yearly/`) | Medium (frontend migration) |
| **Low** | Add `?include_coverage` to profit-by-staff; suppress format suffixes on routers | Low |
| **Low** | Document two-dashboard distinction in API docs | Docs only |

---

## Endpoints to Keep As-Is

All CRUD viewsets, workflow actions, checkout, consumption recording, welcome-pack issuance, expense/purchase-order workflows, face analyzer, public site — these are **actively used and well-scoped**.

---

*Generated: 2026-10-15 | Source: Django URL resolver (`get_resolver()` walk, 223 patterns) + code audit*