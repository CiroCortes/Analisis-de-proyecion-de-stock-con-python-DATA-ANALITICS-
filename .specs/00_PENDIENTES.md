# PENDIENTES (actualizado 27-oct-2026)

## Próximo paso (datos)

1. **Validar en Athena `data/consultas_calculadora_compras.sql`** con `LIMIT 5` (checklist SPEC-08 §5):
   bloque 0 (DESCRIBE), **consulta 8 consumo mensual** (la más importante: hoy el consumo es
   provisional desde PC/OF), **consulta 9 plazos reales** (hoy todo usa `OITM.LeadTime`), 10, 11, 12, 14.
2. **Cuadrar el consumo** de 30 artículos contra el informe de auditoría de stock de B1, por bodega
   (criterio de aceptación fase 1). Confirmar TransType 13, 14, 15, 16, 60.
3. Exportar completo a `data/`, correr `python manage.py calcular_compras` y revisar que
   `CargaDatos` muestre fuente `OINM`.

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
| 8 | 013-PP pide traslados grandes desde 013-09 / 013-07 (hasta 7.000 u) para cubrir sus OF | Ligado al punto OF con cantidades enormes |
| 9 | Ruido de alertas: alza e irregularidad en P/O (1.803 y 1.488) | **Corregido**: solo R/E |

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

## Bloqueado

- **Escribir en SAP** (Service Layer, U_RPEO, U_CRITICO, creación de solicitudes): hasta habilitación
  de IT. Mientras tanto: planilla de exportación (SPEC-13 §5); validar la plantilla DTW con IT.
- **Conexión directa a Athena** (boto3): construida, sin probar (`manage.py check_athena`).

## Trabajo técnico pendiente

- **Fusión del Recomendador (SPEC-19)**: en la rama `feature/fusion-recomendador`. Al fusionar a
  `main`, correr Sincronizar una vez (captura el escenario actual y publica). Tras la marcha
  blanca, decidir si se borra `/purchasing/` y si el motor anterior se reduce a solo el ROP de
  comparación.
- **Quiebre en el Dashboard**: desde SPEC-19 muestra el quiebre real (antes USD 96 M de brecha del
  motor anterior). Avisar a gerencia antes de presentar el Reporte Gerencial.
- **Verificar OF con cantidades enormes**: 2,7 M u comprometidas en 013-PP; sospecha de unidades
  (metros/kilos/litros). Revisar el top 10; afecta traslados y excepciones.
- **Stock en la `013` a secas** (1.704 u): hoy no se cuenta. Revisar si suma a 013-PP.
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
