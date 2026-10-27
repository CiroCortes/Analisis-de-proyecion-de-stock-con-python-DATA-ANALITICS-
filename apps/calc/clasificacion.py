"""Clasificacion RPEO, subclase, ABC, Nuevo, Inmovilizado y nivel de servicio
(documento §3, SPEC-09)."""
from dataclasses import dataclass
from statistics import NormalDist

PANOL, REPUESTOS = 'PANOL', 'REPUESTOS'
R_REGULAR, R_INTERMITENTE = 'REGULAR', 'INTERMITENTE'

# Tabla del documento (§3). Otros niveles: cuantil de la normal redondeado a 2 decimales.
_FACTOR = {0.90: 1.28, 0.95: 1.65, 0.97: 1.88}


@dataclass(frozen=True)
class Clasificacion:
    letra: str          # E, R, P u O
    subclase: str       # REGULAR / INTERMITENTE (solo R; E usa la de su consumo)
    motivo: str


def factor_servicio(nivel):
    nivel = round(float(nivel), 4)
    if nivel in _FACTOR:
        return _FACTOR[nivel]
    return round(NormalDist().inv_cdf(nivel), 2)


def clasificar(meses_con_consumo_12m, tiene_compromiso_activo, es_estrategico, params):
    """Reglas en orden; la primera que se cumple manda (§3)."""
    m = meses_con_consumo_12m
    subclase = R_REGULAR if m >= params.umbral_r_regular else R_INTERMITENTE
    if es_estrategico:
        return Clasificacion('E', subclase, 'Marcado estrategico por el area usuaria')
    if m >= params.umbral_r:
        return Clasificacion('R', subclase, f'Consumo en {m} de 12 meses')
    if tiene_compromiso_activo:
        return Clasificacion('P', '', 'Tiene PC u OF abierto' + (f' y consumo en {m} meses' if m else ''))
    if m >= 1 and not params.p_solo_con_compromiso:
        return Clasificacion('P', '', f'Consumo en {m} de 12 meses')
    if m >= 1:
        return Clasificacion('O', '', f'Consumo en {m} de 12 meses, sin PC ni OF abierto')
    return Clasificacion('O', '', 'Sin consumo en 12 meses y sin PC ni OF abierto')


def _meses_entre(desde, hasta):
    return (hasta.year - desde.year) * 12 + (hasta.month - desde.month) - (1 if hasta.day < desde.day else 0)


def es_nuevo(fecha_creacion, hoy, segmento, params):
    if not fecha_creacion:
        return False
    limite = params.nuevo_meses_panol if segmento == PANOL else params.nuevo_meses_repuestos
    return _meses_entre(fecha_creacion, hoy) < limite


def es_inmovilizado(fecha_ultimo_movimiento, fecha_creacion, hoy, segmento, params):
    """Sin movimiento en 24 meses (repuestos) o 12 (panol). Sin ningun movimiento
    registrado se usa la fecha de creacion."""
    limite = params.inmovilizado_meses_panol if segmento == PANOL else params.inmovilizado_meses_repuestos
    referencia = fecha_ultimo_movimiento or fecha_creacion
    if not referencia:
        return True
    return _meses_entre(referencia, hoy) >= limite


def clases_abc(valores, params):
    """ABC por valor de consumo anual: A = primeros 80% del valor acumulado,
    B = siguiente 15%, C = el resto. Valor 0 es siempre C.
    `valores`: dict codigo -> valor. Devuelve dict codigo -> letra."""
    total = sum(v for v in valores.values() if v > 0)
    resultado = {}
    acumulado = 0.0
    corte_b = params.corte_abc_a + params.corte_abc_b
    for codigo, valor in sorted(valores.items(), key=lambda kv: (-kv[1], kv[0])):
        if valor <= 0 or total <= 0:
            resultado[codigo] = 'C'
            continue
        participacion_previa = acumulado / total
        if participacion_previa < params.corte_abc_a:
            resultado[codigo] = 'A'
        elif participacion_previa < corte_b:
            resultado[codigo] = 'B'
        else:
            resultado[codigo] = 'C'
        acumulado += valor
    return resultado


def clase_xyz(consumo_promedio, variacion, params):
    """Variabilidad del consumo (SPEC-19 §3.1): X estable, Y variable, Z erratico o sin consumo."""
    if consumo_promedio <= 0:
        return 'Z'
    cv = variacion / consumo_promedio
    if cv <= params.corte_xyz_x:
        return 'X'
    if cv <= params.corte_xyz_y:
        return 'Y'
    return 'Z'


def nivel_servicio(abc, es_critico, segmento, params):
    nivel = {'A': params.nivel_servicio_a, 'B': params.nivel_servicio_b}.get(abc, params.nivel_servicio_c)
    if es_critico or segmento == PANOL:
        nivel = max(nivel, params.nivel_servicio_critico)
    return nivel
