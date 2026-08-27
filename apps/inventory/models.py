from django.db import models
from apps.inventory.stock_actual_models import StockActual, CargaStockActual  # noqa: F401


class Category(models.Model):
    code = models.CharField(max_length=100, unique=True, verbose_name="Código Categoría")
    name = models.CharField(max_length=150, verbose_name="Nombre Categoría")
    gerencia = models.CharField(max_length=150, default="Gerencia Repuestos", db_index=True, verbose_name="Gerencia / Área")
    is_active = models.BooleanField(default=True, db_index=True, verbose_name="Incluido en S&OP por Defecto")

    class Meta:
        verbose_name = "Categoría"
        verbose_name_plural = "Categorías"

    def __str__(self):
        status = "✓" if self.is_active else "✗"
        return f"[{status}] {self.name} ({self.gerencia})"


class Warehouse(models.Model):
    code = models.CharField(max_length=20, unique=True, db_index=True, verbose_name="Código Bodega")
    name = models.CharField(max_length=100, verbose_name="Nombre Bodega")
    is_active = models.BooleanField(default=True, db_index=True, verbose_name="Activa")

    class Meta:
        verbose_name = "Bodega"
        verbose_name_plural = "Bodegas"

    def __str__(self):
        return f"{self.code} - {self.name}"


class ProductSKU(models.Model):
    code = models.CharField(max_length=100, primary_key=True, verbose_name="Código SKU")
    description = models.CharField(max_length=255, db_index=True, verbose_name="Descripción Repuesto/Equipo")
    category = models.ForeignKey(Category, null=True, blank=True, on_delete=models.SET_NULL, verbose_name="Categoría")
    unit_cost_usd = models.DecimalField(max_digits=12, decimal_places=2, default=0.00, db_index=True, verbose_name="Costo Unitario USD")
    unit_cost_clp = models.DecimalField(max_digits=14, decimal_places=2, default=0.00, verbose_name="Costo Unitario CLP")
    lead_time_days = models.IntegerField(default=30, verbose_name="Lead Time (Días)")
    is_active = models.BooleanField(default=True, db_index=True, verbose_name="SKU Activo")
    
    # Nuevos atributos del Maestro v7
    clase = models.CharField(max_length=100, blank=True, default='', verbose_name="Clase")
    familia = models.CharField(max_length=100, blank=True, default='', verbose_name="Familia")
    subfamilia = models.CharField(max_length=100, blank=True, default='', verbose_name="SubFamilia")
    modelo = models.CharField(max_length=100, blank=True, default='', verbose_name="Modelo")
    sap_categoria = models.CharField(max_length=100, blank=True, default='', verbose_name="Categoría SAP")
    fec_creacion_sap = models.DateField(null=True, blank=True, verbose_name="Fecha Creación SAP")
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Producto SKU"
        verbose_name_plural = "Productos SKU"
        indexes = [
            models.Index(fields=['code', 'is_active']),
            models.Index(fields=['description']),
            models.Index(fields=['clase']),
            models.Index(fields=['sap_categoria']),
        ]

    def __str__(self):
        return f"{self.code} | {self.description[:40]}"


class ProductionOrderMovement(models.Model):
    """Movimientos de consumo de materiales e insumos en Órdenes de Fabricación (OF)."""
    of_number = models.CharField(max_length=50, db_index=True, verbose_name="Nro. OF")
    product = models.ForeignKey(ProductSKU, on_delete=models.CASCADE, related_name='of_movements', verbose_name="Componente")
    quantity_delivered = models.DecimalField(max_digits=12, decimal_places=2, default=0.00, verbose_name="Cant. Entregada")
    warehouse = models.CharField(max_length=50, blank=True, default='', verbose_name="Almacén")
    start_date = models.DateField(null=True, blank=True, verbose_name="Fecha Inicio")
    end_date = models.DateField(null=True, blank=True, db_index=True, verbose_name="Fecha Término")
    status = models.CharField(max_length=50, default='Cerrada', db_index=True, verbose_name="Estado OF")
    costo_real = models.DecimalField(max_digits=14, decimal_places=2, default=0.00, verbose_name="Costo Real")

    class Meta:
        verbose_name = "Movimiento Orden Fabricación"
        verbose_name_plural = "Movimientos Órdenes Fabricación"
        indexes = [
            models.Index(fields=['product', 'end_date']),
            models.Index(fields=['status', 'end_date']),
        ]

    def __str__(self):
        return f"OF {self.of_number} - SKU {self.product_id} ({self.quantity_delivered} u)"


class SalesOrderMovement(models.Model):
    """Movimientos de ventas y despachos en Pedidos de Clientes (PC)."""
    order_number = models.CharField(max_length=50, db_index=True, verbose_name="Nro. Pedido")
    product = models.ForeignKey(ProductSKU, on_delete=models.CASCADE, related_name='sales_movements', verbose_name="Producto")
    quantity = models.DecimalField(max_digits=12, decimal_places=2, default=0.00, verbose_name="Cantidad Despachada")
    warehouse = models.CharField(max_length=50, blank=True, default='', verbose_name="Almacén PC")
    emission_date = models.DateField(null=True, blank=True, verbose_name="Fecha Emisión")
    delivery_date = models.DateField(null=True, blank=True, db_index=True, verbose_name="Fecha Entrega")
    status = models.CharField(max_length=50, default='Cerrado', db_index=True, verbose_name="Estado Pedido")
    client_name = models.CharField(max_length=200, blank=True, default='', verbose_name="Razón Social Cliente")

    class Meta:
        verbose_name = "Movimiento Pedido Cliente"
        verbose_name_plural = "Movimientos Pedidos Clientes"
        indexes = [
            models.Index(fields=['product', 'delivery_date']),
            models.Index(fields=['status', 'delivery_date']),
        ]

    def __str__(self):
        return f"PC {self.order_number} - SKU {self.product_id} ({self.quantity} u)"

class GoodsReceipt(models.Model):
    """Movimientos de entrada de mercancías (Ingresos Nacionales/Importaciones)."""
    document_number = models.CharField(max_length=50, db_index=True, verbose_name="Nro. Documento")
    product = models.ForeignKey(ProductSKU, on_delete=models.CASCADE, related_name='goods_receipts', verbose_name="Producto")
    quantity = models.DecimalField(max_digits=12, decimal_places=2, default=0.00, verbose_name="Cantidad")
    posting_date = models.DateField(null=True, blank=True, db_index=True, verbose_name="Fecha Contabilización")
    supplier_name = models.CharField(max_length=200, blank=True, default='', verbose_name="Nombre Proveedor")
    total_lines_cost = models.DecimalField(max_digits=14, decimal_places=2, default=0.00, verbose_name="Total Líneas (Costo)")

    class Meta:
        verbose_name = "Entrada de Mercancía"
        verbose_name_plural = "Entradas de Mercancías"
        indexes = [
            models.Index(fields=['product', 'posting_date']),
        ]

    def __str__(self):
        return f"EM {self.document_number} - SKU {self.product_id} ({self.quantity} u)"


class SKUClassification(models.Model):
    """Matriz de Clasificación S&OP y Políticas de Inventario (Reemplazo Slim4).

    Mantiene todos los campos Slim4 existentes e incorpora la nueva
    clasificación REPO dinámica mensual de PESCO:
      R (Rotación)  → VB en planilla: material con 2+ meses de consumo en el año.
      E (Estratégico) → V1: declarado crítico, tiene stock mínimo fijado.
      P (A Pedido)  → PD: solo se mueve cuando hay una OF o PC asociada.
      O (Obsoleto)  → ND: sin movimiento en más de 12 meses, sin OF/PC activa.
    """
    SEGMENT_CHOICES = [
        ('PANOL', 'Pañol (Insumos Taller/Producción)'),
        ('REPUESTOS', 'Repuestos y Accesorios'),
    ]
    ABC_CHOICES = [
        ('A', 'A (9 a 12 meses con movimiento)'),
        ('B', 'B (5 a 8 meses con movimiento)'),
        ('C', 'C (1 a 4 meses con movimiento)'),
        ('D', 'D (Sin movimiento en año móvil)'),
    ]
    POLICY_CHOICES = [
        ('SI_STOCK', 'SÍ STOCK (Mantener ROP & Seguridad)'),
        ('NO_STOCK', 'NO STOCK (Demanda Apagada / A Pedido)'),
    ]
    # ── Clasificación REPO (Nomenclatura Operativa PESCO) ──────────────────────
    REPO_CHOICES = [
        ('R', 'R – Rotación (VB): 2+ meses con consumo en el año'),
        ('E', 'E – Estratégico (V1): Parte crítica con mínimo fijado'),
        ('P', 'P – A Pedido (PD): Compra solo bajo OF o PC'),
        ('O', 'O – Obsoleto (ND): Sin movimiento > 12 meses'),
    ]

    # ── Campos existentes Slim4 (SE MANTIENEN SIN MODIFICAR) ──────────────────
    product = models.OneToOneField(ProductSKU, on_delete=models.CASCADE, primary_key=True, related_name='classification')
    segment = models.CharField(max_length=30, choices=SEGMENT_CHOICES, default='REPUESTOS', db_index=True, verbose_name="Segmento Negocio")
    abc_class = models.CharField(max_length=5, choices=ABC_CHOICES, default='D', db_index=True, verbose_name="Clasificación ABC")
    active_months_count = models.IntegerField(default=0, verbose_name="Meses con Consumo/Venta (Año Móvil)")
    annual_transactions_count = models.IntegerField(default=0, verbose_name="Transacciones Anuales")
    transactions_last_6m = models.IntegerField(default=0, verbose_name="Transacciones Últimos 6 Meses")

    is_new = models.BooleanField(default=False, db_index=True, verbose_name="Artículo Nuevo")
    is_inmovilizado = models.BooleanField(default=False, db_index=True, verbose_name="Inmovilizado / Obsoleto")

    stock_policy = models.CharField(max_length=20, choices=POLICY_CHOICES, default='NO_STOCK', db_index=True, verbose_name="Política de Stock")
    stock_policy_reason = models.CharField(max_length=150, blank=True, default='', verbose_name="Motivo Política")

    service_level = models.DecimalField(max_digits=4, decimal_places=2, default=0.90, verbose_name="Nivel de Servicio")
    z_factor = models.DecimalField(max_digits=4, decimal_places=2, default=1.28, verbose_name="Factor Z")

    annual_demand_units = models.DecimalField(max_digits=12, decimal_places=2, default=0.00, verbose_name="Demanda Anual Real (u)")
    avg_daily_demand = models.DecimalField(max_digits=10, decimal_places=4, default=0.0000, verbose_name="Demanda Diaria Real (DPD)")

    calculated_at = models.DateTimeField(auto_now=True)

    # ── Campos NUEVOS: Clasificación REPO PESCO ───────────────────────────────
    repo_category = models.CharField(
        max_length=1, choices=REPO_CHOICES, default='O', db_index=True,
        verbose_name="Clasificación REPO",
        help_text="R=Rotación, E=Estratégico, P=A Pedido, O=Obsoleto"
    )
    repo_source_code = models.CharField(
        max_length=5, blank=True, default='ND',
        verbose_name="Código Planilla REPO",
        help_text="VB, V1, PD o ND según planilla de parámetros"
    )
    consumption_freq_12m = models.IntegerField(
        default=0,
        verbose_name="Meses con Consumo en Últimos 12 Meses",
        help_text="Contador de meses distintos con salida de material en el año móvil"
    )
    # ROP estadístico calculado según fórmula de la planilla BASE Cambio Parametros
    rop_statistical = models.IntegerField(
        default=0,
        verbose_name="ROP Estadístico (REPO)",
        help_text="Punto de reorden = Stock Mínimo + Stock de Seguridad (fórmula planilla)"
    )
    safety_stock_statistical = models.IntegerField(
        default=0,
        verbose_name="Stock de Seguridad Estadístico",
        help_text="SS = sqrt(LT_meses) × desv_estándar × Z"
    )
    stock_min_statistical = models.IntegerField(
        default=0,
        verbose_name="Stock Mínimo Estadístico",
        help_text="Stock mínimo = (LT_meses + 0.25) × consumo promedio mensual"
    )
    stock_max_statistical = models.IntegerField(
        default=0,
        verbose_name="Stock Máximo Estadístico",
        help_text="Stock máximo = ROP + (3 meses × consumo promedio mensual)"
    )
    avg_monthly_consumption = models.DecimalField(
        max_digits=10, decimal_places=2, default=0.00,
        verbose_name="Consumo Promedio Mensual (12m)",
        help_text="Promedio de unidades consumidas por mes en los últimos 12 meses"
    )
    std_monthly_consumption = models.DecimalField(
        max_digits=10, decimal_places=2, default=0.00,
        verbose_name="Desviación Estándar Mensual (12m)",
        help_text="Desviación estándar de los consumos mensuales en el año móvil"
    )
    has_active_of_or_pc = models.BooleanField(
        default=False,
        verbose_name="Tiene OF o PC Activa",
        help_text="True si existe una Orden de Fabricación o Pedido de Cliente abierto para este SKU"
    )

    class Meta:
        verbose_name = "Clasificación S&OP (Slim4 + REPO)"
        verbose_name_plural = "Clasificaciones S&OP (Slim4 + REPO)"
        indexes = [
            models.Index(fields=['segment', 'abc_class']),
            models.Index(fields=['stock_policy', 'is_inmovilizado']),
            models.Index(fields=['repo_category']),
            models.Index(fields=['repo_category', 'stock_policy']),
        ]

    def __str__(self):
        return f"{self.product_id} [{self.segment}] ABC:{self.abc_class} REPO:{self.repo_category} -> {self.stock_policy}"


class InventoryMetric(models.Model):
    product = models.ForeignKey(ProductSKU, on_delete=models.CASCADE, related_name='metrics')
    warehouse = models.ForeignKey(Warehouse, on_delete=models.CASCADE, related_name='metrics')
    stock_physical = models.IntegerField(default=0, verbose_name="Stock Físico")
    sc_qty = models.IntegerField(default=0, verbose_name="Solicitud Compra (SC)")
    oc_po_qty = models.IntegerField(default=0, verbose_name="OC / PO (Tránsito)")
    comp_pc_qty = models.IntegerField(default=0, verbose_name="Compromiso Pedido Cliente")
    comp_of_qty = models.IntegerField(default=0, verbose_name="Compromiso Orden Fabricación")
    disp_today = models.IntegerField(default=0, verbose_name="Disponible Hoy")
    disp_future = models.IntegerField(default=0, verbose_name="Disponible Futuro")
    stock_transito_inter = models.IntegerField(default=0, verbose_name="Stock en Tránsito Inter-Sucursal (bodegas T*)")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Métrica de Inventario"
        verbose_name_plural = "Métricas de Inventario"
        unique_together = ('product', 'warehouse')
        indexes = [
            models.Index(fields=['product', 'warehouse']),
            models.Index(fields=['disp_future']),
        ]

    def __str__(self):
        return f"{self.product.code} @ {self.warehouse.code}"


class StockProjection(models.Model):
    """Proyección de Stock por SKU y Bodega.

    Conserva todos los campos originales e incorpora la lógica DRP de
    balanceo de inventario (Traslado Interno vs Compra a Proveedor).
    """
    URGENCY_CHOICES = [
        ('URGENTE', '🔴 Urgente'),
        ('MEDIO', '🟡 Medio'),
        ('NORMAL', '🟢 Normal'),
    ]
    # ── Tipo de acción sugerida (DRP Balanceo de Red) ──────────────────────────
    ACTION_CHOICES = [
        ('COMPRAR', '🛒 Compra a Proveedor'),
        ('TRASLADAR', '🚚 Traslado Interno'),
        ('MIXTO', '🔀 Mixto (Traslado + Compra)'),
        ('NINGUNA', '✅ Sin Acción Requerida'),
    ]

    # ── Campos existentes (SE MANTIENEN SIN MODIFICAR) ─────────────────────────
    product = models.ForeignKey(ProductSKU, on_delete=models.CASCADE, related_name='projections')
    warehouse = models.ForeignKey(Warehouse, on_delete=models.CASCADE, null=True, blank=True, related_name='projections')
    rop = models.IntegerField(default=0, verbose_name="Punto de Reorden (ROP)")
    safety_stock = models.IntegerField(default=0, verbose_name="Stock de Seguridad")
    coverage_days = models.IntegerField(default=0, verbose_name="Días de Cobertura")
    shortage_units = models.IntegerField(default=0, verbose_name="Unidades en Quiebre")
    shortage_usd = models.DecimalField(max_digits=14, decimal_places=2, default=0.00, db_index=True, verbose_name="Quiebre en USD")
    suggested_buy_units = models.IntegerField(default=0, db_index=True, verbose_name="Sugerido de Compra (Unidades)")
    urgency_level = models.CharField(max_length=20, choices=URGENCY_CHOICES, default='NORMAL', db_index=True, verbose_name="Nivel de Urgencia")
    calculated_at = models.DateTimeField(auto_now=True)

    # ── Campos NUEVOS: Balanceo DRP (Traslado vs Compra) ──────────────────────
    action_type = models.CharField(
        max_length=15, choices=ACTION_CHOICES, default='NINGUNA', db_index=True,
        verbose_name="Acción Sugerida",
        help_text="COMPRAR: ir a proveedor. TRASLADAR: mover desde otra bodega. MIXTO: ambas."
    )
    suggested_transfer_units = models.IntegerField(
        default=0,
        verbose_name="Sugerido Traslado (Unidades)",
        help_text="Unidades a trasladar desde la bodega central (no comprar a proveedor)"
    )
    transfer_source_warehouse = models.ForeignKey(
        Warehouse, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='transfer_sources',
        verbose_name="Bodega Origen Traslado",
        help_text="Bodega de Santiago desde donde se recomienda el traslado"
    )

    class Meta:
        verbose_name = "Proyección de Stock"
        verbose_name_plural = "Proyecciones de Stock"
        indexes = [
            models.Index(fields=['urgency_level', 'shortage_usd']),
            models.Index(fields=['warehouse', 'urgency_level']),
            models.Index(fields=['product', 'warehouse']),
            models.Index(fields=['action_type']),
        ]

    def __str__(self):
        return f"{self.product.code} @ {self.warehouse.code if self.warehouse else 'Global'} -> {self.urgency_level} [{self.action_type}]"
