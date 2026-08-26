from decimal import Decimal
from django import template

register = template.Library()


@register.filter(name='compact_usd')
def compact_usd(value):
    """
    Formatea valores en USD de forma abreviada y legible para ejecutivos:
    - >= 1,000,000   -> "$1,7M"
    - >= 1,000       -> "$150,5K"
    - < 1,000        -> "$850"
    """
    if value is None or value == '':
        return '$0'
    try:
        val = float(value)
    except (ValueError, TypeError):
        return str(value)

    if val == 0:
        return '$0'

    if abs(val) >= 1_000_000_000:
        num_str = f"{val / 1_000_000_000:.2f}".rstrip('0').rstrip('.')
        return f"${num_str.replace('.', ',')} B"
    elif abs(val) >= 1_000_000:
        num_str = f"{val / 1_000_000:.2f}".rstrip('0').rstrip('.')
        return f"${num_str.replace('.', ',')} M"
    elif abs(val) >= 1_000:
        num_str = f"{val / 1_000:.1f}".rstrip('0').rstrip('.')
        return f"${num_str.replace('.', ',')} K"
    else:
        return f"${val:.2f}".rstrip('0').rstrip('.').replace('.', ',')


@register.filter(name='full_usd')
def full_usd(value):
    """Formato completo con separador de miles: $1.732.450,23"""
    if value is None or value == '':
        return '$0,00'
    try:
        val = float(value)
        return f"${val:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')
    except (ValueError, TypeError):
        return str(value)
