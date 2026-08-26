from django.db import models


class StockActual(models.Model):
    """
    Stock físico actual de bodegas cargado desde SAP.
    Estructura idéntica al sistema sistemaPedidosPesco (repo: CiroCortes/sistemaPedidosPesco).
    Incluye precio unitario y valorización total — fuente de costos USD para el sistema S&OP.
    """
    codigo = models.CharField(max_length=50, db_index=True, verbose_name="Código Material")
    descripcion = models.TextField(null=True, blank=True, verbose_name="Descripción")
    cod_grupo = models.IntegerField(null=True, blank=True, verbose_name="Código Grupo")
    descripcion_grupo = models.CharField(max_length=200, null=True, blank=True, verbose_name="Grupo Artículo")
    bodega = models.CharField(max_length=20, db_index=True, verbose_name="Código Bodega")
    bodega_nombre = models.CharField(max_length=200, null=True, blank=True, verbose_name="Nombre Bodega")
    ubicacion = models.CharField(max_length=100, null=True, blank=True, verbose_name="Ubicación")
    ubicacion_2 = models.CharField(max_length=100, null=True, blank=True, verbose_name="Ubicación 2")
    stock_disponible = models.IntegerField(default=0, verbose_name="Stock Disponible")
    stock_reservado = models.IntegerField(default=0, verbose_name="Stock Reservado")
    precio = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, verbose_name="Precio Unitario $")
    total = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True, verbose_name="Valorización Total $")
    categoria = models.CharField(max_length=100, null=True, blank=True, verbose_name="Categoría")
    ultima_actualizacion = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Stock Actual de Bodega"
        verbose_name_plural = "Stock Actual de Bodegas"
        ordering = ['codigo', 'bodega']
        indexes = [
            models.Index(fields=['codigo', 'bodega']),
            models.Index(fields=['bodega']),
            models.Index(fields=['precio']),
        ]

    def __str__(self):
        return f"{self.codigo} @ {self.bodega} | Stock: {self.stock_disponible}"


class CargaStockActual(models.Model):
    """Historial de cargas del archivo de stock actual de bodegas."""
    ESTADO_CHOICES = [
        ('procesando', 'Procesando'),
        ('completado', 'Completado'),
        ('error', 'Error'),
    ]
    fecha_carga = models.DateTimeField(auto_now_add=True)
    usuario = models.ForeignKey(
        'auth.User', null=True, blank=True,
        on_delete=models.SET_NULL, verbose_name="Usuario"
    )
    nombre_archivo = models.CharField(max_length=255, null=True, blank=True)
    total_productos = models.IntegerField(null=True, blank=True)
    total_bodegas = models.IntegerField(null=True, blank=True)
    total_registros = models.IntegerField(null=True, blank=True)
    estado = models.CharField(max_length=20, choices=ESTADO_CHOICES, default='procesando')
    mensaje_error = models.TextField(null=True, blank=True)
    tiempo_proceso = models.FloatField(null=True, blank=True, verbose_name="Segundos de Proceso")

    class Meta:
        verbose_name = "Carga de Stock Actual"
        verbose_name_plural = "Historial de Cargas de Stock Actual"
        ordering = ['-fecha_carga']

    def __str__(self):
        return f"Carga #{self.pk} — {self.fecha_carga:%Y-%m-%d %H:%M} ({self.estado})"
