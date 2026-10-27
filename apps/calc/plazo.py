"""Plazo de entrega (documento §4.2, SPEC-10 §2)."""
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


def calcular_plazo(dias_oc, lead_time_maestro, params):
    """Plazo real si hay al menos `min_oc_plazo_real` OC validas; si no, el del maestro
    con una variacion del `variacion_entrega_defecto` (25%) del plazo."""
    dias = [float(d) for d in (dias_oc or []) if d is not None]
    validos = [d for d in dias if 0 <= d <= 365]
    invalidos = len(dias) - len(validos)

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
    )
