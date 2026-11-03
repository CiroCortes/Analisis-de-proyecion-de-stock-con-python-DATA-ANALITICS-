# PENDIENTES (actualizado 3-nov-2026)

## 2-nov-2026 (Datalake OIVL y SPEC-31)

| # | Hallazgo | Acción |
|---|---|---|
| 29 | La `oinm` del Datalake pierde movimientos (ago-26 −59 %, dic-25 −55 %, may-26 −38 %; caso 31206011: NC 9783 e IM 35049 ausentes). `oivl` está completa y sin duplicados | **Hecho**: consulta 8 sobre `oivl`. +203 mil u en 12 meses; brecha de NC 2.712 → 9 u. Reportado al dueño del Datalake |
| 30 | Requerimientos de César (doc. y reunión 2-nov) | **Hecho (SPEC-31)**: pantalla Marcas (excluir del cálculo con motivo; equipos de gerencia con plan), SC fuera del tránsito, en camino desglosado, promedio con demanda, alerta de caída por bodega, ABC por venta |
| 31 | Consulta 17 (Ventas Mensuales.txt) | **Hecho** (corrida 31): `linetotal` validado en USD (venta/costo mediana 1,84). ABC por venta: A = 230 artículos, USD 5,15 M |
| 32 | 30 códigos 4999990xxx (USD 841 mil del sugerido) y 10 equipos caros con compra (USD 671 mil) | **Pendiente (Ciro, validado con Ignacio)**: marcarlos en Marcas. Correo a los encargados por el uso del 4999990001 |
| 33 | Venta de exportación (0EX): 13 artículos, USD 460 mil del sugerido (16 %); parecen un proyecto puntual (20401254: 458 u, USD 225 mil) | **Decisión abierta (Ignacio, con la opinión de César)**: demanda normal (hoy), evento atípico o a pedido |
| 34 | Revisión con usuarios (la herramienta sugiere, decide jefatura): 29 A por venta sin disponible, 338 PC/OF antiguos (127 MEDIA, USD 290 mil) para Contraloría, 18 DOBLE_ENVIO, pedido SAP sin OC (USD 133 mil) | **Pendiente** |
| 35 | Service Layer (SPEC-30): el puerto 50000 no responde desde la red de la oficina (3-nov) y falta la clave en `.env` | **Bloqueado**: subdominio (Gisella) y red con TI (Ciro) |
| 36 | 154 OC (239 artículos) con plazo atípico: mediana 66 días contra 7 típicos, sobre todo proveedores nacionales. Inflaban el SS (4201130215: SS 9 → 3, compra 8 → 0) | **Hecho (SPEC-33)**: tope por mediana y alerta PLAZO_ATIPICO. **Pendiente (gerencia y Compras)**: revisar la causa de cada OC (`data/OC_plazo_atipico_2026-11-03.xlsx`) y definir una regla de cierre de OC |
| 37 | Importaciones invisibles (caso 36274254, HIAB): la consulta 5 excluía `cardcode '%PE'` (PE = proveedor **extranjero**, no interno) y no leía las facturas de reserva, donde queda lo pendiente de una importación. 819 artículos, USD 2,4 M en camino que el cálculo no veía. La consulta 9 tampoco medía el plazo de las importaciones (52 de 6.653 entradas) | **Hecho (SPEC-35, corrida 37)**: +USD 1,34 M en camino visible, compra sugerida −USD 0,69 M (186 artículos dejan de comprar). Las entradas a pre-bodega no miden plazo (son el embarque). **Pendiente**: (a) residuo de pedido SAP sin OC, 309 art. USD 1,26 M, sobre todo kits en 013: confirmar si son OF de fabricación (consulta en SPEC-35 §4); (b) plazo real de importación hasta la llegada a destino (SPEC-35 §5) |
| 39 | Residuo de "pedido SAP sin OC" (309 art., USD 1,26 M): son OF; SAP suma el producto de la OF en "Pedido". Kits HIAB con 15 OF abiertas desde ago-2023 (USD 468 mil), RRC desde nov-2023 | **Hecho (SPEC-36)**: OF vigentes (`meses_of_vigente` = 6) cuentan como en camino; antiguas no, con alerta OF_ANTIGUA. **Pendiente (Ciro)**: reexportar la consulta 5 y validar. **Pendiente (Producción/Contraloría)**: cerrar o anular las OF antiguas. **Siguiente**: reconocer artículos fabricados (SPEC-36 §4) |
| 40 | Compras que siguen contando como en camino con mucho atraso (caso 20401255: OC 2505141 de may-25, 73 u en FR vencidas desde ene-26, retenidas en EE.UU.). ~USD 310 mil con más de 90 días, 75 % importaciones | **Pendiente (post marcha blanca)**: que una compra con más de N días de atraso no cuente como llegada inminente, o alerta "importación detenida" para Comex (detector en SPEC-37 §4.2) |
| 42 | Fecha de entrega irreal heredada de la SC (caso 35471214, con Comex: OC 2610879 a HIAB del 28-oct, FR 75825, entrega comprometida 30-10 para una importación de 70 días; la fecha la puso quien hizo la SC). En la red: **264 líneas de importación (223 art., USD 462 mil) prometen llegar en una mediana de 6 días**, 92 con fecha igual o anterior a la OC; 201 ya figuran como "OC atrasada" sin estarlo. Nacionales: 82 líneas, USD 40 mil | **Hecho (corrida 39)**: si la fecha comprometida es menor que `factor_fecha_irreal` (0,5) × el plazo de entrega, el cálculo usa fecha OC + plazo y no la marca atrasada; la ficha muestra la estimada; alerta FECHA_IRREAL para Compras (si la fecha se corre 15 días o más): 307 (56 MEDIA). OC_ATRASADA 813 → 618; QUIEBRE_PROYECTADO +3; sugerido sin cambio. Código: `calc/proyeccion.fecha_llegada_oc`, `alertas.fechas_irreales`. Tests: `tests/test_fecha_irreal.py`. **Pendiente (gerencia)**: proceso, quien emite la SC debe poner la fecha según el lead time |
| 41 | Agente S&OP que lea el sistema, sepa el negocio y vigile las fallas | **Planteado (SPEC-37)**: servidor MCP de solo lectura + modelo en AWS Bedrock; fases 1–4 después de la marcha blanca. Decisiones en §10 |
| 38 | Reportes que hoy son Excel sueltos (OC con plazo atípico, PC/OF antiguos, pedido SAP sin OC) | **Pendiente**: pantalla de Reportes con exportación desde el sistema (spec aparte) |


## Próximo paso (datos)

0. ~~**Datalake: la consulta 8 no es estable**~~ **Resuelto el 2-nov**: la consulta 8 lee `oivl`, completa y sin
   duplicados (hallazgo 29). Lo que sigue es historia (28-oct, SPEC-22 §4). Dos exportaciones con un día de
   diferencia traen filas muy distintas por mes; falta 2025-02 en ambas, 2025-07 en la del 28-oct y
   2026-08 viene con 969 filas contra 4.061. Con el archivo del 28-oct la compra sugerida pasó de
   USD 4,06 M a USD 3,36 M **por el cambio de datos, no por las NC** (las NC mueven ~4.700 u de 12
   meses de sucursales a Santiago). Revisar con IT la carga de OINM antes de confiar en el consumo.
1. **Cuadrar el consumo** de 30 artículos contra el informe de auditoría de stock de B1, por bodega
   (criterio de aceptación fase 1). Confirmar TransType 13, 14, 15, 16, 60. (Consultas 8 a 14 ya
   cargadas el 27-oct: consumo OINM, plazos reales, acuerdos en USD.)
2. **Verificar OF con cantidades enormes** (ver Trabajo técnico).

## Hallazgos del 27-oct

| # | Hallazgo | Acción |
|---|---|---|
| 1 | OC y SC posteadas en la `013` (o sin bodega) **se perdían**: ~1.061 líneas de OC (5.457 u) y ~450 de SC | **Corregido**: se acreditan a 013-PP (`purchase_bodega`). Reprocesar con Sincronizar |
| 2 | Bodegas `000-003`, `000-010`, `000-022` reciben OC/SC (≈43, 71, 29 líneas) | **Resuelto 28-oct (SPEC-22)**: son pre-bodegas de importación; OC, SC y stock se acreditan como tránsito a su sucursal |
| 3 | Caso 4 del documento cuenta dos veces el compromiso (SPEC-11 §3.1) | **Corregido 28-oct** (faltante real). Corregir el caso 4 en el documento |
| 4 | Caso 3: consumo anual 146 ⇒ promedio 12,17, pero el documento calcula con 11,5 (SPEC-17) | Corregir el dato en el documento |
| 5 | 289 artículos que necesitan compra no tienen proveedor | Consulta 10 o completar proveedor en la plataforma |
| 6 | Sin plazos reales hasta la consulta 9 | Validar consulta 9 |
| 7 | E = 0: nadie ha declarado artículos estratégicos | Abastecimiento marca E y mínimos (detalle del artículo) |
| 8 | 013-PP pide traslados grandes desde 013-09 / 013-07 (hasta 7.000 u) para cubrir sus OF | **Resuelto 28-oct (SPEC-21)**: no hay traslados internos de Santiago |
| 9 | Ruido de alertas: alza e irregularidad en P/O (1.803 y 1.488) | **Corregido**: solo R/E |

## Hallazgos del 28-oct (SPEC-21)

| # | Hallazgo | Acción |
|---|---|---|
| 10 | La 013-PP registra el 50% de las salidas a OF pero tiene solo el 8% de los artículos con stock; el 30% de los artículos con consumo sale de 2 o más bodegas | Santiago pasa a ser un solo stock (nodo `013`) |
| 11 | 401 de 509 traslados (27.067 de 27.650 u) eran internos de Santiago hacia 013-PP: ficticios | **Corregido**: 132 traslados, 622 u, solo Santiago ↔ sucursales |
| 12 | El stock de la `013` a secas no se contaba (742 u en 85 artículos) | **Corregido**: suma al nodo Santiago |
| 13 | Faltaba sugerir regiones → Santiago | **Hecho**: 43 traslados (138 u), solo con stock libre |
| 15 | El faltante por bodega y la proyección contaban dos veces los compromisos | **Corregido** (ver Hecho 28-oct) |
| 14 | El 63% de las OC abiertas se postea en la `013`; la exportación de solicitudes usa 013-PP como bodega de entrega | Confirmar con Compras |

Corrida del 28-oct (SPEC-21, datos reales): 132 traslados (89 Santiago → regiones, 484 u; 43
regiones → Santiago, 138 u); 49 nodos con stock retenido visible para jefatura; 427 excepciones;
USD 4,52 M sugerido; quiebre real USD 685 mil.

Corrida del 27-oct con consumo provisional PC/OF: 18.026 artículos; R 2.471, P 580, O 14.975, E 0;
271 a comprar hoy, 1.047 necesitan compra, 409 excepciones, 529 traslados; USD 3,16 M sugerido;
quiebre real USD 717 mil vs brecha contra objetivo USD 3,94 M.

## Hallazgos de la reunión S&OP del 28-oct (SPEC-22 y 23)

| # | Hallazgo | Acción |
|---|---|---|
| 16 | Las NC se restan en la 013-NC/013-IN (Santiago), no en la bodega de la factura: infla la demanda de la sucursal | SPEC-22 + SPEC-25 (2-nov): la NC se resta en la bodega y el mes de la guía (consulta 15 con columnas de guía; re-exportar) |
| 17 | En 1.014 de 2.032 celdas con NC, OINM no registra movimiento (390 mil u; una NC de 360.000 u sobre factura sin movimiento) | Solo se reubica lo que OINM registró. Confirmar con contabilidad si son facturas de reserva |
| 18 | El corte de 180 días de la consulta 5 dejaba fuera OC antiguas pendientes (pre-bodegas: SAP 12.630 u, cargadas ~3.700) | Corregido: consulta 5 sin corte. Tránsito de los nodos: 119 mil → 143 mil u |
| 19 | PC/OF abiertos desde 2023. En el alcance: 6% de las u de PC y 8% de las de OF tienen más de 3 meses; el volumen grande es RETAIL y servicios | SPEC-23: cálculo híbrido (compra −3,6% con solo recientes) + informe de antigüedad para Contraloría |
| 20 | Producción pide ver Santiago también por bodega (013-PS vs 013-PP rotan distinto) | **Hecho 28-oct (SPEC-24)**: Analizar artículos, con Santiago unificado y cada 013-xx |

## Hallazgos del 29-oct (Datalake, NC y picos)

| # | Hallazgo | Acción |
|---|---|---|
| 21 | La tabla `oinm` del Datalake repite movimientos (nov-25: 39.226 filas para 14.660 `transnum`) y le faltan otros (ago-26 del 70100011; feb-25 y jul-25 casi vacíos). Cambia entre exportaciones diarias | **Corregido el duplicado**: consultas 8 y 13 cuentan cada movimiento una vez (compra 3,36 → 2,21 M USD). **Faltantes pendientes**: IT o Service Layer |
| 22 | 013-NC y 013-NC_E son de Cobranzas (facturas rechazadas): NC y refactura sin repuesto físico. 013-IN = devoluciones físicas. 0EX = exportación (venta real) | SPEC-25 (2-nov): 013-NC/NC_E fuera del consumo (NC y refactura). 6.435 u de 12 m vuelven de Santiago a sucursales. La compensación en otras bodegas no aplica (la factura no mueve stock) |
| 23 | Promedio + 3 desvest casi no recorta picos (el pico infla la desvest): 262 de 462 picos sin tocar | **Hecho (SPEC-26)**: tope = menor entre la regla del documento y 4 × mediana; alerta PICO. Compra 2,21 → 2,04 M USD |
| 24 | Bodegas con stock marcadas "EXCLUIDA" que sí contaban (pre-bodegas, 013) y otras sin motivo visible; el catálogo no tenía las T… | **Hecho (SPEC-27)**: tratamiento visible y editable (stock / en camino / no cuenta) con auditoría; catálogo 51 → 131 bodegas. **Pendiente: decidir la 013-IN** |
| 25 | La 013-NC tiene ~USD 1,63 M (USD 33 mil en el alcance) que debería estar en cero tras cada refactura | Lista en la bitácora local para Cobranzas y Contraloría |
| 26 | Dashboard y Analítica no cuadraban con la Calculadora (502 vs 200 urgentes; unidades sumadas) | **Hecho (SPEC-28)**: Panel S&OP único con las cifras de la corrida, en USD |
| 27 | Analizar no mostraba pre-bodegas, consignación ni 013; pedidos en SAP sin OC cargada (USD 1,17 M en pre-bodegas) por exportar stock y OC en días distintos | **Hecho (SPEC-29)**: ventana "Stock en SAP por bodega" con cómo cuenta cada una y avisos. **Regla: exportar todo el mismo día** |
| 28 | Las devoluciones y NC no se ven en la ficha ni en Analizar (riesgo de desconfianza) | Propuesto: conciliación del consumo con SAP, junto con SPEC-25 (requiere separar TransType 16 en la consulta 8) |

## Decisiones abiertas

| # | Decisión | Quién | Hoy implementado |
|---|---|---|---|
| 1 | Costo: `lastpurprc`, precio del acuerdo global, o ambos | Abastecimiento | `lastpurprc`; en solicitudes, precio del acuerdo si existe |
| 2 | Fuente del consumo: OINM con TransType explícitos vs documentos | Abastecimiento / datos | **OIVL** (consulta 8, desde el 2-nov); respaldo PC/OF. Con el Service Layer: SPEC-30 fase 2 |
| 3 | Devoluciones: mes original o mes en que ocurren | Abastecimiento | NC: bodega y mes de la guía (SPEC-25). Devoluciones de entrega (TransType 16): mes en que ocurren |
| 4 | OC con recepciones parciales: primera o última entrada | Abastecimiento | **Primera entrada** |
| 5 | Base de datos: SQLite vs PostgreSQL | Equipo | SQLite (corrida ~10 s) |
| 6 | "Familia" en parámetros: `u_rhfamilia` o grupo SAP | Abastecimiento | Grupo SAP |
| 7 | Bodegas evaluadas: todas las 013-xx físicas vs las 5 del documento | Abastecimiento → documento | Todas las 013-xx |
| 8 | P solo por PC/OF o también por consumo en 1–2 meses | Abastecimiento | Exige PC/OF (`p_solo_con_compromiso`) |
| 9 | Solicitud convertida en OC se cuenta una vez | Compras | Solicitudes exportadas cuentan hasta la siguiente carga de SC |
| 10 | Grupos "por revisar" (111, 131) | Abastecimiento | Activos |
| 11 | Costo de equipos de producción propia | Jefatura | 0 |
| 12 | Stock de seguridad de R-Intermitente (el documento no lo define) | Abastecimiento | ROP − consumo en el plazo (SPEC-10 §4) |
| 13 | Objetivo por bodega / doble conteo del caso 4 | Desarrollo (28-oct) | **Resuelto**: faltante = MAX(0; −disponible) |
| 14 | Alertas de alza e irregularidad solo para R/E | Abastecimiento | Solo R/E |
| 15 | Días de reserva de consumo propio antes de trasladar (protección simétrica) | Abastecimiento | 15 días (`dias_reserva_traslado`) |
| 17 | Base de compromisos del cálculo: todos o solo recientes, y cuántos meses | Abastecimiento / Producción | Todos; se muestra también la otra base (3 meses) |
| 16 | Bodega de entrega de las solicitudes exportadas: 013-PP o 013 | Compras | 013-PP |
| 18 | Compra: el disponible resta todos los compromisos y el punto de pedido ya incluye el consumo del plazo (posible doble conteo, ≈ 38 artículos y USD 0,29 M). Los meses atípicos se recortan del consumo, así que un pedido grande puntual no está en el promedio | Abastecimiento | Fórmula del documento (§4.6) |
| 19 | Comprar por sucursal a su pre-bodega (cross-docking) o centralizar en Santiago | Gerencia (Gisella) | Centralizado (SPEC-21) |
| 20 | Venta de exportación (0EX) como demanda | Ignacio, con la opinión de César | Cuenta como venta |
| 21 | Tratamiento de la 013-IN (devoluciones físicas) | Abastecimiento | Pendiente (SPEC-27) |

## Bloqueado

- **Escribir en SAP: no se hará** (decisión del 28-oct). La plataforma solo sugiere; las solicitudes salen
  por Excel (SPEC-13 §5) y Compras las ingresa en SAP. U_RPEO y U_CRITICO quedan en la plataforma.
- **Service Layer (solo lectura, SPEC-30)**: cliente listo; falta la red (subdominio y TI) y la clave.
- **Conexión directa a Athena** (boto3): construida, sin probar (`manage.py check_athena`).
- **Saldo de acuerdos globales**: `OAT1.planqty` está declarada `DECIMAL(12,6)` en el catálogo
  Glue y hay acuerdos con 500.000.000 → Athena no puede leer la columna (INVALID_CAST_ARGUMENT,
  aunque se haga CAST). La consulta 12 la envía en 0 (sin control de saldo). Pedir al equipo de
  datos ampliar el tipo a `DECIMAL(19,6)` en Glue y restaurar `l.planqty` en la consulta 12.

## Trabajo técnico pendiente

- **Fusión del Recomendador (SPEC-19)**: en la rama `feature/fusion-recomendador`. Al fusionar a
  `main`, correr Sincronizar una vez (captura el escenario actual y publica). Tras la marcha
  blanca, decidir si se borra `/purchasing/` y si el motor anterior se reduce a solo el ROP de
  comparación.
- **Quiebre en el Dashboard**: desde SPEC-19 muestra el quiebre real (antes USD 96 M de brecha del
  motor anterior). Avisar a gerencia antes de presentar el Reporte Gerencial.
- **Verificar OF con cantidades enormes**: 2,7 M u comprometidas en Santiago; sospecha de unidades
  (metros/kilos/litros). Revisar el top 10; afecta excepciones.
- **Consignación**: OF abiertas en 100/102/106 (241.352 u) atribuidas a 013-PP; confirmar quién repone.
- **Bodegas `013-IN`, `957`, `959`**: confirmar.
- **Antofagasta en tránsito**: `022` en `T…-…` = `002-02`; confirmar que no existe una 022 real.
- Clasificación por bodega; correo semanal de alertas; buzón de eventos (fase 2).
- Crear los grupos Django "Administrador Abastecimiento" y "Jefe Abastecimiento" y asignar usuarios.
- Configurar calendario real por proveedor (hoy ancla repartida por código).

## Documentación

- Specs 08–18 escritas el 27-oct. 02, 04 y 05 marcadas obsoletas; HARNESS_RULES reescrita.
- `Requerimientos_Calculadora_Compras5.docx`: incorporar conflictos (SPEC-06 §4), hallazgos 3 y 4,
  y reglas de SPEC-07.
- `03_sop_ui_ux.md`: revisar contra las pantallas nuevas.

## Hecho

**28-oct-2026 (revisión general)**: todas las pantallas recorridas con datos reales sin errores;
CSS de Tailwind servido localmente (`cdn.tailwindcss.com` no responde desde la red de Pesco);
Bodegas como listado; gráfico de consumo por nodo en la ficha; memoria de cálculo plegable al final.
Defectos corregidos (tests en `tests/test_revision_28oct.py`):
1. Nuevo con mínimo manual quedaba O y no compraba su mínimo (sin mínimo sigue como O).
2. Consumo diario, reserva por nodo y ABC mezclaban N meses con 365 días (solo si
   `meses_historia_consumo` ≠ 12); meses con consumo se cuentan sobre los últimos 12.
3. Solicitud aprobada antes de una carga de SC y exportada después dejaba de contar (compra doble):
   nuevo campo `exportada_en`.
4. Stock en camino entre bodegas (T…-…) no entraba en la proyección: excepciones falsas.
5. Alerta URGENTE en artículos P cubiertos (disponible 0).
Corrida: excepciones 393 → 378; sugerido USD 4,25 M → 4,19 M; alertas urgentes 462.
Anotado sin corregir (sin impacto hoy): stock y compromisos fraccionarios se truncan en la carga
(0 filas con decimales en el TXT actual); equivalencias encadenadas A→B→C; el histórico del gráfico
no aplica equivalencias. Antes de producción: SECRET_KEY por variable de entorno, DEBUG=False,
ALLOWED_HOSTS acotado.

**28-oct-2026 (no inflar datos)**: faltante por bodega = lo que realmente falta (antes 367 de 484 u
trasladadas a regiones sin quiebre real; ahora 0). Proyección: MAX(consumo esperado; compromisos) en
vez de sumar ambos (excepciones 427 → 393; sugerido USD 4,52 M → 4,25 M). Casos 4 y 5 corregidos
en los tests; falta corregirlos en el documento. Corrida: 93 traslados (255 u).

**28-oct-2026 (SPEC-21)**: Santiago como un solo stock (nodo `013`, incluye la 013 a secas);
traslados solo Santiago ↔ sucursales en ambos sentidos con protección simétrica (compromisos +
15 días de consumo propio); stock retenido visible para que decida jefatura; guía de picking
("sacar de 013-xx") en cada traslado desde Santiago; sección "¿Comprar todo de una vez?" en la
ficha (consumo por nodo mes a mes, compra en meses, compra mínima hasta el punto de pedido,
Santiago por bodega). Caso 4 del documento: mismo resultado, origen Santiago (desde 013-03).

**27-oct-2026 (noche, SPEC-20)**: ficha única del artículo (la de la Calculadora; la URL antigua
redirige) con documentos cerrados de PC y OF; Dashboard, Reporte Gerencial, Consultar Stock y
Configuración enlazan a la Calculadora; "Recalcular S&OP" ya no despublica la Calculadora
(`recalcular_red()`).

**27-oct-2026 (tarde, SPEC-19)**: fuente única (la Calculadora publica en StockProjection y
SKUClassification; motor anterior en EscenarioActual); eje XYZ y matriz ABC-XYZ; consumo y
cobertura por bodega; inventario histórico + proyección en el detalle; pantallas Bodegas,
Segmentación y Guía; panel "Qué hay que hacer hoy"; ayuda (?) en contexto; Recomendador fuera del
menú; filtros ABC del Dashboard y Recomendador con la definición por valor. Commit de respaldo
del estado anterior subido a `main` (sin documentos internos: el repo es público).

**27-oct-2026**: núcleo de cálculo puro `apps/calc/` (consumo, plazo, clasificación, política, red,
proyección, calendario, simulación); casos dorados 1–5 en verde y 45 tests de reglas; app Django
`apps/calculadora` (modelos, cargadores, corrida, alertas, solicitudes, parámetros con registro);
arreglo de OC/SC en la `013`; pantallas de la Calculadora; Calculadora enganchada al pipeline de
Sincronizar; comando `calcular_compras`.

**26-oct-2026**: ingesta solo TXT · costo por `lastpurprc` · grupos SAP con tipo de material ·
SKUs no inventariables fuera · zonas Santiago/Sucursales · bodegas no físicas, tránsito y
consignación · salidas de OF/PC con bodega no confiable · REPO P (528 SKUs) · motor ignora SKUs
inactivos.
