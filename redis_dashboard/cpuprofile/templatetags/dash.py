from django import template

register = template.Library()


@register.filter
def compact(n):
    """12345 -> 12.3k"""
    if n is None:
        return '—'
    n = float(n)
    for unit in ('', 'k', 'M', 'B'):
        if abs(n) < 1000:
            return f'{n:.0f}{unit}' if unit == '' or n >= 100 else f'{n:.1f}{unit}'
        n /= 1000
    return f'{n:.1f}T'


@register.filter
def usec(v):
    """Microseconds, auto-scaled."""
    if v is None:
        return '—'
    if v >= 1_000_000:
        return f'{v / 1_000_000:.2f} s'
    if v >= 1000:
        return f'{v / 1000:.2f} ms'
    return f'{v:.1f} µs' if v < 100 else f'{v:.0f} µs'


@register.filter
def msec(v):
    if v is None:
        return '—'
    return usec(v * 1000)


@register.filter
def pct(v):
    return '—' if v is None else f'{v:.0f}%' if v >= 10 else f'{v:.1f}%'


@register.filter
def ratio(v, top):
    """Bar width in % of the largest row."""
    try:
        return max(2, round(float(v) / float(top) * 100)) if top else 0
    except (TypeError, ValueError):
        return 0


@register.filter
def get(d, key):
    return d.get(str(key)) if d else None
