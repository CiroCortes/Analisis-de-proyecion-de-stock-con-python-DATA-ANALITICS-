"""Bodegas operativas oficiales del S&OP (5 de Santiago y 5 sucursales)."""

WAREHOUSE_NAMES = {
    '013-PP': '013-PP - Pañol Producción Stgo',
    '013-PS': '013-PS - Pañol Servicios Stgo',
    '013-07': '013-07 - Stgo Ambulancia',
    '013-09': '013-09 - Stgo Semiremolque',
    '013-03': '013-03 - Stgo Emergencias / Rescate',
    '002-02': '002-02 - Sucursal Antofagasta',
    '002': '002 - Sucursal Calama',
    '003': '003 - Sucursal Copiapó',
    '008': '008 - Sucursal Los Ángeles',
    '010': '010 - Sucursal Puerto Montt',
}

ALLOWED_WAREHOUSES = list(WAREHOUSE_NAMES.keys())


# ── Zonas: Santiago (013-xx fisicas) y Sucursales regionales ─────────────────
import re

SANTIAGO = 'SANTIAGO'
SUCURSAL = 'SUCURSAL'
ZONE_LABELS = {SANTIAGO: 'Santiago', SUCURSAL: 'Sucursales'}

SUCURSAL_CITIES = {
    '002': 'Calama',
    '002-02': 'Antofagasta',
    '003': 'Copiapó',
    '008': 'Los Ángeles',
    '010': 'Puerto Montt',
}
SUCURSAL_CODES = list(SUCURSAL_CITIES.keys())

# Bodegas que no son fisicas: no se auditan ni mueven stock en el S&OP
#   - TRANSITO: 013 (a secas, paso previo al despacho) y T013-002, T002-013... (en camino)
#   - NO_CONFORME: 013-NC / 013-NC_E
#   - CONSIGNACION: 96x y 1xx (100, 101-106, 110...)
_TRANSITO_RE = re.compile(r'^(013|T(\d{3})-(\d{3}))$')
_NO_CONFORME_RE = re.compile(r'^013-NC(_E)?$')
_CONSIGNACION_RE = re.compile(r'^(96\d|1\d\d)$')
KIND_LABELS = {'TRANSITO': 'En tránsito', 'NO_CONFORME': 'No conforme', 'CONSIGNACION': 'Consignación'}

# En los codigos de transito Antofagasta figura como 022; la bodega real es 002-02.
# Santiago (013) se acredita a la bodega central 013-PP.
_TRANSIT_DEST = {'022': '002-02', '013': '013-PP'}


def kind_for(code):
    """'' si es fisica; si no, TRANSITO / NO_CONFORME / CONSIGNACION."""
    code = (code or '').upper()
    if _TRANSITO_RE.match(code):
        return 'TRANSITO'
    if _NO_CONFORME_RE.match(code):
        return 'NO_CONFORME'
    if _CONSIGNACION_RE.match(code):
        return 'CONSIGNACION'
    return ''


def is_physical(code):
    return not kind_for(code)


def transit_destination(code):
    """Bodega destino de una bodega de transito T<origen>-<destino>; None si no aplica."""
    m = _TRANSITO_RE.match((code or '').upper())
    if not m or not m.group(2):
        return None
    dest = m.group(3)
    return _TRANSIT_DEST.get(dest, dest)


def zone_for(code):
    """SANTIAGO, SUCURSAL o '' (bodegas fuera de ambas zonas o no fisicas)."""
    code = (code or '').upper()
    if not is_physical(code):
        return ''
    if code == '013' or code.startswith('013-'):
        return SANTIAGO
    if code in SUCURSAL_CITIES:
        return SUCURSAL
    return ''


def city_for(code):
    zone = zone_for(code)
    if zone == SANTIAGO:
        return 'Santiago'
    return SUCURSAL_CITIES.get((code or '').upper(), '')


# La bodega de una linea de OF/PC no es confiable: quien crea la OF muchas veces no indica
# de que almacen sacar (queda la 013 de posteo o una de consignacion) y a veces se edita.
# Regla: una salida solo se atribuye a una bodega especifica si es una bodega fisica con
# zona (013-xx o una sucursal); cualquier otra (013, consignacion, etc.) cuenta como
# demanda de Santiago y se asigna a la bodega central 013-PP.
def commitment_bodega(code):
    return code if zone_for(code) else '013-PP'


# OC y SC de Santiago se postean en la 013 a secas (o sin bodega): la compra de la red se
# recibe en la central, asi que se acreditan a 013-PP. Antes del 27-oct se perdian
# (~1.061 lineas de OC y ~450 de SC). Las demas bodegas sin zona no se tocan.
def purchase_bodega(code):
    code = (code or '').strip().upper()
    if code in ('', '013'):
        return '013-PP'
    return prebodega_destino(code) or code


# Pre-bodegas de importacion (SPEC-22 §2): lo que se compra o llega a una pre-bodega va en
# camino a su sucursal. Antes no se acreditaba a ningun nodo.
PRE_BODEGAS = {'000': '013-PP', '000-002': '002', '000-003': '003', '000-008': '008',
               '000-010': '010', '000-022': '002-02'}


def prebodega_destino(code):
    """Bodega destino de una pre-bodega 000-xxx; None si no es pre-bodega."""
    return PRE_BODEGAS.get((code or '').strip().upper())


# Nodos de la Calculadora (SPEC-21): Santiago es un solo stock (todas las 013-xx, la 013 y lo
# que se atribuye a Santiago, como consignacion); cada sucursal es su propio nodo.
NODO_SANTIAGO = '013'


def nodo_red(code):
    """NODO_SANTIAGO, el codigo de la sucursal o '' si la bodega no pertenece a la red."""
    code = commitment_bodega((code or '').strip().upper())
    zona = zone_for(code)
    if zona == SANTIAGO:
        return NODO_SANTIAGO
    return code if zona == SUCURSAL else ''


def zona_red(code):
    """Zona de una bodega o del nodo Santiago (la 013 no es fisica para zone_for)."""
    return SANTIAGO if (code or '').upper() == NODO_SANTIAGO else zone_for(code)


# ── Tratamiento del stock de cada bodega en el calculo (SPEC-27) ─────────────
# STOCK: disponible en un nodo de la red. TRANSITO: va en camino a un nodo. NO_CUENTA: no esta
# disponible para abastecer. Las bodegas de la red (013-xx y sucursales) siguen con el switch
# de auditoria (is_active); las demas pueden cambiar su tratamiento en Configuracion.
STOCK, TRANSITO, NO_CUENTA = 'STOCK', 'TRANSITO', 'NO_CUENTA'
TRATAMIENTOS = [(STOCK, 'Stock disponible'), (TRANSITO, 'En camino'), (NO_CUENTA, 'No cuenta')]

# Motivos de las bodegas que no cuentan, acordados con Distribucion y Cobranzas (29-oct-2026)
_MOTIVOS_NO_CUENTA = [
    (_NO_CONFORME_RE, 'Notas de crédito de Cobranzas (facturas rechazadas): stock contable, el repuesto está con el cliente'),
    (re.compile(r'^0EX$'), 'Exportación: ya vendido, espera la factura de COMEX'),
    (_CONSIGNACION_RE, 'Consignación en el cliente: no disponible (su consumo sí es demanda de Santiago)'),
    (re.compile(r'^95\d$'), 'Consignación en el cliente: no disponible (su consumo sí es demanda de Santiago)'),
    (re.compile(r'^90\d$'), 'Equipos de demostración'),
    (re.compile(r'^710$'), 'Repuestos en garantía'),
    (re.compile(r'^85\d$'), 'Proveedores o bodegas externas'),
    (re.compile(r'^99\d$'), 'Equipos en desarme'),
]


def nodos_red():
    """[(codigo, nombre)] de los nodos de la Calculadora: Santiago y cada sucursal."""
    return [(NODO_SANTIAGO, 'Santiago')] + list(SUCURSAL_CITIES.items())


def nombre_nodo(nodo):
    return dict(nodos_red()).get(nodo, nodo or '')


def tratamiento_por_defecto(code, is_active=True):
    """(tipo, nodo, motivo) que aplica el calculo a una bodega sin configuracion manual."""
    code = (code or '').strip().upper()
    if code == NODO_SANTIAGO:
        return STOCK, NODO_SANTIAGO, 'Bodega de paso de Santiago: llegadas de regiones y despacho de PC'
    destino = transit_destination(code) or prebodega_destino(code)
    if destino:
        tipo = 'Pre-bodega de importación' if prebodega_destino(code) else 'Traslado en camino'
        return TRANSITO, nodo_red(destino), f'{tipo} hacia {nombre_nodo(nodo_red(destino))}'
    zona = zone_for(code)
    if zona:
        if is_active:
            return STOCK, nodo_red(code), 'Bodega de la red'
        return NO_CUENTA, nodo_red(code), 'Bodega de la red excluida en Configuración'
    for patron, motivo in _MOTIVOS_NO_CUENTA:
        if patron.match(code):
            return NO_CUENTA, '', motivo
    return NO_CUENTA, '', 'Fuera de la red de abastecimiento'


def es_bodega_de_red(code):
    """013-xx fisicas y sucursales: su tratamiento se define con el switch de auditoria."""
    return bool(zone_for(code))
