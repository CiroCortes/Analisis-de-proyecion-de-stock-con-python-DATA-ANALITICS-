from django.urls import path
from . import views

app_name = 'dashboard'

urlpatterns = [
    path('', views.dashboard_home_view, name='home'),
    path('analytics/', views.analytics_view, name='analytics'),
    # Vista Reporte Ejecutivo Gerencial (Fase 3 — Gisella)
    path('gerencial/', views.executive_report_view, name='executive_report'),
    # Chart.js API endpoints — Existentes
    path('api/charts/urgency-distribution/', views.api_chart_urgency_distribution, name='api_urgency_distribution'),
    path('api/charts/shortage-usd-by-warehouse/', views.api_chart_shortage_usd_by_warehouse, name='api_shortage_usd_warehouse'),
    path('api/charts/top-shortage-skus/', views.api_chart_top_shortage_skus, name='api_top_shortage_skus'),
    path('api/charts/coverage-histogram/', views.api_chart_coverage_histogram, name='api_coverage_histogram'),
    path('api/charts/risk-matrix/', views.api_chart_risk_matrix, name='api_risk_matrix'),
    # Chart.js API endpoints — Reporte Gerencial (Fase 3)
    path('api/gerencial/disponibilidad/', views.api_disponibilidad_historica, name='api_disponibilidad'),
    path('api/gerencial/inventario/', views.api_inventario_historico, name='api_inventario'),
    path('api/gerencial/quiebres-dias/', views.api_quiebres_por_dias, name='api_quiebres_dias'),
    path('api/gerencial/materiales-pedido-tendencia/', views.api_materiales_pedido_tendencia, name='api_pedido_tendencia'),
]
