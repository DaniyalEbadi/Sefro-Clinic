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
import are marked inactive rather than deleted. Product detail-page descriptions
are stored separately from card summaries.

When the rate provider is unavailable, the importer still saves the exact
live Toman prices. A positive Toman price with `price_usd=0` means its USD base
is pending; the first successful sync using the updated backend derives that
base from the saved Toman price at the newly available rate, preserving the
public price on that run. Later successful runs reprice from the initialized
USD base. Deploy the updated sync code before enabling a new provider or
running a sync against these pending records; older deployed code would
calculate zero Toman from the pending USD values.

The command reads PriceToDay's USD price in rial and divides by 10 to get
Toman per USD. If that request fails, it reads Nerkhsanj's public
`/data/live.json` feed; `rates.dollar` is already Toman per USD. That feed
requires no API token. The previous Tindex and BrsApi integrations are retired.
If both feeds fail, existing website prices are preserved and the failure is
recorded for `GET /api/v2/site-dashboard/price-sync/status/`. A manager can
use `POST /api/v2/site-dashboard/price-sync/run/` with
`{"rate": "100000"}` to apply an independently verified Toman-per-USD rate
without touching financial exchange rates. This manual step does not restore
unattended twice-daily sync: configure a functioning provider for that.

The protected website dashboard endpoints are:

- `GET/PATCH /api/v2/site-dashboard/services/<slug>/`
- `GET/PATCH /api/v2/site-dashboard/packages/<slug>/`
- `GET/PATCH /api/v2/site-dashboard/products/<slug>/`
- `GET/POST /api/v2/site-dashboard/package-price-options/`
- `GET/PATCH /api/v2/site-dashboard/package-price-options/<id>/`
- `GET/PATCH /api/v2/site-dashboard/settings/`

Authenticated website managers may submit either `price` (Toman)
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
When a valid rate is available, the importer uses the same precise
Toman-to-USD conversion for future imports.

Packages also accept `original_price` (Toman) or `original_price_usd` (USD).
These form a separate pair, so `price` and `original_price_usd` can be supplied
together. Supplying `null` for either original-price field clears both original
prices. Editing an original price leaves the current price unchanged.

All prices must be finite and non-negative, and must fit the destination
Toman database field. Catalog listing remains paginated at 20 records per
page: follow `next` until null to retrieve all 62 services.
