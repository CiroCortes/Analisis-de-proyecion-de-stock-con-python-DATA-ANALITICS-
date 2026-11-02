# SPEC-31: Marcas de gestión por artículo y requerimientos pendientes de César

Fecha: 2-nov-2026. Origen: documento `data/Planificación_requerimeintos_cesar` (César Quiroz) y reunión
S&OP del 2-nov. Código: `apps/calc/` (motor, política, consumo, params), `apps/calculadora/` (servicio,
alertas, cargadores, vistas `views_marcas.py`), consulta 17. Tests: `tests/test_spec31.py`.

---

## 1. Marcas de gestión (las configura Abastecimiento desde la pantalla, sin tocar código)

César pidió poder ir marcando artículos para "ir amoldando el sistema". Hay dos marcas nuevas en
`ArticuloConfig`, editables desde la ficha del artículo y desde la pantalla **Marcas** (§1.3):

### 1.1 Excluir del cálculo

Campos: `excluir_calculo` (sí/no) y `motivo_exclusion`:

| Motivo | Uso |
|---|---|
| `AUXILIAR` | Código auxiliar de entrega (4999990xxx, "ENTREGA DE INSUMOS…"): agrupa lo que entrega el pañol sin desglosar. Su demanda no es de un repuesto real |
| `LIQUIDACION` | Inmovilizado en liquidación: tiene demanda pero no se repone (doc. César §3) |
| `NO_PROCESAR` | Insumo de pañol u otro que Abastecimiento decide no planificar con la herramienta |
| `OTRO` | Con nota obligatoria |

Efecto en el cálculo:
- Método `SIN_COMPRA`: nunca se sugiere compra ni excepción. Aviso "Excluido del cálculo: <motivo>".
- No genera alertas (no hay nada que gestionar).
- Su consumo no entra a la población del ABC (no desplaza a los demás artículos de clase).
- Sigue visible en la grilla, en Analizar y en la ficha, con la marca: se ve su demanda, pero no se compra.
  Si una sucursal pide reponerlo, se evalúa caso a caso (César §3) y se desmarca.

### 1.2 Planificado por gerencia (equipos de alto valor)

Los equipos caros de baja rotación (kits estructurales, motobombas, carrocerías) los planifica la
gerencia en reunión: decide cuánto se va a vender y comprar. La herramienta no compra por
proyección, sino por el plan.

Campos: `plan_gerencia` (sí/no), `plan_unidades` (unidades a cubrir en el período del plan),
`plan_hasta` (último mes del plan) y `nota`.

Efecto en el cálculo (método `GERENCIA`):
- Objetivo = `plan_unidades`. Sugerido = `MAX(0; plan_unidades − disponible futuro)`, redondeado a la
  compra mínima y al múltiplo de SAP. El disponible ya descuenta compromisos y suma OC y traslados:
  una vez emitida la OC del plan, el sugerido vuelve a 0.
- No espera el calendario del proveedor (es una decisión de gerencia, como un P).
- Sin proyección diaria ni excepción (no hay consumo esperado que proyectar).
- Plan vencido (`plan_hasta` < mes actual): sugerido 0 y aviso "Plan de gerencia vencido: actualizar".
- Plan sin unidades (0): sugerido 0 y aviso "Plan de gerencia sin unidades".

### 1.3 Pantalla Marcas

Pantalla nueva en la Calculadora con dos pestañas:

1. **Equipos de gerencia**: candidatos = costo unitario ≥ `umbral_costo_equipo_usd` (parámetro, inicial
   USD 5.000) y meses con consumo en 12 meses ≤ `meses_max_equipo` (inicial 6), más todos los ya marcados.
   Al 2-nov: 145 candidatos, 10 con compra sugerida por USD 670 mil. Columnas: código, descripción,
   costo, letra, consumo de 12 meses y meses con consumo, stock, en camino, comprometido, sugerido de la
   herramienta y plan. Se marca y se escribe el plan en la misma fila.
2. **Excluir del cálculo**: buscador por código o descripción, filtro por segmento (pañol / repuestos)
   y grupo SAP, sugerido y valor. Selección múltiple con motivo, para marcar en bloque (por ejemplo, los
   30 códigos 4999990xxx: USD 880 mil del sugerido al 2-nov). Lista de los ya excluidos con su motivo,
   para desmarcar.

Solo el Administrador de Abastecimiento cambia las marcas (`puede_editar`). Se aplican en el próximo
cálculo.

## 2. Tránsito: solicitudes de compra fuera (doc. César §2)

Slim4 no cuenta las SC como tránsito: no hay certeza de que se conviertan en OC. Parámetro nuevo
`sc_cuenta_en_transito` (inicial **No**). Con No, el en camino de una bodega = OC + traslados en
tránsito (bodegas T…) + pre-bodegas. Las solicitudes aprobadas en la plataforma siguen contando (son
compras decididas que SAP aún no refleja, SPEC-13 §5).

Slim4 suma todo en "total a recibir"; aquí el en camino de la red y de cada nodo se separa por origen.
El cálculo sigue usando el total (acuerdo del 2-nov), y el desglose suma exactamente ese total:

| Origen | Qué es |
|---|---|
| Importación | OC posteada en una pre-bodega (000-xxx) o a un proveedor extranjero (país ≠ CL), y stock ya embarcado en una pre-bodega |
| Compra nacional | OC a proveedor chileno en una bodega de la red |
| Traslado | Transferencia de stock en camino (bodegas T…). Las ST nunca cuentan |
| Pedido SAP sin OC | `OnOrder` de SAP sin línea de OC cargada: OC a proveedores internos (excluidos de la consulta 5) o fabricación |
| Solicitud aprobada | Solicitudes de la plataforma que SAP aún no refleja |
| SC | Solo si `sc_cuenta_en_transito` |
| Ajuste de bodega | Tratamiento manual de una bodega (SPEC-27) |

Corrida 29 (2-nov): 111.880 u en camino; nacional 99.614 u (USD 220 mil), pedido SAP sin OC 5.072 u
(USD 133 mil), importación 4.516 u (USD 66 mil), traslado 2.678 u (USD 82 mil).

**Tres columnas por bodega** (Analizar, su Excel y la ficha): **Por llegar** (total), **Llega por OC**
(importación + nacional + pedido SAP sin OC + solicitudes) y **Llega por traslado**.

**El traslado se sigue contando en la red** (aclaración 2-nov): las unidades salen del stock de Santiago y
van a la sucursal, así que para la compra de la red no suman ni restan. Si no se contaran, la red las
perdería y compraría dos veces (test `test_el_traslado_cuenta_en_la_red_para_no_comprar_dos_veces`).

**Alerta `DOBLE_ENVIO`** (caso de César, filtros de manga): a una sucursal le llega stock por traslado y por
OC, y con lo comprometido le sobra al menos la parte menor. Ejemplo: PC de 200, OC de 200 a la pre-bodega
(100 días) y traslado de 200 desde Santiago mientras tanto → llegan 400 para 200. La alerta avisa que, al
llegar la OC, no hay que volver a enviar: la compra repone Santiago. Corrida 30: 18 casos (por ejemplo
4303390027, Antofagasta: 100 por traslado y 100 por OC, sin compromisos).

**Traslado calzado a un PC vs reposición de stock: no hace falta** (usuario, 2-nov): si va calzado a un PC u
OF, el consumo se registra en el almacén de destino. Al 2-nov, de 2.296 u en bodegas
T…, solo 18 u coinciden con un PC/OF abierto en el destino (157 u en el origen). Con los datos cargados
no se puede saber qué traslado va calzado; hay que leerlo del documento de transferencia (comentario o
ST de origen). Consulta exploratoria en la bitácora del 2-nov.

## 3. Promedio mensual: 12 meses y meses con demanda (doc. César §4)

César propone dividir por los meses con demanda (40 u en 4 meses → 10/mes en vez de 3,3). Revisión:

- **R-Intermitente (§4.5, 3 a 8 meses con consumo) ya usa la intensidad**: el punto de pedido es
  `mayor consumo mensual × salidas en el plazo`, y el mayor mes es ≥ al promedio de los meses con
  demanda. Con el ejemplo de César (4 meses de 10 u): mayor = 10, igual o más que su propuesta. No se
  cambia la fórmula.
- **R-Regular (9 a 12 meses con consumo)**: el promedio ÷12 y el de meses con demanda difieren poco
  (como máximo 12/9). Se mantiene ÷12, que es lo que define el documento.
- Se agrega `promedio_con_demanda` (consumo de 12 meses ÷ meses con consumo) al resultado, y la ficha
  muestra ambos promedios.

## 4. ABC por venta (doc. César §3)

Clasificación adicional, no reemplaza al ABC de inventario (consumo × costo), que sigue mandando el
nivel de servicio.

- Consulta 17 (`Ventas Mensuales.txt`): por artículo, bodega y mes, la venta neta en USD = facturas
  (`inv1.linetotal`, moneda local de la base `pescousd` = USD) menos NC (`rin1.linetotal`). La bodega de
  la factura es la de su guía cuando la tiene.
- `abc_venta` en el resultado: mismos cortes que el ABC (`corte_abc_a`, `corte_abc_b`) sobre la venta de
  12 meses de la red. Sin la consulta 17 queda vacío.
- Pantalla **ABC por venta**: filtro por nodo (red, Santiago o una sucursal); la clase se recalcula sobre
  la venta del nodo elegido. Columnas: venta 12 meses USD, % acumulado, clase de venta, clase de
  inventario, letra y sugerido.

## 5. Alerta de caída por bodega (doc. César §5, reunión 2-nov)

Para revisar con cada gerente de sucursal. `CAIDA_CONSUMO_NODO`: artículo R (no excluido) con consumo
regular en el nodo (al menos `umbral_r` = 3 de los 12 meses) y sin consumo en ese nodo en los últimos
`alerta_caida_meses_nodo` meses (parámetro, inicial 4; César habló de 4 a 6). La alerta indica el nodo
(Santiago o la sucursal), y la pantalla de alertas filtra por bodega. Corrida 28 (2-nov): 332 alertas.

## 8. Resultado en datos reales (corrida 28, 2-nov)

- SC fuera del tránsito: compra sugerida USD 3,96 M → 4,06 M (+94 mil).
- Si se excluyen los 30 códigos 4999990xxx (simulado, no marcado): 4,06 M → 3,22 M (−841 mil). La marca la
  pone Abastecimiento desde la pantalla Marcas.
- Equipos de gerencia: 145 candidatos, 10 con compra sugerida por USD 671 mil.
- ABC por venta: pendiente exportar la consulta 17.

## 6. Ya cubierto (sin cambios)

- Alcance 013-01 a 013-09 y pañoles de servicio: todas las 013-xx físicas son Santiago (SPEC-21).
- Consumo de OF por fecha de emisión (salida de mercancía, TransType 60), no por cierre.
- Ajustes de inventario y traslados no son demanda (consulta 8 solo toma 13, 14, 15, 16, 60).
- Vista transversal del artículo en la red con gráfico por sucursal (Analizar, SPEC-24 y 29).
- Búsqueda por descripción en Analizar.
- Fuente del consumo: `oivl` desde el 2-nov (la `oinm` del Datalake está incompleta).

## 7. Fuera de alcance

- Compra por sucursal hacia su pre-bodega (cross-docking) vs. centralizar en Santiago: decisión de
  gerencia pendiente. El motor sigue el modelo centralizado.
- Escribir las marcas en SAP (prohibido, SAP solo lectura).
