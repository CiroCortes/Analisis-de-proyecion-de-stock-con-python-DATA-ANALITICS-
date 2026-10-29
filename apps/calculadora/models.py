"""Modelos de la Calculadora de Compras (SPEC-08 a SPEC-16).

Datos de origen (cargados desde el Datalake), configuracion editable por Abastecimiento,
resultados de la ultima corrida (se recalculan desde cero en cada ejecucion) e historia
mensual (clasificacion y valor del stock maximo, para alertas e impacto).
"""
from django.conf import settings
from django.db import models

from apps.inventory.models import ProductSKU, Warehouse


# ── Datos de origen ───────────────────────────────────────────────────────────

class Proveedor(models.Model):
    codigo = models.CharField(max_length=30, primary_key=True)
    nombre = models.CharField(max_length=200, blank=True, default='')
    pais = models.CharField(max_length=5, blank=True, default='')
    congelado = models.BooleanField(default=False)
    # Calendario de compra (§4.6.1): vacio = valores generales y ancla repartida por codigo
    frecuencia_compra_dias = models.PositiveIntegerField(null=True, blank=True)
    fecha_ancla = models.DateField(null=True, blank=True, help_text='Un dia de compra; los siguientes cada frecuencia')
    comprador = models.CharField(max_length=100, blank=True, default='')

    class Meta:
        verbose_name = 'Proveedor'
        verbose_name_plural = 'Proveedores'

    @property
    def es_importado(self):
        return bool(self.pais) and self.pais.upper() != 'CL'

    def __str__(self):
        return f'{self.codigo} - {self.nombre}'


class ConsumoMensual(models.Model):
    """Consumo por articulo, bodega y mes cerrado (consulta 8, o reconstruido de PC/OF)."""
    VENTA, OF, SALIDA = 'VENTA', 'OF', 'SALIDA'
    ORIGEN_CHOICES = [(VENTA, 'Venta / entrega'), (OF, 'Consumo de OF'), (SALIDA, 'Otra salida')]

    product = models.ForeignKey(ProductSKU, on_delete=models.CASCADE, related_name='consumos_mensuales')
    bodega = models.CharField(max_length=20, db_index=True)
    mes = models.DateField(db_index=True, help_text='Primer dia del mes')
    origen = models.CharField(max_length=10, choices=ORIGEN_CHOICES, default=VENTA)
    cantidad = models.FloatField(default=0)

    class Meta:
        unique_together = ('product', 'bodega', 'mes', 'origen')
        indexes = [models.Index(fields=['product', 'mes'])]


class PlazoOC(models.Model):
    """Una recepcion de una OC: dias de entrega reales (consulta 9)."""
    nro_oc = models.CharField(max_length=30)
    product = models.ForeignKey(ProductSKU, on_delete=models.CASCADE, related_name='plazos_oc')
    proveedor_codigo = models.CharField(max_length=30, blank=True, default='', db_index=True)
    fecha_oc = models.DateField(null=True)
    fecha_entrada = models.DateField(null=True)
    dias_entrega = models.IntegerField()

    class Meta:
        indexes = [models.Index(fields=['product', 'fecha_entrada'])]


class OCAbierta(models.Model):
    """Linea de OC con cantidad pendiente: transito con fecha para la proyeccion diaria."""
    nro_oc = models.CharField(max_length=30)
    product = models.ForeignKey(ProductSKU, on_delete=models.CASCADE, related_name='oc_abiertas')
    bodega = models.CharField(max_length=20)
    proveedor_codigo = models.CharField(max_length=30, blank=True, default='', db_index=True)
    fecha_oc = models.DateField(null=True)
    fecha_comprometida = models.DateField(null=True)
    cantidad_pendiente = models.FloatField(default=0)


class CompromisoAbierto(models.Model):
    """Linea de PC u OF abierta con su fecha (para la proyeccion y el reparto por fecha)."""
    PC, OF = 'PC', 'OF'
    product = models.ForeignKey(ProductSKU, on_delete=models.CASCADE, related_name='compromisos_abiertos')
    tipo = models.CharField(max_length=2, choices=[(PC, 'Pedido de cliente'), (OF, 'Orden de fabricacion')])
    numero = models.CharField(max_length=30)
    bodega = models.CharField(max_length=20)
    fecha = models.DateField(null=True)
    fecha_emision = models.DateField(null=True, blank=True)   # nivel de servicio por mes de emision
    cantidad = models.FloatField(default=0)


class CompromisoDetalle(models.Model):
    """Linea de PC u OF abierta con responsable, cliente y referencia (consulta 16). Alimenta el
    informe de antiguedad de compromisos abiertos (SPEC-23 §3); el calculo usa CompromisoAbierto."""
    tipo = models.CharField(max_length=2, db_index=True)
    numero = models.CharField(max_length=30, db_index=True)
    codigo_sku = models.CharField(max_length=50, db_index=True)
    bodega = models.CharField(max_length=20, blank=True, default='')
    nodo = models.CharField(max_length=20, blank=True, default='', db_index=True)
    fecha_emision = models.DateField(null=True, db_index=True)
    fecha_entrega = models.DateField(null=True)
    codigo_cliente = models.CharField(max_length=30, blank=True, default='')
    nombre_cliente = models.CharField(max_length=200, blank=True, default='')
    responsable = models.CharField(max_length=120, blank=True, default='', db_index=True)
    referencia = models.CharField(max_length=100, blank=True, default='')
    cantidad = models.FloatField(default=0)
    costo_unitario = models.FloatField(default=0)


class ParametroCompra(models.Model):
    """Complemento del maestro (consulta 10): proveedor preferido, minimo y multiplo."""
    product = models.OneToOneField(ProductSKU, on_delete=models.CASCADE, primary_key=True,
                                   related_name='parametro_compra')
    proveedor_preferido = models.CharField(max_length=30, blank=True, default='')
    lead_time_maestro = models.IntegerField(default=0)
    min_compra = models.FloatField(default=0)
    multiplo_compra = models.FloatField(default=0)
    unidad_medida = models.CharField(max_length=20, blank=True, default='')
    bloqueado = models.BooleanField(default=False)


class AcuerdoGlobal(models.Model):
    """Linea de un acuerdo global (contrato) con proveedor (consulta 12)."""
    nro_acuerdo = models.CharField(max_length=30)
    linea = models.IntegerField(default=0)
    proveedor_codigo = models.CharField(max_length=30, db_index=True)
    product = models.ForeignKey(ProductSKU, on_delete=models.CASCADE, related_name='acuerdos')
    fecha_inicio = models.DateField(null=True)
    fecha_termino = models.DateField(null=True)
    estado = models.CharField(max_length=5, blank=True, default='')
    cantidad_plan = models.FloatField(default=0)
    cantidad_acumulada = models.FloatField(default=0)
    precio_unitario = models.FloatField(default=0)

    @property
    def saldo(self):
        return max(0.0, self.cantidad_plan - self.cantidad_acumulada) if self.cantidad_plan else None


class CargaDatos(models.Model):
    """Registro de cada archivo cargado: de donde salio cada dato y cuando."""
    tabla = models.CharField(max_length=60)
    archivo = models.CharField(max_length=255, blank=True, default='')
    filas = models.IntegerField(default=0)
    fuente = models.CharField(max_length=30, default='TXT')
    cargado_en = models.DateTimeField(auto_now_add=True)
    nota = models.CharField(max_length=255, blank=True, default='')

    class Meta:
        ordering = ['-cargado_en']


# ── Configuracion editable (Abastecimiento) ──────────────────────────────────

class ArticuloConfig(models.Model):
    """Marcas que declara el area usuaria por articulo (§3)."""
    product = models.OneToOneField(ProductSKU, on_delete=models.CASCADE, primary_key=True, related_name='config_calc')
    es_estrategico = models.BooleanField(default=False, verbose_name='Estrategico (E)')
    minimo_declarado = models.FloatField(default=0, verbose_name='Minimo declarado E')
    es_critico = models.BooleanField(default=False, verbose_name='Critico')
    minimo_nuevo = models.FloatField(default=0, verbose_name='Minimo manual articulo nuevo')
    proveedor = models.ForeignKey(Proveedor, null=True, blank=True, on_delete=models.SET_NULL,
                                  verbose_name='Proveedor (si difiere del preferido de SAP)')
    nota = models.CharField(max_length=255, blank=True, default='')
    actualizado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    actualizado_en = models.DateTimeField(auto_now=True)


class Equivalencia(models.Model):
    """Articulo reemplazado: la historia del codigo antiguo se suma al nuevo (§9)."""
    codigo_antiguo = models.CharField(max_length=100, unique=True)
    codigo_nuevo = models.CharField(max_length=100, db_index=True)
    creado_en = models.DateTimeField(auto_now_add=True)


class ParametroValor(models.Model):
    """Valor de un parametro en un nivel. GENERAL no lleva ambito; los demas, el codigo
    de familia, proveedor, articulo o bodega. Manda el mas especifico (§7)."""
    clave = models.CharField(max_length=60)
    nivel = models.CharField(max_length=10, default='GENERAL')
    ambito = models.CharField(max_length=100, blank=True, default='')
    valor = models.CharField(max_length=60)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('clave', 'nivel', 'ambito')


class ParametroCambio(models.Model):
    """Registro de cambios de parametros (§7): consultable y exportable."""
    clave = models.CharField(max_length=60)
    nivel = models.CharField(max_length=10)
    ambito = models.CharField(max_length=100, blank=True, default='')
    valor_anterior = models.CharField(max_length=60, blank=True, default='')
    valor_nuevo = models.CharField(max_length=60, blank=True, default='')
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    fecha = models.DateTimeField(auto_now_add=True)
    motivo = models.CharField(max_length=255, blank=True, default='')

    class Meta:
        ordering = ['-fecha']


class EventoComercial(models.Model):
    """Informacion comercial que cambia la demanda futura (§4.7)."""
    ALZA, BAJA, REEMPLAZO = 'ALZA', 'BAJA', 'REEMPLAZO'
    PROPUESTO, APROBADO, RECHAZADO = 'PROPUESTO', 'APROBADO', 'RECHAZADO'
    product = models.ForeignKey(ProductSKU, null=True, blank=True, on_delete=models.CASCADE, related_name='eventos')
    familia = models.CharField(max_length=100, blank=True, default='', help_text='Grupo SAP si aplica a una familia')
    bodega = models.CharField(max_length=20, blank=True, default='')
    tipo = models.CharField(max_length=10, choices=[(ALZA, 'Alza'), (BAJA, 'Baja'), (REEMPLAZO, 'Reemplazo')], default=ALZA)
    cantidad_adicional = models.FloatField(default=0, help_text='Unidades adicionales en todo el periodo')
    porcentaje = models.FloatField(default=0, help_text='% sobre el consumo promedio (alternativa a la cantidad)')
    mes_inicio = models.DateField()
    mes_fin = models.DateField()
    comentario = models.TextField(blank=True, default='')
    adjunto = models.FileField(upload_to='eventos/', blank=True, null=True)
    estado = models.CharField(max_length=10, default=PROPUESTO,
                              choices=[(PROPUESTO, 'Propuesto'), (APROBADO, 'Aprobado'), (RECHAZADO, 'Rechazado')])
    autor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='eventos_creados')
    aprobado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                     related_name='eventos_aprobados')
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-creado_en']

    @property
    def meses_vigencia(self):
        return (self.mes_fin.year - self.mes_inicio.year) * 12 + self.mes_fin.month - self.mes_inicio.month + 1


# ── Resultados de la corrida ─────────────────────────────────────────────────

class Corrida(models.Model):
    EN_CURSO, OK, ERROR = 'EN_CURSO', 'OK', 'ERROR'
    inicio = models.DateTimeField(auto_now_add=True)
    fin = models.DateTimeField(null=True, blank=True)
    fecha_calculo = models.DateField()
    estado = models.CharField(max_length=10, default=EN_CURSO)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    fuente_consumo = models.CharField(max_length=30, blank=True, default='')
    resumen = models.JSONField(default=dict)
    error = models.TextField(blank=True, default='')

    class Meta:
        ordering = ['-inicio']


class ResultadoArticulo(models.Model):
    """Calculo de la red para un articulo (ultima corrida). Campos = diccionario §4."""
    corrida = models.ForeignKey(Corrida, on_delete=models.CASCADE, related_name='resultados')
    product = models.OneToOneField(ProductSKU, on_delete=models.CASCADE, related_name='resultado_calc')
    proveedor = models.ForeignKey(Proveedor, null=True, blank=True, on_delete=models.SET_NULL)

    # Clasificacion
    letra = models.CharField(max_length=1, db_index=True)
    subclase = models.CharField(max_length=12, blank=True, default='')
    motivo_clasificacion = models.CharField(max_length=150, blank=True, default='')
    abc = models.CharField(max_length=1, db_index=True, default='C')
    xyz = models.CharField(max_length=1, db_index=True, default='Z', help_text='Variabilidad: X estable, Y variable, Z erratico')
    segmento = models.CharField(max_length=10, default='REPUESTOS')
    es_nuevo = models.BooleanField(default=False)
    es_inmovilizado = models.BooleanField(default=False)
    es_critico = models.BooleanField(default=False)
    nivel_servicio = models.FloatField(default=0)
    factor_servicio = models.FloatField(default=0)

    # Consumo
    consumo_meses = models.JSONField(default=list)
    meses_con_consumo_12m = models.IntegerField(default=0)
    consumo_promedio_mes = models.FloatField(default=0)
    consumo_ajustado_mes = models.FloatField(null=True, blank=True)
    consumo_diario = models.FloatField(default=0)
    variacion_consumo = models.FloatField(default=0)
    tope_mes_atipico = models.FloatField(default=0)
    meses_atipicos = models.JSONField(default=list)      # indices de consumo_meses recortados (SPEC-26)
    mediana_con_consumo = models.FloatField(default=0)
    mayor_consumo_mes = models.FloatField(default=0)
    valor_consumo_anual = models.FloatField(default=0)

    # Plazo
    dias_entrega_promedio = models.FloatField(default=0)
    variacion_entrega_dias = models.FloatField(default=0)
    plazo_total_dias = models.FloatField(default=0)
    origen_plazo = models.CharField(max_length=10, default='MAESTRO')
    n_oc = models.IntegerField(default=0)

    # Politica
    metodo = models.CharField(max_length=15, default='SIN_COMPRA')
    ss_calculado = models.FloatField(default=0)
    piso_ss = models.FloatField(default=0)
    stock_seguridad = models.IntegerField(default=0)
    punto_pedido = models.IntegerField(default=0)
    stock_maximo = models.IntegerField(default=0)
    salidas_en_plazo = models.IntegerField(default=0)

    # Posicion de la red
    stock_fisico = models.FloatField(default=0)
    en_transito = models.FloatField(default=0)
    comprometido = models.FloatField(default=0)
    disponible_futuro = models.FloatField(default=0, db_index=True)
    cobertura_dias = models.FloatField(null=True, blank=True)

    # Compra
    necesita_compra = models.BooleanField(default=False, db_index=True)
    comprar = models.BooleanField(default=False, db_index=True)
    faltante = models.FloatField(default=0)
    cantidad_sugerida = models.IntegerField(default=0)
    costo_unitario = models.FloatField(default=0)
    valor_sugerido = models.FloatField(default=0, db_index=True)
    urgencia = models.CharField(max_length=10, default='NORMAL', db_index=True)
    fecha_llegada_estimada = models.DateField(null=True, blank=True)
    valor_stock_maximo = models.FloatField(default=0)

    # Calendario y proyeccion
    proxima_fecha_compra = models.DateField(null=True, blank=True)
    es_dia_compra = models.BooleanField(default=False)
    fecha_quiebre_proyectada = models.DateField(null=True, blank=True, db_index=True)
    fecha_bajo_ss = models.DateField(null=True, blank=True)
    fecha_llegada_posible = models.DateField(null=True, blank=True)
    excepcion = models.BooleanField(default=False, db_index=True)
    causa_excepcion = models.CharField(max_length=15, blank=True, default='')
    cantidad_excepcion = models.IntegerField(default=0)
    dias_quiebre_inevitable = models.IntegerField(default=0)
    oc_atrasada = models.BooleanField(default=False)

    # Escenario actual (motor anterior: compra hasta el punto de pedido) para el panel de KPIs
    cantidad_actual = models.IntegerField(default=0)
    valor_actual = models.FloatField(default=0)
    # Simulacion a 12 meses de ambos escenarios (SPEC-15 §3): {'prop': {...}, 'act': {...}}
    simulacion = models.JSONField(default=dict)

    avisos = models.JSONField(default=list)

    # Calculo hibrido de compromisos (SPEC-23): unidades de PC/OF emitidos antes del corte y la
    # cantidad a comprar con la otra base (None si el articulo no tiene compromisos antiguos)
    comprometido_antiguo = models.FloatField(default=0)
    cantidad_otra_base = models.IntegerField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=['letra', 'urgencia']), models.Index(fields=['proveedor', 'comprar'])]

    @property
    def cantidad_a_comprar(self):
        if self.comprar:
            return self.cantidad_sugerida
        return self.cantidad_excepcion if self.excepcion else 0


class ResultadoBodega(models.Model):
    """Accion por nodo (§5, SPEC-21): Santiago (bodega 013) o una sucursal.
    TRASLADAR / TRASLADAR_PARCIAL / ESPERA_COMPRA / NINGUNA."""
    resultado = models.ForeignKey(ResultadoArticulo, on_delete=models.CASCADE, related_name='bodegas')
    warehouse = models.ForeignKey(Warehouse, on_delete=models.CASCADE)
    stock_fisico = models.FloatField(default=0)
    en_transito = models.FloatField(default=0)
    comprometido = models.FloatField(default=0)
    disponible_futuro = models.FloatField(default=0)
    objetivo = models.FloatField(default=0)
    faltante = models.FloatField(default=0)
    excedente = models.FloatField(default=0)
    accion = models.CharField(max_length=20, default='NINGUNA', db_index=True)
    cantidad_trasladar = models.FloatField(default=0)
    espera_compra = models.FloatField(default=0)
    origenes = models.JSONField(default=list)
    sucursales_con_stock = models.JSONField(default=list)
    urgencia = models.CharField(max_length=10, default='NORMAL')
    # Consumo y cobertura de la bodega (SPEC-19 §3.2): informan donde se acaba primero el stock
    consumo_diario = models.FloatField(default=0)
    cobertura_dias = models.FloatField(null=True, blank=True)
    # Proteccion simetrica y nodo Santiago (SPEC-21): lo que el nodo guarda para si, donde quedo
    # stock retenido que jefatura podria mover, y el stock por bodega 013-xx del nodo Santiago
    protegido = models.FloatField(default=0)
    retenido_en = models.JSONField(default=list)
    componentes = models.JSONField(default=list)


class TrasladoSugerido(models.Model):
    SUGERIDO, APROBADO, DESCARTADO = 'SUGERIDO', 'APROBADO', 'DESCARTADO'
    resultado = models.ForeignKey(ResultadoArticulo, on_delete=models.CASCADE, related_name='traslados')
    product = models.ForeignKey(ProductSKU, on_delete=models.CASCADE)
    origen = models.ForeignKey(Warehouse, on_delete=models.CASCADE, related_name='traslados_salida')
    destino = models.ForeignKey(Warehouse, on_delete=models.CASCADE, related_name='traslados_entrada')
    cantidad = models.FloatField()
    urgencia = models.CharField(max_length=10, default='NORMAL')
    estado = models.CharField(max_length=10, default=SUGERIDO)
    detalle_origen = models.JSONField(default=list)   # desde Santiago: [[bodega 013-xx, cantidad]]


class HistorialMensual(models.Model):
    """Foto mensual por articulo: clasificacion y valor del stock maximo (§3, §8 impacto)."""
    product = models.ForeignKey(ProductSKU, on_delete=models.CASCADE, related_name='historial_calc')
    mes = models.DateField(db_index=True)
    letra = models.CharField(max_length=1)
    subclase = models.CharField(max_length=12, blank=True, default='')
    abc = models.CharField(max_length=1, default='C')
    xyz = models.CharField(max_length=1, default='Z')
    letra_anterior = models.CharField(max_length=1, blank=True, default='')
    motivo = models.CharField(max_length=150, blank=True, default='')
    valor_stock_maximo = models.FloatField(default=0)
    stock_maximo = models.IntegerField(default=0)
    consumo_promedio_mes = models.FloatField(default=0)
    variacion_consumo = models.FloatField(default=0)

    class Meta:
        unique_together = ('product', 'mes')


class EscenarioActual(models.Model):
    """Resultado del motor anterior, guardado antes de que la Calculadora publique en
    StockProjection (SPEC-19 §2.1). Solo alimenta el panel "actual vs propuesto"."""
    product = models.ForeignKey(ProductSKU, on_delete=models.CASCADE, related_name='escenario_actual')
    bodega = models.CharField(max_length=20)
    rop = models.IntegerField(default=0)
    sugerido_compra = models.IntegerField(default=0)
    accion = models.CharField(max_length=15, default='NINGUNA')
    letra = models.CharField(max_length=1, blank=True, default='')
    capturado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=['product', 'bodega'])]


# ── Solicitudes de compra (§6) ───────────────────────────────────────────────

class SolicitudCompra(models.Model):
    BORRADOR, APROBADA, EXPORTADA, DESCARTADA = 'BORRADOR', 'APROBADA', 'EXPORTADA', 'DESCARTADA'
    CALENDARIO, EXCEPCION = 'CALENDARIO', 'EXCEPCION'
    proveedor = models.ForeignKey(Proveedor, null=True, on_delete=models.SET_NULL, related_name='solicitudes')
    bodega_entrega = models.CharField(max_length=20, default='013-PP')
    tipo = models.CharField(max_length=10, default=CALENDARIO,
                            choices=[(CALENDARIO, 'Dia de compra'), (EXCEPCION, 'Fuera de calendario')])
    estado = models.CharField(max_length=10, default=BORRADOR, db_index=True,
                              choices=[(BORRADOR, 'Pendiente'), (APROBADA, 'Aprobada'),
                                       (EXPORTADA, 'Exportada'), (DESCARTADA, 'Descartada')])
    fecha = models.DateField()
    creada_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name='solicitudes_creadas')
    aprobada_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                     related_name='solicitudes_aprobadas')
    aprobada_en = models.DateTimeField(null=True, blank=True)
    exportada_en = models.DateTimeField(null=True, blank=True)
    nro_sap = models.CharField(max_length=30, blank=True, default='')
    creada_en = models.DateTimeField(auto_now_add=True)
    comentario = models.CharField(max_length=255, blank=True, default='')

    class Meta:
        ordering = ['-fecha', 'proveedor_id']

    @property
    def valor_total(self):
        return sum(l.valor for l in self.lineas.all() if l.estado != LineaSolicitud.DESCARTADA)


class LineaSolicitud(models.Model):
    PENDIENTE, APROBADA, DESCARTADA = 'PENDIENTE', 'APROBADA', 'DESCARTADA'
    solicitud = models.ForeignKey(SolicitudCompra, on_delete=models.CASCADE, related_name='lineas')
    product = models.ForeignKey(ProductSKU, on_delete=models.CASCADE)
    cantidad_sugerida = models.FloatField(default=0)
    cantidad_final = models.FloatField(default=0)
    motivo = models.CharField(max_length=255, blank=True, default='')
    precio_unitario = models.FloatField(default=0)
    nro_acuerdo = models.CharField(max_length=30, blank=True, default='')
    linea_acuerdo = models.IntegerField(null=True, blank=True)
    sin_contrato = models.BooleanField(default=False)
    saldo_insuficiente = models.BooleanField(default=False)
    excepcion = models.BooleanField(default=False)
    causa_excepcion = models.CharField(max_length=15, blank=True, default='')
    urgencia = models.CharField(max_length=10, default='NORMAL')
    duplicada_reciente = models.BooleanField(default=False, help_text='Otra solicitud abierta del mismo articulo en 15 dias')
    estado = models.CharField(max_length=10, default=PENDIENTE)

    @property
    def valor(self):
        return self.cantidad_final * self.precio_unitario

    @property
    def modificada(self):
        return self.estado == self.DESCARTADA or self.cantidad_final != self.cantidad_sugerida


# ── Alertas (§8) ─────────────────────────────────────────────────────────────

class Alerta(models.Model):
    NUEVA, REVISADA, RESUELTA = 'NUEVA', 'REVISADA', 'RESUELTA'
    TIPOS = [
        ('CAMBIO_LETRA', 'Cambio de letra REPO'),
        ('CAIDA_CONSUMO', 'Caida de consumo'),
        ('ALZA_CONSUMO', 'Alza de consumo'),
        ('CONSUMO_IRREGULAR', 'Consumo mas irregular'),
        ('NUEVO_CONSUMO', 'Nuevo consumo'),
        ('EVENTO_COMERCIAL', 'Evento comercial'),
        ('QUIEBRE_PROYECTADO', 'Quiebre proyectado'),
        ('BAJO_SS_PROYECTADO', 'Bajo stock de seguridad proyectado'),
        ('OC_ATRASADA', 'OC atrasada'),
        ('URGENTE', 'Urgente'),
        ('BAJO_SS', 'Bajo stock de seguridad'),
        ('SOBRESTOCK', 'Sobrestock'),
        ('CONTRATO', 'Contrato'),
        ('DATOS', 'Datos'),
        ('TRASLADO_SUCURSALES', 'Traslado entre sucursales'),
        ('PICO', 'Pico de consumo recortado'),
    ]
    tipo = models.CharField(max_length=20, choices=TIPOS, db_index=True)
    product = models.ForeignKey(ProductSKU, null=True, blank=True, on_delete=models.CASCADE, related_name='alertas')
    proveedor_codigo = models.CharField(max_length=30, blank=True, default='')
    severidad = models.CharField(max_length=10, default='MEDIA')   # ALTA / MEDIA / BAJA
    mensaje = models.CharField(max_length=300)
    clave = models.CharField(max_length=150, unique=True, help_text='Evita duplicar la misma alerta entre corridas')
    estado = models.CharField(max_length=10, default=NUEVA, db_index=True,
                              choices=[(NUEVA, 'Nueva'), (REVISADA, 'Revisada'), (RESUELTA, 'Resuelta')])
    responsable = models.CharField(max_length=100, blank=True, default='')
    comentario = models.TextField(blank=True, default='')
    vigente = models.BooleanField(default=True, db_index=True, help_text='La condicion se cumple en la ultima corrida')
    creada_en = models.DateTimeField(auto_now_add=True)
    actualizada_en = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-creada_en']
