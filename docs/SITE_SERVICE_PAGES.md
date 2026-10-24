# Site API v2 service pages

The public detail route is `GET /api/v2/services/{slug}/`. It returns the page
title (`name`), short and full descriptions, current Toman/USD price, service
category, duration, image URL, and source URL. The public service list is
paginated and only shows active records. Packages, products, team,
testimonials, contact intake, and face analysis use separate v2 routes.

Current Site API v2 surface:

| Area | Routes |
| --- | --- |
| Public catalogue | `/services/`, `/packages/`, `/products/` (list and slug detail) |
| Public content/intake | `/team/`, `/testimonials/`, `POST /contact/` |
| Face analyzer | `/face/analyze/`, `/face/{id}/tips/`, `/face/history/`, `/face/history/{id}/` |
| Dashboard | `/site-dashboard/login/`, `/me/`, `/logout/`, service/package/product management, package price options, settings, team, testimonials, contact messages, and price-sync status/run |
| Metadata | `/site/info/` (authenticated), `/schema/`, `/docs/` |

All routes above are relative to `/api/v2/`. Financial v1 routes live in a
different URL/schema and are unchanged by the service page editor.

Dashboard service management is confined to `/api/v2/site-dashboard/services/`
and accepts only the independent website-manager session cookie, not a staff JWT. It does not write
to the financial v1 service table. `POST` creates a full service page; `PATCH
/{slug}/` edits its page data. For prices, send **either** `price` (Toman) or
`price_usd` (USD). Toman input is rounded upward to a whole Toman, converted
to an editable USD base at the current exchange rate, and follows subsequent
website price syncs. A content-only PATCH does not require the rate provider.
Edited/created services are marked manually managed, so re-importing the live
catalogue does not overwrite or deactivate them.

Example creation:

```json
{
  "name": "بوتاکس صورت",
  "slug": "botox-face",
  "category": "face",
  "short_description": "کاهش خطوط صورت",
  "description": "با تزریق دقیق در عضلات هدف، خطوط اخم و چروک پیشانی کاهش می‌یابد.",
  "price": "800000",
  "image_url": "https://example.com/botox.jpg"
}
```

For an uploaded photo, send `multipart/form-data` with field `image` to
`POST /api/v2/site-dashboard/services/{slug}/image/`. Only verified JPEG, PNG,
or WebP files up to 5 MB are accepted. The server generates a random object
name under `farabaks3/baran-clinic/services/{slug}/`, saves both the object key
and permanent image URL on the service, and does not list/delete or modify any
other bucket prefix. This is a dedicated S3 client; other Django media files
keep their existing storage.

Set `LIARA_ACCESS_KEY` and `LIARA_SECRET_KEY` in the deployment environment,
using an object-storage key authorized for `farabaks3`. The API endpoint and
bucket are fixed in settings. By default the URL is
`https://storage.c2.liara.site/farabaks3/<key>`; optionally set
`LIARA_WEBSITE_PUBLIC_BASE_URL` to a public bucket/CDN base. Public images need
read access scoped to `baran-clinic/*` or a CDN serving only that prefix; do
not make unrelated bucket folders public. A private prefix will not serve
these permanent URLs. The supplied endpoint/bucket alone cannot authenticate
an actual upload. Do not put credentials in source control.

Liara's Django connection guide is
<https://docs.liara.ir/object-storage/how-tos/connect-via-platform/django/>.
