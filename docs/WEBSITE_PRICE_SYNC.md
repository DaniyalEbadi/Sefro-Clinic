# Website price synchronization

Website catalog prices use editable USD base values and derived Toman values.
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
- `GET/POST/PATCH /api/v2/site-dashboard/package-price-options/<id>/`
- `GET/PATCH /api/v2/site-dashboard/settings/`

Only `price_usd` is editable for services and products. Packages support both
`price_usd` and `original_price_usd`; the corresponding public Toman fields are
derived automatically. Existing authenticated admins and employees may use
these endpoints.
