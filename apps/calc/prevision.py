"""Prevision de demanda a 12 meses para la vista "Analizar articulos" (SPEC-24 §3).

v1 deliberadamente simple y explicable: el mismo promedio que usa el calculo (consumo con los
meses atipicos recortados, SPEC-10 §1) mas una tendencia lineal sobre esos meses. No es
estacional: con 24 meses de historia confiable se puede pasar a una v2.
"""
from dataclasses import dataclass

from .consumo import calcular_consumo


@dataclass(frozen=True)
class Prevision:
    historia: tuple              # consumo real por mes, del mas antiguo al mas reciente
    valores: tuple               # prevision de los proximos meses
    promedio: float              # demanda media mensual (con atipicos recortados)
    tendencia: float             # unidades por mes (pendiente de la recta, acotada)
    meses_con_demanda: int
    meses_desde_ultima: object   # meses desde la ultima demanda (0 = el ultimo mes cerrado); None si nunca


def _pendiente(valores):
    n = len(valores)
    if n < 2:
        return 0.0
    xm = (n - 1) / 2.0
    ym = sum(valores) / n
    den = sum((i - xm) ** 2 for i in range(n))
    return sum((i - xm) * (v - ym) for i, v in enumerate(valores)) / den if den else 0.0


def prever(meses, params, horizonte=12):
    """`meses`: consumo de los ultimos meses cerrados (mas antiguo primero). La tendencia se
    acota para que en el horizonte la prevision no cambie mas de un 50% del promedio: una recta
    sobre 12 meses ruidosos no debe proyectar el doble ni llevar a cero un articulo regular."""
    c = calcular_consumo(meses, params)
    usados = list(c.meses)
    promedio = c.consumo_promedio_mes
    tendencia = _pendiente(usados)
    centro = (len(usados) - 1) / 2.0
    # La recta pasa por el promedio en el centro de la historia: el ultimo mes previsto queda a
    # `distancia` meses de ese centro
    distancia = len(usados) + horizonte - 1 - centro
    if promedio > 0 and horizonte:
        tope = 0.5 * promedio / distancia
        tendencia = max(-tope, min(tope, tendencia))
    else:
        tendencia = 0.0
    valores = tuple(round(max(0.0, promedio + tendencia * (len(usados) + k - centro)), 2) for k in range(horizonte))
    historia = tuple(max(0.0, float(v or 0)) for v in list(meses)[-len(usados):])
    ultima = next((i for i, v in enumerate(reversed(historia)) if v > 0), None)
    return Prevision(historia=historia, valores=valores, promedio=promedio, tendencia=tendencia,
                     meses_con_demanda=sum(1 for v in historia if v > 0), meses_desde_ultima=ultima)
