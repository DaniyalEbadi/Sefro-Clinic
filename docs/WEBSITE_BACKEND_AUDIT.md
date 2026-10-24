# Baran Clinic website / Site API v2 audit

Inspected 2026-10-20. This covers the publicly deployed site and the local
backend; it does not confirm that the deployed frontend consumes this backend.

## Verified live content

- [Services](https://barancliniccenter.com/services): 62 cards, split into
  11 filler/Botox, 18 women's laser, 25 men's laser, and 8 facial services.
- [Packages](https://barancliniccenter.com/packages): 16 cards with 34 price
  options, including a six-session plus two-gift-session package.
- [Products](https://barancliniccenter.com/products): 3 products. All 62
  service detail routes and all 3 product detail routes returned pages with
  an H1; none failed during this audit.
- [About](https://barancliniccenter.com/about): one specialist, clinic
  statistics, about copy, and images. The home page has three testimonials.
- [Contact](https://barancliniccenter.com/contact): address, three telephone
  numbers, and opening hours. Booking buttons lead toward contacting the clinic.

## Price editing implemented in this change

- Existing dashboard PATCH endpoints accept `price` in Toman or `price_usd`
  in dollars; package original prices support either currency as well.
- The same rule applies when creating or updating a package price option.
- Fractional Toman amounts round upward; a Toman edit updates the USD base.
- USD precision is expanded to 12 decimal places so resyncing at the same
  exchange rate preserves a newly entered whole-Toman amount.
- Supplying both currencies for the same price returns 400; invalid amounts,
  negative values, and values that overflow the Toman field are rejected.
- The 20-item public pagination contract remains. Website-dashboard authentication
  is now a separate credential and cookie session; see `WEBSITE_DASHBOARD_BACKEND.md`.
- Session option prices are edited through `package-price-options`; changing
  the legacy package price does not replace every session option price.

## Remaining findings

These were found by reading the importer, routes, local data, deployment
configuration, and live provider responses. They are not fixed by the price
editing change and should not be treated as completed backend features.

| Area | Finding / impact |
| --- | --- |
| Live exchange refresh | The primary provider returned HTTP 401 and the backup returned no valid rate during the audit. Cached/default rates still allow dashboard edits, but live twice-daily repricing cannot succeed until provider configuration is working. |
| Scheduling | A sync command and recommended 00:00/12:00 Tehran schedule exist. No price-sync scheduler is defined in this repository's deployment configuration; an external scheduler must be verified/configured. |
| Clinic settings | The imported settings record has an empty address, repeated phone numbers, and phone values stored as statistics. The importer needs section-specific extraction. |
| Public settings | Settings currently have an authenticated dashboard endpoint only. A public settings read endpoint is needed before frontend clinic content can be driven by these records. |
| Product descriptions | The live product detail page contains longer descriptive text, but `SiteProduct` stores only its card's short description. |
| Team/testimonial import | The current importer contains hardcoded team/testimonial text rather than parsing their live sections and does not reconcile missing people/testimonials. |
| Financial isolation | Updated 2026-10-24: website price synchronization no longer writes `finance.ExchangeRate`; dashboard rate lookup uses website sync history or the external providers without refreshing the financial ledger. |
| Import overwrite behavior | Updated 2026-10-24: dashboard-edited catalog, settings, team, and testimonial records are marked manually managed and preserved on later imports. Unedited imported records continue to follow the live source. |
| Shopping cart | A product detail page shows an add-to-cart action. Site API v2 currently has no cart, order, payment, or checkout APIs; a commerce flow would require a separate specification. |

The catalog read and price-editing APIs are available. The findings above
prevent calling the entire website backend fully complete or its live
exchange-rate automation operational based on the current evidence.
