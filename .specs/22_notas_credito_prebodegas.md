# SPEC-22: Notas de crédito en el consumo y pre-bodegas como tránsito

Fecha: 28-oct-2026. Origen: reunión S&OP del 28-oct con Abastecimiento y Producción.
Código: `apps/calculadora/cargadores.py`, `apps/data_ingestion/warehouses.py`,
`apps/data_ingestion/datalake_ingest.py`. Consultas 5 (modificada) y 15 (nueva).
Tests: `tests/test_notas_credito_prebodegas.py`.

---

## 1. Notas de crédito

### Problema (planteado por Abastecimiento)

Un ejecutivo factura en una sucursal y el repuesto sale de otra; la factura se anula con una nota
de crédito (NC) y se vuelve a facturar donde corresponde. En SAP la NC suele registrarse en la
`013-NC` (o `013-IN`), no en la bodega de la factura. El consumo de la consulta 8 (OINM) resta la
NC donde se registró y en su mes, así que:

- la sucursal de la factura conserva una venta que no ocurrió (demanda inflada);
- Santiago (la 013-NC cae en el nodo Santiago) recibe una devolución que no le corresponde.

Ejemplo real: 30202505, factura de 145 u en Calama (27-ago) anulada por NC en 013-NC (4-sep).
Calama queda con 320 u en agosto y Santiago con −145 u en septiembre.

Datos (consulta 15, 24 meses, 2.765 líneas): 1.536 NC en 013-NC y 820 en 013-IN; 1.130 líneas
(12.432 u) se registran en otro nodo que su factura y 1.172 en otro mes.

### Regla

La consulta 8 separa las NC (TransType 14) con origen `NC`. Al cargar el consumo:

1. Las filas `NC` de OINM **no se suman** donde se registraron.
2. Esa cantidad se resta en la bodega y el mes de la factura o entrega de origen de las líneas de
   NC de esa misma bodega y mes (consulta 15), hasta agotar lo que registró OINM.
3. Lo que no se puede ligar a un origen (NC sin documento base o sin consulta 15) queda como
   devolución donde ocurrió, como antes.
4. Nunca se resta más de lo que tiene la celda de origen. Si la venta original no está en la
   consulta 8 (mes incompleto en el Datalake, ver §4), el resto de la NC queda donde se registró.

**Solo se reubica lo que OINM registró.** Hallazgo de la carga del 28-oct: en 1.014 de 2.032
celdas (artículo, bodega, mes) con NC, OINM no tiene movimiento (390 mil u; un solo caso de 360.000 u
sobre una factura del 31-dic que tampoco movió stock, probablemente una factura de reserva). Una NC sin movimiento no
anula ninguna salida registrada, así que no se resta en ningún lado. Por eso no se usa
`rin1.noinvtrymv` (viene en `N` para todas) ni la cantidad de la NC.

El total de la red no cambia; cambian el **nodo** y el **mes**. Con una consulta 8 sin la marca
`NC` (exportada antes del 28-oct) no se reubica nada y la carga lo informa.

Los meses netos negativos de la red se siguen contando como 0 (SPEC-10 §1, decisión #3).

## 2. Pre-bodegas de importación

| Pre-bodega | Destino |
|---|---|
| `000` (central) | Santiago (`013-PP`) |
| `000-002` | Calama `002` |
| `000-003` | Copiapó `003` |
| `000-008` | Los Ángeles `008` |
| `000-010` | Puerto Montt `010` |
| `000-022` | Antofagasta `002-02` |

- **OC y SC** posteadas en una pre-bodega se acreditan a la bodega destino (`purchase_bodega`).
  Antes no se acreditaban a ningún nodo.
- **Stock físico** en una pre-bodega cuenta como **tránsito** hacia el destino (como las `T…-…`).
  Su `onorder` de OITW no se suma: ya viene en las líneas de OC (evita doble conteo).
- Al 28-oct SAP mostraba 12.630 u pedidas a pre-bodegas y 1.473 u en stock en ellas.

## 3. OC sin corte de 180 días

La consulta 5 trae todas las OC abiertas. Con el corte se perdían OC antiguas aún pendientes
(caso de 200 u en tránsito que no aparecían en Santiago). Las OC vencidas siguen marcándose como
atrasadas (`oc_atrasada`).

## 4. Hallazgo: la consulta 8 no es estable entre exportaciones (28-oct)

Al re-exportar la consulta 8 (27-oct vs 28-oct, mismos 24 meses cerrados) el número de filas por mes
cambia mucho y faltan meses completos: 2025-02 no viene en ninguna de las dos; 2025-07 no viene el
28-oct (1.084 filas el 27-oct); 2026-08 trae 969 filas el 28-oct contra 4.061 el 27-oct; 2025-03 y
2025-10 traían 95 y 63 filas el 27-oct. El OINM del Datalake parece incompleto o en recarga.
Ninguna cifra basada en consumo es confiable hasta cuadrarlo con IT y con el informe de auditoría de
stock de B1 (pendiente #1).
