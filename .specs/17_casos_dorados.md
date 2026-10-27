# SPEC-17: Casos de Prueba Dorados

Documento fuente: §10. Criterio de aceptación de la fase de cálculo (§13): los casos 1 a 5 deben
dar exactamente estos resultados. Archivo: `tests/test_calc_golden.py`. Estado al 27-oct-2026:
**todos en verde** (11 tests), junto con 45 tests de reglas en `tests/test_calc_reglas.py`.

```
python -m pytest tests/test_calc_golden.py tests/test_calc_reglas.py -q
```

---

## Caso 1: R-Regular (`TestCaso1RRegular`)

Entrada: clase A, no crítico. Consumo 2, 0, 3, 1, 0, 2, 4, 1, 0, 3, 2, 2. OC: 40, 52, 48, 38, 47 días.
Stock 4, tránsito 0, comprometido 1. Mínimo 5, múltiplo 5.

| Campo | Esperado |
|---|---|
| consumo_promedio_mes / variacion_consumo | 1,67 / 1,30 |
| dias_entrega_promedio / variacion | 45 / 5,83 |
| plazo_total_meses | 1,57 |
| ss_calculado / piso | 3,13 / 3,33 |
| stock_seguridad / punto_pedido / stock_maximo | 4 / 8 / 13 |
| disponible_futuro | 3 → entra en la compra |
| cantidad_sugerida | 10 |

También se verifica de punta a punta con `calcular_articulo` (letra R, subclase REGULAR).

## Caso 2: R-Intermitente (`TestCaso2RIntermitente`)

Consumo en 3 de 12 meses, mayor consumo 12, salidas extra 1.

| plazo_total_meses | salidas_en_plazo | punto_pedido | stock_maximo |
|---|---|---|---|
| 2 | 1 | 12 | 24 |
| 6 | 2 | 24 | 36 |
| 9 | 3 | 36 | 48 |

## Caso 3: 81310204 KIT ELECTRICO GRUAS HIAB, 013-PP (`TestCaso3KitElectricoHiab`)

R, clase A, plazo SAP 7 días sin OC, costo USD 166,78, stock 12, OF 9.

| Campo | Esperado |
|---|---|
| plazo_total_meses / variación | 0,3 / 0,058 |
| ss_calculado | 8,76 |
| stock_seguridad / punto_pedido / stock_maximo | 23 / 33 / 68 |
| disponible / cantidad | 3 / 65 |
| valor | USD 10.841 |

**Inconsistencia del documento**: indica consumo anual 146 (⇒ promedio 146 ÷ 12 = 12,17) pero
calcula con promedio 11,5 y variación 8,42. El test entrega 11,5 / 8,42 directamente a la
política. Pedir a Abastecimiento que corrija el dato en el documento.

## Caso 4: 31302313 FILTRO RETORNO, 002 (`TestCaso4Traslado`)

002: comprometido 1, disponible −1, objetivo 1 ⇒ faltante 2. 013-03 con 2 disponibles sin
necesitarlos ⇒ **TRASLADAR 2 desde 013-03 a 002, sin comprar**.
Ver el conflicto de doble conteo en SPEC-11 §3.1.

## Caso 5: compra fuera de calendario (`TestCaso5FueraDeCalendario`)

Próxima compra en 12 días, plazo 10, recepción 2, stock 6, sin OC, consumo diario 0,5, pedido de 4
unidades a 2 días.

| Campo | Esperado |
|---|---|
| stock_proyectado días 1–5 | 5,5 · 1 · 0,5 · 0 · −0,5 |
| fecha_quiebre_proyectada | día 5 |
| fecha_llegada_posible | día 24 |
| excepcion | sí |
| dias_quiebre_inevitable | 7 |

## Regla

Si una fórmula cambia, primero se cambia el documento o la spec, después el test dorado y al final
el código. Un test dorado en rojo bloquea la entrega.
