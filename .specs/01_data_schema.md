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

> La lista fija de bodegas de §2.2 está superada: las zonas y bodegas no físicas se definen en
> `apps/data_ingestion/warehouses.py` (SPEC-07 §4).

## 3. Campos agregados en octubre 2026 (`inventory`)

| Modelo | Campo | Uso |
|---|---|---|
| Category | `tipo` | Tipo de material del grupo SAP (`group_types.py`): define si se abastece |
| ProductSKU | `sap_group_code`, `sap_group_name` | Grupo de artículos SAP (`oitb`); es la "familia" de los parámetros (SPEC-14) |
| ProductSKU | `gestiona_inventario` | `invntitem`; `N` deja el SKU inactivo |
| ProductSKU | `es_vendible`, `fec_creacion_sap`, `clase`, `familia`, `subfamilia`, `modelo`, `sap_categoria` | Maestro v7 |
| InventoryMetric | `stock_transito_inter` | Stock en bodegas `T…-…` acreditado a la bodega destino |
| StockProjection | `action_type`, `suggested_transfer_units`, `transfer_source_warehouse` | DRP del motor anterior |
| SKUClassification | `repo_category`, `rop_statistical`, … | Motor anterior; su ROP es el "escenario actual" |

## 4. Modelos de la Calculadora (`apps/calculadora/models.py`)

| Grupo | Modelo | Contenido |
|---|---|---|
| Datos de origen | `Proveedor` | Código, nombre, país, congelado, calendario (frecuencia, fecha ancla), comprador |
| | `ConsumoMensual` | Artículo × bodega × mes × origen (VENTA / OF / SALIDA), cantidad |
| | `PlazoOC` | Una recepción por línea de OC: fechas y `dias_entrega` |
| | `OCAbierta` | Línea de OC con pendiente y fecha comprometida |
| | `CompromisoAbierto` | Línea abierta de PC u OF con fecha |
| | `ParametroCompra` | Proveedor preferido, lead time maestro, mínimo, múltiplo, unidad, bloqueado |
| | `AcuerdoGlobal` | Línea de acuerdo global: vigencia, plan, acumulado, precio (`saldo` calculado) |
| | `CargaDatos` | Registro de cada carga (tabla, archivo, filas, fuente, nota) |
| Configuración | `ArticuloConfig` | E, mínimo declarado, crítico, mínimo de nuevo, proveedor alternativo |
| | `Equivalencia` | Código antiguo → nuevo (la historia se suma al nuevo) |
| | `ParametroValor`, `ParametroCambio` | Parámetros por nivel y su registro de cambios |
| | `EventoComercial` | Ajuste de demanda propuesto / aprobado |
| Resultados | `Corrida` | Cada ejecución: fecha, estado, fuente de consumo, resumen |
| | `ResultadoArticulo` | Diccionario de campos §4 por artículo (red), incluye simulación |
| | `ResultadoBodega`, `TrasladoSugerido` | Acción por bodega y traslados |
| | `HistorialMensual` | Foto mensual: letra, ABC, stock máximo y su valor |
| | `SolicitudCompra`, `LineaSolicitud` | Solicitudes por proveedor y sus líneas |
| | `Alerta` | Alertas con estado, responsable y vigencia |

Detalle de cada campo: SPEC-08 (origen), SPEC-10 a SPEC-16 (cálculo y uso).
