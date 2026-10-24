# Face analyzer in Site API v2

The four face analyzer routes are available at `/api/v2/face/` and in
`/api/v2/docs/` under **Site Face Analyzer**. The existing `/api/v3/face/`
routes continue to use the same analysis records. The financial `/api/`
schema does not include these routes.

| Method | Site API v2 route | Access |
| --- | --- | --- |
| POST | `/api/v2/face/analyze/` | Public; multipart `image`; throttled |
| POST | `/api/v2/face/{id}/tips/` | Public for anonymous analyses; owner or admin for staff analyses; throttled |
| GET | `/api/v2/face/history/` | Authenticated staff; own records, or all for admin |
| GET | `/api/v2/face/history/{id}/` | Authenticated owner or admin |

The full analysis response includes the existing scores, detected attributes,
suggestions, and `skin_plan`, plus a `recommendations` object. Its Persian
`summary`, `next_steps`, and `disclaimer` accompany three arrays: `services`,
`products`, and `packages`. Each catalog item has `id`, `slug`, `name`,
`price_toman` (a whole-Toman string), `source_url`, `api_url`, `image_url`,
`matched_concern`, and `reason`. Services also have `is_from_price`. Packages
also have active `price_options` with session and gift counts and whole-Toman
prices.

Recommendations are computed when the full response is read, so a staff
history detail shows current catalog prices and active status. The analysis
scores and detected concerns remain the stored snapshot. The rule mapping
offers only active website records; a low score alone never selects a clinic
procedure. A package is shown only when it contains a selected active service.
The current imported laser packages have no linked services, so an empty
`packages` array is expected for skin concerns. Recommendations are options
for discussion, not a medical diagnosis.

Professional skin-plan tips now link to `website.SiteService`. The migration
clears old financial service IDs and reconnects only tips whose recorded slug
exactly matches a website service. Historical tips without a match keep their
text and slug but have a null service link. New tips for unavailable website
services are omitted. The optional LLM prompt receives only active website
service records.

## Local model deployment

The default local provider uses MediaPipe. MediaPipe Tasks versions require a
compatible `face_landmarker.task` model. Set `FACE_ANALYZER_MODEL_PATH` to the
model file or its containing directory; relative paths resolve from the
project root. The development workspace currently has the file at
`models/face_analyzer/face_landmarker.task`, but that asset is not tracked by
Git. Provision it explicitly on each deployed host. A missing runtime or
model returns HTTP 503; an invalid image or no detected face returns HTTP 400.
The external provider remains available through
`FACE_ANALYZER_MODEL_PROVIDER=external` and its existing API settings.
