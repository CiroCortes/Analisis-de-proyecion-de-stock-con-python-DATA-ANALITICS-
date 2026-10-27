"""Proyeccion diaria y compras fuera de calendario (documento §4.6.2, SPEC-12).

Los dias se cuentan desde hoy: dia 1 = manana. La capa Django convierte fechas en dias.
"""
import math
from dataclasses import dataclass


@dataclass(frozen=True)
class Excepcion:
    dia_quiebre: int                 # primer dia con stock proyectado < 0 (None si no quiebra)
    dia_bajo_ss: int                 # primer dia bajo el stock de seguridad (None si no)
    dia_llegada_posible: int         # proxima compra normal + entrega + recepcion
    excepcion: bool                  # quiebre antes de que pueda llegar la compra normal
    dias_quiebre_inevitable: int     # dias de quiebre aunque se compre hoy


def dia_llegada_oc(dias_hasta_fecha_comprometida, dias_recepcion):
    """Fecha comprometida + recepcion; si ya paso, hoy + recepcion (OC atrasada)."""
    rec = int(math.ceil(dias_recepcion))
    return max(0, dias_hasta_fecha_comprometida) + rec


def proyectar(stock_inicial, consumo_diario, compromisos=(), llegadas=(), horizonte=120):
    """Stock esperado al cierre de cada dia 1..horizonte:
    stock de hoy - consumo_diario x dias - compromisos a su fecha + llegadas de OC a su fecha.
    `compromisos` y `llegadas`: iterables de (dia, cantidad). Los dias <= 0 cuentan en el dia 1."""
    salidas = [0.0] * (horizonte + 1)
    entradas = [0.0] * (horizonte + 1)
    for dia, q in compromisos:
        d = min(max(1, int(dia)), horizonte + 1)
        if d <= horizonte:
            salidas[d] += float(q)
    for dia, q in llegadas:
        d = max(1, int(dia))
        if d <= horizonte:
            entradas[d] += float(q)

    serie = []
    acumulado = float(stock_inicial)
    for d in range(1, horizonte + 1):
        acumulado += entradas[d] - salidas[d]
        serie.append(acumulado - consumo_diario * d)
    return serie


def evaluar_excepcion(serie, stock_seguridad, dias_a_proxima_compra, dias_entrega, dias_recepcion,
                      es_dia_compra=False):
    """`excepcion` = quiebre proyectado antes de que llegue la proxima compra normal.
    El dia de compra del proveedor no hay excepcion: el articulo entra en la compra del dia
    (igual se informa el quiebre inevitable)."""
    quiebre = next((i + 1 for i, v in enumerate(serie) if v < 0), None)
    bajo_ss = next((i + 1 for i, v in enumerate(serie) if v < stock_seguridad), None)
    plazo = int(math.ceil(dias_entrega + dias_recepcion))
    llegada_posible = int(dias_a_proxima_compra) + plazo
    excepcion = quiebre is not None and quiebre < llegada_posible and not es_dia_compra
    inevitable = max(0, plazo - quiebre) if quiebre is not None else 0
    return Excepcion(quiebre, bajo_ss, llegada_posible, excepcion, inevitable)
