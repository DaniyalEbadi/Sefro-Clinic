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
response. Resetting a website username's password invalidates only that
username's sessions. Multiple website usernames can be linked to the same
staff identity without replacing one another; none of their website passwords
can authenticate the financial dashboard.

Frontend changes required for the new isolated login:

- Public homepage settings are `GET /api/v2/site/settings/` (no cookie or
  clinic login required). The response contains `clinic_name`, `logo_url`,
  `address`, `phone_numbers`, `contact_email`, `social_links`, `working_hours`,
  `about_title`, `about_text`, `statistics`, `hero_image_url`, and
  `about_image_url`. Website managers edit the same record with
  `PATCH /api/v2/site-dashboard/settings/`. Newly added branding/social
  fields default to empty until a manager fills them in. Frontend static
  fallbacks should be treated as fallbacks, not the authoritative source.
- Public catalog lists are paginated objects (`count`, `next`, `previous`,
  `results`), not top-level arrays. Render `results` and follow `next` when
  the page needs the full catalog (for example, all 62 services).
- `POST /api/v2/site-dashboard/login/` with website username/password, then
  `GET /api/v2/site-dashboard/me/` and `POST /api/v2/site-dashboard/logout/`.
  Do not use `/api/auth/me/` or `/api/auth/logout/` for the website dashboard.
- Treat `GET /me/` HTTP 401 as a settled logged-out state and clear any
  loading indicator; do not retry it indefinitely or attempt clinic JWT
  refresh. Login HTTP 401 means invalid website credentials, not a pending
  session. On network/5xx errors, show a recoverable error state rather than
  leaving authentication loading forever.
- Send cookies (`credentials: 'include'`) and `X-CSRFToken` from the `csrftoken`
  cookie on PATCH/POST actions after login. Never store a website session token
  in browser JavaScript storage. Clinic and website sessions may coexist.
- If the frontend is on a different origin from the API, add its exact scheme,
  host, and port to both `CORS_ALLOWED_ORIGINS` and `CSRF_TRUSTED_ORIGINS` in
  the backend environment. For example, a frontend on
  `http://localhost:3000` needs that exact value in both lists. The browser
  sends an OPTIONS preflight before JSON login; an absent
  `Access-Control-Allow-Origin` header means the request is blocked before
  authentication. Do not set `CORS_ALLOW_ALL_ORIGINS=True` for a
  credentialed dashboard. Prefer the same host spelling on both sides
  (`localhost` versus `127.0.0.1`) so SameSite cookies behave predictably.
- Manage team at `/team/`, testimonials at `/testimonials/`, and visitor messages
  at `/contact-messages/` under `/api/v2/site-dashboard/`. Team/testimonials
  support GET/POST/PATCH; hide with `is_active=false` rather than deleting.
  Contact messages support GET and PATCH of `is_handled` only. Visitor text is
  never editable through the dashboard.
- Read `GET /price-sync/status/` when loading the dashboard. Before any run,
  it returns HTTP 200 with `status: "never_run"`; after a failed run, it also
  exposes the last successful `effective_rate` if one exists. Do not POST a
  sync automatically on login or on every page load.
- Trigger `POST /price-sync/run/` only on a manager's explicit refresh action.
  Omit the body to try the configured providers, or send
  `{ "rate": "100000" }` to use a manager-supplied Toman-per-USD rate if they
  are unavailable. Automatic requests made within five minutes of a finished
  run return its cached result and a `Retry-After` header; a cached failure
  remains HTTP 503, not HTTP 429. A manual rate can be submitted immediately.
  Synchronization is serialized across workers and updates website prices and
  website sync history only, never the financial ExchangeRate ledger.
- Website-manager login, authenticated website-dashboard requests, and public
  Site API v2 reads have separate rate-limit buckets. The manager's bucket is
  keyed by website credential, not by the linked clinic user, so website
  managers sharing one staff identity do not consume each other's quota or
  the financial API quota. Contact submissions keep their stricter limit.
- Product and package pages now support create and content-only PATCH in
  addition to Toman/USD price changes. A package's `service_ids` write field
  controls service links; `services` remains a read-only summary. Existing
  slugs cannot be changed because they are public URLs and crawl identities.
  Dashboard-edited catalog/content rows are protected from later imports.

The repository includes a `sync_website_prices` management command for an
external twice-daily scheduler; no scheduler configuration is included here.
Production migrations and credential provisioning must be deployed explicitly.

For local backend tests, the isolated test database bootstraps the fixed
`sefro_admin` test fixture regardless of `CLINIC_ADMIN_USERNAME` in `.env`;
normal commands and production continue to use the configured username.
Check the effective `DATABASE_URL` before assuming a catalog is empty. A
server started with a `DATABASE_URL` pointing to a different PostgreSQL
database is not reading the local `sefro_clinic` catalog. To run against the
local development database in PowerShell, explicitly clear that override for
the process:

```powershell
$env:DATABASE_URL=''
& 'venv\Scripts\python.exe' manage.py runserver
```

Never run migrations or imports on a remote database merely to make a local
frontend appear populated.
