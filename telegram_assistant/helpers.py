from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import json
from urllib.parse import urlparse

LIMA = ZoneInfo('America/Lima')


def date_value(value, now=None):
    if value is None:
        return None
    now = (now or datetime.now(LIMA)).astimezone(LIMA)
    days = {'hoy': 0, 'ayer': 1}
    if value in days:
        result = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days[value])
    elif value == 'esta_semana':
        result = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=now.weekday())
    else:
        try:
            result = datetime.fromisoformat(value.replace('Z', '+00:00'))
        except (ValueError, AttributeError):
            raise ValueError('Fecha inválida: usa ISO 8601, hoy, ayer o esta_semana.') from None
        if result.tzinfo is None:
            result = result.replace(tzinfo=LIMA)
    return result.astimezone(timezone.utc)


def positive(value, name='mensaje_id', zero=False):
    if isinstance(value, bool) or not isinstance(value, int) or value < (0 if zero else 1):
        raise ValueError(f'{name} debe ser un entero {"no negativo" if zero else "positivo"}.')
    return value


def parse_link(url):
    parsed = urlparse(url)
    if parsed.scheme != 'https' or parsed.netloc not in ('t.me', 'telegram.me'):
        raise ValueError('Usa un enlace HTTPS de t.me o telegram.me.')
    parts = parsed.path.strip('/').split('/')
    if parts[0] == 's':
        parts = parts[1:]
    if len(parts) == 3 and parts[0] == 'c' and parts[1].isdigit() and parts[2].isdigit():
        return '-100' + parts[1], positive(int(parts[2]))
    if len(parts) == 2 and parts[0] not in ('joinchat', '+') and parts[1].isdigit():
        return '@' + parts[0], positive(int(parts[1]))
    raise ValueError('El enlace debe apuntar a un mensaje concreto, no una invitación.')


def budget_result(result, budget=24000):
    """Bound all text leaves, preserving IDs and explicit truncation metadata."""
    positive(budget, 'presupuesto_texto')
    if not 1000 <= budget <= 100000:
        raise ValueError('presupuesto_texto debe estar entre 1000 y 100000.')
    remaining, clipped = budget, False

    def visit(obj, key=''):
        nonlocal remaining, clipped
        if isinstance(obj, dict):
            return {k: visit(v, k) for k, v in obj.items()}
        if isinstance(obj, list):
            return [visit(v, key) for v in obj]
        if isinstance(obj, str) and key in ('text', 'indexed_text', 'transcript', 'description', 'preview'):
            kept = obj[:remaining]
            remaining -= len(kept)
            if len(kept) != len(obj):
                clipped = True
                return kept + ' [texto truncado; recupera el original por ID]'
            return kept
        return obj

    bounded = visit(result)
    bounded['text_truncated'] = clipped
    return bounded
