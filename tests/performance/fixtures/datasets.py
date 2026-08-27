"""Reusable fixtures wrapping the data factories into named scenarios.

Each builder isolates its dataset behind test-class isolation (Django wraps
every TestCase in a transaction rollback), so suites can request the scale
they need without cross-contamination.
"""
from .factories import build_clinic_dataset, create_products, create_site_content

SMALL = dict(customers=60, visits_per_customer=2, payments_per_customer=2, services=15)
"""Single-clinic branch: ~60 customers, 120 visits, 120 payments."""

MEDIUM = dict(customers=300, visits_per_customer=3, payments_per_customer=3, services=25)
"""Busier branch: ~300 customers, ~900 visits, ~900 payments."""

API_BENCH = dict(customers=150, visits_per_customer=2, payments_per_customer=3, services=20)
"""Steady-state dataset for endpoint benchmarks."""

PRODUCT_CATALOG = 500
"""Inventory rows used by product list/search/scaling tests."""


def small_clinic():
    return build_clinic_dataset(**SMALL)


def medium_clinic():
    return build_clinic_dataset(**MEDIUM)


def api_bench_clinic():
    return build_clinic_dataset(**API_BENCH)


def product_catalog(count=PRODUCT_CATALOG):
    return create_products(count)


def site_catalog():
    return create_site_content()
