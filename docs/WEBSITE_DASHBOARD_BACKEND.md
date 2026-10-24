# Website dashboard backend contract

The website manager login is independent from the clinic's financial JWT
session. It uses a separate username/password linked to an existing `ClinicUser`
identity (admin or employee), without adding another financial account role.
The password is hashed. The browser receives an opaque, HttpOnly
`website_dashboard_session` cookie scoped to `/api/v2/site-dashboard/`; only a
SHA-256 hash of its random secret is stored in PostgreSQL. Sessions expire
after eight hours, are revoked on logout, and are invalidated when a manager's
website password is reset. The website cookie cannot authenticate `/api/auth/`
or financial routes; clinic JWTs cannot authenticate website-dashboard routes.

Provision a website manager after migrations, using an existing staff account:

```powershell
$env:WEBSITE_MANAGER_NEW_PASSWORD = '<strong private password>'
& 'venv\Scripts\python.exe' manage.py set_website_manager --clinic-username <staff-username> --website-username <distinct-website-username> --password-env WEBSITE_MANAGER_NEW_PASSWORD
Remove-Item Env:WEBSITE_MANAGER_NEW_PASSWORD
```

Do not put the password in a shell command argument, source file, or API
response. Provisioning a new password invalidates old website sessions.

Frontend changes required for the new isolated login:

- `POST /api/v2/site-dashboard/login/` with website username/password, then
  `GET /api/v2/site-dashboard/me/` and `POST /api/v2/site-dashboard/logout/`.
  Do not use `/api/auth/me/` or `/api/auth/logout/` for the website dashboard.
- Send cookies (`credentials: 'include'`) and `X-CSRFToken` from the `csrftoken`
  cookie on PATCH/POST actions after login. Never store a website session token
  in browser JavaScript storage. Clinic and website sessions may coexist.
- Manage team at `/team/`, testimonials at `/testimonials/`, and visitor messages
  at `/contact-messages/` under `/api/v2/site-dashboard/`. Team/testimonials
  support GET/POST/PATCH; hide with `is_active=false` rather than deleting.
  Contact messages support GET and PATCH of `is_handled` only. Visitor text is
  never editable through the dashboard.
- Trigger a manual price refresh with `POST /price-sync/run/`; inspect the
  latest run with `GET /price-sync/status/`. The refresh is throttled and
  serialized across workers. It updates website prices and website sync
  history only, never the financial ExchangeRate ledger.
- Product and package pages now support create and content-only PATCH in
  addition to Toman/USD price changes. A package's `service_ids` write field
  controls service links; `services` remains a read-only summary. Existing
  slugs cannot be changed because they are public URLs and crawl identities.
  Dashboard-edited catalog/content rows are protected from later imports.

The repository includes a `sync_website_prices` management command for an
external twice-daily scheduler; no scheduler configuration is included here.
Production migrations and credential provisioning must be deployed explicitly.
