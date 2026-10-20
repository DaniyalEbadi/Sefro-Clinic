# Website price synchronization

Website catalog prices can be entered in either Toman or USD through the
authenticated dashboard. USD remains the base used by rate synchronization.
Derived Toman prices are always rounded upward to a whole Toman, so values such
as `799.999` are stored and returned as `800.00`.

Run the synchronization command twice per day in the deployment environment:

```text
python manage.py sync_website_prices
```

Recommended Tehran schedule:

- `00:00 Asia/Tehran`
- `12:00 Asia/Tehran`

The initial public catalog import is idempotent and can be run with:

```text
python manage.py import_website_catalog
```

It imports the live services, packages, every package price option, products,
team members, testimonials, and site settings. Records missing from a later
import are marked inactive rather than deleted.

The command tries the configured primary provider first and BrsApi as the
backup. If both providers fail, existing website prices are preserved and the
failure is recorded for `GET /api/v2/site-dashboard/price-sync/status/`.

The protected website dashboard endpoints are:

- `GET/PATCH /api/v2/site-dashboard/services/<slug>/`
- `GET/PATCH /api/v2/site-dashboard/packages/<slug>/`
- `GET/PATCH /api/v2/site-dashboard/products/<slug>/`
- `GET/POST /api/v2/site-dashboard/package-price-options/`
- `GET/PATCH /api/v2/site-dashboard/package-price-options/<id>/`
- `GET/PATCH /api/v2/site-dashboard/settings/`

Existing authenticated admins and employees may submit either `price` (Toman)
or `price_usd` (USD) for services, products, packages, and package price options.
Do not send both currencies for the same price: this returns HTTP 400 without
changing the record. A valid exchange rate is required for either currency;
if no rate is available the request returns HTTP 503 without saving changes.

For example:

```http
PATCH /api/v2/site-dashboard/services/botox-face/
Content-Type: application/json

{"price": "1800000"}
```

This stores `1800000.00` Toman and derives `price_usd` using the current rate.
Fractional Toman amounts are rounded upward (`799.999` becomes `800.00`).
USD bases retain 12 decimal places so converting an entered Toman price back
at the same rate preserves it. Future rate changes continue to adjust the
Toman price. Existing stored USD values are preserved by the precision migration.
The importer uses the same precise Toman-to-USD conversion for future imports.

Packages also accept `original_price` (Toman) or `original_price_usd` (USD).
These form a separate pair, so `price` and `original_price_usd` can be supplied
together. Supplying `null` for either original-price field clears both original
prices. Editing an original price leaves the current price unchanged.

All prices must be finite and non-negative, and must fit the destination
Toman database field. Catalog listing remains paginated at 20 records per
page: follow `next` until null to retrieve all 62 services.
