# SPEC-20: Ficha única del artículo y recálculo único

Estado: **implementado** (27-oct-2026).
Depende de: SPEC-19. Completa su §2 (fuente única) en la navegación y en los botones de recálculo.

## 1. Problema

SPEC-19 unificó los **números** (la Calculadora publica en `StockProjection` y
`SKUClassification`), pero quedaron dos caminos que contradecían la fuente única:

1. **Dos fichas de artículo.** El Dashboard, el Reporte Gerencial, Consultar Stock y el
   Recomendador enlazaban a `/inventory/sku/<código>/`, la ficha del motor anterior: consumo
   desde PC/OF, clasificación "REPO PESCO" y proyección por bodega. La Calculadora tiene su
   propia ficha (`/calculadora/articulo/<código>/`) con consumo OINM, E/R/P/O, ABC-XYZ,
   memoria de cálculo y proyección de 120 días. Un gerente podía ver dos diagnósticos distintos
   para el mismo código.
2. **Recálculos que despublicaban.** "Recalcular S&OP" (Configuración) y la acción
   `sync_engine` (Sincronizar) corrían **solo** el motor anterior, que reescribe
   `StockProjection` y `SKUClassification`. Tras usarlos, el Dashboard volvía a los números
   antiguos hasta la siguiente sincronización.

## 2. Decisión

* **Una sola ficha**: la de la Calculadora. `inventory:sku_detail` se conserva como URL y
  redirige (302) a `calculadora:articulo`, para no romper marcadores ni enlaces copiados.
  Se elimina la plantilla `inventory/sku_detail.html`; queda en el historial de git (2513a8a).
* **Un solo recálculo**: `servicio.recalcular_red(usuario, recargar)` ejecuta, en orden,
  motor anterior → `capturar_escenario_actual()` → (cargadores si `recargar`) →
  `ejecutar_corrida()`, que publica. Lo usan Sincronizar (`recargar=True`), "Recalcular S&OP"
  de Configuración y `sync_engine`. "Recalcular ahora" del Panel sigue corriendo solo la
  Calculadora (el escenario actual capturado sigue vigente).
* **Recomendador**: solo se llega desde Indicadores ("Ver escenario anterior"). Los botones
  "Recomendador" del Reporte Gerencial y de Configuración pasan a "Calculadora"; el enlace
  "Ver Recomendador S&OP" del Dashboard pasa a "Ver grilla de compras". Los códigos dentro del
  Recomendador también abren la ficha de la Calculadora.

## 3. Lo que se trae de la ficha anterior

Lo único que la ficha anterior tenía y la de la Calculadora no: los **documentos cerrados** que
respaldan el consumo. Nueva sección "Movimientos recientes" en el detalle del artículo:

| Tabla | Fuente | Filtro | Columnas |
|---|---|---|---|
| Despachos de PC cerrados | `SalesOrderMovement` | `status='Cerrado'`, últimos 25 por entrega | PC, entrega, bodega, cliente, cantidad |
| Consumo en OF cerradas | `ProductionOrderMovement` | `status='Cerrada'`, últimos 25 por término | OF, término, bodega, cantidad |

Los PC y OF abiertos ya aparecen en "Compromisos abiertos". La nota al pie aclara que el
consumo del cálculo viene del kárdex (OINM), que incluye otras salidas.

No se trae: el gráfico de consumo con forecast (lo reemplazan el gráfico de consumo mensual y
la línea histórico + proyección de SPEC-19 §5) ni la tarjeta "Clasificación REPO PESCO"
(reglas reemplazadas por SPEC-09).

## 4. Criterios de aceptación

* Ninguna plantilla usa `{% url 'inventory:sku_detail' %}`; `purchasing:list` solo aparece en
  Indicadores y en el propio Recomendador (test de guarda en `tests/test_unificacion_articulo.py`).
* `/inventory/sku/<código>/` redirige a la ficha de la Calculadora y exige sesión.
* La ficha muestra PC y OF cerrados y no los abiertos.
* Tras "Recalcular S&OP" en Configuración, la última corrida queda `OK`, publicada, y
  `StockProjection.rop` de la central es el punto de pedido de la Calculadora.
