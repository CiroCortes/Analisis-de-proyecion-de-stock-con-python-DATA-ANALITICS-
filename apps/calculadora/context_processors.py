"""Subnavegacion de la Calculadora: (url, etiqueta, icono, url_names activas, descripcion breve)."""

SUBNAV = [
    ('panel', 'Hoy', 'fa-house', ('panel',),
     'Resumen ejecutivo del día: qué comprar hoy, urgencias, quiebres y traslados.'),
    ('grilla', 'Compras', 'fa-table-list', ('grilla', 'articulo'),
     'Grilla completa de artículos con stock, consumo, punto de pedido y compra sugerida.'),
    ('analizar', 'Analizar', 'fa-magnifying-glass-chart', ('analizar',),
     'Simulador de un SKU: proyección día a día, memoria de cálculo y ajuste manual.'),
    ('solicitudes', 'Solicitudes', 'fa-file-invoice-dollar', ('solicitudes', 'solicitud_detalle'),
     'Órdenes de compra sugeridas por proveedor para revisar, aprobar y exportar.'),
    ('bodegas', 'Bodegas', 'fa-warehouse', ('bodegas',),
     'Estado de inventario y coberturas desglosado por cada sucursal de la red.'),
    ('traslados', 'Traslados', 'fa-truck-ramp-box', ('traslados',),
     'Movimientos de stock sugeridos desde Santiago hacia sucursales con déficit.'),
    ('compromisos', 'Compromisos', 'fa-hourglass-half', ('compromisos',),
     'Pedidos de clientes (PC) y órdenes de fabricación (OF) abiertos y su antigüedad.'),
    ('alertas', 'Alertas', 'fa-bell', ('alertas',),
     'Avisos de quiebres inminentes, órdenes atrasadas y alzas de consumo.'),
    ('segmentacion', 'Segmentación', 'fa-table-cells', ('segmentacion',),
     'Clasificación de artículos por rotación (REPO), valor (ABC) y variabilidad (XYZ).'),
    ('abc_venta', 'ABC venta', 'fa-sack-dollar', ('abc_venta',),
     'Ranking de artículos según su peso en ventas y consumo valorizado.'),
    ('marcas', 'Marcas', 'fa-tags', ('marcas',),
     'Gestión de marcas y líneas excluidas o planificadas por gerencia.'),
    ('indicadores', 'Indicadores', 'fa-chart-column', ('indicadores',),
     'KPIs de abastecimiento, quiebre real, cobertura y comparación entre escenarios.'),
    ('eventos', 'Eventos', 'fa-bullhorn', ('eventos',),
     'Picos de demanda o eventos comerciales registrados para ajustar la proyección.'),
    ('parametros', 'Parámetros', 'fa-sliders', ('parametros',),
     'Reglas del modelo: meses de stock de seguridad, cobertura objetivo y tolerancias.'),
    ('proveedores', 'Proveedores', 'fa-calendar-days', ('proveedores',),
     'Calendario de compra por proveedor y días asignados de emisión de OC.'),
    ('guia', 'Guía', 'fa-circle-question', ('guia',),
     'Glosario de términos, fórmulas y criterios usados en toda la plataforma.'),
]


def calculadora(request):
    match = getattr(request, 'resolver_match', None)
    if not match or match.app_name != 'calculadora':
        return {}
    return {'calc_subnav': SUBNAV}
