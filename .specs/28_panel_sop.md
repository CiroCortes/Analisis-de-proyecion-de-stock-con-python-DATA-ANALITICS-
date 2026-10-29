# SPEC-28: Panel S&OP (fusión de Dashboard y Analítica)

Fecha: 29-oct-2026. Origen: revisión de las pantallas gerenciales. Dashboard y Analítica leían lo
que publica la Calculadora (SPEC-19), pero volvían a sumar con otras definiciones y no cuadraban:

| Indicador | Dashboard / Analítica | Calculadora |
|---|---|---|
| Urgentes | 502 (un artículo cuenta si cualquier nodo es urgente) | 200 |
| Quiebre | USD 692 mil (suma por nodo) | USD 662 mil |
| Compra sugerida | 27.168 "unidades" (suma de artículos distintos) | USD 2,04 M |

Además, el histograma de cobertura contaba 7.960 filas de artículos que no se reponen como "sin
stock", y la matriz de riesgo mezclaba unidades de artículos distintos.
Código: `apps/dashboard/panel.py`, `dashboard_home_view`, `templates/dashboard/home.html`.
Tests: `tests/test_panel_sop.py`.

---

## 1. Regla

- Una sola pantalla, **Panel S&OP** (`/`). `/analytics/` redirige al panel con sus filtros.
- Fuente: la última corrida OK de la Calculadora (`ResultadoArticulo`, `ResultadoBodega`, `Alerta`).
- **Sin filtros, cada KPI es idéntico al resumen de la corrida** (mismas fórmulas que
  `servicio._resumen`; lo verifica un test).
- Todo en USD. Nunca se suman unidades de artículos distintos.

## 2. Contenido

1. **KPI**: compra sugerida hoy (día de compra + excepciones), necesitan compra en el ciclo,
   quiebre real (disponible futuro < 0) con urgentes, stock de la red con sobrestock (misma regla
   que la alerta), brecha contra el objetivo.
2. **Red por nodo**: stock, faltante y excedente en USD, urgentes y traslados que recibe;
   gráfico de faltante por nodo.
3. **Por política REPO**: artículos, stock, compra hoy y necesidad por R, E, P y O.
4. **Cobertura solo de R y E** (los que deben tener stock), por tramos de días.
5. **Compra sugerida por corrida**: muestra saltos por cambios de datos o parámetros.
6. **Alertas vigentes** por tipo, con enlace a la lista filtrada.
7. **Mayores compras de hoy**, con enlace a la ficha del artículo.
8. **Origen de los datos**: última carga de cada consulta.

Filtros en una fila: grupo, política REPO, clase ABC.

## 3. Se quitó

- La pantalla Analítica y sus 5 APIs de gráficos (urgencias por bodega, quiebre por bodega,
  top quiebre, histograma de cobertura, matriz de riesgo).
- En el Reporte Gerencial, "días de quiebre" pasa a llamarse **días de demanda faltante**
  (faltante ÷ demanda diaria; no son días sin stock).

## 4. Hallazgo con la corrida 20

1.594 de 2.264 artículos R/E (70 %) tienen más de 180 días de stock; sobrestock USD 1,49 M y
excedente de Santiago USD 4,8 M sobre su objetivo. La red está más cargada de stock que en riesgo
de quiebre (USD 662 mil).
