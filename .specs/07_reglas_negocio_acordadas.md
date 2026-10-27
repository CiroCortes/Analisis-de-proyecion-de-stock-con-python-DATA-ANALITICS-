# SPEC-07: Reglas de Negocio Acordadas (octubre 2026)

Registro de las reglas que Abastecimiento definió mientras se ordenaba el sistema, antes de
implementar la Calculadora de Compras (SPEC-06). **Estas reglas ya están aplicadas en el código**
y deben respetarse en cualquier cálculo nuevo. Si una regla cambia, se cambia aquí primero.

Estado: vigente al 26-oct-2026. Reemplaza lo que contradiga en SPEC-02 y HARNESS_RULES.

---

## 1. Fuente de datos

- La ingesta es 100% por archivos TXT del Datalake (Athena / SAP B1) en `data/`. El Excel se eliminó.
- El usuario descarga los TXT con un task de DBeaver. **No hay acceso directo a Athena desde la
  plataforma** (decisión de seguridad de IT). El conector boto3 (`athena_client.py`,
  `manage.py check_athena`, `manage.py sync_datalake`) quedó construido pero sin probar y sin uso.
- Los nombres de archivo pueden venir como `oitm_oitb.txt`, `oitw-1793037653080.txt`, etc.
  El cargador (`datalake_ingest._find_file`) toma el más reciente de cada tabla.
- Consultas vigentes: `data/consultas_optimizadas_datalake.sql` (las 7 actuales; el conector
  espera exactamente 7). Consultas nuevas de la Calculadora:
  `data/consultas_calculadora_compras.sql` (borrador).
- Escribir en SAP (Service Layer, campos de usuario U_RPEO / U_CRITICO) **está descartado** hasta
  que se solicite y apruebe la habilitación de Service Layer.

## 2. Costo

- Costo de un artículo = **precio de última compra** (`lastpurprc`), llevado a USD con el último
  tipo de cambio (`ortt`). Respaldo: `avgprice`. **No** usar `avgprice` como fuente principal
  (venía en 0 en el 98% de los SKUs).
- Artículos de producción propia (equipos): no tienen precio de compra; se dejan en 0.
  Valorizarlos al costo de producción es una decisión pendiente de jefatura.
- La carga conserva el costo anterior cuando el TXT trae 0.

## 3. Alcance de artículos (qué se audita)

- Cada artículo pertenece a un **grupo de artículos SAP** (`oitb`, campo `itmsgrpcod`, con nombre).
  `categoria_sop` (7, 10, 11…) es otra clasificación, más gruesa, y se conserva en `sap_categoria`.
- Cada grupo tiene un **tipo de material** (`apps/inventory/group_types.py`):

| Tipo | Se abastece | Ejemplos |
|---|---|---|
| Repuestos | Sí | RPTS. EQ. IZAJE, RPTS. EQ. FORESTAL… |
| Accesorios | Sí | ACCESORIO ASPIRACION, ACCESORIOS IZAJE… |
| Pañol / Insumos | Sí | PAÑOL EPP, PAÑOL HERRAMIENTAS, MAT. MENOR RHINOX… |
| Materiales de producción | Sí | PESCO AMBULANCIAS, HIDRAULICA |
| Por revisar | Sí (hasta decidir) | MAT. MENOR DE EMERGE, ARTICULOS PERSONAL |
| Equipos y venta | **No** | EQUIPOS IZAJE, EQUIPOS ESPECIALES, CAMIONES-CHASIS, RETAIL… |
| Servicios y gastos | **No** | SERVICIOS *, GARANTIAS *, ACTIVO FIJO, GASTOS *… |

- El estado activo/excluido se decide por grupo en Configuración → Grupos. Un grupo excluido no
  entra a proyecciones, recomendador, compras ni reportes.
- Regla fija adicional: artículo con `invntitem = 'N'` (servicio, gasto, activo) **siempre** queda
  fuera (`ProductSKU.is_active = False`). Los SKUs que dejan de venir en el maestro (solo trae
  vigentes, `frozenfor = 'N'`) también se desactivan.
- El motor de clasificación y el DRP ignoran los SKUs inactivos.

## 4. Bodegas

Definidas en `apps/data_ingestion/warehouses.py`.

- **Zona Santiago**: todas las bodegas físicas `013-xx`. Todas pueden mover stock entre sí y
  hacia sucursales (dar y recibir). Central = `013-PP`.
- **Zona Sucursales**: `002` Calama, `002-02` Antofagasta, `003` Copiapó, `008` Los Ángeles,
  `010` Puerto Montt. (En SAP Antofagasta es `002-02`; en los códigos de tránsito figura como `022`.)
- **No físicas** (se excluyen de los cálculos y no se pueden activar):
  - **Tránsito**: `013` a secas y las `T<origen>-<destino>` (T013-002, T022-013, …).
  - **No conforme**: `013-NC`, `013-NC_E`.
  - **Consignación**: `96x` y `1xx` (100, 101–106, 110…).
- Otras bodegas (`000*`, `0EX`, `200`, `710`, `85x`, `90x`, `98x`, `99x`, `TANF-CAL`) no pertenecen a
  ninguna zona y quedan fuera.

### 4.1 Cómo funciona el tránsito

Un traslado Santiago → sucursal pasa por: bodega origen (013-03) → `013` (posteo) → `T013-002`
(en camino) → el operador de destino lo recibe en `002`. Por eso:

- El stock de una bodega `T…-…` se acredita como **en tránsito a la bodega destino**
  (stock físico + `onorder` de esa bodega T). Destino `022` = `002-02`; destino `013` = `013-PP`.
- El stock de la `013` a secas **no se cuenta** (es de paso).
- La `013` se usa también para **facturar PC y consumir OF de Santiago**: esas salidas son
  demanda real de Santiago (ver 5).
- Limitación conocida: el stock que ya salió de la bodega origen y está en la `013` no es visible
  como entrante en el destino hasta que pasa a una bodega `T`.

## 5. Salidas de OF y PC (demanda y compromisos)

- Cuentan **todas** las salidas de OF y PC. La bodega de la línea **no es confiable**: quien crea la
  OF muchas veces no indica de qué almacén sacar (queda la `013` de posteo o una de consignación),
  y a veces se edita a mano.
- Atribución (`commitment_bodega`): si la línea está en una bodega con zona (013-xx físicas o
  sucursales), se atribuye a esa bodega; en cualquier otra (013, consignación, etc.) se atribuye a
  `013-PP`.
- Antes de esta regla se perdía entre el 74% y el 80% de los compromisos abiertos (estaban en la `013`).

## 6. Clasificación REPO (vigente en el motor actual)

| Letra | Regla vigente | Nota |
|---|---|---|
| R | consumo en 2 o más meses del año | la Calculadora lo cambia a 3 o más (SPEC-06) |
| E | pañol con nivel de servicio ≥ 95% y política SI_STOCK | la Calculadora lo cambia: lo declara el área usuaria |
| **P** | no es R ni E y tiene **PC u OF abierto** en alguna bodega | "a pedido": se pide cuando el comercial vende; reorden = lo comprometido |
| O | resto: sin movimiento y sin OF/PC activo | no se recompra |

- Los PC/OF **abiertos** no se guardan como movimientos (solo los cerrados). Los abiertos viven
  como compromisos en `InventoryMetric.comp_pc_qty / comp_of_qty` y de ahí se detecta P.
- Pendiente de confirmar: ¿P se activa solo por PC, o también por OF? (hoy: ambos, como en la
  Calculadora §3).

## 7. Qué está aplicado en el código

| Regla | Dónde |
|---|---|
| Zonas, bodegas no físicas, tránsito, atribución de salidas | `apps/data_ingestion/warehouses.py` |
| Carga del maestro (grupo SAP, `invntitem`, desactivación) | `apps/data_ingestion/datalake_ingest.py` |
| Tipos de material y recomendación por grupo | `apps/inventory/group_types.py` |
| Pantalla de grupos y bodegas | `apps/inventory/views.py`, `templates/inventory/configurar_grupos.html` |
| Filtro de zona y orden en el recomendador | `apps/purchasing/views.py`, `templates/purchasing/list.html` |
| Motor REPO + DRP | `apps/inventory/classification_engine.py` |
