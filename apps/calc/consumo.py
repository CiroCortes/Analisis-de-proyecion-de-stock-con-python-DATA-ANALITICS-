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
    mediana_con_consumo: float = 0.0   # mediana de los meses con consumo (SPEC-26)
    tope_por_mediana: bool = False     # el tope vino de k x mediana y no de promedio + 3 desvest


def _desvest(valores):
    return statistics.stdev(valores) if len(valores) > 1 else 0.0


def calcular_consumo(meses, params, meses_evento=()):
    """Estadisticas de consumo de los ultimos N meses cerrados (N = meses_historia_consumo).

    - `meses`: unidades por mes, del mas antiguo al mas reciente. Si vienen menos de N
      se completan con ceros al inicio (un mes sin movimiento cuenta como cero).
      Los netos negativos (mas devoluciones que salidas) cuentan como cero.
    - `meses_evento`: indices de meses asociados a un evento comercial aprobado: no se
      marcan como atipicos y no cuentan para `mayor_consumo_mes` (§4.5, §4.7).

    Tope de mes atipico (SPEC-26): el menor entre promedio + 3 desvest (documento §4.1) y
    k x mediana de los meses con consumo (`multiplicador_pico_mediana`, 0 = desactivado). El
    promedio y la desvest incluyen el pico, asi que por si solos casi no recortan; la mediana
    no se mueve con uno o dos meses extremos. Un alza sostenida (2 o mas de los ultimos 3 meses
    sobre el tope) es un cambio de nivel, no un pico: esos meses no se recortan.
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
    # Los umbrales R (3) y R-Regular (9) son "de 12 meses": se cuentan sobre los ultimos 12
    con_consumo = sum(1 for v in valores[-12:] if v > 0)
    positivos = [v for v in valores if v > 0]
    mediana = statistics.median(positivos) if positivos else 0.0
    por_mediana = False
    if params.multiplicador_pico_mediana > 0 and mediana > 0:
        tope_mediana = params.multiplicador_pico_mediana * mediana
        if tope_mediana < tope:
            tope, por_mediana = tope_mediana, True
    atipicos = ()
    if con_consumo >= params.umbral_r and variacion > 0:
        sobre = [i for i, v in enumerate(valores) if v > tope and i not in eventos]
        recientes = [i for i in sobre if i >= n - 3]
        if len(recientes) >= 2:
            sobre = [i for i in sobre if i < n - 3]
        atipicos = tuple(sobre)
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
        consumo_diario=promedio * 12 / 365.0,     # = total / 365 con 12 meses de historia
        variacion_consumo=variacion,
        tope_mes_atipico=tope,
        meses_atipicos=atipicos,
        mayor_consumo_mes=mayor,
        mediana_con_consumo=mediana,
        tope_por_mediana=por_mediana,
    )
