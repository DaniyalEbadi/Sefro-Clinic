"""Performance report generator.

Aggregates all JSON results under reports/data/<phase>/ and produces a
Markdown performance report at docs/performance_report.md.

Run with: python manage.py test tests.performance.reports.test_report_generation
"""
import json
from pathlib import Path

from django.test import TestCase

from tests.performance.conftest import PERF_PHASE, RESULTS_DIR

REPORT_OUTPUT = Path(__file__).resolve().parent.parent.parent.parent / 'docs' / 'performance_report.md'


class ReportGenerationTests(TestCase):
    """Generate the performance report from collected metrics."""

    def test_generate_report(self):
        data_dir = RESULTS_DIR
        if not data_dir.exists():
            data_dir.mkdir(parents=True, exist_ok=True)

        metrics = {}
        for json_file in sorted(data_dir.glob('*.json')):
            try:
                metrics[json_file.stem] = json.loads(json_file.read_text(encoding='utf-8'))
            except (json.JSONDecodeError, OSError):
                continue

        if not metrics:
            self.skipTest(f'No metrics found in {data_dir}. Run performance tests first.')

        lines = [
            '# Sefro Clinic — Performance Report',
            '',
            f'**Phase:** `{PERF_PHASE}`',
            f'**Metrics collected:** {len(metrics)}',
            f'**Data directory:** `{data_dir}`',
            '',
        ]

        # Endpoint benchmarks
        endpoint_keys = [k for k in metrics if k.startswith(('crud_', 'auth_', 'dashboard', 'reports_', 'inventory_'))]
        if endpoint_keys:
            lines.append('## Endpoint Benchmarks')
            lines.append('')
            lines.append('| Endpoint | p50 (ms) | p95 (ms) | p99 (ms) | RPS | Errors |')
            lines.append('|----------|----------|----------|----------|-----|--------|')
            for key in sorted(endpoint_keys):
                m = metrics[key]
                lines.append(
                    f"| {key} | {m.get('p50_ms', '-')} | {m.get('p95_ms', '-')} | "
                    f"{m.get('p99_ms', '-')} | {m.get('throughput_rps', '-')} | "
                    f"{m.get('error_rate', '-')} |"
                )
            lines.append('')

        # Query counts
        query_keys = [k for k in metrics if 'query' in k.lower() or k.startswith('scale_')]
        if query_keys:
            lines.append('## Database Performance')
            lines.append('')
            for key in sorted(query_keys):
                m = metrics[key]
                lines.append(f'### {key}')
                lines.append(f'```json\n{json.dumps(m, indent=2)[:500]}\n```')
                lines.append('')

        # Concurrency
        conc_keys = [k for k in metrics if k.startswith(('concurrency_', 'stress_', 'spike_', 'endurance_'))]
        if conc_keys:
            lines.append('## Load / Concurrency')
            lines.append('')
            for key in sorted(conc_keys):
                m = metrics[key]
                lines.append(f'### {key}')
                lines.append(f'- Workers: {m.get("workers", "-")}')
                lines.append(f'- Requests executed: {m.get("executed_requests", "-")}')
                lines.append(f'- Error rate: {m.get("error_rate", "-")}')
                lines.append(f'- P95: {m.get("p95_ms", "-")} ms')
                lines.append(f'- Aggregate RPS: {m.get("aggregate_rps", "-")}')
                lines.append('')

        # Plans
        plan_keys = [k for k in metrics if k.startswith('explain_')]
        if plan_keys:
            lines.append('## Database Plan Analysis')
            lines.append('')
            for key in sorted(plan_keys):
                m = metrics[key]
                lines.append(f'- **{key}**: uses_index={m.get("uses_index", "unknown")}')
            lines.append('')

        # Cache
        cache_keys = [k for k in metrics if k.startswith('cache_')]
        if cache_keys:
            lines.append('## Cache Performance')
            lines.append('')
            for key in sorted(cache_keys):
                m = metrics[key]
                lines.append(f'### {key}')
                lines.append(f'```json\n{json.dumps(m, indent=2)[:400]}\n```')
                lines.append('')

        # Background
        bg_keys = [k for k in metrics if k.startswith(('background_', 'blocking_'))]
        if bg_keys:
            lines.append('## Background Tasks')
            lines.append('')
            for key in sorted(bg_keys):
                m = metrics[key]
                lines.append(f'- **{key}**: {json.dumps(m)[:300]}')
            lines.append('')

        # Response sizes
        size_keys = [k for k in metrics if 'size' in k.lower()]
        if size_keys:
            lines.append('## Response Sizes')
            lines.append('')
            for key in sorted(size_keys):
                m = metrics[key]
                lines.append(f'```json\n{json.dumps(m, indent=2)[:400]}\n```')
            lines.append('')

        # Memory
        mem_keys = [k for k in metrics if 'memory' in k.lower()]
        if mem_keys:
            lines.append('## Memory Analysis')
            lines.append('')
            for key in sorted(mem_keys):
                m = metrics[key]
                lines.append(f'- **{key}**: {json.dumps(m)[:300]}')
            lines.append('')

        lines.append('---')
        lines.append('*Report generated automatically by the performance test suite.*')

        REPORT_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        REPORT_OUTPUT.write_text('\n'.join(lines), encoding='utf-8')
        self.assertTrue(REPORT_OUTPUT.exists(), f'Failed to write report to {REPORT_OUTPUT}')
        self.assertGreater(len(lines), 10, 'Report is suspiciously short')
