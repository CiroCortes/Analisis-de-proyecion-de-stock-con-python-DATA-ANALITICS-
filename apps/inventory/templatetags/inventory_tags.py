from decimal import Decimal
from django import template

register = template.Library()


@register.filter(name='compact_usd')
def compact_usd(value):
    """
    Formatea valores en USD de forma inequívoca y legible:
    - >= 1.000.000.000 -> "$1,70 B USD"
    - >= 1.000.000     -> "$2,28 M USD" (o "$2,28 Millones USD")
    - >= 1.000         -> "$150,5 K USD" (o "$150,5 Mil USD")
    - < 1.000          -> "$850 USD"
    """
    if value is None or value == '':
        return '$0 USD'
    try:
        val = float(value)
    except (ValueError, TypeError):
        return str(value)

    if val == 0:
        return '$0 USD'

    sign = '-' if val < 0 else ''
    abs_val = abs(val)

    if abs_val >= 1_000_000_000:
        num_str = f"{abs_val / 1_000_000_000:.2f}".replace('.', ',')
        return f"{sign}${num_str} B USD"
    elif abs_val >= 1_000_000:
        num_str = f"{abs_val / 1_000_000:.2f}".replace('.', ',')
        return f"{sign}${num_str} M USD"
    elif abs_val >= 100_000:
        # Entre 100.000 y 999.999 se muestra claro con separador de miles completo o K explícito
        num_str = f"{abs_val / 1_000:.1f}".replace('.', ',')
        return f"{sign}${num_str} K USD"
    elif abs_val >= 1_000:
        # Entre 1.000 y 99.999 mostramos con separador de miles directo para no confundir
        num_str = f"{abs_val:,.0f}".replace(',', '.')
        return f"{sign}${num_str} USD"
    else:
        num_str = f"{abs_val:.2f}".rstrip('0').rstrip('.').replace('.', ',')
        return f"{sign}${num_str} USD"


@register.filter(name='full_usd')
def full_usd(value):
    """Formato completo con separador de miles: $1.732.450,23 USD"""
    if value is None or value == '':
        return '$0,00 USD'
    try:
        val = float(value)
        sign = '-' if val < 0 else ''
        formatted = f"{abs(val):,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')
        return f"{sign}${formatted} USD"
    except (ValueError, TypeError):
        return str(value)


@register.filter(name='chile_num')
def chile_num(value, decimals=0):
    """
    Formatea números con separador de miles con punto y coma decimal:
    ej: 1234567.89 -> 1.234.568 (dec=0) o 1.234.567,89 (dec=2)
    """
    if value is None or value == '':
        return '—'
    try:
        val = float(value)
        sign = '-' if val < 0 else ''
        d = int(decimals)
        if d == 0:
            formatted = f"{round(abs(val)):,d}".replace(',', '.')
        else:
            formatted = f"{abs(val):,.{d}f}".replace(',', 'X').replace('.', ',').replace('X', '.')
        return f"{sign}{formatted}"
    except (ValueError, TypeError):
        return str(value)
