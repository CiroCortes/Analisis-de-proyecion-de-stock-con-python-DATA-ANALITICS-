# SPEC-06: Plan SDD de la Calculadora de Compras

Documento fuente: `Requerimientos_Calculadora_Compras5.docx` (23-oct-2026, Gerencia de Supply Chain).
Copia de texto para búsqueda: `.specs/fuente_requerimientos_calculadora_compras5.txt`.
Reglas de negocio ya aplicadas en el sistema: `.specs/07_reglas_negocio_acordadas.md`.
Pendientes: `.specs/00_PENDIENTES.md`.

Estado al 27-oct-2026:

| Fase | Estado |
|---|---|
| 0 Especificación | Specs 08–18 escritas; quedan decisiones abiertas (SPEC-00) |
| 1 Datos | Cargadores listos; consultas 8–14 **sin validar en Athena**; consumo provisional desde PC/OF |
| 2 Clasificación | Implementada (letra consolidada, ABC, historial mensual); falta el cierre de dos meses |
| 3 Cálculo | **Implementado** en `apps/calc/`; casos dorados 1–5 en verde (SPEC-17) |
| 4 Traslados y solicitudes | Implementados; exportación a planilla (SAP bloqueado) |
| 5 Pantallas | `/calculadora/`: panel, grilla, detalle, solicitudes, traslados, alertas, eventos, indicadores, parámetros, proveedores |
| 6 Marcha blanca | Pendiente: requiere datos validados (consultas 8 y 9) |

Arquitectura: SPEC-18.

---

## 1. Qué pide el documento (resumen)

| Sección | Contenido |
|---|---|
| 1 | Alcance, bodegas evaluadas, requisitos generales (un solo motor, recalcula desde cero, stock diario, clasificación mensual) |
| 2 | Datos de origen SAP B1 vía Datalake; 24 meses de historia de movimientos y OC |
| 3 | Clasificación mensual E/R/P/O, subclase R-Regular / R-Intermitente, Nuevo, Inmovilizado, es_crítico, ABC y nivel de servicio |
| 4 | Cálculo por artículo: consumo, plazo real, stock de seguridad, punto de pedido, stock máximo, intermitentes, disponible futuro, cantidad a comprar, ciclo por proveedor, proyección diaria 120 días, compras fuera de calendario, ajuste comercial |
| 5 | **Compra única por artículo para la red** (recibida en 013-PP) y distribución a bodegas por traslado |
| 6 | Solicitudes de compra por proveedor con acuerdo global; creación en B1 |
| 7 | Parámetros configurables (tabla + pantalla + auditoría + simulación + roles) |
| 8 | Grilla, 14 alertas, reporte de impacto en valor, gráficos, indicadores de gestión |
| 9 | Casos borde |
| 10 | Casos de prueba 1 a 5 (criterio de aceptación del cálculo) |
| 11 | Cambios respecto a la versión actual |
| 12 | Decisiones y pendientes |
| 13 | Entregables por fase y criterios de aceptación |

Los casos de prueba 1, 2, 3 y 5 se recalcularon a mano el 26-oct-2026 y **cuadran** con el documento.
El caso 4 (traslado) depende de datos reales.

## 2. Qué existe hoy vs qué falta

El motor actual cubre cerca del 15–20%: clasificación REPO básica, un ROP por bodega y traslados
desde Santiago.

| Existe | Falta (nuevo) |
|---|---|
| Carga desde TXT del Datalake | Historial mensual de consumo (24 meses) y de clasificación |
| Clasificación R/E/P/O (reglas distintas a las nuevas) | Subclases, ABC por valor, Nuevo/Inmovilizado, historial |
| ROP por bodega, compra hasta el punto de pedido | SS con variación de proveedor, punto de pedido, stock máximo, intermitentes |
| COMPRAR/TRASLADAR/MIXTO por bodega | **Una compra por artículo para la red**; bodegas solo con traslados; ESPERA COMPRA |
| Recomendador (lista) | Solicitudes por proveedor, contratos, aprobación, calendario de 15 días |
| — | Proyección diaria 120 días, compras fuera de calendario |
| — | Eventos comerciales, parámetros editables, alertas, gráficos, KPIs, roles |

## 3. Decisiones tomadas

| Tema | Decisión | Fecha |
|---|---|---|
| Escribir en SAP (Service Layer, U_RPEO, U_CRITICO) | **Descartado por ahora**; se retoma al solicitar la habilitación de Service Layer. Fase 1: solicitudes como archivo (DTW) o solo en pantalla | 26-oct |
| Base de datos (SQLite vs PostgreSQL) | **Pendiente.** Se decide cuando estén claros los consumos del Datalake | 26-oct |
| Costo | `lastpurprc` en USD, no `avgprice` (ver SPEC-07 §2) | 26-oct |
| Fuente del consumo | Movimientos de inventario (`OINM`) agregados por mes en la consulta; no PC/OF cerrados | propuesta, validar mañana |
| Alcance por grupos, invntitem, bodegas, tránsito, atribución de salidas | Ver SPEC-07 | 26-oct |
| Documento de requerimientos | Se implementa a medida de lo solicitado | 26-oct |

Las decisiones que el propio documento marca como cerradas (12 meses cerrados, recepción 2 días,
compra cada 15 días, piso SS 2/4 meses, cobertura 3 meses, R = 3 o más meses, solicitud convertida
en OC cuenta una vez *pendiente de Compras*, sucursales sin punto de pedido propio) se asumen
vigentes.

## 4. Conflictos y huecos detectados en el documento

Se resuelven en la fase 0 y se anotan en el documento fuente antes de implementar.

1. **Costo**: el documento usa `AvgPrice` (OITM/OITW). Pesco usa precio de última compra. Hay que
   decidir: `lastpurprc`, precio del acuerdo global (§6) o ambos según el caso.
2. **Bodegas evaluadas**: el documento lista 5 de Santiago (013-PP, PS, 07, 09, 03) + 5 sucursales.
   Lo acordado: todas las `013-xx` físicas pueden mover stock (SPEC-07 §4). Alinear.
3. **Reglas ya acordadas que el documento no recoge**: alcance por grupos/tipos, `invntitem`,
   bodegas de tránsito/consignación/no conforme, la 013 de posteo, salidas con bodega no confiable.
   Agregarlas al documento como requisitos.
4. **Consumo y doble conteo**: el documento suma ventas, entregas, salidas y OF. Sumar entregas
   (ODLN) y facturas (OINV) puede contar dos veces lo mismo. Propuesta: tomar solo `OINM` con
   TransType explícitos (13, 14, 15, 16, 60) y validar contra el informe de auditoría de stock de B1.
5. **Devoluciones**: el documento resta "del mes del movimiento original"; `OINM` las resta en el
   mes en que ocurren. Decidir si la diferencia importa.
6. **Venta vs OF diferenciados** (gráficos): `OINM` no distingue emisiones a OF de otras salidas de
   mercancía (mermas, ajustes). Requiere `IGE1.basetype = 202` (consulta 8b).
7. **Recepciones parciales de una OC**: el documento define plazo = fecha entrada − fecha OC. Con
   varias entradas por línea hay que decidir si cuenta la primera o la última.
8. **Escritura en SAP**: Service Layer / campos de usuario / DTW requieren IT. Descartado por ahora.
9. **Volumen**: 24 meses por artículo y bodega solo es viable con consumo ya agregado por mes en SQL.
10. **Base de datos**: historial mensual, roles, auditoría y varios usuarios presionan hacia
    PostgreSQL. Decidir tras validar los consumos.
11. **Familia como nivel de parámetros** (§7): ¿familia = `u_rhfamilia` o grupo de artículos SAP?
12. **Valor de quiebres**: el sistema actual mezcla "brecha contra objetivo" con "quiebre real
    (disponible ≤ 0)". El documento pide separarlos (§5 y §12).
13. **Pendientes del propio documento ya resueltos**: categoría P con 0 artículos (corregido el
    26-oct); archivo de solicitudes de compra (llega como `oprq_prq1`).
14. **`.specs` desactualizado**: SPEC-01..05 y HARNESS_RULES describen el sistema antiguo (Excel,
    ROP con DPD×lead time, lista fija de 9 bodegas). La Calculadora los reemplaza (ver §6).

## 5. Metodología SDD

Flujo por cada módulo: **spec → criterios de aceptación → tests → implementación → verificación**.

- La spec de cada módulo vive en `.specs/` y se escribe antes del código. El código no se mueve si
  la spec no está de acuerdo.
- Cada spec incluye: requisitos (qué), campos y fórmulas (cómo), casos borde, casos de prueba con
  resultados exactos, y qué datos necesita.
- **Núcleo de cálculo puro** (`apps/calc/`, sin dependencias de Django): funciones que reciben
  números y devuelven resultados. Así las fórmulas se prueban contra el documento sin base de datos.
- **Tests dorados**: los casos 1 a 5 de la sección 10 del documento se convierten en pruebas pytest
  con los valores exactos. Son el criterio de aceptación de la fase de cálculo.
- Los servicios (lectura/escritura de BD) y las pantallas se montan sobre el núcleo.
- Tareas verticales y pequeñas: una tarea = una regla o un campo del diccionario, con su test.
- Regla del arnés que se mantiene: toda función de cálculo o ingesta tiene test pytest en verde.

### 5.1 Módulos de spec previstos

| Spec | Contenido | Secciones del documento | Código |
|---|---|---|---|
| [08](08_contrato_datos.md) | Contrato de datos: consultas, TXT/tablas, respaldos | 2 | `calculadora/cargadores.py` |
| [09](09_clasificacion.md) | Clasificación RPEO, subclases, ABC, Nuevo, Inmovilizado, historial | 3 | `calc/clasificacion.py` |
| [10](10_motor_calculo.md) | Motor de cálculo por artículo (diccionario de campos) | 4.1–4.6, 9 | `calc/consumo,plazo,politica,motor.py` |
| [11](11_red_distribucion.md) | Compra de la red y distribución a bodegas | 5 | `calc/red.py` |
| [12](12_ciclo_proyeccion.md) | Ciclo por proveedor, proyección diaria, fuera de calendario | 4.6.1, 4.6.2 | `calc/calendario,proyeccion.py` |
| [13](13_solicitudes.md) | Solicitudes de compra y acuerdos globales | 6 | `calculadora/solicitudes.py` |
| [14](14_parametros.md) | Parámetros configurables, auditoría, simulación, roles | 7 | `calc/params.py`, `calculadora/parametros.py` |
| [15](15_alertas_indicadores.md) | Alertas, impacto, indicadores | 8 | `calculadora/alertas.py`, `calc/simulacion.py` |
| [16](16_eventos_comerciales.md) | Eventos comerciales | 4.7 | `calculadora/servicio.py` |
| [17](17_casos_dorados.md) | Casos de prueba dorados (1–5) | 10 | `tests/test_calc_golden.py` |
| [18](18_arquitectura.md) | Arquitectura, flujo, pantallas, comandos | 1, 13 | `apps/calculadora/` |

## 6. Specs existentes a reconciliar

| Spec | Estado |
|---|---|
| 01_data_schema | Actualizada el 27-oct (campos nuevos y modelos de la Calculadora) |
| 02_rop_business_rules | **Marcada obsoleta** → SPEC-10/11 |
| 03_sop_ui_ux | Revisar contra pantallas actuales |
| 04_almanaque_calculos_repo | **Marcada obsoleta** → SPEC-09/10 |
| 05_documentacion_tecnica_repo_drp | **Marcada obsoleta** → SPEC-11 (el motor sigue como escenario actual) |
| HARNESS_RULES | Reescrita el 27-oct |

## 7. Orden de implementación propuesto

1. **Fase 0 – Especificación** (en curso): cerrar decisiones, actualizar el documento y las specs.
2. **Fase 3 – Cálculo** (puede empezar ya, no necesita datos nuevos): módulo puro `apps/calc/`,
   fórmulas del §4 y tests dorados 1 a 5.
3. **Fase 1 – Datos** (en paralelo): validar en Athena `data/consultas_calculadora_compras.sql`
   (consumo mensual 24 meses, plazos de OC, parámetros de compra, proveedores, acuerdos, traslados).
   Cuadrar el consumo de 30 artículos contra el informe de auditoría de stock de B1 por bodega.
4. **Fase 2 – Clasificación** mensual con historial; reclasificar dos cierres.
5. **Compra de la red + traslados + proyección diaria** (§5 y §4.6.2).
6. **Fase 4 – Solicitudes** por proveedor con contrato (en pantalla / archivo DTW).
7. **Fase 5 – Pantallas**: grilla, parámetros, alertas, gráficos, impacto, indicadores.
8. **Fase 6 – Marcha blanca**: 2 meses en paralelo con el proceso actual.

Criterios de aceptación por fase: los del documento §13.

## 8. Archivos de apoyo creados el 26-oct-2026

- `data/consultas_calculadora_compras.sql` — consultas 8 a 14 (borrador, sin validar en Athena).
- `.specs/07_reglas_negocio_acordadas.md` — reglas de negocio vigentes.
- `.specs/00_PENDIENTES.md` — lista priorizada de pendientes.
- `.specs/fuente_requerimientos_calculadora_compras5.txt` — texto del documento fuente.
