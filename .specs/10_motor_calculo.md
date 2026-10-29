# SPEC-10: Motor de Cálculo por Artículo (diccionario de campos)

Documento fuente: §4.1–4.6, §9. Código: `apps/calc/` (`consumo.py`, `plazo.py`, `politica.py`,
`motor.py`, `redondeo.py`). Python puro, sin Django.
Tests: `tests/test_calc_golden.py` (casos 1–3) y `tests/test_calc_reglas.py`.

El cálculo es **por artículo para la red**: consumo consolidado de todas las bodegas y disponible
de la red (SPEC-11). Orden en `calcular_articulo`: consumo → plazo → clasificación → método →
política → disponible → compra → distribución → proyección → excepción.

---

## 0. Redondeo

- `redondear_mas(x)` = REDONDEAR.MAS(x; 0) con tolerancia 1e-9 (7,0000000001 → 7). Negativos → 0.
- `al_multiplo(x, m)` sube al múltiplo `OrdrMulti`; `m ≤ 0` solo redondea hacia arriba.

## 1. Consumo (`calcular_consumo`)

| Campo | Cálculo |
|---|---|
| meses | Últimos N meses cerrados (N = 12); si faltan se completan con 0 al inicio; netos negativos → 0 |
| meses_con_consumo_12m | Meses con consumo > 0 |
| consumo_promedio_mes | Σ meses ÷ 12 (los ceros cuentan) |
| consumo_diario | Σ meses ÷ 365 |
| variacion_consumo | DESVEST.M de los 12 meses |
| tope_mes_atipico | El menor entre promedio + 3 × variación y 4 × mediana de los meses con consumo (**SPEC-26**) |
| meses_atipicos | Meses > tope, **solo si meses_con_consumo ≥ umbral_r (3)** y no asociados a evento; si 2 de los últimos 3 superan el tope es alza sostenida y no se recortan (SPEC-26) |
| mayor_consumo_mes | MAX de los meses sin atípicos ni meses de evento; si queda 0, el máximo recortado |

- Los atípicos se recortan al tope (`recortar_atipicos`) y promedio/variación se recalculan con la
  serie recortada.
- **Por qué solo con consumo regular**: con 12 meses, un único mes con consumo siempre supera
  promedio + 3σ (máximo z posible = 11/√12 ≈ 3,18). En un esporádico ese mes es su consumo
  normal; recortarlo lo dejaría fuera de `mayor_consumo_mes` y bajaría su política.
- Meses de evento comercial aprobado no son atípicos (§4.7).

## 2. Plazo (`calcular_plazo`)

| Campo | Cálculo |
|---|---|
| dias_entrega_oc | Plazos de `PlazoOC` (últimos 24 meses); se excluyen < 0 o > 365 (`n_oc_invalidas`, alerta) |
| dias_entrega_promedio | Promedio si hay ≥ 3 OC válidas (`REAL`); si no `OITM.LeadTime` (`MAESTRO`) |
| variacion_entrega_dias | DESVEST.M de los plazos; con maestro: 25% del plazo |
| plazo_total_dias / _meses | (promedio + dias_recepcion) ; ÷ 30 |
| variacion_entrega_meses | variación ÷ 30 |

Lead time maestro = `ParametroCompra.lead_time_maestro` si viene, si no `ProductSKU.lead_time_days`.

## 3. Política general (R-Regular y E) — `politica_general`

| Campo | Fórmula |
|---|---|
| ss_calculado | factor × RAIZ(plazo_meses × var_consumo² + consumo² × var_entrega_meses²) |
| meses_piso_ss | 2 si plazo_total_dias ≤ 60; si no 4 |
| stock_seguridad | REDONDEAR.MAS(MAX(ss_calculado; piso × consumo)); E: MAX con el mínimo declarado |
| meses_revision | frecuencia_compra_dias ÷ 30 (0,5) |
| punto_pedido | REDONDEAR.MAS(c × (plazo_meses + revisión) + SS) |
| stock_maximo | REDONDEAR.MAS(punto_pedido + meses_cobertura × c) |

`c` = consumo promedio, o el **ajustado** por evento comercial (§4.7): el ajuste solo cambia punto
de pedido y máximo; el stock de seguridad usa el historial.

## 4. R-Intermitente — `politica_intermitente`

| Campo | Fórmula |
|---|---|
| salidas_en_plazo | MAX(1; REDONDEAR.MAS(meses_con_consumo ÷ 12 × plazo_meses)) |
| punto_pedido | mayor_consumo_mes × salidas_en_plazo |
| stock_maximo | punto_pedido + mayor_consumo_mes × salidas_extra (1) |
| stock_seguridad | MAX(0; REDONDEAR.MAS(punto_pedido − consumo × plazo_meses)) |

El documento no define el SS de esta regla. Se usa lo que el punto de pedido cubre por sobre el
consumo esperado en el plazo; solo afecta la urgencia MEDIO y las alertas de bajo SS.
**Decisión a validar con Abastecimiento.**

## 5. Métodos especiales

| Situación | Método | Regla |
|---|---|---|
| Bloqueado en SAP (`ParametroCompra.bloqueado`) | SIN_COMPRA | Sin sugerido + aviso |
| Letra O | SIN_COMPRA | No se recompra |
| Letra P | A_PEDIDO | Compra lo comprometido que el stock de la red no cubre: MAX(0; −disponible), al mínimo y múltiplo. **No espera el calendario** (es un pedido concreto) |
| Nuevo (no P) | NUEVO | Punto de pedido = máximo = MAX(mínimo nuevo; mínimo declarado). Sin mínimo: aviso "revisar" |
| R-Intermitente | INTERMITENTE | §4 |
| R-Regular, E | GENERAL | §3 |

## 6. Disponible y compra — `evaluar_compra`

| Campo | Cálculo |
|---|---|
| disponible_futuro | stock_fisico + en_transito − comprometido (red) |
| umbral_compra | punto_pedido + c × meses_revision |
| necesita_compra | disponible ≤ umbral (sin importar el calendario) |
| comprar | necesita_compra **y** hoy es día de compra del proveedor |
| faltante | MAX(0; stock_maximo − disponible) — siempre hasta el máximo |
| cantidad_sugerida | `cantidad_minima`: MAX(faltante; meses_minimo_compra × c; MinOrdrQty) al múltiplo. Se calcula cuando `necesita_compra`, aunque no sea día de compra (la usa la excepción) |
| valor_sugerido | cantidad × costo (USD, `lastpurprc`); en la solicitud, precio del acuerdo |
| urgencia | URGENTE si disponible ≤ 0; MEDIO si < SS; si no NORMAL |
| cobertura_dias | disponible ÷ consumo_diario (vacío sin consumo) |
| valor_stock_maximo | stock_maximo × costo |
| fecha_llegada_estimada | hoy + plazo_total_dias |

Consumo cero (§9): no se sugiere compra, **salvo** E o Nuevo con mínimo (SS > 0 o método NUEVO).

## 7. Avisos de datos

Sin costo; sin plazo (maestro 0 y sin OC); OC con plazo inválido; plazo real > 1,5 × maestro;
nuevo sin mínimo; bloqueado. Alimentan la alerta `DATOS` (SPEC-15).

## 8. Escenario actual

Para el panel (SPEC-15 §3) se guarda junto al resultado el sugerido del motor anterior
(`StockProjection.suggested_buy_units`, compra hasta el punto de pedido) y su valor.
