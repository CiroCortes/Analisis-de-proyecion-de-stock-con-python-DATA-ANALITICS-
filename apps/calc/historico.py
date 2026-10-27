"""Inventario historico reconstruido hacia atras (SPEC-19 §3.3).

Mismo metodo que el grafico del dashboard: desde el stock fisico de hoy,
stock_fin_mes(m-1) = stock_fin_mes(m) - entradas(m) + consumo(m).
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class PuntoHistorico:
    stock: float          # stock al cierre del mes (0 si la reconstruccion dio negativo)
    inconsistente: bool   # la reconstruccion dio negativo: falta algun movimiento


def reconstruir(stock_hoy, entradas_meses, consumo_meses, entradas_mes_en_curso=0, consumo_mes_en_curso=0):
    """`entradas_meses` y `consumo_meses`: meses cerrados del mas antiguo al mas reciente.
    Devuelve el stock al cierre de cada uno de esos meses (misma longitud y orden).
    El mes en curso (aun abierto) se descuenta primero para llegar al cierre del ultimo mes."""
    n = len(consumo_meses)
    entradas = list(entradas_meses) + [0.0] * (n - len(entradas_meses))
    stock = float(stock_hoy) - float(entradas_mes_en_curso) + float(consumo_mes_en_curso)
    puntos = []
    for i in range(n - 1, -1, -1):
        puntos.append(PuntoHistorico(max(0.0, stock), stock < 0))
        stock = stock - float(entradas[i]) + float(consumo_meses[i])
    return list(reversed(puntos))
