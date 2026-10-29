from django.urls import path
from . import views

app_name = 'dashboard'

urlpatterns = [
    path('', views.dashboard_home_view, name='home'),
    path('analytics/', views.analytics_view, name='analytics'),   # redirige al Panel S&OP (SPEC-28)
    # Vista Reporte Ejecutivo Gerencial (Fase 3 — Gisella)
    path('gerencial/', views.executive_report_view, name='executive_report'),
    # Chart.js API endpoints — Reporte Gerencial (Fase 3)
    path('api/gerencial/disponibilidad/', views.api_disponibilidad_historica, name='api_disponibilidad'),
    path('api/gerencial/inventario/', views.api_inventario_historico, name='api_inventario'),
    path('api/gerencial/quiebres-dias/', views.api_quiebres_por_dias, name='api_quiebres_dias'),
    path('api/gerencial/materiales-pedido-tendencia/', views.api_materiales_pedido_tendencia, name='api_pedido_tendencia'),
]
