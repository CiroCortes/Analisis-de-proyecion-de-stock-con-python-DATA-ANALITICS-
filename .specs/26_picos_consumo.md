# SPEC-26: Picos de consumo (tope por mediana)

Fecha: 29-oct-2026. Origen: acuerdo con Abastecimiento. En SAP hay muchos movimientos que no
reflejan la demanda real: PC con muchas salidas, OC con muchas entradas, ciclos de NC y refactura,
árboles de proceso, movimientos no cerrados. Además, el Datalake trae duplicados (bitácora local
`data/bitacora_datalake.md`). Acuerdo: tratarlos como **picos** y que la planificación no los tome.
Código: `apps/calc/consumo.py`, `apps/calc/params.py`, `apps/calculadora/alertas.py`.
Tests: `tests/test_picos_consumo.py`.

---

## 1. Problema

La regla del documento (§4.1, SPEC-10 §1) recorta un mes cuando supera **promedio + 3 × desvest**.
El promedio y la desvest se calculan con el pico incluido, así que el tope sube con el pico y casi
no recorta.

Caso real (corrida 18, 29-oct): 40101060, un mes de 34.000 u con mediana de 16 u. El tope quedó en
33.539: se recortaron 461 u y el promedio siguió en 3.986 u al mes. En los 2.264 artículos con
3 o más meses de consumo, 462 tenían un mes de 4 o más veces la mediana con 30 % o más del año.
De esos, 262 no se recortaban y los otros 200 casi nada.

## 2. Regla

Con los meses de la ventana (`meses_historia_consumo`, 12):

1. `mediana_con_consumo` = mediana de los meses con consumo > 0.
2. **Tope** = el menor entre `promedio + multiplicador_atipico × desvest` (regla del documento) y
   `multiplicador_pico_mediana × mediana_con_consumo`. Con `multiplicador_pico_mediana = 0` rige
   solo la regla del documento.
3. Se recortan al tope los meses sobre él, con las mismas condiciones de antes:
   - solo si el artículo tiene `umbral_r` (3) o más meses con consumo (en un esporádico ese mes es
     su consumo normal);
   - los meses con evento comercial aprobado no se recortan (§4.7).
4. **Alza sostenida no es pico**: si 2 o más de los últimos 3 meses superan el tope, es un cambio
   de nivel. Esos meses no se recortan (los cubre la alerta `ALZA_CONSUMO`). Un pico antiguo se
   sigue recortando aunque haya alza reciente.
5. Promedio, desvest, consumo diario, `mayor_consumo_mes` y la previsión (SPEC-24) usan la serie
   recortada, como antes.

¿Por qué la mediana? Uno o dos meses extremos no la mueven, a diferencia del promedio y la desvest.
Es la medida que usan los sistemas de planificación (Slim4 filtra picos de forma parecida).

## 3. Parámetro

| Clave | Etiqueta | Defecto | Rango | Niveles |
|---|---|---|---|---|
| multiplicador_pico_mediana | Pico de consumo: veces la mediana mensual (0 = sin tope) | 4 | 0–20 | G |

Simulación sobre la corrida 18 (demanda media de los artículos con 3 o más meses, en USD/mes):

| k | Artículos afectados | Demanda media |
|---|---|---|
| sin tope | — | 581 mil |
| 3 | 676 | 506 mil (−12,9 %) |
| **4** | **404** | **518 mil (−10,9 %)** |
| 5 | 223 | 525 mil (−9,8 %) |

Se eligió 4: recorta los picos evidentes sin tocar la variabilidad normal de un repuesto.
Valores entre 0 y 2 recortarían consumo normal; no usarlos.

## 4. Alerta PICO

Por cada mes recortado de un artículo R o E (los que se reponen) se genera la alerta `PICO`
(severidad BAJA, clave tipo + artículo + mes del pico). El mensaje indica el mes, la cantidad
original, el tope y la mediana, y pide revisar si fue una venta puntual, un proyecto o un error de
registro. Si fue demanda real que se repetirá, se registra un evento comercial (SPEC-16) y ese mes
deja de recortarse.

`ResultadoArticulo` guarda `meses_atipicos` (índices de `consumo_meses`) y `mediana_con_consumo`.
La memoria de cálculo muestra la regla que mandó (mediana o promedio + 3 desvest) con sus números.

## 5. Resultado (corrida 19, 29-oct, datos deduplicados)

| | Corrida 18 (sin tope por mediana) | Corrida 19 (k = 4) |
|---|---|---|
| Compra sugerida (USD) | 2.212.835 | 2.039.006 (−7,9 %) |
| Artículos que necesitan compra | 767 | 746 |
| Alertas PICO | — | 480 (414 artículos) |

48 artículos cambian su compra y ninguno sube. El mayor es el 40101060 (etiqueta autoadhesiva):
34.000, 8.000 y 6.250 u en oct-dic 2025 y luego 0 a 16 u al mes. Pasa de 15.965 u
(USD 161 mil) a no comprar, con 3 alertas PICO para revisión.

## 6. Fuera de alcance

- El resaltado de meses atípicos por nodo en el detalle del artículo (SPEC-21 §5) sigue con su
  regla visual (`multiplicador_atipico` × promedio del nodo).
- Los meses **faltantes** del Datalake bajan el consumo en vez de subirlo; esta regla no los corrige.
