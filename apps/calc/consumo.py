"""Consumo (documento §4.1, SPEC-10 §1)."""
import statistics
from dataclasses import dataclass


@dataclass(frozen=True)
class Consumo:
    meses: tuple                 # consumo de los meses usados (recortados), del mas antiguo al mas reciente
    meses_originales: tuple      # sin recorte de atipicos
    meses_con_consumo_12m: int
    consumo_total_12m: float
    consumo_promedio_mes: float
    consumo_diario: float
    variacion_consumo: float
    tope_mes_atipico: float
    meses_atipicos: tuple        # indices (0 = mas antiguo) recortados al tope
    mayor_consumo_mes: float


def _desvest(valores):
    return statistics.stdev(valores) if len(valores) > 1 else 0.0


def calcular_consumo(meses, params, meses_evento=()):
    """Estadisticas de consumo de los ultimos N meses cerrados (N = meses_historia_consumo).

    - `meses`: unidades por mes, del mas antiguo al mas reciente. Si vienen menos de N
      se completan con ceros al inicio (un mes sin movimiento cuenta como cero).
      Los netos negativos (mas devoluciones que salidas) cuentan como cero.
    - `meses_evento`: indices de meses asociados a un evento comercial aprobado: no se
      marcan como atipicos y no cuentan para `mayor_consumo_mes` (§4.5, §4.7).
    """
    n = params.meses_historia_consumo
    valores = [max(0.0, float(v or 0)) for v in list(meses)[-n:]]
    valores = [0.0] * (n - len(valores)) + valores
    eventos = set(meses_evento)

    promedio = sum(valores) / n
    variacion = _desvest(valores)
    tope = promedio + params.multiplicador_atipico * variacion

    # Solo se buscan atipicos con consumo regular (>= umbral R): en 12 meses un unico mes
    # con consumo siempre supera promedio + 3 desvest, y en un esporadico ese mes es su
    # consumo normal, no una anomalia (SPEC-10 §1).
    con_consumo = sum(1 for v in valores if v > 0)
    atipicos = ()
    if con_consumo >= params.umbral_r and variacion > 0:
        atipicos = tuple(i for i, v in enumerate(valores) if v > tope and i not in eventos)
    usados = list(valores)
    if params.recortar_atipicos and atipicos:
        for i in atipicos:
            usados[i] = tope
        promedio = sum(usados) / n
        variacion = _desvest(usados)

    candidatos = [v for i, v in enumerate(valores) if i not in atipicos and i not in eventos]
    mayor = max(candidatos) if candidatos and max(candidatos) > 0 else max(usados)
    total = sum(usados)

    return Consumo(
        meses=tuple(usados),
        meses_originales=tuple(valores),
        meses_con_consumo_12m=con_consumo,
        consumo_total_12m=total,
        consumo_promedio_mes=promedio,
        consumo_diario=total / 365.0,
        variacion_consumo=variacion,
        tope_mes_atipico=tope,
        meses_atipicos=atipicos,
        mayor_consumo_mes=mayor,
    )
