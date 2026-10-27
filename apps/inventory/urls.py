from django.urls import path
from . import views

app_name = 'inventory'

urlpatterns = [
    path('sku/<str:code>/', views.sku_detail_view, name='sku_detail'),
    # Stock Actual de Bodegas SAP
    path('stock-actual/', views.cargar_stock_actual, name='cargar_stock_actual'),
    path('stock-actual/consultar/', views.consultar_stock_actual, name='consultar_stock_actual'),
    # Centro Maestro de Configuración S&OP (Bodegas, Grupos y Parámetros)
    path('configuracion/', views.configuracion_view, name='configuracion'),
    path('configurar-grupos/', views.configuracion_view, name='configurar_grupos'),
]
