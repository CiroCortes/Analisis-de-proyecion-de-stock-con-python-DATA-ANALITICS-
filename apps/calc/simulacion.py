"""Simulacion de escenarios para el panel de indicadores (documento §8, SPEC-15 §3).

Compara el escenario actual (motor anterior: compra hasta el punto de pedido, sin
calendario) con el propuesto (compra hasta el maximo en el calendario del proveedor).
Simulacion diaria a nivel red con consumo uniforme: no pronostica, solo muestra como se
comportaria cada politica con el consumo historico.
"""
from dataclasses import dataclass

from .redondeo import al_multiplo


@dataclass(frozen=True)
class Escenario:
    umbral: float            # se compra cuando la posicion (fisico + pedido) <= umbral
    hasta: float             # nivel hasta el que se compra
    plazo_dias: int
    revision_dias: int = 1   # 1 = revisa todos los dias (sin calendario)
    primera_revision: int = 0
    minimo_compra: float = 0
    multiplo: float = 0


@dataclass(frozen=True)
class ResultadoSimulacion:
    inventario: tuple         # unidades al dia 90, 180 y 365
    dias_quiebre: int
    unidades_no_atendidas: float
    compras_mes: tuple        # unidades compradas por mes (6 meses)
    stock_minimo: float


CORTES = (90, 180, 365)


def simular(stock_inicial, consumo_diario, escenario, llegadas=(), horizonte=365):
    """`stock_inicial` = fisico - comprometido de la red; `llegadas` = [(dia, cantidad)]
    del transito actual."""
    entradas = [0.0] * (horizonte + escenario.plazo_dias + 2)
    pedido = 0.0
    for dia, q in llegadas:
        d = max(1, int(dia))
        if d < len(entradas):
            entradas[d] += q
            pedido += q

    disponible = float(stock_inicial)
    inventario, compras, dias_quiebre, no_atendido = {}, [0.0] * 6, 0, 0.0
    minimo = disponible
    for d in range(0, horizonte + 1):
        # Dia 0 = hoy: solo revision (si hoy es dia de compra); el consumo corre desde el dia 1
        if d > 0:
            disponible += entradas[d]
            pedido -= entradas[d]
            disponible -= consumo_diario
            if disponible < 0:
                dias_quiebre += 1
                no_atendido += min(consumo_diario, -disponible)
            minimo = min(minimo, disponible)
        revisa = d >= escenario.primera_revision and (d - escenario.primera_revision) % max(1, escenario.revision_dias) == 0
        if revisa and disponible + pedido <= escenario.umbral and escenario.hasta > 0:
            q = al_multiplo(max(escenario.hasta - (disponible + pedido), escenario.minimo_compra), escenario.multiplo)
            if q > 0:
                llegada = d + escenario.plazo_dias
                if llegada < len(entradas):
                    entradas[llegada] += q
                pedido += q
                if d <= 180:
                    compras[min(5, max(0, d - 1) // 30)] += q
        if d in CORTES:
            inventario[d] = max(0.0, disponible)
    return ResultadoSimulacion(tuple(inventario.get(c, 0.0) for c in CORTES), dias_quiebre, no_atendido,
                               tuple(compras), minimo)
