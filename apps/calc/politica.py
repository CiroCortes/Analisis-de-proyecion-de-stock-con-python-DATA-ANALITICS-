"""Stock de seguridad, punto de pedido, stock maximo y cantidad a comprar
(documento §4.3 a §4.6, SPEC-10 §3 a §6)."""
import math
from dataclasses import dataclass

from .redondeo import al_multiplo, redondear_mas

GENERAL, INTERMITENTE, NUEVO, A_PEDIDO, SIN_COMPRA = 'GENERAL', 'INTERMITENTE', 'NUEVO', 'A_PEDIDO', 'SIN_COMPRA'
URGENTE, MEDIO, NORMAL = 'URGENTE', 'MEDIO', 'NORMAL'


@dataclass(frozen=True)
class Politica:
    metodo: str
    factor_servicio: float
    ss_calculado: float
    meses_piso_ss: float
    piso_ss: float
    stock_seguridad: int
    meses_revision: float
    punto_pedido: int
    stock_maximo: int
    salidas_en_plazo: int = 0
    consumo_usado: float = 0.0       # consumo_promedio_mes, o el ajustado por evento comercial


def politica_general(consumo_promedio, variacion_consumo, plazo, factor, params,
                     minimo_declarado=0, consumo_ajustado=None):
    """Formula general para R-Regular y E (§4.3, §4.4). `consumo_ajustado` (§4.7) solo
    cambia punto de pedido y maximo; el stock de seguridad usa el historial."""
    ss_calc = factor * math.sqrt(
        plazo.plazo_total_meses * variacion_consumo ** 2
        + consumo_promedio ** 2 * plazo.variacion_entrega_meses ** 2
    )
    meses_piso = params.meses_piso_ss_corto if plazo.plazo_total_dias <= params.umbral_plazo_largo_dias \
        else params.meses_piso_ss_largo
    piso = meses_piso * consumo_promedio
    ss = redondear_mas(max(ss_calc, piso))
    if minimo_declarado:
        ss = max(ss, redondear_mas(minimo_declarado))

    c = consumo_promedio if consumo_ajustado is None else consumo_ajustado
    revision = params.meses_revision
    rop = redondear_mas(c * (plazo.plazo_total_meses + revision) + ss)
    maximo = redondear_mas(rop + params.meses_cobertura * c)
    return Politica(GENERAL, factor, ss_calc, meses_piso, piso, ss, revision, rop, maximo, consumo_usado=c)


def politica_intermitente(meses_con_consumo_12m, mayor_consumo_mes, consumo_promedio, plazo, params,
                          minimo_declarado=0):
    """Regla de salidas segun plazo para R-Intermitente (§4.5).

    El documento no define el stock de seguridad de esta regla; se usa lo que el punto
    de pedido cubre por sobre el consumo esperado en el plazo (SPEC-10 §5, decision a
    validar). Solo se usa para la urgencia MEDIO y las alertas de bajo SS."""
    salidas = max(1, redondear_mas(meses_con_consumo_12m / 12.0 * plazo.plazo_total_meses))
    rop = redondear_mas(mayor_consumo_mes * salidas)
    if minimo_declarado:
        rop = max(rop, redondear_mas(minimo_declarado))
    maximo = redondear_mas(rop + mayor_consumo_mes * params.salidas_extra)
    ss = max(0, redondear_mas(rop - consumo_promedio * plazo.plazo_total_meses))
    return Politica(INTERMITENTE, 0.0, 0.0, 0.0, 0.0, ss, params.meses_revision, rop, maximo,
                    salidas_en_plazo=salidas, consumo_usado=consumo_promedio)


def politica_minimo(metodo, minimo, params):
    """Nuevo (minimo manual), P (lo comprometido, se resuelve en la compra) u O (cero)."""
    m = redondear_mas(minimo or 0)
    return Politica(metodo, 0.0, 0.0, 0.0, 0.0, 0, params.meses_revision, m, m)


@dataclass(frozen=True)
class Compra:
    disponible_futuro: float
    umbral_compra: float
    necesita_compra: bool        # disponible <= umbral, sin importar el calendario
    comprar: bool                # necesita_compra y hoy es dia de compra del proveedor
    faltante: float
    cantidad_sugerida: int
    valor_sugerido: float
    urgencia: str
    cobertura_dias: float        # None si no hay consumo
    valor_stock_maximo: float


def disponible_futuro(stock_fisico, en_transito, comprometido):
    return float(stock_fisico) + float(en_transito) - float(comprometido)


def urgencia(disponible, stock_seguridad):
    if disponible <= 0:
        return URGENTE
    if disponible < stock_seguridad:
        return MEDIO
    return NORMAL


def evaluar_compra(politica, disponible, consumo_promedio, consumo_diario, costo, params,
                   min_compra=0, multiplo=0, es_dia_compra=True):
    """Campo `comprar` y `cantidad_sugerida` (§4.6). Siempre se compra hasta el maximo,
    nunca hasta el punto de pedido. Con consumo cero no se sugiere compra (§9), salvo P,
    que compra lo comprometido que el stock no cubre."""
    c = politica.consumo_usado
    umbral = politica.punto_pedido + c * politica.meses_revision
    cobertura = disponible / consumo_diario if consumo_diario > 0 else None
    urg = urgencia(disponible, politica.stock_seguridad)
    valor_max = politica.stock_maximo * costo

    if politica.metodo == A_PEDIDO:
        # P: lo comprometido en la red que el stock no cubre. No espera el calendario:
        # es un pedido de cliente u OF concreto.
        falta = max(0.0, -disponible)
        cantidad = al_multiplo(max(falta, min_compra or 0), multiplo) if falta > 0 else 0
        return Compra(disponible, 0.0, cantidad > 0, cantidad > 0, falta, cantidad, cantidad * costo,
                      URGENTE if disponible < 0 else NORMAL, cobertura, 0.0)

    # Consumo cero no compra (§9), salvo un E o Nuevo con minimo declarado
    sin_consumo = consumo_promedio <= 0 and politica.stock_seguridad <= 0 and politica.metodo != NUEVO
    if politica.metodo == SIN_COMPRA or sin_consumo or politica.stock_maximo <= 0:
        return Compra(disponible, umbral, False, False, 0.0, 0, 0.0,
                      urg if politica.stock_maximo > 0 else NORMAL, cobertura, valor_max)

    necesita = disponible <= umbral
    falta = max(0.0, politica.stock_maximo - disponible)
    cantidad = cantidad_minima(falta, c, params, min_compra, multiplo) if necesita and falta > 0 else 0
    return Compra(disponible, umbral, cantidad > 0, cantidad > 0 and es_dia_compra, falta, cantidad,
                  cantidad * costo, urg, cobertura, valor_max)


def cantidad_minima(faltante, consumo_mes, params, min_compra=0, multiplo=0):
    """MAX(faltante; meses_minimo_compra x consumo; MinOrdrQty) al multiplo OrdrMulti."""
    return al_multiplo(max(faltante, params.meses_minimo_compra * consumo_mes, min_compra or 0), multiplo)
