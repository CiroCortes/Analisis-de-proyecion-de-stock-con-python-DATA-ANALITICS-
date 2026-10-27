from django.urls import path

from . import views_fusion as fu
from . import views_gestion as g
from . import views_planificacion as v

app_name = 'calculadora'

urlpatterns = [
    # Planificacion (SPEC-18 §4.1): panel, grilla, detalle de articulo, indicadores
    path('', v.panel, name='panel'),
    path('correr/', v.correr, name='correr'),
    path('grilla/', v.grilla, name='grilla'),
    path('grilla/excel/', v.grilla_excel, name='grilla_excel'),
    path('articulo/<str:code>/', v.articulo, name='articulo'),
    path('articulo/<str:code>/config/', v.articulo_config, name='articulo_config'),
    path('indicadores/', v.indicadores, name='indicadores'),

    # Gestion (SPEC-18 §4.2): solicitudes, traslados, alertas, eventos, parametros, proveedores
    path('solicitudes/', g.solicitudes, name='solicitudes'),
    path('solicitudes/generar/', g.solicitudes_generar, name='solicitudes_generar'),
    path('solicitudes/exportar/', g.solicitudes_exportar, name='solicitudes_exportar'),
    path('solicitudes/<int:pk>/', g.solicitud_detalle, name='solicitud_detalle'),
    path('solicitudes/<int:pk>/linea/<int:lpk>/', g.solicitud_linea, name='solicitud_linea'),
    path('solicitudes/<int:pk>/aprobar/', g.solicitud_aprobar, name='solicitud_aprobar'),
    path('solicitudes/<int:pk>/descartar/', g.solicitud_descartar, name='solicitud_descartar'),
    path('traslados/', g.traslados, name='traslados'),
    path('traslados/excel/', g.traslados_excel, name='traslados_excel'),
    path('alertas/', g.alertas, name='alertas'),
    path('alertas/<int:pk>/', g.alerta_actualizar, name='alerta_actualizar'),
    path('eventos/', g.eventos, name='eventos'),
    path('eventos/<int:pk>/estado/', g.evento_estado, name='evento_estado'),
    path('parametros/', g.parametros, name='parametros'),
    path('parametros/simular/', g.parametros_simular, name='parametros_simular'),
    path('parametros/historial/excel/', g.parametros_historial_excel, name='parametros_historial_excel'),
    path('proveedores/', g.proveedores, name='proveedores'),

    # Fusion del Recomendador (SPEC-19): bodegas y zonas, segmentacion ABC-XYZ, guia
    path('bodegas/', fu.bodegas, name='bodegas'),
    path('bodegas/excel/', fu.bodegas_excel, name='bodegas_excel'),
    path('segmentacion/', fu.segmentacion, name='segmentacion'),
    path('guia/', fu.guia, name='guia'),
]
