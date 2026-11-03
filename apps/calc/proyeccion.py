"""Proyeccion diaria y compras fuera de calendario (documento §4.6.2, SPEC-12).

Los dias se cuentan desde hoy: dia 1 = manana. La capa Django convierte fechas en dias.
"""
import datetime
import math
from dataclasses import dataclass


@dataclass(frozen=True)
class Excepcion:
    dia_quiebre: int                 # primer dia con stock proyectado < 0 (None si no quiebra)
    dia_bajo_ss: int                 # primer dia bajo el stock de seguridad (None si no)
    dia_llegada_posible: int         # proxima compra normal + entrega + recepcion
    excepcion: bool                  # quiebre antes de que pueda llegar la compra normal
    dias_quiebre_inevitable: int     # dias de quiebre aunque se compre hoy


def fecha_llegada_oc(fecha_oc, fecha_comprometida, plazo_entrega_dias, factor_irreal):
    """(fecha estimada de llegada, es_irreal) de una linea de OC o FR (pendiente #42).
    La fecha comprometida se hereda de la SC y a veces es imposible (35471214: 2 dias para una
    importacion de 70). Si promete llegar en menos de factor_irreal x el plazo de entrega del articulo,
    se estima fecha de la OC + plazo de entrega. factor_irreal = 0 desactiva la regla."""
    if fecha_comprometida is None:
        return None, False
    if factor_irreal > 0 and fecha_oc and plazo_entrega_dias > 0 and             (fecha_comprometida - fecha_oc).days < factor_irreal * plazo_entrega_dias:
        return fecha_oc + datetime.timedelta(days=int(math.ceil(plazo_entrega_dias))), True
    return fecha_comprometida, False


def dia_llegada_oc(dias_hasta_fecha_comprometida, dias_recepcion):
    """Fecha comprometida + recepcion; si ya paso, hoy + recepcion (OC atrasada)."""
    rec = int(math.ceil(dias_recepcion))
    return max(0, dias_hasta_fecha_comprometida) + rec


def proyectar(stock_inicial, consumo_diario, compromisos=(), llegadas=(), horizonte=120):
    """Stock esperado al cierre de cada dia 1..horizonte:
    stock de hoy + llegadas de OC a su fecha - MAX(consumo_diario x dias; compromisos acumulados).
    Los PC y OF abiertos son parte del consumo esperado (el historial de inventario, OIVL, incluye las ventas y
    las salidas a OF): solo se descuenta lo que los compromisos superan al consumo. El documento
    los restaba ademas del consumo y los contaba dos veces: corregido el 28-oct (SPEC-12 §4).
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
    stock, comprometido = float(stock_inicial), 0.0
    for d in range(1, horizonte + 1):
        stock += entradas[d]
        comprometido += salidas[d]
        serie.append(stock - max(consumo_diario * d, comprometido))
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
