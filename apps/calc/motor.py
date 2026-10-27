"""Calculo completo de un articulo para la red (SPEC-10 a SPEC-12).

Orden: consumo -> plazo -> clasificacion -> metodo -> politica -> disponible de la red ->
compra -> distribucion a bodegas -> proyeccion diaria -> excepcion. Cada ejecucion parte
de cero (documento §1): no se reutilizan valores de corridas anteriores.
"""
import datetime
from dataclasses import dataclass, field

from . import clasificacion as cl
from . import politica as pol
from . import red
from .consumo import calcular_consumo
from .params import Params
from .plazo import MAESTRO, calcular_plazo
from .proyeccion import evaluar_excepcion, proyectar

OC_ATRASADA, PEDIDO, EVENTO, CONSUMO, DATO_FALTANTE = 'OC_ATRASADA', 'PEDIDO', 'EVENTO', 'CONSUMO', 'DATO_FALTANTE'


@dataclass
class EntradaArticulo:
    codigo: str
    hoy: datetime.date
    params: Params = field(default_factory=Params)
    segmento: str = cl.REPUESTOS
    abc: str = 'C'
    es_estrategico: bool = False
    minimo_declarado: float = 0
    es_critico: bool = False
    minimo_nuevo: float = 0
    bloqueado: bool = False
    fecha_creacion: datetime.date = None
    fecha_ultimo_movimiento: datetime.date = None
    consumo_meses: list = field(default_factory=list)   # red, meses cerrados, antiguo -> reciente
    meses_evento: tuple = ()
    ajuste_comercial: float = 0                          # unidades/mes de eventos aprobados vigentes
    dias_oc: list = field(default_factory=list)
    lead_time_maestro: float = 0
    costo: float = 0
    min_compra: float = 0
    multiplo: float = 0
    bodegas: list = field(default_factory=list)          # [red.Bodega]
    compromisos: list = field(default_factory=list)      # [(dia, cantidad)] de la red
    llegadas: list = field(default_factory=list)         # [(dia, cantidad)] OC y solicitudes
    oc_atrasada: bool = False
    dias_a_proxima_compra: int = 0
    es_dia_compra: bool = True


@dataclass
class ResultadoArticulo:
    codigo: str
    clasificacion: cl.Clasificacion
    es_nuevo: bool
    es_inmovilizado: bool
    nivel_servicio: float
    consumo: object
    plazo: object
    politica: pol.Politica
    compra: pol.Compra
    stock_fisico: float
    en_transito: float
    comprometido: float
    acciones: list
    traslados: list
    serie: list
    excepcion: object
    cantidad_excepcion: int = 0
    causa_excepcion: str = ''
    avisos: list = field(default_factory=list)

    @property
    def letra(self):
        return self.clasificacion.letra

    @property
    def cantidad_a_comprar(self):
        """Lo que entra en una solicitud: la del dia de compra o la de la excepcion."""
        if self.compra.comprar:
            return self.compra.cantidad_sugerida
        return self.cantidad_excepcion if self.excepcion and self.excepcion.excepcion else 0


def calcular_articulo(e):
    p = e.params
    consumo = calcular_consumo(e.consumo_meses, p, e.meses_evento)
    plazo = calcular_plazo(e.dias_oc, e.lead_time_maestro, p)

    stock, transito, comprometido = red.totales_red(e.bodegas)
    clasif = cl.clasificar(consumo.meses_con_consumo_12m, comprometido > 0, e.es_estrategico, p)
    nuevo = cl.es_nuevo(e.fecha_creacion, e.hoy, e.segmento, p)
    inmovilizado = (not nuevo and clasif.letra == 'O'
                    and cl.es_inmovilizado(e.fecha_ultimo_movimiento, e.fecha_creacion, e.hoy, e.segmento, p))
    nivel = cl.nivel_servicio(e.abc, e.es_critico, e.segmento, p)
    factor = cl.factor_servicio(nivel)
    avisos = []

    ajustado = consumo.consumo_promedio_mes + e.ajuste_comercial if e.ajuste_comercial else None
    if ajustado is not None:
        ajustado = max(0.0, ajustado)

    letra = clasif.letra
    if e.bloqueado:
        politica = pol.politica_minimo(pol.SIN_COMPRA, 0, p)
        avisos.append('Articulo bloqueado en SAP: excluido del sugerido')
    elif letra == 'O':
        politica = pol.politica_minimo(pol.SIN_COMPRA, 0, p)
    elif letra == 'P':
        politica = pol.politica_minimo(pol.A_PEDIDO, 0, p)
    elif nuevo:
        minimo = max(e.minimo_nuevo or 0, e.minimo_declarado or 0)
        politica = pol.politica_minimo(pol.NUEVO, minimo, p)
        if not minimo:
            avisos.append('Articulo nuevo sin minimo manual: revisar')
    elif letra == 'R' and clasif.subclase == cl.R_INTERMITENTE:
        politica = pol.politica_intermitente(consumo.meses_con_consumo_12m, consumo.mayor_consumo_mes,
                                             consumo.consumo_promedio_mes, plazo, p)
    else:
        politica = pol.politica_general(consumo.consumo_promedio_mes, consumo.variacion_consumo, plazo,
                                        factor, p, e.minimo_declarado if letra == 'E' else 0, ajustado)

    disponible = pol.disponible_futuro(stock, transito, comprometido)
    compra = pol.evaluar_compra(politica, disponible, consumo.consumo_promedio_mes, consumo.consumo_diario,
                                e.costo, p, e.min_compra, e.multiplo, e.es_dia_compra)
    acciones, traslados = red.distribuir(letra, e.bodegas)

    serie, excepcion, cantidad_exc, causa = [], None, 0, ''
    if politica.metodo in (pol.GENERAL, pol.INTERMITENTE, pol.NUEVO) and (consumo.consumo_diario > 0 or e.compromisos):
        serie = proyectar(stock, consumo.consumo_diario, e.compromisos, e.llegadas, p.horizonte_proyeccion_dias)
        excepcion = evaluar_excepcion(serie, politica.stock_seguridad, e.dias_a_proxima_compra,
                                      plazo.dias_entrega_promedio, plazo.dias_recepcion, e.es_dia_compra)
        if excepcion.excepcion:
            cantidad_exc = compra.cantidad_sugerida or pol.cantidad_minima(
                max(politica.stock_maximo - disponible, -min(serie)), politica.consumo_usado, p,
                e.min_compra, e.multiplo)
            causa = _causa(e, excepcion, consumo)

    if e.costo <= 0:
        avisos.append('Articulo sin costo')
    if plazo.origen == MAESTRO and not e.lead_time_maestro:
        avisos.append('Articulo sin plazo de entrega')
    if plazo.n_oc_invalidas:
        avisos.append(f'{plazo.n_oc_invalidas} OC con plazo negativo o mayor a 365 dias (excluidas)')
    if plazo.origen != MAESTRO and e.lead_time_maestro and plazo.dias_entrega_promedio > 1.5 * e.lead_time_maestro:
        avisos.append('Plazo real 50% mayor al del maestro')

    return ResultadoArticulo(
        codigo=e.codigo, clasificacion=clasif, es_nuevo=nuevo, es_inmovilizado=inmovilizado,
        nivel_servicio=nivel, consumo=consumo, plazo=plazo, politica=politica, compra=compra,
        stock_fisico=stock, en_transito=transito, comprometido=comprometido,
        acciones=acciones, traslados=traslados, serie=serie, excepcion=excepcion,
        cantidad_excepcion=cantidad_exc, causa_excepcion=causa, avisos=avisos,
    )


def _causa(e, excepcion, consumo):
    if e.oc_atrasada:
        return OC_ATRASADA
    if any(d <= excepcion.dia_quiebre and q >= max(1.0, consumo.consumo_promedio_mes) for d, q in e.compromisos):
        return PEDIDO
    if e.ajuste_comercial > 0:
        return EVENTO
    if e.costo <= 0 or not e.lead_time_maestro:
        return DATO_FALTANTE
    return CONSUMO
