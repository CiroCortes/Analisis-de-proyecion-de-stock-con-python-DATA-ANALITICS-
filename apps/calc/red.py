"""Compra para la red y distribucion a bodegas (documento §5, SPEC-11).

La compra se calcula una sola vez por articulo con el consumo y el disponible de toda
la red y se recibe en la central (013-PP). Las bodegas no compran: solo reciben
traslados. Lo que Santiago no cubre queda en ESPERA COMPRA, porque ese compromiso ya
esta incluido en la compra de la red.
"""
import datetime
from dataclasses import dataclass, field

TRASLADAR, TRASLADAR_PARCIAL, ESPERA_COMPRA, NINGUNA = 'TRASLADAR', 'TRASLADAR_PARCIAL', 'ESPERA_COMPRA', 'NINGUNA'


@dataclass(frozen=True)
class Bodega:
    codigo: str
    es_central: bool = False
    es_santiago: bool = False
    stock_fisico: float = 0
    en_transito: float = 0          # OC + SC + traslados en camino hacia la bodega
    comprometido: float = 0         # PC + OF pendientes atribuidos a la bodega
    fecha_compromiso: datetime.date = None   # compromiso mas cercano (prioridad de reparto)

    @property
    def disponible_futuro(self):
        return self.stock_fisico + self.en_transito - self.comprometido


@dataclass(frozen=True)
class Traslado:
    origen: str
    destino: str
    cantidad: float


@dataclass
class AccionBodega:
    codigo: str
    objetivo: float
    disponible_futuro: float
    faltante: float
    accion: str = NINGUNA
    cantidad_trasladar: float = 0
    espera_compra: float = 0
    excedente: float = 0
    origenes: list = field(default_factory=list)          # [(bodega_origen, cantidad)]
    sucursales_con_stock: list = field(default_factory=list)  # para alertar traslado entre sucursales


def objetivo_bodega(letra, bodega):
    """§5, tabla 'Objetivo por bodega'. R/E/P: lo comprometido localmente (la central
    guarda ademas el resto del stock de la red, que es lo que sobra). O: cero."""
    if letra == 'O':
        return 0.0
    return float(max(0, bodega.comprometido))


def totales_red(bodegas):
    stock = sum(b.stock_fisico for b in bodegas)
    transito = sum(b.en_transito for b in bodegas)
    comprometido = sum(b.comprometido for b in bodegas)
    return stock, transito, comprometido


def distribuir(letra, bodegas):
    """Acciones por bodega y traslados sugeridos, en el orden del §5:
    1. excedente de otras bodegas de Santiago (disponible - su objetivo);
    2. stock libre de la central (fisico - sus compromisos - traslados ya sugeridos);
    3. si no alcanza, ESPERA COMPRA.
    Si varias bodegas piden, primero las URGENTES (disponible <= 0) y despues la fecha
    comprometida mas cercana."""
    acciones = {}
    for b in bodegas:
        obj = objetivo_bodega(letra, b)
        disp = b.disponible_futuro
        acciones[b.codigo] = AccionBodega(b.codigo, obj, disp, max(0.0, obj - disp))

    central = next((b for b in bodegas if b.es_central), None)
    excedentes = {}
    for b in bodegas:
        if b.es_santiago and not b.es_central:
            exc = max(0.0, b.disponible_futuro - acciones[b.codigo].objetivo)
            if exc > 0:
                excedentes[b.codigo] = exc
    libre_central = 0.0
    if central is not None:
        libre_central = max(0.0, central.stock_fisico - central.comprometido)
        acciones[central.codigo].excedente = libre_central
    for codigo, exc in excedentes.items():
        acciones[codigo].excedente = exc

    max_fecha = datetime.date.max
    solicitantes = sorted(
        (b for b in bodegas if acciones[b.codigo].faltante > 0),
        key=lambda b: (b.disponible_futuro > 0, b.fecha_compromiso or max_fecha, b.codigo),
    )

    traslados = []
    for b in solicitantes:
        a = acciones[b.codigo]
        pendiente = a.faltante
        for origen in sorted((c for c in excedentes if c != b.codigo), key=lambda c: (-excedentes[c], c)):
            if pendiente <= 0:
                break
            q = min(pendiente, excedentes[origen])
            if q <= 0:
                continue
            excedentes[origen] -= q
            pendiente -= q
            a.origenes.append((origen, q))
        if pendiente > 0 and central is not None and not b.es_central and libre_central > 0:
            q = min(pendiente, libre_central)
            libre_central -= q
            pendiente -= q
            a.origenes.append((central.codigo, q))

        a.cantidad_trasladar = a.faltante - pendiente
        a.espera_compra = pendiente
        if a.cantidad_trasladar > 0 and pendiente <= 0:
            a.accion = TRASLADAR
        elif a.cantidad_trasladar > 0:
            a.accion = TRASLADAR_PARCIAL
        else:
            a.accion = ESPERA_COMPRA
        if pendiente > 0 and not b.es_santiago:
            a.sucursales_con_stock = [
                o.codigo for o in bodegas
                if not o.es_santiago and o.codigo != b.codigo
                and o.disponible_futuro - acciones[o.codigo].objetivo > 0
            ]
        traslados.extend(Traslado(origen, b.codigo, q) for origen, q in a.origenes)

    return list(acciones.values()), traslados
