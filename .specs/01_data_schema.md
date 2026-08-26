# SPEC-01: Esquema de Datos y Modelos Django (PostgreSQL/SQLite)

## 1. Visión General
Definición de modelos relacionales para el sistema de proyección de stock S&OP Pesco S.A.

## 2. Modelos

### 2.1 Category / Gerencia (`inventory.Category`)
- `id`: AutoField (PK)
- `code`: CharField(max_length=50, unique=True)
- `name`: CharField(max_length=100)
- `gerencia`: CharField(max_length=100)  # Gerencia a la que pertenece

### 2.2 Warehouse (`inventory.Warehouse`)
- `id`: AutoField (PK)
- `code`: CharField(max_length=20, unique=True) # Ej: '013-PP', '002', '010'
- `name`: CharField(max_length=100)
- `is_active`: BooleanField(default=True)

Bodegas permitidas en el arnés:
`['013-PP', '013-PS', '013-07', '013-09', '002', '002-02', '003', '008', '010']`

### 2.3 ProductSKU (`inventory.ProductSKU`)
- `code`: CharField(max_length=50, primary_key=True) # SKU
- `description`: CharField(max_length=255)
- `category`: ForeignKey(Category, null=True, on_delete=SET_NULL)
- `unit_cost_usd`: DecimalField(max_digits=12, decimal_places=2, default=0.00)
- `unit_cost_clp`: DecimalField(max_digits=12, decimal_places=2, default=0.00)
- `lead_time_days`: IntegerField(default=30)
- `is_active`: BooleanField(default=True)

### 2.4 InventoryMetric (`inventory.InventoryMetric`)
- `id`: AutoField (PK)
- `product`: ForeignKey(ProductSKU, on_delete=CASCADE)
- `warehouse`: ForeignKey(Warehouse, on_delete=CASCADE)
- `stock_physical`: IntegerField(default=0)
- `sc_qty`: IntegerField(default=0)          # Solicitudes de Compra
- `oc_po_qty`: IntegerField(default=0)       # Órdenes de Compra en Tránsito
- `comp_pc_qty`: IntegerField(default=0)     # Compromisos Pedidos Cliente
- `comp_of_qty`: IntegerField(default=0)     # Compromisos Órdenes Fabricación
- `disp_today`: IntegerField(default=0)      # Disponible Hoy
- `disp_future`: IntegerField(default=0)     # Disponible Futuro
- `updated_at`: DateTimeField(auto_now=True)

### 2.5 StockProjection (`inventory.StockProjection`)
- `id`: AutoField (PK)
- `product`: ForeignKey(ProductSKU, on_delete=CASCADE)
- `warehouse`: ForeignKey(Warehouse, on_delete=CASCADE, null=True, blank=True) # NULL para global
- `rop`: IntegerField(default=0)              # Punto de Reorden
- `safety_stock`: IntegerField(default=0)     # Stock de Seguridad
- `coverage_days`: IntegerField(default=0)
- `shortage_units`: IntegerField(default=0)   # Unidades en quiebre
- `shortage_usd`: DecimalField(max_digits=14, decimal_places=2, default=0.00) # Quiebre en USD
- `suggested_buy_units`: IntegerField(default=0) # Unidades a comprar recomendadas
- `urgency_level`: CharField(max_length=20, choices=[('URGENTE', 'Urgente'), ('MEDIO', 'Medio'), ('NORMAL', 'Normal')])
- `calculated_at`: DateTimeField(auto_now=True)
