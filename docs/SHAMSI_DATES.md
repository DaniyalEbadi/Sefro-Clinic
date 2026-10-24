# Shamsi dates in Sefro Clinic

First-party Django models in `accounts`, `customers`, `face_analyzer`, `finance`,
`logs`, and `website` keep native PostgreSQL date/timestamp columns for ranges,
timezones, ordering, indexes, and financial calculations. Each native date
column also has a stored, read-only `<field>_shamsi` text column. Date-only
mirrors use `YYYY-MM-DD`; timestamps use Tehran-local
`YYYY-MM-DD HH:MM:SS.ffffff` to preserve the time precisely. The native field
is authoritative; never write the mirror directly from API input.

Migration `finance.0024_backfill_shamsi_dates` fills mirrors on existing rows
after all schema migrations have added their columns. Normal `save()` and
`bulk_create()` populate mirrors automatically; partial `save(update_fields=...)`
adds the matching mirror field. `QuerySet.update()` and `bulk_update()` bypass
field hooks: any new direct update of a native date must also update its
mirror with `Sefro_Clinic.shamsi_storage.shamsi_storage_value`. The existing
direct update of product-cost history does this.

Public API date input and output uses Shamsi. Historical monthly-close JSON
snapshots are normalized on read without recalculating their financial data;
new snapshots store Shamsi period strings. Django/framework-owned tables
(sessions, token blacklist, etc.) retain their native timestamp schema.

Before deploying these migrations to a production database, take a fresh
backup, confirm the exact target database, and schedule time for the batched
backfill. These changes do not automatically migrate the production database.
