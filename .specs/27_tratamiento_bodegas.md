# SPEC-27: Tratamiento del stock de cada bodega (Configuración > Bodegas)

Fecha: 29-oct-2026. Origen: Abastecimiento vio bodegas con stock marcadas "EXCLUIDA" (pre-bodegas,
013, 013-IN, 013-NC, 0EX) sin saber si la Calculadora las usaba. La pantalla mostraba solo el
switch de auditoría (`is_active`), pero el cálculo aplicaba reglas por código que no se veían.
Código: `apps/data_ingestion/warehouses.py` (`tratamiento_por_defecto`), `Warehouse` (campos
`tratamiento`, `nodo_destino`, `motivo`, `modificado_por/en`), `servicio.ajustes_por_tratamiento`,
`inventory/views.py` (`_guardar_tratamiento`), `cargadores.cargar_bodegas`.
Tests: `tests/test_tratamiento_bodegas.py`.

---

## 1. Tres tratamientos

| Tratamiento | Qué hace en el cálculo |
|---|---|
| **Stock** de un nodo | Suma al stock físico del nodo (Santiago o una sucursal) |
| **En camino** a un nodo | Suma al tránsito del nodo y llega en `dias_recepcion` |
| **No cuenta** | No se usa para abastecer |

## 2. Tratamiento automático (por código)

| Bodega | Automático | Motivo |
|---|---|---|
| 013-xx físicas y sucursales | Stock de su nodo si está incluida; si no, no cuenta | Bodega de la red |
| `013` | Stock de Santiago (no editable: es el nodo) | Bodega de paso (SPEC-21) |
| `T<origen>-<destino>` | En camino al destino | Traslado |
| `000`, `000-0xx` | En camino a su sucursal (000 → Santiago) | Pre-bodega de importación (SPEC-22) |
| `013-NC`, `013-NC_E` | No cuenta | Cobranzas, facturas rechazadas: stock contable |
| `0EX` | No cuenta | Exportación: ya vendido, espera factura COMEX |
| 1xx, 95x, 96x | No cuenta | Consignación en el cliente (su consumo sí es demanda de Santiago) |
| 90x | No cuenta | Demos |
| 710, 85x, 99x | No cuenta | Garantías, proveedores/bodegas externas, desarme |
| Otras | No cuenta | Fuera de la red |

## 3. Cambio manual

- **Bodegas de la red**: se incluyen (stock de su nodo) o se excluyen (no cuenta). Es el mismo
  `is_active` de antes.
- **Demás bodegas** (salvo la 013): automático, stock de un nodo, en camino a un nodo o no cuenta,
  con motivo opcional. Se guarda quién y cuándo. Requiere permiso de edición de parámetros.
- Los cambios se aplican al recalcular. El botón "Recalcular con esta configuración" corre la red.

### Cómo se aplica

La carga ya deja el tratamiento automático (tránsito de T y 000 en `InventoryMetric`, stock de la
013). Para cada bodega con tratamiento manual, `ajustes_por_tratamiento` resta lo que aportaba el
automático y suma lo que aporta el elegido, por artículo y nodo, con el stock de `StockActual`.
Santiago recibe el ajuste en la bodega 013 (el núcleo suma Santiago en un nodo); una sucursal, en
su propia bodega (se crea si no tenía posición). Nunca queda stock negativo. **Sin
configuración manual el cálculo no cambia**: la corrida 20 dio lo mismo que la 19.

Solo se reubica el stock físico. Lo solicitado en una bodega de tránsito (`onorder`) sigue igual.

## 4. Catálogo completo

La consulta 14 solo actualizaba nombres. Ahora `cargar_bodegas` crea **excluidas** las bodegas que
vienen en la consulta 14 o en el stock y no estaban en el catálogo (51 → 131 al 29-oct). Así
aparecen las T…, la TANF-CAL (tránsito Antofagasta–Calama con código no estándar: se puede pasar a
"En camino a Calama") y las demás, sin entrar como stock de la red sin que alguien lo decida.

## 5. Pantalla

KPI de bodegas que aportan stock, en camino y que no cuentan, con su valor en el alcance (USD de
artículos activos de grupos activos). Tabla ordenada por tratamiento y valor: cómo cuenta, motivo,
marca MANUAL con usuario y fecha, SKUs, stock, USD y el control para cambiarla.

## 6. Pendiente

- **013-IN** (devoluciones físicas, "Compras nacionales"): sigue excluida; en el alcance son 9 u
  (USD 678). Definir con Distribución si su stock está disponible.
- La 013-NC tiene ~USD 1,63 M (USD 33 mil en el alcance): lista en la bitácora para Cobranzas.
