"""Subnavegacion de la Calculadora: (url, etiqueta, icono, url_names que la marcan activa)."""

SUBNAV = [
    ('panel', 'Hoy', 'fa-house', ('panel',)),
    ('grilla', 'Compras', 'fa-table-list', ('grilla', 'articulo')),
    ('analizar', 'Analizar', 'fa-magnifying-glass-chart', ('analizar',)),
    ('solicitudes', 'Solicitudes', 'fa-file-invoice-dollar', ('solicitudes', 'solicitud_detalle')),
    ('bodegas', 'Bodegas', 'fa-warehouse', ('bodegas',)),
    ('traslados', 'Traslados', 'fa-truck-ramp-box', ('traslados',)),
    ('compromisos', 'Compromisos', 'fa-hourglass-half', ('compromisos',)),
    ('alertas', 'Alertas', 'fa-bell', ('alertas',)),
    ('segmentacion', 'Segmentación', 'fa-table-cells', ('segmentacion',)),
    ('indicadores', 'Indicadores', 'fa-chart-column', ('indicadores',)),
    ('eventos', 'Eventos', 'fa-bullhorn', ('eventos',)),
    ('parametros', 'Parámetros', 'fa-sliders', ('parametros',)),
    ('proveedores', 'Proveedores', 'fa-calendar-days', ('proveedores',)),
    ('guia', 'Guía', 'fa-circle-question', ('guia',)),
]


def calculadora(request):
    match = getattr(request, 'resolver_match', None)
    if not match or match.app_name != 'calculadora':
        return {}
    return {'calc_subnav': SUBNAV}
