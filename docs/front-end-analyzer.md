# Frontend Analyze — sefro-clinic-pwa

> Location of this file: `backend/docs/front-analyze.md`
> Subject: frontend app that lives in repo root (`../..` relative to `backend/`).
> Stack: React 19 + TypeScript ~6.0 + Vite 8 + Tailwind CSS v4 + react-router v7 + TanStack Query v5 + PWA.

This doc explains the frontend in detail with a visual file tree.

---

## 1. TL;DR

* Persian (fa, RTL) clinic-management PWA: `کلینیک زیبایی باران`.
* Entry: `index.html` → `src/main.tsx` → `src/routes/index.tsx` → `src/App.tsx` (Sidebar layout + `<Outlet/>`).
* Data: `src/config/api.ts` (endpoint map) → `src/services/*.ts` (axios calls) → `src/hooks/api/*.ts` (TanStack Query wrappers) → pages/components.
* UI: custom design system in `src/components/ui/` + domain components (`accounting/`, `analytics/`, `patients/`, `services/`, `settings/`, `warehouse/`, `wizard/`, `dashboard/`).
* State: `AuthContext`, `WizardContext`, `QueryProvider`, `ToastProvider`, `QuickActionProvider`, `CommandPaletteContext`.
* PWA: `vite-plugin-pwa` (`registerType: prompt`), manifest fa/RTL, `src/components/PwaUpdater.tsx`.
* Tests: Vitest unit (`src/**/__tests__`), Playwright e2e (`e2e/*.spec.ts`).

---

## 2. Tech stack (from `package.json`)

| Area | Lib |
|---|---|
| App | `react@19`, `react-dom@19`, `react-router@7` |
| Build | `vite@8`, `@vitejs/plugin-react@6`, `typescript~6.0`, `@rolldown/plugin-babel` + React Compiler |
| Style | `tailwindcss@4`, `@tailwindcss/vite`, `prettier-plugin-tailwindcss` |
| Data | `@tanstack/react-query@5`, `axios@1.18`, `zod@4` |
| UI extras | `react-icons@5`, `recharts@3`, `sonner@2`, `motion@12`, `driver.js@1.6` (walkthrough), `react-calendar-datetime-picker@2`, `jalaali-js@1.2` |
| PWA / export | `vite-plugin-pwa@1.3`, `xlsx@0.18` |
| Test / quality | `vitest@4`, `jsdom`, `@testing-library/*`, `@playwright/test@1.61`, `eslint@10`, `husky@9`, `lint-staged` |

Commands:

```bash
pnpm dev          # Vite dev 127.0.0.1:5174, /api → http://localhost:8000
pnpm build        # tsc -b && vite build
pnpm typecheck    # tsc -b
pnpm lint         # eslint .
pnpm test         # vitest watch
pnpm test:unit    # vitest run
pnpm test:e2e     # playwright test
pnpm preview      # vite preview
```

---

## 3. Boot / entry flow

```
index.html (lang=fa dir=rtl, Vazirmatn, #root)
  └─ src/main.tsx
       ├─ QueryProvider (TanStack Query)
       │    └─ AuthProvider
       │         └─ ToastProvider
       │              └─ RouterProvider(router)
       └─ src/routes/index.tsx (createBrowserRouter)
            ├─ / → App (Sidebar layout)
            └─ /auth → Auth (no sidebar)
```

* `src/main.tsx` (22 lines): StrictMode + providers above, nothing else.
* `src/App.tsx` (75 lines): defines `items: SidebarItem[]` (داشبورد `/`, پذیرش `/wizard`, مراجعین `/patients`, حسابداری `/accounting`, تقویم `/calendar`, خدمات `/services`, گزارش‌ها `/analytics`, انبار `/warehouse`, تنظیمات `/settings`, لاگ `/logs`, + DEV-only `/design-system`), filters `/logs` by `usePermissions().canViewLogs`, renders `<Sidebar/>`, `<Outlet/>`, `<CommandPalette/>`, `<PwaUpdater/>`, `<LoadingBar/>`, `<WalkthroughButton/>` inside `WizardProvider + QuickActionProvider + CommandPaletteContext`.
* `vite.config.ts`: `base: /dashboard/` on build, dev on `/`; dev server `127.0.0.1:5174` with `/api` proxy; PWA manifest name `کلینیک زیبایی باران`, `dir: rtl`, `lang: fa`.

---

## 4. Routing (`src/routes/index.tsx`, 61 lines)

Parent `/` → `App`, `errorElement: <ErrorFallback/>`, child `RequireAuth`. Lazy-loaded via `lazyRoute(() => import(...))`.

| Path | File | Guard |
|---|---|---|
| `/` (index) | `routes/Dashboard.tsx` | `RequireAuth` |
| `/wizard` | `routes/WizardPage.tsx` | `RequireAuth` |
| `/patients` | `routes/Patients.tsx` | `RequireAuth` |
| `/calendar` | `routes/Calendar.tsx` | `RequireAuth` |
| `/services` | `routes/Services.tsx` | `RequireAuth` |
| `/warehouse` | `routes/Warehouse.tsx` | `RequireAuth` |
| `/accounting` | `routes/Accounting.tsx` | `RequireAuth` |
| `/analytics` | `routes/Analytics.tsx` | `RequireAuth` |
| `/settings` | `routes/Settings.tsx` | `RequireAuth` |
| `/logs` | `routes/Logs.tsx` | `RequireAuth + RequireRole(routePermissions['/logs'])` (admin only) |
| `/design-system` | `routes/DesignSystem.tsx` | DEV only |
| `*` | `<NotFound/>` | — |
| `/auth` | `routes/Auth.tsx` | `RedirectIfAuth` (separate layout) |

`basename`: `/` in DEV, `/dashboard` in build (served behind Django/nginx subpath).

`routes/RouteGuard.tsx`: `RequireAuth`, `RedirectIfAuth`, `RequireRole`.

---

## 5. Pages (what each route does)

* `Dashboard.tsx` — KPI cards + charts (`components/dashboard/FinanceKpiCards`, `ExchangeRateCard`, recharts).
* `WizardPage.tsx` — پذیرش multi-step wizard (patient → service → payment) backed by `contexts/WizardContext.tsx` + `components/wizard/WizardStep*.tsx` + `lib/wizard-storage.ts`.
* `Patients.tsx` — مراجعین CRUD/search/Excel (`components/patients/PatientFormModal.tsx`, `lib/excel.ts`).
* `Calendar.tsx` — تقویم visits/appointments (Jalali picker, reserve/confirm/complete/cancel).
* `Services.tsx` — خدمات + packages (`components/services/ServiceFormModal`, `ServiceDetailModal`, `PackagesTab`, `PackageFormModal`).
* `Warehouse.tsx` — انبار products/purchases/usages (`components/warehouse/PurchaseModal`, `UsagesTab`, `PriceCell`, `CostHistoryModal`).
* `Accounting.tsx` — حسابداری sales/checkout/refund/payouts/operating-expenses (`components/accounting/*` — 9 files).
* `Analytics.tsx` — گزارش‌ها (`components/analytics/FinancialSummaryTab`, `ProfitBreakdownTab`, `lib/report-chart.ts`).
* `Settings.tsx` — تنظیمات (`components/settings/ServiceCategoriesTab`, `ExchangeRatesTab`, `CompensationRulesTab`).
* `Logs.tsx` — لاگ سیستم admin-only.
* `Auth.tsx` — login (`hooks/useLoginForm.ts`, `services/auth.ts`).
* `DesignSystem.tsx` — DEV-only showcase of `components/ui`.

---

## 6. Data layer

### 6.1 `src/config/api.ts` (101 lines)

```ts
API_BASE_URL = import.meta.env.VITE_API_URL ?? ""
API_PREFIX = "/api"
API_URL = `${API_BASE_URL}${API_PREFIX}`
endpoints = { auth, customers, visits, products, services, reports, dashboard, workTime, logs, sales, payouts, packages, serviceCategories, finance }
```

Mirrors Django backend (`backend/`): `/auth/*`, `/customers/`, `/visits/`, `/inventory/products/`, `/services/`, `/reports/*`, `/dashboard/`, `/work-time/`, `/logs/`, `/finance/*`.

### 6.2 `src/services/` (19 modules + 18 tests)

`auth.ts`, `customers.ts`, `visits.ts`, `services.ts`, `serviceItems.ts`, `serviceCategories.ts`, `products.ts`, `inventoryFinance.ts`, `sales.ts`, `payouts.ts`, `packages.ts`, `financeReports.ts`, `operatingExpenses.ts`, `exchangeRates.ts`, `reports.ts`, `dashboard.ts`, `logs.ts`, `work-time.ts`, `fetch-all-pages.ts`. Pure axios functions, no React.

### 6.3 `src/hooks/api/` (19 hooks + 10 tests)

One Query/Mutation hook per domain: `useAuthQuery`, `useCustomersQuery`, `useVisitsQuery`, `useServicesQuery`, `useServiceItemsQuery`, `useServiceCategoriesQuery`, `useProductsQuery`, `useInventoryFinanceQuery`, `useSalesQuery`, `usePayoutsQuery`, `usePackagesQuery`, `useFinanceReportsQuery`, `useOperatingExpensesQuery`, `useExchangeRatesQuery`, `useReportsQuery`, `useDashboardQuery`, `useLogsQuery`, `useWorkTimeQuery`, `index.ts` barrel. Uses `lib/query-keys.ts` for keys.

### 6.4 `src/hooks/` (global)

`useCommandPalette.ts`, `useLoginForm.ts`, `usePermissions.ts` (role gating, e.g. logs), `useQuickActions.ts`, `useWalkthrough.ts` (driver.js).

### 6.5 `src/contexts/`

`AuthContext.tsx` (user/me/role), `WizardContext.tsx` (wizard state), `QueryProvider.tsx`, `commandPalette.ts`, `quickAction.ts`, `Toast` lives under `components/ui/Toast/`.

---

## 7. UI / components

### 7.1 Design system `src/components/ui/` (25 components)

`Alert`, `Avatar`, `Badge`, `Button`, `CalendarOverlay`, `Card`, `EmptyState`, `ErrorFallback`, `Input`, `JalaliDatePicker`, `LoadingBar`, `Modal`, `NotFound`, `Pagination`, `PortalTargetContext`, `Progress`, `Select`, `Skeleton`, `Spinner`, `Table`, `Tabs`, `Textarea`, `Toggle`, `Tooltip`, `Toast/*`, barrel `index.ts`. 21 test files in `__tests__/`.

### 7.2 Domain components

* `accounting/` (9): `SalesTab`, `CheckoutModal`, `VisitCheckoutModal`, `ConsumptionStep`, `RefundModal`, `PayoutsTab`, `OperatingExpensesTab`, `OperatingExpenseFormModal`, `OperatingExpenseCategoryModal`.
* `warehouse/` (4): `UsagesTab`, `PurchaseModal`, `PriceCell`, `CostHistoryModal`.
* `services/` (4): `ServiceFormModal`, `ServiceDetailModal`, `PackagesTab`, `PackageFormModal`.
* `wizard/` (3): `WizardStepPatient`, `WizardStepService`, `WizardStepPayment`.
* `settings/` (3): `ServiceCategoriesTab`, `ExchangeRatesTab`, `CompensationRulesTab`.
* `dashboard/` (2): `FinanceKpiCards`, `ExchangeRateCard`.
* `analytics/` (2): `FinancialSummaryTab`, `ProfitBreakdownTab`.
* `patients/` (1): `PatientFormModal`.
* Root: `Sidebar.tsx`, `CommandPalette.tsx`, `SearchButton.tsx`, `QuickActionProvider.tsx`, `PwaUpdater.tsx`, `walkthrough/WalkthroughButton.tsx`.

### 7.3 Styling

`src/index.css` (251 lines): `@import "tailwindcss"` + `@theme` tokens `primary-*` (blue), `success-*` (emerald), `warning-*` (amber), `danger-*` (red), `info-*` (sky), `surface-*` (slate); breakpoints `mobile 23.4375rem, tablet 48rem, laptop 80rem, desktop 90rem, largeDesktop 120rem`; Vazirmatn font; RTL fixes; walkthrough + calendar-blue-theme + scrollbar styles. No dark mode.

---

## 8. Lib / types / data

`src/lib/` (13): `api-client.ts` (axios instance + interceptors), `api-error.ts`, `query-keys.ts`, `pagination.ts`, `validations.ts` (zod helpers), `format.ts`, `currency.ts`, `digits.ts` (fa/en digits), `date.ts` (Jalali), `excel.ts` (xlsx export), `report-chart.ts`, `transform.ts`, `wizard-storage.ts`. 9 tests.

`src/types/` (16): `api.ts`, `auth.ts`, `patient.ts`, `appointment.ts`, `service.ts`, `finance.ts`, `warehouse.ts`, `analytics.ts`, `dashboard.ts`, `settings.ts`, `wizard.ts`, `sidebar.ts`, `toast.ts`, `common.ts`, `index.ts`, `jalaali-js.d.ts`. `import type` required (`verbatimModuleSyntax`).

`src/data/walkthroughSteps.ts`: driver.js steps.

`src/config/roles.ts`: `routePermissions` (e.g. `/logs` admin-only).

---

## 9. Tests

* Unit (Vitest, ~235 files under `src`, co-located `__tests__`): ui (21), services (18), hooks/api (10), lib (9), routes (2), contexts (1), config (1), wizard (2), patients (1), services-components (2), accounting (4).
* E2E (Playwright, `e2e/` 20 files): `auth.setup.ts`, `helpers.ts`, `auth`, `dashboard`, `patients`, `calendar`, `services`, `warehouse`, `accounting`, `analytics`, `settings`, `logs`, `checkout-flow`, `complete-flow`, `appointment-flow`, `visit-lifecycle`, `calendar-wizard-validation`, `finance-roles`, `error-handling`, `responsive`.
* Config: `vitest.config.ts`, `playwright.config.ts`, `playwright.no-server.config.ts`.

---

## 10. PWA / deploy

* `vite-plugin-pwa` `registerType: prompt`, `injectRegister: false`; icons in `public/` (`favicon.svg`, `apple-touch-icon.svg`, `icon-192.svg`, `icon-512.svg`); `PwaUpdater.tsx` prompts update.
* Build base `/dashboard/` (Django serves frontend under `/dashboard/`); dev `/`. See `liara.json`, `Dockerfile`, `nginx.conf`, `supervisord.conf`, `start.sh` in repo root.

---

## 11. Visual file tree

### 11.1 Repo root (frontend + backend)

```
sefro-clinic-pwa/
├── index.html                  # fa/RTL, Vazirmatn, #root
├── package.json                # React19/Vite8/Tailwind4/Query5
├── vite.config.ts              # base /dashboard on build, PWA, /api proxy
├── tsconfig.app.json / tsconfig.json / tsconfig.node.json
├── vitest.config.ts / playwright.config.ts / eslint.config.js
├── public/
│   ├── favicon.svg
│   ├── apple-touch-icon.svg
│   ├── icon-192.svg
│   └── icon-512.svg
├── src/                        # ← detailed below (235 files)
├── e2e/                        # 20 Playwright specs
├── backend/                    # Django DRF API (this docs/ lives inside it)
│   └── docs/
│       └── front-analyze.md    # ← this file
├── website/                    # separate static site
├── docs/                       # repo-level docs (superpowers/)
├── .github/workflows/ci.yml    # lint → typecheck → test → build
├── Dockerfile / nginx.conf / supervisord.conf / start.sh / liara.json
└── AGENTS.md / README.md / DESIGN.md
```

### 11.2 `src/` full tree (generated from disk)

```
src/
├── App.tsx
├── main.tsx
├── index.css
├── components/
│   ├── Sidebar.tsx
│   ├── CommandPalette.tsx
│   ├── SearchButton.tsx
│   ├── QuickActionProvider.tsx
│   ├── PwaUpdater.tsx
│   ├── accounting/
│   │   ├── SalesTab.tsx
│   │   ├── CheckoutModal.tsx
│   │   ├── VisitCheckoutModal.tsx
│   │   ├── ConsumptionStep.tsx
│   │   ├── RefundModal.tsx
│   │   ├── PayoutsTab.tsx
│   │   ├── OperatingExpensesTab.tsx
│   │   ├── OperatingExpenseFormModal.tsx
│   │   └── OperatingExpenseCategoryModal.tsx
│   ├── analytics/
│   │   ├── FinancialSummaryTab.tsx
│   │   └── ProfitBreakdownTab.tsx
│   ├── dashboard/
│   │   ├── FinanceKpiCards.tsx
│   │   └── ExchangeRateCard.tsx
│   ├── patients/
│   │   └── PatientFormModal.tsx
│   ├── services/
│   │   ├── ServiceFormModal.tsx
│   │   ├── ServiceDetailModal.tsx
│   │   ├── PackagesTab.tsx
│   │   └── PackageFormModal.tsx
│   ├── settings/
│   │   ├── ServiceCategoriesTab.tsx
│   │   ├── ExchangeRatesTab.tsx
│   │   └── CompensationRulesTab.tsx
│   ├── warehouse/
│   │   ├── UsagesTab.tsx
│   │   ├── PurchaseModal.tsx
│   │   ├── PriceCell.tsx
│   │   └── CostHistoryModal.tsx
│   ├── wizard/
│   │   ├── WizardStepPatient.tsx
│   │   ├── WizardStepService.tsx
│   │   └── WizardStepPayment.tsx
│   ├── walkthrough/
│   │   └── WalkthroughButton.tsx
│   └── ui/                     # design system (barrel index.ts)
│       ├── Alert.tsx / Avatar.tsx / Badge.tsx / Button.tsx
│       ├── CalendarOverlay.tsx / Card.tsx / EmptyState.tsx
│       ├── ErrorFallback.tsx / Input.tsx / JalaliDatePicker.tsx
│       ├── LoadingBar.tsx / Modal.tsx / NotFound.tsx
│       ├── Pagination.tsx / Progress.tsx / Select.tsx
│       ├── Skeleton.tsx / Spinner.tsx / Table.tsx
│       ├── Tabs.tsx / Textarea.tsx / Toggle.tsx / Tooltip.tsx
│       ├── PortalTargetContext.ts / index.ts
│       └── Toast/
│           ├── ToastContext.tsx / ToastProvider.tsx / index.ts
├── routes/
│   ├── index.tsx               # createBrowserRouter
│   ├── RouteGuard.tsx          # RequireAuth / RedirectIfAuth / RequireRole
│   ├── Dashboard.tsx
│   ├── WizardPage.tsx
│   ├── Patients.tsx
│   ├── Calendar.tsx
│   ├── Services.tsx
│   ├── Warehouse.tsx
│   ├── Accounting.tsx
│   ├── Analytics.tsx
│   ├── Settings.tsx
│   ├── Logs.tsx                # admin-only
│   ├── Auth.tsx
│   └── DesignSystem.tsx        # DEV only
├── services/                   # axios layer (no React)
│   ├── auth.ts / customers.ts / visits.ts
│   ├── services.ts / serviceItems.ts / serviceCategories.ts
│   ├── products.ts / inventoryFinance.ts
│   ├── sales.ts / payouts.ts / packages.ts
│   ├── financeReports.ts / operatingExpenses.ts
│   ├── exchangeRates.ts / reports.ts / dashboard.ts
│   ├── logs.ts / work-time.ts / fetch-all-pages.ts
├── hooks/
│   ├── useCommandPalette.ts / useLoginForm.ts
│   ├── usePermissions.ts / useQuickActions.ts / useWalkthrough.ts
│   └── api/                    # TanStack Query wrappers
│       ├── useAuthQuery.ts / useCustomersQuery.ts
│       ├── useVisitsQuery.ts / useServicesQuery.ts
│       ├── useServiceItemsQuery.ts / useServiceCategoriesQuery.ts
│       ├── useProductsQuery.ts / useInventoryFinanceQuery.ts
│       ├── useSalesQuery.ts / usePayoutsQuery.ts
│       ├── usePackagesQuery.ts / useFinanceReportsQuery.ts
│       ├── useOperatingExpensesQuery.ts / useExchangeRatesQuery.ts
│       ├── useReportsQuery.ts / useDashboardQuery.ts
│       ├── useLogsQuery.ts / useWorkTimeQuery.ts
│       └── index.ts
├── lib/
│   ├── api-client.ts / api-error.ts / query-keys.ts
│   ├── pagination.ts / validations.ts / format.ts
│   ├── currency.ts / digits.ts / date.ts
│   ├── excel.ts / report-chart.ts / transform.ts
│   └── wizard-storage.ts
├── types/
│   ├── api.ts / auth.ts / patient.ts / appointment.ts
│   ├── service.ts / finance.ts / warehouse.ts
│   ├── analytics.ts / dashboard.ts / settings.ts
│   ├── wizard.ts / sidebar.ts / toast.ts / common.ts
│   ├── index.ts / jalaali-js.d.ts
├── contexts/
│   ├── AuthContext.tsx / WizardContext.tsx
│   ├── QueryProvider.tsx / commandPalette.ts / quickAction.ts
├── config/
│   ├── api.ts                  # endpoints map
│   └── roles.ts                # routePermissions
├── data/
│   └── walkthroughSteps.ts
└── test/
    └── setup.ts
```

> Counts: `src` 235 files; `components` 5 root + 9 accounting + 2 analytics + 2 dashboard + 1 patients + 4 services + 3 settings + 4 warehouse + 3 wizard + 1 walkthrough + 25 ui (+21 ui tests); `routes` 14; `services` 19 (+18 tests); `hooks/api` 19 (+10 tests); `lib` 13 (+9 tests); `types` 16.

### 11.3 `e2e/` + `public/`

```
e2e/
├── auth.setup.ts / helpers.ts
├── auth.spec.ts / dashboard.spec.ts / patients.spec.ts
├── calendar.spec.ts / services.spec.ts / warehouse.spec.ts
├── accounting.spec.ts / analytics.spec.ts / settings.spec.ts
├── logs.spec.ts / checkout-flow.spec.ts / complete-flow.spec.ts
├── appointment-flow.spec.ts / visit-lifecycle.spec.ts
├── calendar-wizard-validation.spec.ts / finance-roles.spec.ts
├── error-handling.spec.ts / responsive.spec.ts

public/
├── favicon.svg / apple-touch-icon.svg
├── icon-192.svg / icon-512.svg
```

---

## 12. How to read this frontend (suggested order)

1. `package.json` → `index.html` → `src/main.tsx` → `src/App.tsx` → `src/routes/index.tsx`
2. `src/config/api.ts` + `src/config/roles.ts`
3. `src/lib/api-client.ts` → `src/services/auth.ts` → `src/hooks/api/useAuthQuery.ts` → `src/contexts/AuthContext.tsx`
4. `src/components/ui/index.ts` + `src/index.css`
5. One vertical slice: `routes/Patients.tsx` → `components/patients/PatientFormModal.tsx` → `hooks/api/useCustomersQuery.ts` → `services/customers.ts` → `types/patient.ts`
6. Wizard slice: `routes/WizardPage.tsx` → `contexts/WizardContext.tsx` → `components/wizard/*` → `lib/wizard-storage.ts`
