"""Clasificacion de los grupos de articulos SAP (oitb) en tipos de material.

El tipo define la recomendacion de alcance S&OP: que grupos se abastecen
(repuestos, accesorios, panol, materiales de produccion) y cuales se excluyen
(equipos terminados, servicios y gastos). Se asigna al cargar el maestro y se
puede aplicar de nuevo desde Configuracion > Grupos.
"""
import re

REPUESTO, ACCESORIO, PANOL, PRODUCCION, REVISAR, EQUIPO, SERVICIO = (
    'REPUESTO', 'ACCESORIO', 'PANOL', 'PRODUCCION', 'REVISAR', 'EQUIPO', 'SERVICIO')

# tipo -> (etiqueta, se_abastece, explicacion)
TIPOS = {
    REPUESTO:   ('Repuestos', True, 'Repuestos de equipos; se reponen con compras.'),
    ACCESORIO:  ('Accesorios', True, 'Accesorios de equipos; se reponen con compras.'),
    PANOL:      ('Pañol / Insumos', True, 'Herramientas, EPP e insumos de consumo.'),
    PRODUCCION: ('Materiales de producción', True, 'Materiales que consumen las OF de fabricación.'),
    REVISAR:    ('Por revisar', True, 'Grupo mixto o no reconocido: se deja activo hasta que lo decidas.'),
    EQUIPO:     ('Equipos y venta', False, 'Equipos terminados o de venta; se fabrican o venden, no se abastecen.'),
    SERVICIO:   ('Servicios y gastos', False, 'Servicios, gastos, activos y provisiones; no son inventario.'),
}
TIPO_CHOICES = [(k, v[0]) for k, v in TIPOS.items()]

_SERVICIO_KW = (
    'SERVIC', 'SERV.', 'GARANT', 'ARRIENDO', 'GASTO', 'HONORARIO', 'PROVISION',
    'ACTIVO FIJO', 'RECUP', 'PATENTE', 'CHATARRA', 'OT EN PROCESO', 'PRE-ENTREGA',
    'PREPARAC', 'MEJORAS', 'FACTURACION', 'CONSIGNACION', 'DESARMES',
    'ARTICULOS OFICINA', 'ARTICULOS PUBLICIDAD', 'ARTICULOS MANTENCION',
)
_SERVICIO_RE = re.compile(r'^(MOD|MOI)\b')
_EQUIPO_PREFIX = ('EQUIPOS ', 'CAMIONES', 'VEHICULOS', 'CONTENEDORES', 'RETAIL')
_PANOL_RE = re.compile(r'^PA.OL|^MAT\. MENOR RHINOX|^HERRAMIENTAS|^TALLER')


def infer_tipo(name, service_ratio=0.0):
    """Tipo de material de un grupo SAP segun su nombre y la proporcion de SKUs
    que SAP marca como no inventariables (invntitem = 'N')."""
    n = (name or '').upper().strip()
    if service_ratio >= 0.8:
        return SERVICIO
    if any(k in n for k in _SERVICIO_KW) or _SERVICIO_RE.match(n):
        return SERVICIO
    if n.startswith(_EQUIPO_PREFIX):
        return EQUIPO
    if n.startswith('RPTS'):
        return REPUESTO
    if n.startswith('ACCESORIO'):
        return ACCESORIO
    if _PANOL_RE.match(n):
        return PANOL
    if 'AMBULANCIAS' in n or n == 'HIDRAULICA':
        return PRODUCCION
    return REVISAR


def se_abastece(tipo):
    return TIPOS.get(tipo, TIPOS[REVISAR])[1]


def assign_group_types(force=False):
    """Asigna tipo a los grupos sin tipo (o a todos con force=True).
    A los grupos que reciben tipo por primera vez tambien les fija el estado
    recomendado; los ya clasificados conservan lo que decidio el usuario."""
    from django.db.models import Count, Q
    from apps.inventory.models import Category

    updated = 0
    qs = Category.objects.annotate(
        n=Count('productsku'),
        n_serv=Count('productsku', filter=Q(productsku__gestiona_inventario=False)),
    )
    for c in qs:
        if c.tipo and not force:
            continue
        tipo = infer_tipo(c.name, (c.n_serv / c.n) if c.n else 0.0)
        c.tipo = tipo
        c.is_active = se_abastece(tipo)
        c.save(update_fields=['tipo', 'is_active'])
        updated += 1
    return updated
