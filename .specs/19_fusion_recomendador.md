# SPEC-19: Fusión del Recomendador en la Calculadora

Estado: **en implementación** (rama `feature/fusion-recomendador`, 27-oct-2026).
Depende de: SPEC-10 a SPEC-18. Reemplaza la convivencia descrita en SPEC-18 §5.

## 1. Objetivo

Un solo motor y una sola verdad (documento §1: "un solo motor de cálculo para todo").
La Calculadora pasa a ser la fuente de todas las pantallas; del Recomendador se conserva lo
que el usuario ya conoce y valora: la mirada **por bodega y zona**, la **foto del inventario
en el tiempo** y la **segmentación** de artículos. El sistema debe poder usarlo un gerente de
Abastecimiento sin conocer las fórmulas: cada número dice qué significa y qué hacer con él.

### Qué se absorbe y qué no

| Del Recomendador | Decisión | Cómo |
|---|---|---|
| Vista por bodega, filtro Santiago / Sucursales, pastillas por acción | **Se absorbe** | Pantalla "Bodegas" (§4) |
| Cobertura en días por bodega | **Se absorbe** | Consumo diario por bodega (§3.2) |
| Reconstrucción histórica del inventario (dashboard) | **Se absorbe** | Histórico + proyección en el detalle del artículo (§5) |
| ABC por frecuencia (A–D por meses con movimiento) | **Se transforma** | Eje XYZ de variabilidad y matriz ABC-XYZ (§6) |
| Motivos legibles de la política ("Caso 2: demanda apagada") | **Se absorbe** | Motivo en lenguaje simple de la letra y la acción |
| Compra por bodega, acción MIXTO, compra hasta el punto de pedido | **No** | El documento las reemplaza (§5, §11) |
| "Monto total de quiebre" que mezcla brecha y quiebre | **No** | Se publica el quiebre real (disponible < 0) |
| Reglas REPO antiguas (R ≥ 2 meses, servicio 90/85/80) | **No** | Rige SPEC-09 |

## 2. Fuente única: publicación en las tablas que usa el resto del sistema

El Dashboard, el Reporte Gerencial, el Asistente IA, el detalle de SKU y el Recomendador leen
`StockProjection` (por artículo y bodega) y `SKUClassification` (por artículo). En vez de
reescribir esas pantallas, la Calculadora **publica** sus resultados en esas tablas al final
de cada corrida. Así todo el sistema muestra los mismos números el mismo día.

### 2.1 Escenario actual (motor anterior)

El motor anterior se sigue ejecutando en el pipeline solo para el panel "actual vs propuesto".
Su resultado se guarda en `EscenarioActual` (artículo × bodega: ROP, sugerido de compra,
acción, letra) **antes** de que la Calculadora publique. La corrida lee el escenario actual de
esa tabla (si está vacía, de `StockProjection` como hasta ahora).

### 2.2 Publicación en `StockProjection` (una fila por artículo y bodega con posición)

| Campo | Valor publicado |
|---|---|
| `rop` | Central: punto de pedido de la red. Otras: objetivo de la bodega (lo comprometido) |
| `safety_stock` | Central: stock de seguridad de la red. Otras: 0 |
| `coverage_days` | Disponible de la bodega ÷ consumo diario de la bodega (0 si no hay consumo) |
| `shortage_units` / `shortage_usd` | **Quiebre real**: max(0, −disponible) de la bodega × costo |
| `suggested_buy_units` | Central: cantidad a comprar de la red (día de compra o excepción). Otras: 0 |
| `suggested_transfer_units`, `transfer_source_warehouse` | Del reparto (§5 del documento); origen principal |
| `action_type` | Central con compra: COMPRAR. Otras: TRASLADAR / TRASLADAR_PARCIAL / ESPERA_COMPRA / NINGUNA |
| `urgency_level` | URGENTE si disponible ≤ 0 con objetivo o compra; MEDIO si bajo SS o con faltante; NORMAL |

`ACTION_CHOICES` agrega TRASLADAR_PARCIAL y ESPERA_COMPRA; MIXTO queda solo por compatibilidad
histórica (la Calculadora no lo produce).

### 2.3 Publicación en `SKUClassification`

`repo_category` = letra de la Calculadora; `abc_class` = ABC por valor; `stock_policy` = SI_STOCK
para R y E, NO_STOCK para P y O, con `stock_policy_reason` = motivo en lenguaje simple;
`is_new`, `is_inmovilizado`, `service_level`, `z_factor`, `rop_statistical`,
`safety_stock_statistical`, `stock_max_statistical`, `avg_monthly_consumption`,
`std_monthly_consumption`, `consumption_freq_12m`, `avg_daily_demand`, `annual_demand_units`,
`has_active_of_or_pc` = valores de la Calculadora. `segment` se conserva (PANOL / REPUESTOS).

Consecuencia visible: el "quiebre USD" del Dashboard pasa de la brecha contra el objetivo
(USD 96 M, motor anterior) al quiebre real. El Reporte Gerencial lo explica en una nota.

## 3. Cambios en el cálculo

### 3.1 Eje XYZ (variabilidad del consumo)

`cv = variacion_consumo ÷ consumo_promedio_mes` (coeficiente de variación de 12 meses).

| Clase | Regla | Lectura |
|---|---|---|
| X | cv ≤ `corte_xyz_x` (0,5) | Estable: se puede automatizar |
| Y | cv ≤ `corte_xyz_y` (1,0) | Variable: revisar en cada compra |
| Z | cv > 1,0 o sin consumo | Errático o esporádico: criterio del comprador |

Parámetros nuevos (SPEC-14): `corte_xyz_x`, `corte_xyz_y`, nivel GENERAL.
Se guarda en `ResultadoArticulo.xyz` y `HistorialMensual.xyz`.

### 3.2 Consumo y cobertura por bodega

`consumo_diario_bodega = consumo de la bodega en 12 meses cerrados ÷ 365` (ConsumoMensual por
bodega, con la atribución de SPEC-07 §5). `cobertura_dias_bodega = disponible ÷ consumo diario`.
No cambia la compra (que es de la red); solo informa dónde se acaba primero el stock.
Campos nuevos en `ResultadoBodega`: `consumo_diario`, `cobertura_dias`.

### 3.3 Inventario histórico por artículo

`stock_fin_mes(m−1) = stock_fin_mes(m) − entradas(m) + consumo(m)`, desde el stock físico de hoy
hacia atrás 12 meses cerrados (mismo método del dashboard). Entradas = Entradas de Mercancía
(GoodsReceipt); consumo = ConsumoMensual de la red. Valores negativos se muestran como 0 y
marcan "dato inconsistente" (falta un movimiento). Función pura `calc.historico.reconstruir`.

## 4. Pantalla "Bodegas" (`/calculadora/bodegas/`)

Para el comprador y el jefe de bodega: "¿qué bodega está en riesgo y qué se mueve?".
- Filtro de zona (Santiago / Sucursales), bodega, acción, urgencia, búsqueda.
- Tarjetas por bodega: artículos en riesgo, quiebre real USD, traslados entrantes y salientes,
  artículos en espera de compra, cobertura mediana.
- Pastillas clicables por acción (Trasladar / Parcial / Espera compra).
- Tabla artículo × bodega: disponible, objetivo, faltante, cobertura en días, acción, origen,
  urgencia. Orden: Santiago primero, luego sucursales; dentro, mayor urgencia y menor cobertura.
- Exportación a Excel.

## 5. Detalle del artículo: pasado y futuro en un gráfico

Una línea continua: 12 meses de inventario reconstruido (§3.3) + 120 días proyectados, con
bandas de stock de seguridad, punto de pedido y máximo, llegadas de OC y el día de quiebre.

## 6. Pantalla "Segmentación" (`/calculadora/segmentacion/`)

Matriz 3×3 ABC (valor) × XYZ (variabilidad). Cada celda: n° de artículos, valor del stock,
valor a comprar, y una recomendación en lenguaje simple. Clic en la celda abre la grilla
filtrada. Recomendaciones (editables en una versión futura):

| | X (estable) | Y (variable) | Z (errático) |
|---|---|---|---|
| **A** | Automatizar con revisión semanal | Revisar cada compra | Decidir con el comercial; evitar sobrestock |
| **B** | Automatizar | Automatizar con revisión mensual | Revisar antes de aprobar |
| **C** | Automatizar al máximo | Automatizar | Comprar a pedido o lote mínimo |

## 7. Experiencia para el usuario gerencial

1. **Inicio de la Calculadora = "Qué hay que hacer hoy"**: 4 tarjetas de acción con frase simple
   y botón ("12 proveedores tienen día de compra hoy por USD 85 mil → Revisar solicitudes";
   "409 artículos se quiebran antes de la próxima compra → Ver excepciones"; "53 traslados
   urgentes → Ver bodegas"; "Alertas altas sin revisar → Ver alertas").
   Debajo, el estado de los datos en semáforo (verde = real, amarillo = provisional, rojo = falta).
2. **Guía** (`/calculadora/guia/`): glosario en lenguaje simple (qué es R, E, P, O, ABC, XYZ,
   stock de seguridad, punto de pedido, máximo, disponible a futuro, excepción, traslado
   parcial, espera compra) con un ejemplo numérico de cada uno y "qué hacer" cuando aparece.
3. **Ayuda en contexto**: los títulos de columnas y tarjetas llevan un ícono (?) con la
   definición corta del glosario (`title`), sin salir de la pantalla.
4. **Menú**: "Recomendador" sale del menú principal; queda accesible desde Indicadores como
   "Escenario anterior". La URL `/purchasing/` sigue funcionando.

## 8. Criterios de aceptación

- Tras una corrida, `StockProjection` y `SKUClassification` contienen los valores de la
  Calculadora; el Dashboard, el Reporte Gerencial y el Recomendador muestran la misma compra
  de la red y el mismo quiebre real que la Calculadora.
- La comparación "actual vs propuesto" sigue usando el motor anterior (EscenarioActual).
- XYZ, cobertura por bodega e histórico con tests unitarios (núcleo puro) y de servicio.
- Pantallas Bodegas, Segmentación y Guía responden < 1 s con la base real.
- Suite completa en verde.

## 9. Fuera de alcance

Reescribir las consultas del Dashboard sobre los modelos de la Calculadora (la publicación lo
hace innecesario por ahora); recomendaciones editables por celda ABC-XYZ; políticas
distintas por segmento (podría venir en SPEC-20 si Abastecimiento lo pide).
