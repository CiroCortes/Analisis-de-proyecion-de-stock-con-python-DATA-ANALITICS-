# SPEC-32: Estado de los requerimientos (gerencia v5 y Abastecimiento) al 3-nov-2026

Fecha: 3-nov-2026. Origen: revisión general después del hito del 2-nov (consumo desde OIVL, SPEC-25 y 31).
Fuentes: `Requerimientos_Calculadora_Compras5.docx` (gerencia de Supply Chain, 23-oct; texto en
`fuente_requerimientos_calculadora_compras5.txt`) y el documento de requerimientos de Abastecimiento
con la reunión del 2-nov (SPEC-31). Principio: **la herramienta sugiere; no compra ni escribe en SAP**.

Estados: **Hecho** · **Parcial** · **Pendiente** · **Cambió** (por una decisión registrada) · **Decidir**.

---

## 1. Correcciones de esta revisión

1. **Aviso de duplicados falso al regenerar** (§5 del doc.). `solicitudes.generar` buscaba las líneas de
   los últimos 15 días *antes* de borrar los borradores del mismo día: al regenerar, cada línea quedaba
   "duplicada" contra su propio borrador anterior y la aprobación pedía confirmar duplicados inexistentes.
   Corregido: se buscan después de borrar.
2. **Solicitud exportada que se volvía a sugerir.** Una exportada dejaba de contar como en camino con la
   siguiente carga de SC (se suponía que la SC de SAP la reemplazaba). Desde SPEC-31 las SC no cuentan,
   así que entre esa carga y la OC la cantidad desaparecía y se sugería de nuevo. Ahora:
   - si `sc_cuenta_en_transito` = Sí: regla anterior (hasta la siguiente carga de SC);
   - si No: cuenta hasta que hay una **OC abierta del mismo artículo y proveedor emitida desde la
     exportación**, o hasta que pasan `dias_vigencia_exportada` días (parámetro nuevo, inicial **45**), para
     no frenar la compra si la solicitud nunca se convirtió en OC.

   Tests en `tests/test_revision_28oct.py::RevisionNov3Test`.
3. Specs y comentarios al día con OIVL (08, 22, `cargadores.py`, `proyeccion.py`); referencias a tests
   inexistentes en SPEC-22 y 23; decisiones #2 y #3 y numeración en `00_PENDIENTES.md`.

## 2. Documento de gerencia (v5)

| § | Requerimiento | Estado | Dónde / nota |
|---|---|---|---|
| 1 | Un solo motor, recalcula todo en cada corrida | Hecho | SPEC-18/19 |
| 1 | Actualización diaria automática | Pendiente | Hoy: TXT exportados a mano + Sincronizar. Vía: Service Layer (SPEC-30), espera red y subdominio |
| 1 | Bodegas evaluadas (5 + 5) | Cambió | Todas las 013-xx físicas; Santiago un solo nodo (SPEC-21) |
| 2 | Consumo neto de devoluciones y NC, 24 meses | Hecho | Consulta 8 sobre **OIVL**; NC a la bodega y mes de la guía; 013-NC fuera (SPEC-25) |
| 2 | Traslados en tránsito | Cambió | Solo stock en bodegas T…; las ST nunca cuentan (SPEC-31 §2) |
| 2 | SC abiertas en el tránsito | Cambió | No cuentan por defecto (pedido de Abastecimiento, 2-nov) |
| 2 | Costo AvgPrice | Cambió | `lastpurprc` en USD (decisión abierta #1) |
| 2 | Saldo de acuerdos globales | Bloqueado | `planqty` ilegible en Glue: falta que datos amplíe el tipo |
| 3 | Clasificación E/R/P/O, subclases, Nuevo, Inmovilizado, ABC y nivel de servicio, historial | Hecho | SPEC-09. Además ABC por venta informativo (SPEC-31 §4) |
| 3 | P por consumo en 1–2 meses o compromiso | Cambió | Exige compromiso (#8) |
| 3 | Clasificación por bodega | Pendiente | Solo consolidada; lo cercano es `CAIDA_CONSUMO_NODO` |
| 3 | Reclasificación el 1er día hábil | Parcial | Cada corrida reescribe la foto del mes; sin disparo automático |
| 3 | Letra y crítico en UDF de SAP | Cambió | Viven en la plataforma (SAP solo lectura) |
| 4.1 | Promedio, diario, desviación | Hecho | + promedio con demanda informativo |
| 4.1 | Tope de mes atípico | Cambió | Menor entre prom + 3σ y 4 × mediana (SPEC-26) |
| 4.2–4.5 | Plazo real + 2 días, SS, PP y máximo, regla R-Intermitente | Hecho | SS de R-Intermitente no definido en el doc. (#12) |
| 4.6 | Disponible futuro, cantidad, urgencia, cobertura | Hecho | Posible doble conteo PP/compromisos (#18) |
| 4.6.1 | Calendario por proveedor | Parcial | Funciona con ancla repartida por código: falta cargar el calendario real |
| 4.6.2 | Proyección diaria, excepción, causa, alertas | Hecho / Cambió | Descuenta MAX(consumo; compromisos) (SPEC-12 §4); el caso 5 cambia |
| 4.6.2 | Solicitud de excepción generada sola el mismo día | Parcial | Se genera con "Generar" o `calcular_compras --solicitudes` |
| 4.6.2 | Solicitudes creadas a mano marcadas como excepción | Pendiente | No existe crear líneas a mano |
| 4.7 | Eventos comerciales | Hecho | SPEC-16. Buzón de correo: fase 2 |
| 5 | Compra de la red en 013-PP, reparto, prioridades, acciones por bodega | Hecho / Cambió | Faltante = MAX(0; −disponible); sin traslados internos de Santiago; protección simétrica |
| 5 | Aviso de duplicado 15 días | Hecho | Corregido el falso positivo (§1) |
| 6 | Solicitudes por proveedor con acuerdo de menor precio, edición y aprobación | Hecho | — |
| 6 | Crear la SC en B1 | Cambió | Exportación a Excel (nunca se escribe en SAP) |
| 7 | Parámetros editables por nivel, rangos, simulación | Hecho | Simulación solo nivel general |
| 7 | Umbrales de alerta como parámetros | Parcial | Fijos en código: caída 50 %, alza 150 %, irregular 50 %, ventana duplicado 15 d, plazo 1,5× |
| 7 | Roles | Parcial | Código listo; faltan los grupos de Django y asignar usuarios |
| 7 | Registro de cambios | Parcial | Parámetros sí; crítico, mínimos y marcas solo guardan el último usuario |
| 8 | Grilla, vistas, memoria de cálculo, Excel | Parcial | Faltan columnas nacional/importado y variación de entrega |
| 8 | Alertas con estado, responsable y comentario | Hecho | 14 del doc. + PICO, DOBLE_ENVIO, CAIDA_CONSUMO_NODO, COMPROMISO_ANTIGUO |
| 8 | Correo semanal de alertas | Pendiente | — |
| 8 | Reporte de impacto | Parcial | Falta el corte por bodega; requiere 2 fotos mensuales |
| 8 | Gráficos | Parcial | Faltan marcas de eventos y cambios de letra |
| 8 | Filtros (comprador, bodega en Indicadores) | Parcial | Sin filtro por comprador; Indicadores no filtra por bodega |
| 8 | Panel escenario actual vs propuesto | Parcial | Cobertura solo por letra/ABC; quiebres a 365 d (doc.: 120) |
| 9 | Casos borde | Hecho | Equivalencias solo desde el admin, sin cadenas A→B→C |
| 10 | Casos de prueba 1–5 | Hecho con desvíos | Caso 3: dato inconsistente del doc.; casos 4 y 5 cambian a propósito |

## 3. Requerimientos de Abastecimiento (SPEC-31)

| Punto | Estado |
|---|---|
| Alcance de bodegas 013-xx y pañoles | Hecho |
| Consumo de OF por fecha de emisión | Hecho |
| Traslados y ajustes no son demanda; ST no cuentan | Hecho |
| SC fuera del tránsito; en camino por OC y por traslado | Hecho (+ corrección §1.2) |
| Promedio de meses con demanda | Hecho: regla R-Intermitente + ambos promedios en la ficha |
| Vista del artículo en toda la red, búsqueda por descripción | Hecho |
| Alerta de tendencia y caída por bodega | Hecho |
| Marca excluir del cálculo / liquidación; equipos de gerencia | Hecho. **Falta cargar las marcas** (Ciro, validado con Ignacio) |
| ABC por venta | Hecho (consulta 17) |
| NC ligada a su factura y guía | Hecho (SPEC-25) |
| Comprar por sucursal a su pre-bodega | **Decidir** (gerencia). El motor sigue centralizado |

## 4. Criterios de aceptación del documento (§13)

| Fase | Estado |
|---|---|
| 1. Datos | No cumplido: carga manual; falta cuadrar 30 artículos con el informe de auditoría de B1 |
| 2. Clasificación | No cumplido: faltan dos cierres de mes revisados |
| 3. Cálculo | Tests verdes; casos 3, 4 y 5 requieren que gerencia corrija o acepte el documento |
| 4. Traslados y solicitudes | Criterio a ajustar: "el Excel coincide con lo aprobado" en vez de "creadas en B1" |
| 5. Pantallas | Implementado; falta la prueba de un comprador sin ayuda |
| 6. Marcha blanca | Pendiente: tras validar el Service Layer de pruebas |

## 5. Para decidir (gerencia y jefatura)

1. Aceptar los cambios de los casos 4 y 5 y corregir el dato del caso 3 en el documento.
2. Comprar por sucursal o centralizar.
3. Venta de exportación (0EX) como demanda (USD 460 mil del sugerido).
4. Prioridad de lo Pendiente/Parcial antes de la marcha blanca. Propuesta: umbrales de alerta como
   parámetros, filtro por comprador, grupos de roles y registro de cambios de las marcas (cortos);
   correo semanal, clasificación por bodega y gráficos con marcas (después).
