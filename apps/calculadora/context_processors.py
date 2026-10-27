"""Subnavegacion de la Calculadora: (url, etiqueta, icono, url_names que la marcan activa)."""

SUBNAV = [
    ('panel', 'Panel', 'fa-gauge-high', ('panel',)),
    ('grilla', 'Grilla de compras', 'fa-table-list', ('grilla', 'articulo')),
    ('solicitudes', 'Solicitudes', 'fa-file-invoice-dollar', ('solicitudes', 'solicitud_detalle')),
    ('traslados', 'Traslados', 'fa-truck-ramp-box', ('traslados',)),
    ('alertas', 'Alertas', 'fa-bell', ('alertas',)),
    ('eventos', 'Eventos comerciales', 'fa-bullhorn', ('eventos',)),
    ('indicadores', 'Indicadores', 'fa-chart-column', ('indicadores',)),
    ('parametros', 'Parámetros', 'fa-sliders', ('parametros',)),
    ('proveedores', 'Proveedores', 'fa-calendar-days', ('proveedores',)),
]


def calculadora(request):
    match = getattr(request, 'resolver_match', None)
    if not match or match.app_name != 'calculadora':
        return {}
    return {'calc_subnav': SUBNAV}
