"""Cross-cutting DRF exception handling.

``PeriodClosedError`` is raised deep inside services (refunds, expense
workflows, opex CRUD, purchase-order receiving, payout re-pricing), far from
the view that started the request. Mapping it in one place keeps every
endpoint answering 409 Conflict with the same shape, instead of each view
needing its own try/except (and any new mutation path staying protected for
free).
"""
from rest_framework.response import Response
from rest_framework.views import exception_handler


def api_exception_handler(exc, context):
    from finance.services.periods_guard import PeriodClosedError

    if isinstance(exc, PeriodClosedError):
        payload = {'error': str(exc)}
        if exc.year is not None:
            payload['period'] = f'{exc.year}-{exc.month:02d}'
        return Response(payload, status=409)
    return exception_handler(exc, context)
