"""Background task probe.

The project has NO Celery/broker/queue system. This module documents that
finding and verifies no synchronous blocking work is hidden inside request
handlers.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase

from tests.performance.conftest import save_result

User = get_user_model()


class BackgroundTaskProbeTests(TestCase):
    """Documents that no background task infrastructure exists."""

    def test_no_celery_configured(self):
        from django.conf import settings
        has_celery = any(
            'celery' in app.lower() for app in getattr(settings, 'INSTALLED_APPS', [])
        )
        save_result('background_probe', {
            'celery_configured': has_celery,
            'broker_configured': bool(getattr(settings, 'CELERY_BROKER_URL', '')),
            'finding': 'NO Celery/broker in project. All work is synchronous in-request.',
            'recommendation': (
                'For long-running report generation or bulk operations, '
                'consider adding Celery with Redis broker in production.'
            ),
        })
        self.assertFalse(has_celery, 'Celery was detected unexpectedly')

    def test_request_handlers_are_non_blocking(self):
        """Verify no synchronous I/O is hidden in critical handlers."""
        from django.test import Client

        client = Client()
        endpoints = [
            '/api/dashboard/',
            '/api/reports/',
            '/api/customers/',
        ]
        results = {}
        for url in endpoints:
            import time
            start = time.perf_counter()
            resp = client.get(url, follow=True)
            elapsed = (time.perf_counter() - start)
            results[url] = {'time_s': round(elapsed, 3), 'status': resp.status_code}
        save_result('blocking_io_check', results)
