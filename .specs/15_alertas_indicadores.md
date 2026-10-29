# SPEC-15: Alertas, Indicadores e Impacto

Documento fuente: §8. Código: `apps/calculadora/alertas.py`, `apps/calc/simulacion.py`,
`apps/calculadora/servicio.py` (`_simulaciones`, `_resumen`), `solicitudes.intervencion_comprador`.
Pantallas: `/calculadora/alertas/`, `/calculadora/indicadores/`.

---

## 1. Alertas (`generar`, al final de cada corrida)

| Tipo | Condición | Severidad | Clave |
|---|---|---|---|
| QUIEBRE_PROYECTADO | `excepcion`; texto con días de quiebre inevitable | ALTA | tipo + sku |
| BAJO_SS_PROYECTADO | Sin excepción, disponible ≥ SS y `fecha_bajo_ss` dentro de 15 días | MEDIA | tipo + sku |
| OC_ATRASADA | Alguna OC con fecha comprometida vencida | MEDIA | tipo + sku |
| URGENTE | Artículo activo (máximo > 0 o P) con disponible ≤ 0 | ALTA | tipo + sku |
| BAJO_SS | No urgente y disponible < SS | MEDIA | tipo + sku |
| SOBRESTOCK | Disponible > máximo + 3 × consumo | BAJA | tipo + sku + mes |
| CAIDA_CONSUMO | R con 3 meses en cero, o promedio 3 meses < 50% del promedio | MEDIA / BAJA | tipo + sku + mes |
| ALZA_CONSUMO | **Solo R/E**: promedio 3 meses > 150% del promedio | MEDIA | tipo + sku + mes |
| CONSUMO_IRREGULAR | **Solo R/E**: desvest 6 meses difiere > 50% de la de 12 | BAJA | tipo + sku + mes |
| NUEVO_CONSUMO | P u O con consumo en 2 de los últimos 3 meses | MEDIA | tipo + sku + mes |
| PICO | **Solo R/E**: mes recortado por pico de consumo (SPEC-26) | BAJA | tipo + sku + mes del pico |
| CAMBIO_LETRA | `HistorialMensual` del mes con letra anterior distinta | MEDIA | tipo + sku + mes |
| TRASLADO_SUCURSALES | Bodega en espera y otra sucursal con stock libre | MEDIA | tipo + sku + bodega |
| EVENTO_COMERCIAL | Evento propuesto pendiente; o aprobado vencido con consumo real < 50% de lo anunciado | MEDIA / BAJA | tipo + pend/venc + id |
| CONTRATO | Acuerdo que vence en ≤ 60 días; o línea de solicitud sin contrato / sobre saldo (al generar solicitudes) | MEDIA / BAJA | tipo + acuerdo + línea / sku + proveedor |
| DATOS | Avisos del motor (sin costo, sin plazo, plazo inválido o 50% sobre maestro, nuevo sin mínimo, bloqueado) o sin proveedor con necesidad de compra; solo R/E/P o con necesidad | BAJA | tipo + sku |

Alza e irregularidad se limitaron a R/E el 27-oct: en P/O cualquier mes con consumo es "alza" y lo
cubre NUEVO_CONSUMO (en la primera corrida eran 1.803 y 1.488 alertas).

### 1.1 Ciclo de vida

- Las alertas diarias se identifican por tipo + artículo; las mensuales agregan el mes.
- Si la condición se repite, la alerta se **mantiene** (estado, responsable y comentario se
  conservan; mensaje y severidad se actualizan). Si deja de cumplirse queda `vigente = False`.
- Estados: NUEVA → REVISADA → RESUELTA, con responsable y comentario (pantalla de alertas).
- Pendiente: suscripción por correo semanal (§8 del documento).

## 2. Resumen de la corrida (`Corrida.resumen`)

Artículos, letras, comprar hoy, necesitan compra, excepciones, urgentes, valor sugerido, valor del
stock máximo, traslados y unidades, **quiebre real** (Σ −disponible × costo con disponible < 0) y
**brecha contra objetivo** (Σ faltante × costo), separados como pide el documento (§5, §12).

Corrida del 27-oct con consumo provisional PC/OF: 18.026 artículos; R 2.471, P 580, O 14.975, E 0;
271 a comprar hoy, 1.047 necesitan compra, 409 excepciones, 529 traslados; USD 3,16 M sugerido;
quiebre real USD 717 mil vs brecha USD 3,94 M.

## 3. Indicadores: escenario actual vs propuesto (`simular`)

Simulación diaria a 365 días, por artículo y a nivel red, con consumo uniforme (consumo diario
histórico; no pronostica). Solo artículos con consumo y máximo > 0.

| | Escenario actual | Escenario propuesto |
|---|---|---|
| Regla | Motor anterior: compra hasta el ROP (`rop_statistical`) cuando la posición ≤ ROP | Compra hasta el máximo cuando la posición ≤ umbral |
| Revisión | Todos los días (sin calendario) | Días de compra del proveedor (frecuencia, desde la próxima fecha; día 0 = hoy si es día de compra) |
| Plazo | Maestro + 2 | Plazo total (real o maestro + recepción) |
| Mínimos | — | MAX(MinOrdrQty; meses mínimos × consumo), múltiplo |

Inicio: físico − comprometido de la red, más las llegadas de OC actuales. Posición = disponible +
pedido en camino. Se guarda en `ResultadoArticulo.simulacion` = `{'prop'|'act': {inv: [90, 180,
365 días], dq: días en quiebre, na: unidades no atendidas, cm: compras por mes (6)}}`.

| Indicador | Cálculo |
|---|---|
| Inventario proyectado (USD) | inv × costo a 3, 6 y 12 meses, ambos escenarios y diferencia |
| Cobertura (meses) | inventario ÷ consumo, ponderado por valor, por familia / letra / ABC |
| Quiebres proyectados | Artículos con dq > 0, días y valor no atendido (na × costo) |
| Compras sugeridas (USD) | cm × costo por mes y proveedor (6 meses) |
| Exceso y obsolescencia | Exceso: valor sobre máximo + 3 meses; obsolescencia: valor de O e inmovilizados |
| Intervención del comprador | `intervencion_comprador` (SPEC-13 §6) |

Los filtros (bodega, familia, proveedor, letra, ABC) se aplican en la vista agregando por artículo.

## 4. Reporte de impacto en valor

Compara `HistorialMensual.valor_stock_maximo` del mes contra el mes anterior, por artículo,
familia y bodega, y muestra los 20 artículos que más mueven el total. Requiere al menos dos meses
de historia (la primera foto es de octubre 2026).
