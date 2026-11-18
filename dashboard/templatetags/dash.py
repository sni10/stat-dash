from django import template

register = template.Library()

NBSP = '\u00a0'  # not U+202F: the Outfit font draws the narrow one almost zero-width
SYMBOLS = {'usd': '$', 'uah': '₴'}


@register.filter
def num(value, decimals=0):
    """1162.79 -> '1 162,79' (Russian grouping and decimal comma)."""
    if value is None or value == '':
        return '—'
    text = f'{float(value):,.{int(decimals)}f}'
    return text.replace(',', NBSP).replace('.', ',')


@register.filter
def money(value, cur):
    return '—' if value is None else f'{num(value, 2)}{NBSP}{SYMBOLS.get(cur, cur)}'


@register.filter
def pct(value):
    """0.0284 -> '+2,8 %'."""
    if value is None or value == '':
        return '—'
    return f'{value * 100:+.1f}'.replace('.', ',') + f'{NBSP}%'
