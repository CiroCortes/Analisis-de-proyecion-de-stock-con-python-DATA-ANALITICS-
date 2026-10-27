from django.contrib import admin

from . import models


@admin.register(models.Proveedor)
class ProveedorAdmin(admin.ModelAdmin):
    list_display = ('codigo', 'nombre', 'pais', 'frecuencia_compra_dias', 'fecha_ancla', 'comprador')
    search_fields = ('codigo', 'nombre')


@admin.register(models.ArticuloConfig)
class ArticuloConfigAdmin(admin.ModelAdmin):
    list_display = ('product', 'es_estrategico', 'minimo_declarado', 'es_critico', 'minimo_nuevo', 'proveedor')
    search_fields = ('product__code', 'product__description')
    raw_id_fields = ('product',)


@admin.register(models.Equivalencia)
class EquivalenciaAdmin(admin.ModelAdmin):
    list_display = ('codigo_antiguo', 'codigo_nuevo', 'creado_en')
    search_fields = ('codigo_antiguo', 'codigo_nuevo')


@admin.register(models.CargaDatos)
class CargaDatosAdmin(admin.ModelAdmin):
    list_display = ('tabla', 'archivo', 'filas', 'fuente', 'cargado_en', 'nota')


@admin.register(models.Corrida)
class CorridaAdmin(admin.ModelAdmin):
    list_display = ('pk', 'inicio', 'fin', 'fecha_calculo', 'estado', 'fuente_consumo', 'usuario')


@admin.register(models.ParametroCambio)
class ParametroCambioAdmin(admin.ModelAdmin):
    list_display = ('fecha', 'clave', 'nivel', 'ambito', 'valor_anterior', 'valor_nuevo', 'usuario')
