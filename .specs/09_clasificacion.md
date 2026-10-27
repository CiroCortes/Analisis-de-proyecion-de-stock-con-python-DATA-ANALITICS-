# SPEC-09: Clasificación RPEO, ABC y Nivel de Servicio

Documento fuente: §3. Código: `apps/calc/clasificacion.py`, `apps/calculadora/servicio.py` (`_historial`).
Tests: `tests/test_calc_reglas.py::TestClasificacion`.

---

## 1. Letra (consolidado de la red)

Se calcula con los últimos 12 meses **cerrados** (sin el mes en curso) del consumo de toda la red.
Reglas en orden; la primera que se cumple manda (`clasificar`):

| # | Letra | Regla | Método de cálculo (SPEC-10) |
|---|---|---|---|
| 1 | E | Marcado estratégico en la plataforma (`ArticuloConfig.es_estrategico`) | General con el mínimo declarado como piso |
| 2 | R | Consumo en ≥ `umbral_r` (3) de 12 meses | Regular o Intermitente según subclase |
| 3 | P | Tiene PC u OF abierto en la red | Cubre lo comprometido no cubierto |
| 4 | P / O | Consumo en 1–2 meses sin compromiso | Ver §1.1 |
| 5 | O | Sin consumo y sin PC/OF abierto | No se recompra |

Subclase (para R y E): `REGULAR` si consumo en ≥ `umbral_r_regular` (9) meses, si no `INTERMITENTE`.
Un E siempre usa la fórmula general (la subclase es informativa).

### 1.1 Regla P (`p_solo_con_compromiso`)

- `True` (por defecto, **acuerdo del 26-oct**, SPEC-07 §6): P exige PC u OF abierto. Consumo en
  1–2 meses sin compromiso → **O**.
- `False`: regla literal del documento (consumo en 1–2 meses **o** compromiso activo → P).
- El resultado de compra es el mismo en ambos casos (P sin compromiso compra 0); cambia la
  etiqueta y las alertas. Decisión abierta #8.

## 2. Marcas

| Marca | Regla | Efecto |
|---|---|---|
| Nuevo | Creado hace < 8 meses (repuestos) o < 4 (pañol), por `fec_creacion_sap` | No usa historia: mínimo manual (`minimo_nuevo`) |
| Inmovilizado | Letra O, no nuevo, sin movimiento en ≥ 24 meses (repuestos) o ≥ 12 (pañol). Sin movimientos registrados se usa la fecha de creación | Solo se reporta (liquidación fuera de alcance) |
| Crítico | `ArticuloConfig.es_critico` | Nivel de servicio mínimo 97% |
| Segmento pañol | Grupo SAP con tipo `PANOL` (`group_types.py`) | Plazos de Nuevo/Inmovilizado y servicio 97% |

"Último movimiento" = último mes con consumo > 0 en `ConsumoMensual`.

## 3. ABC por valor

- Valor de consumo anual = consumo 12 meses × `unit_cost_usd`, sobre **todos** los artículos del alcance.
- Orden descendente; un artículo es A si el valor acumulado **antes** de él es < 80%; B si < 95%;
  resto C. Valor 0 → C siempre. Cortes editables (`corte_abc_a`, `corte_abc_b`).

## 4. Nivel de servicio y factor

| Caso | Nivel | factor_servicio |
|---|---|---|
| Clase A | 97% | 1,88 |
| Clase B | 95% | 1,65 |
| Clase C | 90% | 1,28 |
| Crítico o pañol | máx(nivel ABC, 97%) | 1,88 |

Factor: tabla del documento para 90/95/97%; otros niveles = cuantil de la normal redondeado a 2
decimales (99% → 2,33).

## 5. Historial mensual (`HistorialMensual`)

- Una fila por artículo y mes (`mes` = primer día del mes en curso).
- **Cada corrida del mes reescribe la foto del mes** (la letra puede cambiar si cambian los datos
  dentro del mes; queda la última).
- `letra_anterior` = letra del último mes registrado **antes** del mes en curso; `motivo` se llena
  solo cuando cambia.
- Guarda también ABC, stock máximo y su valor, consumo promedio y variación (reporte de impacto,
  SPEC-15 §4).
- El cambio de letra genera la alerta `CAMBIO_LETRA` (SPEC-15).

## 6. No implementado

- Clasificación **por bodega** (§3 del documento pide bodega y consolidado): solo se calcula la
  letra consolidada, que es la que manda para comprar.
- Escribir la letra en SAP (`U_RPEO`) y leer `U_CRITICO`: bloqueado hasta habilitar Service Layer.
- Reclasificación automática el primer día hábil del mes: hoy ocurre en cada corrida (ver §5).
