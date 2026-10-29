# SPEC-29: Stock en SAP por bodega en Analizar (y desfase entre exportaciones)

Fecha: 29-oct-2026. Origen: Abastecimiento comparó el 35071069 (batería HIDUO) con el maestro de
artículos de SAP (Datos de inventario) y no encontró en Analizar las pre-bodegas, la consignación
ni la 013, ni podía saber si el tránsito estaba sumado a Santiago.
Código: `analisis.bodegas_sap`, `analisis.fechas_datos`, `templates/calculadora/analizar.html`,
`StockActual.stock_pedido` (OITW.OnOrder). Tests: `tests/test_analizar.py::BodegasSapTest`.

---

## 1. Ventana "Stock en SAP por bodega"

Debajo de "Mismo artículo en todas las ubicaciones", para el artículo seleccionado:

| Columna | Origen |
|---|---|
| Bodega | Todas las bodegas con stock, pedido en SAP u OC abierta |
| En stock | Consulta 2 (OITW.OnHand), igual que SAP |
| Pedido SAP | OITW.OnOrder (antes se leía y se descartaba; ahora se guarda) |
| OC abiertas | Consulta 5, por la bodega de la OC |
| Cómo cuenta | Tratamiento de la bodega (SPEC-27): stock de un nodo, en camino a un nodo, no cuenta |

Pie: stock que usa el cálculo, en camino y lo que no cuenta. El tránsito de OC y SC sigue en la
columna "Por recibir" de la ventana de ubicaciones (por nodo).

## 2. Avisos

- **Desfase entre exportaciones**: muestra la fecha de cada consulta (stock, OC, SC, PC, OF). Si
  hay más de 4 horas entre la más antigua y la más nueva, avisa: lo recibido entre una y otra
  puede no aparecer ni en stock ni en OC.
- **Pedido en SAP sin OC cargada**: si OnOrder supera las OC abiertas de esa bodega, marca la
  fila y el total ("⚠ 20 u sin OC"). El cálculo no ve esas unidades.

## 3. Caso 35071069 (datos del 27/28-oct vs SAP del 29-oct)

| Bodega | SAP 29-oct | Stock 27-oct | Pedido SAP 27-oct | OC 28-oct |
|---|---|---|---|---|
| 000-022 | 15 | 0 | 20 | — |
| 000-002 | 10 | 0 | 10 | — |
| 000-010 | 7 | 0 | 5 | — |
| 013 | 7 | 1 | 0 | — |
| 013-03 | 4 | 10 | 0 | — |

Las 35 u pedidas a pre-bodegas llegaron entre la exportación del stock (27-oct 16:49) y la de OC
(28-oct 16:03): la OC ya estaba cerrada y el stock todavía no las tenía. El cálculo no las vio y
sugirió comprar 95 u. No es un error de la regla: es el desfase entre exportaciones.

En toda la red (artículos del alcance), el pedido en SAP sin OC abierta cargada suma
**USD 1,17 M en pre-bodegas** (686 líneas), USD 1,15 M en bodegas de la red (OnOrder también
incluye órdenes de fabricación) y USD 60 mil en tránsitos (solicitudes de traslado).

## 4. Regla operativa

Exportar **todas las consultas el mismo día y en la misma tanda** (stock, OC, SC, PC, OF). Es
condición para que la compra sugerida sea confiable; la pantalla lo avisa si no se cumple.

## 5. Pendiente (propuesto, no implementado)

Conciliación del consumo con SAP en la ficha y en Analizar: salidas, devoluciones, NC (con el mes
de registro y el mes donde se restan), refacturas de Cobranzas y picos recortados, hasta la
demanda usada. Requiere que la consulta 8 separe las devoluciones (16) y hacerlo junto con la SPEC-25.
