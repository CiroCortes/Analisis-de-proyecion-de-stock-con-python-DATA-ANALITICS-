# SPEC-25: Notas de crédito ligadas a la guía y bodegas de Cobranzas fuera del consumo

Fecha: 2-nov-2026. Origen: reunión S&OP del 2-nov (César Quiroz, Ignacio Gómez) y pendientes #16 y #22.
Corrige la SPEC-22 §1. Código: `apps/calculadora/cargadores.py`, `apps/data_ingestion/warehouses.py`.
Consulta 15 (modificada). Tests: `tests/test_reunion_28oct.py` (`NotasCreditoTest`).

---

## 1. Cómo se vende en Pesco

Todo sale con **guía de despacho** (entrega, TransType 15) y después se emite la **factura** basada en
la guía (`inv1.basetype = 15`). La guía mueve el stock: es la venta que cuenta la consulta 8, en su
bodega y su mes. La factura no mueve stock. También existe el caso contrario, la factura de reserva
seguida de la guía (`dln1.basetype = 13`); tampoco duplica, porque la reserva no mueve stock.

La NC se emite contra la **factura**. Slim4 (query de R. Holloway) sigue NC → factura → guía para
restar la NC en la sucursal que despachó.

## 2. Problema

1. **NC ligada a la factura y no a la guía (SPEC-22).** La factura puede ser de otro mes (o de otra
   bodega) que la guía. Si en la bodega y el mes de la factura no hay venta, la NC no se puede restar
   y queda en la 013-IN o la 013-NC, que caen en Santiago. Medido el 2-nov (12 meses, alcance):
   599 de 1.113 líneas de NC de la 013-NC/013-IN, 4.289 u, no encuentran venta en la celda de la factura.
2. **Ciclo de Cobranzas en la 013-NC.** Una factura rechazada se anula con NC en la 013-NC (entra
   stock virtual) y se refactura desde la 013-NC (sale ese stock). La SPEC-22 resta la NC en la
   sucursal de origen y cuenta la refactura como venta de Santiago: **la demanda se muda de la
   sucursal a Santiago**. Al 2-nov: 8.837 u refacturadas desde la 013-NC en 12 meses. Si OINM no
   registró la NC (unas 2.400 u), la refactura además se suma a la venta original (doble conteo).

## 3. Regla

### 3.1 Bodegas de Cobranzas (013-NC, 013-NC_E) fuera del consumo

Ningún movimiento de una bodega `NO_CONFORME` (`warehouses.es_nc_comercial`) cuenta como consumo:
ni la NC, ni la refactura (`FACTURA`), ni entregas o salidas. La mercadería no volvió físicamente:
la venta original de la guía sigue siendo demanda real en su sucursal. La carga informa las unidades
descartadas.

### 3.2 NC física: se resta donde está la guía

Para las NC de las demás bodegas (013-IN, sucursales) se mantiene la SPEC-22 §1 (solo se reubica lo
que registró OINM, nunca deja negativo el origen, lo no ligado queda donde ocurrió), con un cambio:
la celda de origen es la de la **guía** cuando la consulta 15 la trae, y la de la factura si no.

### 3.3 Consulta 15

Agrega tres columnas al final: `numero_guia`, `bodega_guia`, `fecha_guia`. La guía se obtiene:

- factura basada en guía: `inv1.basetype = 15` → `dln1` (`baseentry`, `baseline`);
- factura de reserva: la primera `dln1` con `basetype = 13` sobre esa línea de factura;
- NC directa sobre una guía (`rin1.basetype = 15`): esa misma guía.

Las líneas de `dln1` se deduplican por (`docentry`, `linenum`) (el Datalake repite filas, ver la
bitácora del 29-oct). Un archivo de 10 columnas (exportado antes del 2-nov) sigue funcionando con la
regla anterior (factura).

## 4. Fuera de alcance

- La compensación NC ↔ refactura en otras bodegas (propuesta en la bitácora) no se implementa: con el
  flujo guía → factura, una refactura fuera de la 013-NC no mueve stock y no está en OINM.
- NC registradas en la 013-IN que OINM no tiene (4.069 u en documentos, 1.357 u en OINM al 2-nov):
  RESUELTO el 2-nov. La tabla `oinm` del Datalake está incompleta (por ejemplo, ago-26 trae 59 % menos que
  `oivl`). La consulta 8 pasó a leer `oivl`, y la brecha de NC bajó de 2.712 u a 9 u, sin necesidad de
  una regla nueva. Se reportó al dueño del Datalake.
- Proceso (César, 2-nov): una bodega de NC por sucursal resolvería el problema de raíz.
