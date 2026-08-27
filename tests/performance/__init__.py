"""Production-grade performance test suite for Sefro Clinic.

Runs under Django's own test runner (``manage.py test tests.performance``) with
zero extra dependencies. Suites are layered:

* Deterministic regression tests (query counts, plans, structure) always run.
* Timed micro/endpoint benchmarks run in a fast, low-iteration mode by default
  and are robust to shared-CI noise via generous tolerances.
* Heavy suites (load, stress, spike, endurance, large-scale scalability) are
  opt-in: set ``SEFRO_PERF_HEAVY=1``. CI runs them from the scheduled workflow.
"""
