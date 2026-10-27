# SPEC-08: Contrato de Datos de la Calculadora

Documento fuente: §2. Código: `apps/calculadora/cargadores.py`, `apps/data_ingestion/datalake_ingest.py`.
Estado: implementado el 27-oct-2026. Consultas 8 a 14 **sin validar en Athena**.

---

## 1. Reglas generales

- La ingesta es por TXT del Datalake en `data/` (SPEC-07 §1). No hay acceso directo a Athena.
- `find_data_file(nombre_largo, prefijo)` toma el archivo **más reciente** entre el nombre largo y
  cualquier `prefijo*.txt` (variantes del task de DBeaver: `oitw-1793….txt`).
- Formato: tabla con pipes (`|col|col|`), cabecera + separador; `iter_txt_rows` salta ambos.
  Números con coma de miles (`2,301,711`) se limpian con `_clean_num`; vacío o inválido = 0.
- **Cada carga reemplaza su tabla completa** (es una foto del Datalake) y deja un registro en
  `CargaDatos` (tabla, archivo, filas, fuente, nota).
- Un archivo faltante **nunca** se toma como cero en silencio: se usa el respaldo de §3 y queda
  anotado en `CargaDatos.fuente` / `nota` (y en `Corrida.fuente_consumo`).
- Solo se cargan filas de SKUs presentes en el maestro.

## 2. Archivos

### 2.1 Pipeline actual (`consultas_optimizadas_datalake.sql`, 7 consultas)

| TXT (nombre largo) | Prefijo | Consulta | Cargador | Destino |
|---|---|---|---|---|
| Maestro de Artículos & Costos.txt | `oitm` | 1 | `ingest_datalake_maestro` | `ProductSKU`, `Category` |
| Stock Físico por Bodega.txt | `oitw` | 2 | `ingest_datalake_stock_fisico` | `StockActual`, `InventoryMetric` |
| Órdenes de Fabricación (OF).txt | `owor_wor1` | 3 | `ingest_datalake_ofs` + `cargar_compromisos` | `ProductionOrderMovement`, compromisos OF, `CompromisoAbierto` |
| Pedidos de Clientes (PC).txt | `ordr_rdr1` | 4 | `ingest_datalake_pedidos` + `cargar_compromisos` | `SalesOrderMovement`, compromisos PC, `CompromisoAbierto` |
| Órdenes de Compra en Tránsito (OC).txt | `opor_por1` | 5 | `ingest_datalake_ocs` + `cargar_oc_abiertas` | tránsito OC, `OCAbierta`, `Proveedor` |
| Solicitudes de Compra (SC).txt | `oprq_prq1` | 6 | `ingest_datalake_scs` | SC abiertas en `InventoryMetric.sc_qty` |
| Entradas de Mercancías.txt | `opdn_pdn1` | 7 | `_proveedor_por_historia` (respaldo de proveedor) | `Proveedor` |

### 2.2 Calculadora (`consultas_calculadora_compras.sql`, borrador)

| TXT | Prefijo | Consulta | Columnas | Cargador | Destino |
|---|---|---|---|---|---|
| Consumo Mensual.txt | `consumo_mensual` | 8 | codigo_sku, bodega, mes, origen, cantidad_neta | `cargar_consumo_mensual` | `ConsumoMensual` |
| Consumo OF Mensual.txt | `consumo_of_mensual` | 8b (opcional) | codigo_sku, bodega, mes, cantidad_of | idem (mueve SALIDA → OF) | `ConsumoMensual` |
| Plazos de Entrega OC.txt | `plazos_oc` | 9 | nro_oc, codigo_sku, codigo_proveedor, bodega_oc, fecha_oc, fecha_comprometida, nro_entrada, fecha_entrada, dias_entrega, cantidad_oc, cantidad_recibida | `cargar_plazos_oc` | `PlazoOC` |
| Parametros de Compra.txt | `parametros_compra` | 10 | codigo_sku, proveedor_preferido, lead_time_maestro, min_compra, multiplo_compra, unidades_por_paquete, unidad_medida, congelado, vigente | `cargar_parametros_compra` | `ParametroCompra` |
| Proveedores.txt | `ocrd` | 11 | codigo_proveedor, nombre_proveedor, pais, congelado | `cargar_proveedores` | `Proveedor` (no toca el calendario) |
| Bodegas.txt | `owhs` | 12 | codigo_bodega, nombre_bodega, inactiva | `cargar_bodegas` | `Warehouse.name` |
| Traslados Abiertos.txt | — | 13 | — | **no se carga**: solo para validar que el tránsito por bodegas `T` no se duplica | — |
| Acuerdos Globales.txt | `ooat_oat1` | 14 | nro_acuerdo, codigo_proveedor, fecha_inicio, fecha_termino, estado, linea_acuerdo, codigo_sku, cantidad_plan, cantidad_acumulada, precio_unitario | `cargar_acuerdos` | `AcuerdoGlobal` |

`cargar_todo()` corre en este orden: OC abiertas → compromisos → proveedores → bodegas →
parámetros de compra → plazos → acuerdos → consumo. Se llama al final del pipeline actual
(necesita maestro y movimientos ya cargados).

## 3. Respaldos cuando falta un archivo

| Falta | Respaldo | Marca |
|---|---|---|
| Consulta 8 (consumo) | Se reconstruye desde PC cerrados (VENTA, por fecha de entrega) y OF cerradas (OF, por fecha de cierre) | `fuente = 'PC_OF'` (provisional) |
| Consulta 10 (parámetros) | Proveedor preferido = último proveedor que entregó el artículo (Entradas de Mercancías) o el de su OC abierta más reciente. Sin mínimo ni múltiplo | `fuente = 'RESPALDO'` |
| Consulta 9 (plazos) | `OITM.LeadTime` del maestro con variación del 25% (SPEC-10 §2) | `fuente = 'SIN_ARCHIVO'` |
| Consulta 14 (acuerdos) | Todas las líneas quedan "sin contrato" y se valorizan al costo | `fuente = 'SIN_ARCHIVO'` |

- Proveedor interno excluido del respaldo: `96877150P` (PEÑA SPOERER, recepciones de producción propia).
- Con la consulta 10 cargada, los SKUs sin `proveedor_preferido` igual reciben el respaldo.

## 4. Reglas de bodega y casos especiales

- **OC y SC en la `013` (o sin bodega) → `013-PP`** (`purchase_bodega`). La compra de la red se
  recibe en la central. Hallazgo del 27-oct: antes se perdían **~1.061 líneas de OC (5.457 u) y
  ~450 líneas de SC** porque `InventoryMetric` solo guarda bodegas con zona. Las demás bodegas
  sin zona no se reasignan.
- Bodegas `000-003`, `000-010`, `000-022` reciben OC/SC (43, 71 y 29 líneas aprox.). Parecen bodegas
  de posteo de sucursales: **por confirmar** antes de reasignarlas.
- PC y OF abiertos: bodega según `commitment_bodega` (SPEC-07 §5). Fecha: entrega/cierre o, si
  falta, emisión/creación.
- **Recepciones parciales**: de cada línea de OC se toma la **primera** entrada (decisión abierta
  #4). Plazos negativos o > 365 días se guardan y el cálculo los excluye y cuenta (SPEC-10 §2).
- Consumo: netos negativos (más devoluciones que salidas) se tratan como 0 en el cálculo.
  Devoluciones restan en el mes en que ocurren (OINM), no en el del movimiento original
  (decisión abierta #3).

## 5. Checklist de validación en Athena (fase 1)

1. Bloque 0: `SHOW TABLES` / `DESCRIBE` de `oinm`, `owtq`, `ooat`, `oat1`, `ocrd`, `owhs`, `oitm`.
2. Consulta 8 con `LIMIT 5`; confirmar TransType 13, 14, 15, 16, 60.
3. Cuadrar el consumo de 30 artículos contra el informe de auditoría de stock de B1, por bodega
   (criterio de aceptación fase 1, documento §13).
4. Consultas 9, 10, 11, 12, 14 con `LIMIT 5`; ajustar nombres de columna según `DESCRIBE`.
5. Consulta 13: comparar contra el stock de bodegas `T` antes de decidir si se suma.
6. Quitar `LIMIT`, exportar a `data/` con el nombre de la cabecera y correr `manage.py calcular_compras`.
   Verificar en `CargaDatos` que la fuente de consumo pase de `PC_OF` a `OINM`.
