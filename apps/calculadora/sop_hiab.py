"""Compatibilidad hacia atrás: delega todo al motor multi-marca `sop_equipos`."""
from .sop_equipos import (  # noqa: F401
    BODEGAS_EXCLUIDAS_STOCK_EQUIPOS,
    CLASE_EQUIPOS,
    ClaveModelo,
    SEMAFORO_META,
    UMBRAL_OPTIMO_MESES,
    UMBRAL_PRECAUCION_MESES,
    UMBRAL_SOBRESTOCK_MESES,
    calcular_cobertura_meses,
    clasificar_origen_sku,
    es_bodega_stock_equipo,
    evaluar_semaforo,
    evaluar_simulacion,
    get_sop_equipos_data,
    inferir_nombre_marca,
    resolver_modelo,
    simular_propuesta_compra,
)


def get_sop_hiab_data(grupo='', marca='', solo_con_actividad=True, force_refresh=False):
    """Alias de compatibilidad hacia `get_sop_equipos_data`."""
    return get_sop_equipos_data(grupo=grupo, marca=marca, solo_con_actividad=solo_con_actividad)
