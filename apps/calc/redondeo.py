"""Redondeos como en Excel, tolerantes al error de punto flotante."""
import math

_EPS = 1e-9


def redondear_mas(x):
    """REDONDEAR.MAS(x; 0) para x >= 0: 7.0000000001 -> 7, 7.2 -> 8."""
    return int(math.ceil(x - _EPS)) if x > 0 else 0


def al_multiplo(x, multiplo):
    """Sube x al multiplo indicado (OITM.OrdrMulti). Multiplo <= 0 no redondea."""
    if not multiplo or multiplo <= 0:
        return redondear_mas(x)
    return int(redondear_mas(x / multiplo) * multiplo)
