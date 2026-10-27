"""Parametros del calculo con sus valores iniciales (documento §7, SPEC-14).

Ningun valor de negocio queda escrito en las formulas: todas leen un `Params`.
La capa Django resuelve los niveles (general / familia / proveedor / articulo / bodega)
y entrega un `Params` por articulo con `dataclasses.replace`.
"""
from dataclasses import dataclass, fields, replace


@dataclass(frozen=True)
class Params:
    # Nivel de servicio por clase ABC y minimo para criticos / panol
    nivel_servicio_a: float = 0.97
    nivel_servicio_b: float = 0.95
    nivel_servicio_c: float = 0.90
    nivel_servicio_critico: float = 0.97

    # Plazos
    dias_recepcion: float = 2
    frecuencia_compra_dias: int = 15
    min_oc_plazo_real: int = 3
    variacion_entrega_defecto: float = 0.25
    meses_historia_oc: int = 24

    # Stock de seguridad, punto de pedido y maximo
    umbral_plazo_largo_dias: float = 60
    meses_piso_ss_corto: float = 2
    meses_piso_ss_largo: float = 4
    meses_cobertura: float = 3
    meses_minimo_compra: float = 1
    salidas_extra: int = 1

    # Consumo
    meses_historia_consumo: int = 12
    multiplicador_atipico: float = 3
    recortar_atipicos: bool = True

    # Clasificacion
    umbral_r: int = 3
    umbral_r_regular: int = 9
    nuevo_meses_repuestos: int = 8
    nuevo_meses_panol: int = 4
    inmovilizado_meses_repuestos: int = 24
    inmovilizado_meses_panol: int = 12
    corte_abc_a: float = 0.80
    corte_abc_b: float = 0.15
    # Regla P acordada el 26-oct (SPEC-07 §6): P exige PC u OF abierto. Con False se usa
    # la regla literal del documento (consumo en 1-2 meses O compromiso activo).
    p_solo_con_compromiso: bool = True
    # Eje XYZ por coeficiente de variacion del consumo mensual (SPEC-19 §3.1)
    corte_xyz_x: float = 0.5
    corte_xyz_y: float = 1.0

    # Proyeccion diaria
    horizonte_proyeccion_dias: int = 120

    # Alertas
    alerta_bajo_ss_dias: int = 15
    alerta_contrato_vence_dias: int = 60
    alerta_sobrestock_meses: float = 3

    @property
    def meses_revision(self):
        return self.frecuencia_compra_dias / 30.0


# Metadatos para la pantalla de parametros: clave -> (etiqueta, niveles, minimo, maximo)
GENERAL, FAMILIA, PROVEEDOR, ARTICULO, BODEGA = 'GENERAL', 'FAMILIA', 'PROVEEDOR', 'ARTICULO', 'BODEGA'
NIVELES = [GENERAL, FAMILIA, PROVEEDOR, ARTICULO, BODEGA]
# Orden de prioridad: manda el mas especifico
PRIORIDAD = {GENERAL: 0, FAMILIA: 1, BODEGA: 1, PROVEEDOR: 2, ARTICULO: 3}

_GFA = (GENERAL, FAMILIA, ARTICULO)
CATALOGO = {
    'nivel_servicio_a': ('Nivel de servicio clase A', _GFA, 0.80, 0.995),
    'nivel_servicio_b': ('Nivel de servicio clase B', _GFA, 0.80, 0.995),
    'nivel_servicio_c': ('Nivel de servicio clase C', _GFA, 0.80, 0.995),
    'nivel_servicio_critico': ('Nivel de servicio minimo criticos y panol', (GENERAL,), 0.80, 0.995),
    'dias_recepcion': ('Dias de recepcion', (GENERAL, BODEGA), 0, 60),
    'frecuencia_compra_dias': ('Frecuencia de compra (dias)', (GENERAL, PROVEEDOR), 1, 180),
    'meses_cobertura': ('Meses de cobertura sobre el punto de pedido', _GFA, 0, 24),
    'meses_minimo_compra': ('Meses minimos por compra', _GFA, 0, 12),
    'umbral_plazo_largo_dias': ('Umbral plazo corto / largo (dias)', (GENERAL, FAMILIA), 1, 365),
    'meses_piso_ss_corto': ('Piso SS plazo corto (meses)', _GFA, 0, 12),
    'meses_piso_ss_largo': ('Piso SS plazo largo (meses)', _GFA, 0, 12),
    'salidas_extra': ('Salidas extra R-Intermitente', _GFA, 0, 12),
    'meses_historia_consumo': ('Meses de historia de consumo', (GENERAL,), 6, 24),
    'meses_historia_oc': ('Meses de historia de OC', (GENERAL,), 6, 36),
    'min_oc_plazo_real': ('Minimo de OC para usar plazo real', (GENERAL,), 1, 20),
    'variacion_entrega_defecto': ('Variacion de entrega por defecto (% del plazo)', (GENERAL,), 0, 1),
    'multiplicador_atipico': ('Multiplicador del tope de mes atipico', (GENERAL,), 1, 10),
    'umbral_r': ('Umbral R (meses con consumo de 12)', (GENERAL,), 1, 12),
    'umbral_r_regular': ('Umbral R-Regular (meses con consumo de 12)', (GENERAL,), 1, 12),
    'nuevo_meses_repuestos': ('Antiguedad para Nuevo, repuestos (meses)', (GENERAL,), 0, 36),
    'nuevo_meses_panol': ('Antiguedad para Nuevo, panol (meses)', (GENERAL,), 0, 36),
    'inmovilizado_meses_repuestos': ('Meses para Inmovilizado, repuestos', (GENERAL,), 6, 60),
    'inmovilizado_meses_panol': ('Meses para Inmovilizado, panol', (GENERAL,), 6, 60),
    'corte_abc_a': ('Corte ABC clase A (% valor acumulado)', (GENERAL,), 0.5, 0.95),
    'corte_abc_b': ('Corte ABC clase B (% valor siguiente)', (GENERAL,), 0.01, 0.45),
    'p_solo_con_compromiso': ('P exige PC u OF abierto', (GENERAL,), 0, 1),
    'corte_xyz_x': ('Corte XYZ clase X (coef. de variacion maximo)', (GENERAL,), 0.05, 3),
    'corte_xyz_y': ('Corte XYZ clase Y (coef. de variacion maximo)', (GENERAL,), 0.1, 5),
    'horizonte_proyeccion_dias': ('Horizonte de proyeccion diaria (dias)', (GENERAL,), 30, 365),
    'alerta_bajo_ss_dias': ('Alerta bajo SS proyectado (dias)', (GENERAL,), 1, 90),
    'alerta_contrato_vence_dias': ('Alerta contrato por vencer (dias)', (GENERAL,), 1, 365),
    'alerta_sobrestock_meses': ('Sobrestock: meses sobre el maximo', (GENERAL,), 0, 24),
}

DEFAULTS = Params()


def tipo_de(clave):
    """Tipo python del parametro (int, float o bool) segun el valor por defecto."""
    return type(getattr(DEFAULTS, clave))


def convertir(clave, valor):
    """Convierte un valor de texto/numero al tipo del parametro."""
    t = tipo_de(clave)
    if t is bool:
        if isinstance(valor, str):
            return valor.strip().lower() in ('1', 'true', 'si', 'sí', 'yes', 'on')
        return bool(valor)
    if isinstance(valor, str):
        valor = valor.replace(',', '.').strip()
    return t(float(valor)) if t is int else t(valor)


def validar(clave, valor):
    """Devuelve el valor convertido o lanza ValueError con un mensaje legible."""
    if clave not in CATALOGO:
        raise ValueError(f'Parametro desconocido: {clave}')
    etiqueta, _, minimo, maximo = CATALOGO[clave]
    try:
        v = convertir(clave, valor)
    except (TypeError, ValueError):
        raise ValueError(f'{etiqueta}: "{valor}" no es un numero valido')
    if not isinstance(v, bool) and not (minimo <= v <= maximo):
        raise ValueError(f'{etiqueta}: {v} fuera de rango ({minimo} a {maximo})')
    return v


def con_valores(base, valores):
    """Params nuevo con los valores dados (dict clave -> valor ya convertido)."""
    validos = {f.name for f in fields(Params)}
    return replace(base, **{k: v for k, v in valores.items() if k in validos})
