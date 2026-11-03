"""Plazo de entrega (documento §4.2, SPEC-10 §2; plazos atipicos SPEC-33)."""
import statistics
from dataclasses import dataclass

REAL, MAESTRO = 'REAL', 'MAESTRO'


@dataclass(frozen=True)
class Plazo:
    dias_entrega_promedio: float
    variacion_entrega_dias: float
    dias_recepcion: float
    plazo_total_dias: float
    plazo_total_meses: float
    variacion_entrega_meses: float
    origen: str                  # REAL (OC recibidas) o MAESTRO (OITM.LeadTime)
    n_oc: int                    # OC validas usadas
    n_oc_invalidas: int          # plazos negativos o > 365 dias (error de dato, §9)
    tope_plazo_dias: float = 0.0  # tope de plazo atipico (0 = sin recorte, SPEC-33)
    n_oc_atipicas: int = 0        # OC recortadas al tope


def tope_plazo(validos, params):
    """SPEC-33: el mayor entre `multiplicador_plazo_mediana` x mediana y mediana + `dias_min_plazo_atipico`.
    Una OC sobre el tope no es el plazo del proveedor: suele ser una OC que quedo abierta o una
    recepcion registrada tarde. 0 si no aplica (sin multiplicador o pocas OC)."""
    k = getattr(params, 'multiplicador_plazo_mediana', 0)
    if not k or len(validos) < params.min_oc_plazo_real:
        return 0.0
    mediana = statistics.median(validos)
    return max(k * mediana, mediana + getattr(params, 'dias_min_plazo_atipico', 0))


def calcular_plazo(dias_oc, lead_time_maestro, params):
    """Plazo real si hay al menos `min_oc_plazo_real` OC validas; si no, el del maestro
    con una variacion del `variacion_entrega_defecto` (25%) del plazo."""
    dias = [float(d) for d in (dias_oc or []) if d is not None]
    validos = [d for d in dias if 0 <= d <= 365]
    invalidos = len(dias) - len(validos)

    tope, atipicas = tope_plazo(validos, params), 0
    if tope:
        atipicas = sum(1 for d in validos if d > tope)
        validos = [min(d, tope) for d in validos]
    if len(validos) >= params.min_oc_plazo_real:
        promedio = statistics.mean(validos)
        variacion = statistics.stdev(validos) if len(validos) > 1 else 0.0
        origen = REAL
    else:
        promedio = max(0.0, float(lead_time_maestro or 0))
        variacion = params.variacion_entrega_defecto * promedio
        origen = MAESTRO

    total_dias = promedio + params.dias_recepcion
    return Plazo(
        dias_entrega_promedio=promedio,
        variacion_entrega_dias=variacion,
        dias_recepcion=params.dias_recepcion,
        plazo_total_dias=total_dias,
        plazo_total_meses=total_dias / 30.0,
        variacion_entrega_meses=variacion / 30.0,
        origen=origen,
        n_oc=len(validos) if origen == REAL else 0,
        n_oc_invalidas=invalidos,
        tope_plazo_dias=tope if atipicas else 0.0,
        n_oc_atipicas=atipicas,
    )
