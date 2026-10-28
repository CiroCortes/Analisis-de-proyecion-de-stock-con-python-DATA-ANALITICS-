"""Compra para la red y distribucion entre Santiago y sucursales (documento §5, SPEC-11, SPEC-21).

La compra se calcula una sola vez por articulo con el consumo y el disponible de toda
la red. Santiago es un solo stock (SPEC-21 §2): sus bodegas estan fisicamente juntas y el
recolector consume desde cualquiera de ellas, asi que solo se sugieren traslados Santiago <->
sucursales. Ningun nodo entrega lo que protege para si (compromisos + reserva de consumo).
Lo que no se cubre queda en ESPERA COMPRA, porque ya esta incluido en la compra de la red.
"""
import datetime
from dataclasses import dataclass, field

from .redondeo import redondear_mas

TRASLADAR, TRASLADAR_PARCIAL, ESPERA_COMPRA, NINGUNA = 'TRASLADAR', 'TRASLADAR_PARCIAL', 'ESPERA_COMPRA', 'NINGUNA'

# Nodo Santiago: la 013 ("Bodega Central" en SAP), por donde salen las ventas de Santiago
NODO_SANTIAGO = '013'


@dataclass(frozen=True)
class Bodega:
    codigo: str
    es_central: bool = False
    es_santiago: bool = False
    stock_fisico: float = 0
    en_transito: float = 0          # OC + SC + traslados en camino hacia la bodega
    comprometido: float = 0         # PC + OF pendientes atribuidos a la bodega
    fecha_compromiso: datetime.date = None   # compromiso mas cercano (prioridad de reparto)
    consumo_diario: float = 0       # consumo propio (reserva de la proteccion, SPEC-21 §3)
    componentes: tuple = ()         # nodo Santiago: ((bodega, stock_fisico), ...)

    @property
    def disponible_futuro(self):
        return self.stock_fisico + self.en_transito - self.comprometido


@dataclass(frozen=True)
class Traslado:
    origen: str
    destino: str
    cantidad: float
    desde: tuple = ()               # origen Santiago: ((bodega 013-xx, cantidad), ...)


@dataclass
class AccionBodega:
    codigo: str
    objetivo: float
    disponible_futuro: float
    faltante: float
    accion: str = NINGUNA
    cantidad_trasladar: float = 0
    espera_compra: float = 0
    excedente: float = 0            # libre: lo que el nodo puede entregar
    protegido: float = 0
    origenes: list = field(default_factory=list)          # [(bodega_origen, cantidad)]
    sucursales_con_stock: list = field(default_factory=list)  # para alertar traslado entre sucursales
    retenido_en: list = field(default_factory=list)       # [(donante, stock retenido)]: decide jefatura


def objetivo_bodega(letra, bodega):
    """§5, tabla 'Objetivo por bodega'. R/E/P: lo comprometido localmente. O: cero."""
    if letra == 'O':
        return 0.0
    return float(max(0, bodega.comprometido))


def faltante_bodega(objetivo, bodega):
    """Lo que realmente le falta al nodo: su objetivo contra lo que tiene (stock + transito).
    = MAX(0; -disponible) cuando el objetivo es lo comprometido. El documento (caso 4) compara
    contra el disponible, que ya desconto el compromiso, y lo contaba dos veces: corregido el
    28-oct (SPEC-11 §3.1)."""
    return max(0.0, objetivo - (bodega.stock_fisico + bodega.en_transito))


def totales_red(bodegas):
    stock = sum(b.stock_fisico for b in bodegas)
    transito = sum(b.en_transito for b in bodegas)
    comprometido = sum(b.comprometido for b in bodegas)
    return stock, transito, comprometido


def agrupar_santiago(bodegas):
    """Suma las bodegas de Santiago en un nodo (NODO_SANTIAGO) y deja las sucursales igual.
    Los totales de la red no cambian."""
    stgo = [b for b in bodegas if b.es_santiago]
    resto = [b for b in bodegas if not b.es_santiago]
    if not stgo:
        return resto
    fechas = [b.fecha_compromiso for b in stgo if b.fecha_compromiso]
    stock_por_bodega = {}
    for b in stgo:
        for codigo, q in (b.componentes or ((b.codigo, b.stock_fisico),)):
            stock_por_bodega[codigo] = stock_por_bodega.get(codigo, 0) + q
    nodo = Bodega(
        NODO_SANTIAGO, es_central=True, es_santiago=True,
        stock_fisico=sum(b.stock_fisico for b in stgo), en_transito=sum(b.en_transito for b in stgo),
        comprometido=sum(b.comprometido for b in stgo), fecha_compromiso=min(fechas) if fechas else None,
        consumo_diario=sum(b.consumo_diario for b in stgo),
        componentes=tuple(sorted(((c, q) for c, q in stock_por_bodega.items() if q > 0), key=lambda x: (-x[1], x[0]))),
    )
    return [nodo] + resto


def protegido(bodega, dias_reserva):
    """Lo que el nodo guarda para si: compromisos + su consumo durante la reserva, en unidades
    enteras hacia arriba (SPEC-21 §3)."""
    return max(0.0, bodega.comprometido) + redondear_mas(max(0.0, bodega.consumo_diario) * max(0, dias_reserva))


def libre(bodega, dias_reserva):
    return max(0.0, bodega.stock_fisico - protegido(bodega, dias_reserva))


def _desde(componentes, usado, cantidad):
    """Reparte un traslado desde Santiago entre sus bodegas, la de mayor stock primero."""
    partes = []
    for codigo, stock in componentes:
        if cantidad <= 0:
            break
        q = min(cantidad, stock - usado.get(codigo, 0))
        if q > 0:
            usado[codigo] = usado.get(codigo, 0) + q
            partes.append((codigo, q))
            cantidad -= q
    return tuple(partes)


def distribuir(letra, nodos, dias_reserva=0):
    """Acciones por nodo y traslados sugeridos (SPEC-21 §4). `nodos` ya agrupados
    (`agrupar_santiago`): Santiago es el central.
    - Sucursal: pide su faltante real al libre de Santiago.
    - Santiago: pide su faltante real al libre de las sucursales, la de mayor libre primero.
    Si varios piden, primero los URGENTES (disponible <= 0) y despues la fecha comprometida
    mas cercana."""
    acciones, libres = {}, {}
    for b in nodos:
        obj = objetivo_bodega(letra, b)
        disp = b.disponible_futuro
        a = AccionBodega(b.codigo, obj, disp, faltante_bodega(obj, b), protegido=protegido(b, dias_reserva))
        libres[b.codigo] = a.excedente = libre(b, dias_reserva)
        acciones[b.codigo] = a

    central = next((b for b in nodos if b.es_central), None)
    sucursales = [b for b in nodos if not b.es_central]
    max_fecha = datetime.date.max
    solicitantes = sorted(
        (b for b in nodos if acciones[b.codigo].faltante > 0),
        key=lambda b: (b.disponible_futuro > 0, b.fecha_compromiso or max_fecha, b.codigo),
    )

    traslados, usado_santiago = [], {}
    for b in solicitantes:
        a = acciones[b.codigo]
        necesidad = a.faltante
        if b.es_central:
            donantes = sorted(sucursales, key=lambda d: (-libres[d.codigo], d.codigo))
        else:
            donantes = [central] if central is not None else []
        pendiente = necesidad
        for d in donantes:
            if pendiente <= 0:
                break
            q = min(pendiente, libres[d.codigo])
            if q > 0:
                libres[d.codigo] -= q
                pendiente -= q
                a.origenes.append((d.codigo, q))

        a.cantidad_trasladar = necesidad - pendiente
        a.espera_compra = pendiente
        if a.cantidad_trasladar > 0 and pendiente <= 0:
            a.accion = TRASLADAR
        elif a.cantidad_trasladar > 0:
            a.accion = TRASLADAR_PARCIAL
        elif pendiente > 0:
            a.accion = ESPERA_COMPRA
        if pendiente > 0:
            a.retenido_en = [(d.codigo, r) for d in donantes
                             if (r := min(d.stock_fisico, protegido(d, dias_reserva))) > 0]
            if not b.es_santiago:
                a.sucursales_con_stock = [o.codigo for o in sucursales if o.codigo != b.codigo and libres[o.codigo] > 0]
        for origen, q in a.origenes:
            desde = _desde(central.componentes, usado_santiago, q) if central is not None and origen == central.codigo else ()
            traslados.append(Traslado(origen, b.codigo, q, desde))

    return list(acciones.values()), traslados
