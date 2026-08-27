"""Shared configuration and measurement harness for the performance suite.

Framework neutral: importable from ``manage.py test`` (unittest) without any
third-party tooling. Concrete responsibilities:

* Explicit performance budgets (thresholds registry).
* Latency percentiles and endpoint metering helpers.
* Database query capture / N+1 analysis.
* Threaded concurrency runner for in-process load simulation.
* JSON result recorder feeding ``reports/`` artifacts.

Heavy scenarios are opt-in via ``SEFRO_PERF_HEAVY=1`` so fast CI stays fast.
"""
import json
import os
import queue
import statistics
import threading
import time
import tracemalloc
from decimal import Decimal
from pathlib import Path

from django.db import connection
from django.test.utils import CaptureQueriesContext

# ---------------------------------------------------------------------------
# Environment gates
# ---------------------------------------------------------------------------

HEAVY = os.environ.get('SEFRO_PERF_HEAVY') == '1'
"""When unset, heavy suites (load/stress/spike/endurance/scalability soak)
are skipped; deterministic regression tests always run."""

# Result phase label used to group recorded metrics (e.g. "before"/"after").
PERF_PHASE = os.environ.get('SEFRO_PERF_PHASE', 'run')

RESULTS_DIR = Path(__file__).resolve().parent / 'reports' / 'data' / PERF_PHASE


def perf_phase(label):
    """Context-free helper returning the directory for a phase label."""
    return RESULTS_DIR.parent / label


def save_result(name, payload):
    """Persist one benchmark result as JSON under reports/data/<phase>/."""
    out_dir = Path(payload.pop('_dir', None) or RESULTS_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f'{name}.json'
    path.write_text(json.dumps(payload, indent=2, default=str), encoding='utf-8')
    return path


# ---------------------------------------------------------------------------
# Performance budgets (explicit pass/fail criteria)
# ---------------------------------------------------------------------------

BUDGETS = {
    # Deterministic budgets: exact numbers, stable across environments.
    'max_queries_customer_list': 5,
    'max_queries_customer_detail': 4,
    'max_queries_visit_list': 4,
    'max_queries_payment_list': 4,
    'max_queries_product_list': 3,
    'max_queries_product_search': 3,
    'max_queries_dashboard': 8,
    'max_queries_reports_summary': 10,
    'max_queries_me_endpoint': 2,
    # Environment dependent latency budgets in milliseconds (deliberately
    # generous so shared CI runners do not produce flaky failures; the
    # recorded p50/p95 numbers still show real regressions over time).
    'login_p95_ms_fast_mode': 2000,
    'token_refresh_max_ms_fast_mode': 1000,
    'crud_list_p95_ms_fast_mode': 1500,
    'detail_p95_ms_fast_mode': 1200,
    'search_p95_ms_fast_mode': 1500,
    'dashboard_p95_ms_fast_mode': 2500,
    'reports_heavy_p95_ms_fast_mode': 3000,
    # Heavy-mode budgets (dedicated machine / scheduled workflow).
    'load_error_rate_max': 0.01,
    'endurance_memory_growth_max_mb': 50,
}


def budget(key):
    return BUDGETS[key]


is_postgres = connection.vendor == 'postgresql'

# ---------------------------------------------------------------------------
# Latency statistics
# ---------------------------------------------------------------------------


def percentile(sorted_values, pct):
    """Nearest-rank percentile of an already sorted list."""
    if not sorted_values:
        return 0
    idx = min(len(sorted_values) - 1, max(0, int(round(pct / 100 * len(sorted_values))) - 1))
    return sorted_values[idx]


def summarize_latencies(latencies_ms):
    if not latencies_ms:
        return {}
    ordered = sorted(latencies_ms)
    return {
        'n': len(ordered),
        'min_ms': round(ordered[0], 2),
        'p50_ms': round(percentile(ordered, 50), 2),
        'p75_ms': round(percentile(ordered, 75), 2),
        'p90_ms': round(percentile(ordered, 90), 2),
        'p95_ms': round(percentile(ordered, 95), 2),
        'p99_ms': round(percentile(ordered, 99), 2),
        'max_ms': round(ordered[-1], 2),
        'mean_ms': round(statistics.fmean(ordered), 2),
    }


class EndpointMeter:
    """Serial request metering against Django's test client (in-process WSGI)."""

    def __init__(self, client):
        self.client = client

    def run(self, method, url, data=None, iterations=30):
        dispatch = getattr(self.client, method.lower())
        latencies, errors, sizes, statuses = [], 0, [], []
        for _ in range(iterations):
            started = time.perf_counter()
            response = dispatch(url, data) if data is not None else dispatch(url)
            elapsed_ms = (time.perf_counter() - started) * 1000
            latencies.append(elapsed_ms)
            statuses.append(response.status_code)
            body = getattr(response, 'content', b'') or b''
            sizes.append(len(body))
            if response.status_code >= 400:
                errors += 1
        summary = summarize_latencies(latencies)
        total_time_s = sum(latencies) / 1000 or 1e-9
        summary.update({
            'url': url,
            'method': method.upper(),
            'iterations': iterations,
            'errors': errors,
            'error_rate': round(errors / iterations, 4),
            'throughput_rps': round(iterations / total_time_s, 1),
            'avg_response_bytes': round(sum(sizes) / len(sizes)) if sizes else 0,
            'max_response_bytes': max(sizes) if sizes else 0,
        })
        return summary


# ---------------------------------------------------------------------------
# Query analysis
# ---------------------------------------------------------------------------


class QueryProbe:
    """Capture and analyze queries emitted inside a context manager block."""

    def __init__(self):
        self.capture = CaptureQueriesContext(connection)

    def __enter__(self):
        self.capture.__enter__()
        return self

    def __exit__(self, *exc_info):
        return self.capture.__exit__(*exc_info)

    @property
    def count(self):
        return len(self.capture)

    @property
    def sql_statements(self):
        return [entry['sql'] for entry in self.capture.captured_queries]

    def duplicates(self):
        seen, dups = set(), []
        for sql in self.sql_statements:
            if sql in seen:
                dups.append(sql)
            seen.add(sql)
        return dups

    def statements_matching(self, fragment):
        frag = fragment.lower()
        return [sql for sql in self.sql_statements if frag in sql.lower()]


def measure_query_count(func, *args, **kwargs):
    """Run func once, return (result, query_count)."""
    with QueryProbe() as probe:
        result = func(*args, **kwargs)
    return result, probe.count


# ---------------------------------------------------------------------------
# Concurrency runner (in-process threaded load)
# ---------------------------------------------------------------------------


def run_concurrent(workers, requests_per_worker, client_factory, call_fn):
    """Fire concurrent requests through separate threads/clients.

    ``client_factory(index)`` builds one client per worker thread *before*
    the barrier so authentication cost is not measured per request.
    ``call_fn(client, worker_index, call_index)`` executes one request and
    returns the HTTP status code.

    Each worker thread closes its DB connection at exit so pooled
    connections never leak between test cases.
    """
    results_q = queue.Queue()
    start_barrier = threading.Barrier(workers)

    def worker(worker_index):
        client = client_factory(worker_index)
        local_latencies, local_errors = [], 0
        try:
            start_barrier.wait(timeout=30)
            for i in range(requests_per_worker):
                started = time.perf_counter()
                status = call_fn(client, worker_index, i)
                elapsed_ms = (time.perf_counter() - started) * 1000
                local_latencies.append(elapsed_ms)
                if status is None or status >= 400:
                    local_errors += 1
        except Exception as exc:  # noqa: BLE001 - surface worker failure as error metric
            local_errors += requests_per_worker - len(local_latencies)
            results_q.put({'worker': worker_index, 'fatal': str(exc)})
        else:
            results_q.put({
                'worker': worker_index,
                'latencies': local_latencies,
                'errors': local_errors,
            })
        finally:
            connection.close()

    threads = [threading.Thread(target=worker, args=(i,), daemon=True) for i in range(workers)]
    wall_start = time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=max(60, requests_per_worker * workers))
    wall_s = time.perf_counter() - wall_start

    all_latencies, total_errors, fatals = [], 0, []
    for _ in range(workers):
        item = results_q.get()
        if 'fatal' in item:
            fatals.append(item['fatal'])
            continue
        all_latencies.extend(item['latencies'])
        total_errors += item['errors']

    expected = workers * requests_per_worker
    summary = summarize_latencies(all_latencies)
    executed = len(all_latencies)
    summary.update({
        'workers': workers,
        'requests_per_worker': requests_per_worker,
        'expected_requests': expected,
        'executed_requests': executed,
        'worker_errors': total_errors,
        'fatals': fatals[:5],
        'error_rate': round((total_errors + sum(1 for _ in fatals) * requests_per_worker) / max(expected, 1), 4),
        'wall_seconds': round(wall_s, 2),
        'aggregate_rps': round(executed / wall_s, 1) if wall_s else 0,
    })
    return summary


class EndpointWorker:
    """Convenience call_fn: authenticated worker cycling fixed endpoints."""

    def __init__(self, endpoints):
        self.endpoints = endpoints

    def __call__(self, client, worker_index, call_index):
        url, method = self.endpoints[call_index % len(self.endpoints)]
        response = getattr(client, method.lower())(url)
        return response.status_code


# ---------------------------------------------------------------------------
# Memory probing (best effort, cross platform, no new dependencies)
# ---------------------------------------------------------------------------


def process_rss_bytes():
    """Return current process RSS in bytes, or None when undetectable."""
    try:
        if os.name == 'nt':
            import ctypes

            class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
                _fields_ = [
                    ('cb', ctypes.c_uint32),
                    ('PageFaultCount', ctypes.c_uint32),
                    ('PeakWorkingSetSize', ctypes.c_size_t),
                    ('WorkingSetSize', ctypes.c_size_t),
                    ('QuotaPeakPagedPoolUsage', ctypes.c_size_t),
                    ('QuotaPagedPoolUsage', ctypes.c_size_t),
                    ('QuotaPeakNonPagedPoolUsage', ctypes.c_size_t),
                    ('QuotaNonPagedPoolUsage', ctypes.c_size_t),
                    ('PagefileUsage', ctypes.c_size_t),
                    ('PeakPagefileUsage', ctypes.c_size_t),
                ]

            counters = PROCESS_MEMORY_COUNTERS()
            counters.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS)
            handle = ctypes.windll.kernel32.GetCurrentProcess()
            if ctypes.windll.psapi.GetProcessMemoryInfo(
                handle, ctypes.byref(counters), counters.cb
            ):
                return counters.WorkingSetSize
            return None
        import resource

        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
    except Exception:  # noqa: BLE001 - best effort only
        return None


class MemoryTracker:
    """Track RSS growth and Python allocations across a workload."""

    def __enter__(self):
        tracemalloc.start()
        self.rss_start = process_rss_bytes()
        return self

    def __exit__(self, *exc_info):
        _, peak_alloc = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        rss_end = process_rss_bytes()
        self.result = {
            'rss_start_mb': round(self.rss_start / 1048576, 1) if self.rss_start else None,
            'rss_end_mb': round(rss_end / 1048576, 1) if rss_end else None,
            'rss_growth_mb': round((rss_end - self.rss_start) / 1048576, 1)
            if rss_end and self.rss_start
            else None,
            'python_peak_allocated_mb': round(peak_alloc / 1048576, 1),
        }
        return False


# ---------------------------------------------------------------------------
# Money helper
# ---------------------------------------------------------------------------


def money(value):
    return Decimal(value).quantize(Decimal('0.01'))
