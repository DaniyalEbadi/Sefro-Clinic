import re

from django.core.exceptions import ValidationError
from django.core.validators import ProhibitNullCharactersValidator

_SURROGATE_PATTERN = re.compile(r'[\ud800-\udfff]')


def _reject_surrogates(value):
    if isinstance(value, str) and _SURROGATE_PATTERN.search(value):
        raise ValidationError('Unicode surrogate characters are not allowed.')


TEXT_SANITIZERS = [ProhibitNullCharactersValidator(), _reject_surrogates]
