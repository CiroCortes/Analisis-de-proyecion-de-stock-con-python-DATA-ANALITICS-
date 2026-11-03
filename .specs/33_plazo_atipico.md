# SPEC-33: Plazos de entrega atípicos (OC que no reflejan el plazo del proveedor)

Fecha: 3-nov-2026. Origen: revisión del artículo 4201130215 (pistola neumática, pañol herramientas).
Código: `apps/calc/plazo.py`, `apps/calc/params.py`, `apps/calculadora/alertas.py`, ficha del artículo.
Tests: `tests/test_spec33.py`.

---

## 1. Hallazgo

La grilla sugería comprar 8 u de 4201130215 (USD 1 mil) para un consumo de 1,5 u/mes con 9 u disponibles.
El stock de seguridad era 9 u (6 meses de consumo). La causa es una sola OC:

| OC | Proveedor | Emisión → primera entrada | Días |
|---|---|---|---|
| 2402156 | Würth | 07-02-2024 → 27-11-2024 | **294** |
| 2606588 | Würth | 17-06-2026 → 25-08-2026 | 69 |
| Las otras 10 | Würth | — | 2 a 11 |

Esa OC sube el plazo promedio de ~6 a 34,5 días y la variación del plazo a 84 días. Por la fórmula del
stock de seguridad (§4.3), la variación del proveedor explicaba el 90 % del SS.

**Los datos de SAP no están mal: muestran un proceso.** Una OC de un proveedor nacional que entrega en una
semana no tarda 294 días: quedó abierta, se emitió mucho antes de necesitarse o la recepción se registró
tarde. La herramienta lo deja a la vista; corregirlo es tarea de Compras y de gerencia.

## 2. En toda la red (corrida 35, 3-nov)

- **154 OC** (305 líneas) de los últimos 24 meses tienen un plazo atípico, en **239 artículos** (219 son R).
- Plazo atípico mediano: **66 días**, contra un plazo típico mediano de **7 días** en esos mismos artículos.
- Son sobre todo proveedores nacionales: Würth (24 OC), Ferretería Marsella (21), Kupfer (12), Apro (10),
  Treck (8).
- Hay OC con muchos artículos atrasados a la vez (OC 2606894: 17 artículos, 58 días; OC 2501626: 15
  artículos, 96 días): parece una OC completa que quedó abierta o se recibió tarde, no un artículo con
  quiebre en el proveedor.
- Por año de emisión: 2024 = 25, 2025 = 65, 2026 = 64. **Sigue ocurriendo.**

Lista para Compras: `data/OC_plazo_atipico_2026-11-03.xlsx` (local, no se sube), con una columna "Causa"
para completar.

## 3. Regla

Con las OC válidas del artículo (0 a 365 días, ventana `meses_historia_oc`) y solo si hay
`min_oc_plazo_real` (3) o más:

1. **Tope** = el mayor entre `multiplicador_plazo_mediana` × mediana y mediana + `dias_min_plazo_atipico`.
2. Las OC sobre el tope **se recortan al tope** (no se borran): el promedio y la variación del plazo usan
   la serie recortada. Se recorta y no se excluye porque una parte puede ser atraso real del proveedor.
3. Con `multiplicador_plazo_mediana` = 0 rige la regla del documento (sin tope).

Es la misma idea de los picos de consumo (SPEC-26): la mediana no se mueve con uno o dos casos extremos.
Los días mínimos evitan marcar como atípico una OC de 11 días cuando la mediana es 2, y una importación
pareja (mediana de 120 días) solo se marca sobre 480 días.

| Clave | Etiqueta | Defecto | Rango | Niveles |
|---|---|---|---|---|
| multiplicador_plazo_mediana | Plazo atípico: veces la mediana de los plazos de OC (0 = sin tope) | 4 | 0–20 | G |
| dias_min_plazo_atipico | Plazo atípico: días mínimos sobre la mediana | 30 | 0–365 | G |

Caso 4201130215: mediana 6, tope 36. Plazo 34,5 → 10,3 días; SS 9 → 3; punto de pedido 12 → 5; máximo
17 → 10; **compra 8 → 0**.

## 4. Alerta `PLAZO_ATIPICO`

Una por artículo, con las 3 OC más largas (número, días, mes de emisión y de entrada), el tope y el plazo
típico. **MEDIA** si el artículo necesita compra; **BAJA** si no. Mensaje: "Revisar con Compras si la OC
quedó abierta o la recepción se registró tarde". Corrida 35: 239 alertas.

En la ficha, las OC atípicas se marcan en ámbar en la tabla de plazos, y la memoria de cálculo indica
cuántas OC se recortaron y a cuántos días.

## 5. Impacto (misma fecha, corrida 34 sin tope vs. 35 con tope)

| | Sin tope | Con tope |
|---|---|---|
| Artículos que necesitan compra | 1.073 | 1.061 (−12) |
| Valor del stock máximo | USD 6,482 M | USD 6,467 M (−15 mil) |
| Cantidad a comprar de los 239 artículos | — | −USD 9,8 mil |
| Sugerido de hoy | USD 3,35 M | USD 3,35 M (hoy no les toca compra a estos proveedores) |

**El impacto en dinero es chico; el valor está en el hallazgo de proceso.** Son artículos baratos de
proveedores nacionales, pero con un stock de seguridad de 2 a 3 veces lo necesario (por ejemplo 4602240012:
SS 1.555 → 570 u). El ahorro se nota en el inventario, no en una compra puntual.

## 6. Ficha: "Compra de la red"

La tabla "Posición y acción por nodo" muestra traslados entre bodegas; la compra se decide para toda la
red (SPEC-11 §2) y no aparecía ahí. Se agrega una línea sobre la tabla: "Compra de la red: 8 u a la
013-PP, hoy · llegaría el 09-12", o "no se sugiere compra". Así la grilla y la ficha no parecen
contradecirse (consulta del usuario, 3-nov).

## 7. Para gerencia

1. **Revisar las 154 OC con Compras** (lista en Excel) y clasificar la causa: OC que quedó abierta,
   OC emitida antes de tiempo (compra programada), recepción registrada tarde o atraso real del proveedor.
2. **Definir una regla de proceso**: por ejemplo, cerrar o revisar cada mes las OC nacionales con más de
   30 días sin recepción. La alerta `OC_ATRASADA` ya las muestra en las OC abiertas (385 hoy).
3. Si se confirma que son atrasos reales de un proveedor, es información para negociar (plazo comprometido
   vs. real) y se puede subir `dias_min_plazo_atipico` para ese caso.
