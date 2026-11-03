# SPEC-37: Agente S&OP con servidor MCP (AWS Bedrock)

Fecha: 3-nov-2026. Estado: **planteado**, se implementa después de la marcha blanca.
Origen: la sesión del 3-nov, en que los casos 36274254, 36274821, 32010492 y 20401255 se resolvieron
siempre con el mismo método: leer la ficha, cruzar OC, facturas de reserva, OF, stock de SAP y plazos,
medir cuántos casos más hay y explicarlo. Ese método se puede automatizar.

---

## 1. Objetivo

Un agente que **conozca el negocio de Abastecimiento de Pesco**, lea el sistema y responda con evidencia
preguntas como:

- "¿Por qué el 20401255 aparece urgente si tiene una importación en camino?"
- "¿Qué importaciones llevan más de 6 meses detenidas?"
- "¿Qué OF antiguas inflan el 'Pedido' de SAP y quién las tiene?"
- "¿Qué cambió en el sugerido entre la corrida de ayer y la de hoy, y por qué?"

Además, **vigila**: después de cada corrida revisa las fallas conocidas (OF y PC antiguos, compras atrasadas,
tránsito detenido, plazos atípicos, códigos raros, pedido de SAP sin documento) y deja un resumen por
responsable.

## 2. Principios (no negociables)

1. **Solo lectura.** No crea ni modifica nada en SAP ni en la plataforma; no aprueba solicitudes ni cambia
   parámetros o marcas. Rige [SAP solo lectura] y las reglas de TI del Service Layer (SPEC-30).
2. **Sugiere, no decide.** Como la Calculadora: informa y recomienda; deciden Ignacio y Gisella.
3. **Toda afirmación con evidencia.** Cada número sale de una herramienta y se cita el documento
   (OC 2505141, FR 59761, OF 2308271, PC 2609370). Si un dato no está, lo dice; no lo deduce.
4. **Los datos de SAP son reales; lo que falla es el proceso.** Los hallazgos se plantean como procesos que
   corregir (OF sin cerrar, OC que quedó abierta), no como "error de datos".
5. **Dice qué tan frescos son los datos:** fecha de cada exportación y desfase entre ellas.
6. **Conoce su límite:** la causa de fondo muchas veces no está en SAP (en el 20401255, el problema con el
   proveedor lo sabía Comex). El agente detecta el síntoma, lo mide y dice **a quién preguntar**.

## 3. Arquitectura

```
 Usuarios (plataforma)        Otros clientes MCP (opcional, fase 4)
        │                               │
        ▼                               ▼
 Agente (plataforma Django) ──► Servidor MCP "pesco-sop" (solo lectura)
   modelo en AWS Bedrock            │            │             │
   con uso de herramientas          ▼            ▼             ▼
                              Base de la    Conocimiento   SAP en vivo (fase 3)
                              Calculadora   (.specs,       Service Layer / Athena,
                              (corridas,    glosario)      solo GET y con límites
                              OC, OF, PC…)
```

- **Servidor MCP:** una sola definición de las herramientas (§4), con nombre, descripción y parámetros.
  Lo usa el agente de la plataforma, y cualquier otro cliente que soporte MCP se conecta sin reprogramar
  nada. Vive junto a Django y reutiliza su código.
- **Modelo en Bedrock:** uno con uso de herramientas (por ejemplo, Claude en Bedrock), en la cuenta AWS de
  Pesco. A definir en §10.
- **Reemplaza al asistente actual** (`apps/ai_assistant`): hoy usa Gemini y solo le pasa al modelo las 10
  urgencias del motor anterior, sin herramientas, así que no puede investigar un caso.

## 4. Herramientas del servidor MCP

Casi todas envuelven código que ya existe. Todas devuelven JSON con los números y los documentos, más la
fecha de los datos.

### 4.1 Artículo

| Herramienta | Qué devuelve | Código existente |
|---|---|---|
| `ficha_articulo(codigo)` | Clase, ABC, consumo, SS, punto de pedido, máximo, disponible, compra sugerida, urgencia, "qué dice" | `ResultadoArticulo`, `views_planificacion._que_dice`, `_decision_compra` |
| `en_camino(codigo)` | OC, facturas de reserva y OF (vigentes y antiguas), con fechas, atraso, bodega SAP y origen | `OCAbierta`, `servicio.transito_por_nodo` |
| `compromisos(codigo)` | PC y OF abiertos con emisión, fecha, bodega y responsable | `CompromisoAbierto`, `CompromisoDetalle` |
| `posicion_sap(codigo)` | Stock, pedido y comprometido por bodega de SAP y cómo cuenta cada una | `analisis.bodegas_sap` |
| `consumo(codigo, meses)` | Consumo mensual por bodega y tipo (venta, salida, NC), picos recortados | `servicio.historico_articulo`, `ConsumoMensual` |
| `plazos(codigo)` | OC recibidas con días de entrega, típicas y atípicas | `PlazoOC`, `alertas.plazos_atipicos` |
| `alertas_articulo(codigo)` | Alertas vigentes con severidad y mensaje | `Alerta` |
| `memoria_calculo(codigo)` | Paso a paso del cálculo de ese artículo | `servicio.calcular_detalle`, `views_planificacion._memoria` |

### 4.2 Detectores de la red (las fallas encontradas)

| Herramienta | Falla | Origen |
|---|---|---|
| `compras_atrasadas(dias, tipo)` | OC o FR con fecha vencida que siguen contando como en camino | 20401255 (3-nov): ~USD 310 mil con más de 90 días |
| `importaciones_detenidas(dias)` | FR con mucho atraso y entradas parciales muy espaciadas | 20401255: OC de may-25, 6 entradas en 16 meses, 73 u en EE.UU. |
| `ofs_antiguas()` | OF abiertas sin cerrar que inflan el "Pedido" de SAP | SPEC-36: kits HIAB, 15 OF desde ago-2023 |
| `compromisos_antiguos()` | PC/OF abiertos hace meses, con su responsable | SPEC-23, SPEC-31 §6 |
| `pedido_sap_sin_documento()` | `OnOrder` de SAP sin OC, FR ni OF cargada | SPEC-35/36: residuo USD 252 mil |
| `plazos_atipicos()` | OC que no reflejan el plazo real del proveedor | SPEC-33 |
| `codigos_genericos()` | Códigos que no son productos (4999990xxx) y siguen en el sugerido | Pendiente #32: USD 640 mil |
| `buscar_alertas(tipo, severidad, nodo)` | Cualquier alerta de la última corrida | `Alerta` |
| `comparar_corridas(a, b)` | Qué cambió en el sugerido, el tránsito y el SS, y en qué artículos | Método usado en SPEC-35/36 |
| `frescura_datos()` | Fecha de cada exportación y desfase | `analisis.fechas_datos` |

### 4.3 Conocimiento del negocio

| Herramienta | Qué hace |
|---|---|
| `buscar_reglas(tema)` | Busca en los `.specs/` y en el glosario (§5) y devuelve el párrafo con su spec |
| `glosario(termino)` | Definición corta y en qué spec se acordó |

### 4.4 SAP en vivo (fase 3)

`documento_sap(tipo, numero)`: lee una OC, FR, OF o PC desde el Service Layer (solo GET, con los límites
del SPEC-30), para confirmar el estado al minuto. Ejemplo: comprobar que la OC 2505141 está cerrada y que
lo pendiente quedó en la FR.

## 5. Glosario del negocio (semilla)

Es lo que hace que el agente "sepa el negocio". Sale de los specs y **cada spec nuevo agrega sus términos**.

| Término | Regla | Spec |
|---|---|---|
| Proveedor `…P` / `…PE` | `P` = nacional, `PE` = **extranjero** (no interno) | 35 |
| Factura de reserva (FR) | En una importación la OC se pasa a FR y su línea se cierra; lo pendiente vive en la FR | 35 |
| Pre-bodega `000-xxx` | Stock embarcado, en camino a su destino; la entrada a pre-bodega es el **embarque**, no la llegada | 22, 35 |
| "Pedido" de SAP (`OnOrder`) | Suma OC + FR + **producto de OF abiertas** | 35, 36 |
| OF antigua | OF abierta hace más de `meses_of_vigente` meses: no cuenta, se avisa a Producción | 36 |
| Compromiso antiguo | PC/OF emitido hace más de `meses_compromisos_recientes` meses | 23 |
| Santiago | Un solo nodo de cálculo (todas las 013); cada 013-xx tiene su posición propia | 21, 34 |
| 013 a secas | Llegadas de regiones y despacho de PC de Santiago | 21 |
| 013-NC / 013-IN | NC comercial / ingreso físico | 25 |
| 4999990xxx | Códigos genéricos de entrega de materiales; no son productos | 32 (pend.) |
| Plazo atípico | OC sobre max(4 × mediana; mediana + 30): se recorta | 33 |
| Pico de consumo | Mes recortado a la mediana | 26 |
| `PrcrmntMtd` | No se usa en Pesco (todo `B`): no sirve para reconocer lo fabricado | 36 |

## 6. Vigía (después de cada corrida)

El agente corre los detectores de §4.2 y deja en el Panel un **resumen por responsable**, con lo nuevo
desde la corrida anterior y el valor en USD:

- **Compras:** compras atrasadas, plazos atípicos, sugerido que cambió mucho.
- **Comex:** importaciones detenidas (FR atrasadas, entradas parciales espaciadas).
- **Producción:** OF antiguas, pedido de SAP sin documento.
- **Contraloría:** PC/OF antiguos, códigos genéricos.

Primero, solo en pantalla. Correos o mensajes, cuando el resumen esté validado.

## 7. Casos dorados (cómo medir si responde bien)

Preguntas con respuesta conocida del 3-nov. El agente debe dar los mismos hechos y documentos:

| Pregunta | Respuesta esperada |
|---|---|
| ¿Por qué 36274254 no tenía OC? | Importación HIAB: OC 2610008 pasó a FR 74500; 1 u de 000-022 a 002-02; antes se excluía el sufijo PE |
| ¿Qué es el "pedido" de 36274821? | 15 OF de 1 u desde 17-08-2023 sin cerrar (USD 468 mil); no llegarán; Producción debe cerrarlas |
| ¿Hay que comprar butacas 32010492? | No: 83 u en fabricación (OF 2609227 y 2610193) |
| ¿Qué pasa con 20401255? | OC 2505141 (may-25, 250 u) con 6 entradas parciales; 73 u en FR 59761/60238, vencidas desde ene-26; PC 2609370 de 120 u; aun contando lo que viene, faltan 49 |
| ¿Por qué 4201130215 compraba 8 u? | OC 2402156 de 294 días inflaba el SS; con el tope, la compra es 0 |

Metas antes de abrirlo a usuarios: 100 % de los hechos de los casos dorados, ningún número sin fuente, y
"no lo sé" cuando el dato no está.

## 8. Seguridad y TI

- **Datos fuera de la plataforma:** con Bedrock, las consultas quedan en la cuenta AWS de Pesco. Confirmar con
  TI la región y que se acepta enviar costos y proveedores al modelo.
- **Acceso:** solo usuarios autenticados de la plataforma; las herramientas respetan los roles (César consulta,
  no edita).
- **Auditoría:** se registra cada pregunta, las herramientas usadas y la respuesta.
- **SAP:** fase 3 solo con el cliente del SPEC-30 (GET, límites de carga, red Pesco).
- **Costo:** tope mensual y por usuario; la vigía corre una vez por corrida.

## 9. Fases

| Fase | Contenido | Requisito |
|---|---|---|
| 0 | Marcha blanca de la Calculadora con datos validados | En curso |
| 1 | Servidor MCP con §4.1, §4.2 y §4.3 sobre la base de la Calculadora; chat en la plataforma; casos dorados | Cuenta Bedrock y modelo elegido |
| 2 | Vigía con resumen por responsable en el Panel | Fase 1 validada |
| 3 | `documento_sap` en vivo por Service Layer | Pendiente #35 (red y subdominio) |
| 4 | Otros clientes MCP (por ejemplo, un asistente de escritorio para Ignacio) | Política de TI |

## 10. Decisiones abiertas

1. Modelo y región en Bedrock (TI y Gisella).
2. Quién usa el agente en la fase 1 (propuesta: Ciro, Ignacio, César).
3. Cuánto tiempo se guardan las conversaciones (auditoría).
4. Retirar el asistente Gemini actual cuando entre la fase 1.
5. Si la vigía también propone acciones (por ejemplo, "anular OF 2308271") o solo informa.

## 11. Fuera de alcance

- Escribir en SAP o en la plataforma, aprobar compras o cambiar parámetros.
- Reemplazar el cálculo: el agente explica y vigila lo que calcula la Calculadora.
- Leer correos o conversaciones (la causa que solo sabe Comex queda fuera; el agente dice a quién preguntar).
