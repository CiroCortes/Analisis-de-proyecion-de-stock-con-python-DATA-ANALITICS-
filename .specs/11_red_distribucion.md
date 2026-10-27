# SPEC-11: Compra para la Red y Distribución a Bodegas

Documento fuente: §5. Código: `apps/calc/red.py`, `apps/calculadora/servicio.py` (`_entrada`, `_guardar`).
Tests: `test_calc_golden.py::TestCaso4Traslado`, `test_calc_reglas.py::TestRed`.

---

## 1. Bodegas de la red

Bodegas activas con zona (SPEC-07 §4): todas las `013-xx` físicas (central `013-PP`) y las
sucursales `002`, `002-02`, `003`, `008`, `010`. Por bodega (`red.Bodega`):

| Campo | Origen |
|---|---|
| stock_fisico | `InventoryMetric.stock_physical` |
| en_transito | OC + SC + stock en bodegas `T` hacia ella; en 013-PP además las solicitudes aprobadas de la plataforma (SPEC-12 §3) |
| comprometido | PC + OF pendientes atribuidos (`commitment_bodega`) |
| fecha_compromiso | Fecha del compromiso abierto más cercano |

## 2. Compra única de la red

- Totales de la red = suma de las bodegas (`totales_red`). Los traslados entre bodegas no cambian
  el total; el stock en `T` cuenta una vez (en el destino).
- Con ese consumo y disponible se calcula **una sola** cantidad por artículo (SPEC-10), recibida
  en 013-PP. Las bodegas no generan compras propias.

## 3. Objetivo por bodega (`objetivo_bodega`)

| Letra | Objetivo |
|---|---|
| R, E, P | Lo comprometido localmente (la central guarda además el resto del stock de la red) |
| O | 0 |

`faltante = MAX(0; objetivo − disponible_futuro)`.

### 3.1 Conflicto: doble conteo del compromiso (caso 4)

El caso 4 del documento (002: comprometido 1, disponible −1 → faltante 2) fija
`faltante = objetivo − disponible`, donde `disponible` **ya descuenta** el compromiso. El
compromiso se cuenta dos veces: una sucursal con stock = comprometido (disponible 0) igual
muestra faltante = comprometido y pide traslado.
**Se implementó literal para cumplir el caso dorado.** Propuesta para Abastecimiento: objetivo
de sucursales = 0 sobre el disponible (o faltante = MAX(0; −disponible)); en el caso 4 daría 1.
Requiere corregir el caso 4 del documento. Decisión abierta.

## 4. Reparto (`distribuir`)

1. **Excedente** de las otras bodegas de Santiago (no central): disponible − objetivo, si > 0.
2. **Stock libre de la central**: físico − compromisos propios − traslados ya sugeridos. Lo
   comprometido en 013-PP nunca se traslada; el tránsito de la central no se reparte.
3. Lo que no se cubre queda en **ESPERA COMPRA** (ya está en la compra de la red).

- La central también puede pedir (si su disponible no cubre sus propios compromisos), pero solo
  a excedentes de otras bodegas de Santiago.
- Prioridad entre solicitantes: primero los URGENTES (disponible ≤ 0), después la fecha
  comprometida más cercana, después el código.
- Donantes: el de mayor excedente primero (menos traslados). Una bodega puede recibir de varios
  orígenes (`origenes`).

| Situación | Acción |
|---|---|
| Se cubre todo | TRASLADAR |
| Se cubre una parte | TRASLADAR_PARCIAL (resto en espera) |
| No hay stock libre | ESPERA_COMPRA |
| Sin faltante | NINGUNA |

- Si una sucursal queda esperando y otra sucursal tiene disponible sobre su objetivo, se anota en
  `sucursales_con_stock` y se genera la alerta `TRASLADO_SUCURSALES` (el comprador decide).
- Traslados entre sucursales no se sugieren automáticamente.

## 5. Persistencia

- `ResultadoBodega`: solo bodegas con stock, tránsito, compromiso o faltante.
- `TrasladoSugerido`: origen, destino, cantidad; urgencia URGENTE si el destino tiene disponible ≤ 0.
- Los traslados se recalculan a diario; las compras siguen el calendario (SPEC-12).

## 6. Observación con datos reales

Corrida del 27-oct con consumo provisional PC/OF: 529 traslados. Los más grandes van de 013-09 y
013-07 a 013-PP (hasta 7.000 u) para cubrir compromisos de OF de la central; ligado a la
sospecha de OF con cantidades enormes (2,7 M u en 013-PP, SPEC-00).
