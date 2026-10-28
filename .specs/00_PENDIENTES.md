# PENDIENTES (actualizado 28-oct-2026)

## Próximo paso (datos)

1. **Cuadrar el consumo** de 30 artículos contra el informe de auditoría de stock de B1, por bodega
   (criterio de aceptación fase 1). Confirmar TransType 13, 14, 15, 16, 60. (Consultas 8 a 14 ya
   cargadas el 27-oct: consumo OINM, plazos reales, acuerdos en USD.)
2. **Verificar OF con cantidades enormes** (ver Trabajo técnico).

## Hallazgos del 27-oct

| # | Hallazgo | Acción |
|---|---|---|
| 1 | OC y SC posteadas en la `013` (o sin bodega) **se perdían**: ~1.061 líneas de OC (5.457 u) y ~450 de SC | **Corregido**: se acreditan a 013-PP (`purchase_bodega`). Reprocesar con Sincronizar |
| 2 | Bodegas `000-003`, `000-010`, `000-022` reciben OC/SC (≈43, 71, 29 líneas) | Confirmar si son bodegas de posteo de sucursales y a cuál se acreditan |
| 3 | Caso 4 del documento cuenta dos veces el compromiso (SPEC-11 §3.1) | Abastecimiento decide; corregir el caso en el documento |
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
| 14 | El 63% de las OC abiertas se postea en la `013`; la exportación de solicitudes usa 013-PP como bodega de entrega | Confirmar con Compras |

Corrida del 28-oct (SPEC-21, datos reales): 132 traslados (89 Santiago → regiones, 484 u; 43
regiones → Santiago, 138 u); 49 nodos con stock retenido visible para jefatura; 427 excepciones;
USD 4,52 M sugerido; quiebre real USD 685 mil.

Corrida del 27-oct con consumo provisional PC/OF: 18.026 artículos; R 2.471, P 580, O 14.975, E 0;
271 a comprar hoy, 1.047 necesitan compra, 409 excepciones, 529 traslados; USD 3,16 M sugerido;
quiebre real USD 717 mil vs brecha contra objetivo USD 3,94 M.

## Decisiones abiertas

| # | Decisión | Quién | Hoy implementado |
|---|---|---|---|
| 1 | Costo: `lastpurprc`, precio del acuerdo global, o ambos | Abastecimiento | `lastpurprc`; en solicitudes, precio del acuerdo si existe |
| 2 | Fuente del consumo: OINM con TransType explícitos vs documentos | Abastecimiento / datos | OINM (consulta 8); respaldo PC/OF |
| 3 | Devoluciones: mes original o mes en que ocurren | Abastecimiento | Mes en que ocurren |
| 4 | OC con recepciones parciales: primera o última entrada | Abastecimiento | **Primera entrada** |
| 5 | Base de datos: SQLite vs PostgreSQL | Equipo | SQLite (corrida ~10 s) |
| 6 | "Familia" en parámetros: `u_rhfamilia` o grupo SAP | Abastecimiento | Grupo SAP |
| 7 | Bodegas evaluadas: todas las 013-xx físicas vs las 5 del documento | Abastecimiento → documento | Todas las 013-xx |
| 8 | P solo por PC/OF o también por consumo en 1–2 meses | Abastecimiento | Exige PC/OF (`p_solo_con_compromiso`) |
| 9 | Solicitud convertida en OC se cuenta una vez | Compras | Solicitudes exportadas cuentan hasta la siguiente carga de SC |
| 10 | Grupos "por revisar" (111, 131) | Abastecimiento | Activos |
| 11 | Costo de equipos de producción propia | Jefatura | 0 |
| 12 | Stock de seguridad de R-Intermitente (el documento no lo define) | Abastecimiento | ROP − consumo en el plazo (SPEC-10 §4) |
| 13 | Objetivo por bodega / doble conteo del caso 4 | Abastecimiento | Literal del documento (SPEC-11 §3.1) |
| 14 | Alertas de alza e irregularidad solo para R/E | Abastecimiento | Solo R/E |
| 15 | Días de reserva de consumo propio antes de trasladar (protección simétrica) | Abastecimiento | 15 días (`dias_reserva_traslado`) |
| 16 | Bodega de entrega de las solicitudes exportadas: 013-PP o 013 | Compras | 013-PP |

## Bloqueado

- **Escribir en SAP** (Service Layer, U_RPEO, U_CRITICO, creación de solicitudes): hasta habilitación
  de IT. Mientras tanto: planilla de exportación (SPEC-13 §5); validar la plantilla DTW con IT.
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
- **Doble conteo en la proyección**: descuenta consumo diario y compromisos (como pide el
  documento); revisar con datos de la consulta 8 (SPEC-12 §4).
- Clasificación por bodega; correo semanal de alertas; buzón de eventos (fase 2).
- Crear los grupos Django "Administrador Abastecimiento" y "Jefe Abastecimiento" y asignar usuarios.
- Configurar calendario real por proveedor (hoy ancla repartida por código).

## Documentación

- Specs 08–18 escritas el 27-oct. 02, 04 y 05 marcadas obsoletas; HARNESS_RULES reescrita.
- `Requerimientos_Calculadora_Compras5.docx`: incorporar conflictos (SPEC-06 §4), hallazgos 3 y 4,
  y reglas de SPEC-07.
- `03_sop_ui_ux.md`: revisar contra las pantallas nuevas.

## Hecho

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
