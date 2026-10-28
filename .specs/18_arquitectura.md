# SPEC-18: Arquitectura de la Calculadora de Compras

Estado: implementado el 27-oct-2026. Specs relacionadas: 08 (datos) a 17 (casos dorados).

---

## 1. Capas

| Capa | Ubicación | Responsabilidad | Regla |
|---|---|---|---|
| Núcleo de cálculo | `apps/calc/` | Fórmulas puras: `params`, `consumo`, `plazo`, `clasificacion`, `politica`, `red`, `proyeccion`, `calendario`, `simulacion`, `redondeo`, `motor` | **Sin imports de Django**; recibe números, devuelve dataclasses |
| Ingesta | `apps/data_ingestion/` | Pipeline de TXT actual, zonas y bodegas (`warehouses.py`) | Sin cambios de contrato (7 consultas) |
| Calculadora (Django) | `apps/calculadora/` | `models`, `cargadores`, `servicio`, `alertas`, `solicitudes`, `parametros`, `excel`, vistas | Lee/escribe BD y arma las entradas del núcleo |
| Pantallas | `views_planificacion.py`, `views_gestion.py`, `templates/calculadora/` | Grilla, detalle, solicitudes, etc. | Tailwind + paleta `pesco-*` de `base.html` |
| Motor anterior | `apps/inventory/classification_engine.py` | REPO + DRP por bodega | Se conserva como **escenario actual** |

## 2. Flujo de datos

```
TXT del Datalake (data/)
  └─ run_full_datalake_pipeline()         apps/data_ingestion/datalake_ingest.py
       1-6  maestro, stock, OF, PC, OC, SC  → ProductSKU, InventoryMetric, movimientos
       7    run_classification_engine()     → SKUClassification, StockProjection (escenario actual)
       8    cargar_todo()                   apps/calculadora/cargadores.py
              → OCAbierta, CompromisoAbierto, Proveedor, ParametroCompra, PlazoOC,
                AcuerdoGlobal, ConsumoMensual (+ CargaDatos)
            ejecutar_corrida()              apps/calculadora/servicio.py
              Datos (todo en memoria) → Resolutor de parámetros → ABC de la población
              → por artículo: _entrada → apps.calc.motor.calcular_articulo → simulación
              → ResultadoArticulo, ResultadoBodega, TrasladoSugerido, HistorialMensual
              → alertas.generar → Alerta
  └─ Pantallas /calculadora/…  →  solicitudes.generar → SolicitudCompra → Excel (DTW)
```

Cada corrida recalcula todo desde cero y reemplaza los resultados de la anterior (documento §1).
El detalle de un artículo se recalcula en memoria (`calcular_detalle`) para la memoria de cálculo
y la serie diaria de 120 días.

## 3. Comandos

| Comando | Qué hace |
|---|---|
| Pantalla **Sincronizar** (`/ingest/`) | Pipeline completo (pasos 1–8) |
| `python manage.py calcular_compras` | `cargar_todo()` + corrida |
| `… --sin-carga` | Solo la corrida |
| `… --solicitudes` | Además genera las solicitudes del día |
| Botón "Recalcular" del panel (`/calculadora/correr/`) | Corrida desde la plataforma |

## 4. Pantallas (`/calculadora/`, app `calculadora`)

### 4.1 Planificación (`views_planificacion.py`)

| URL | Nombre | Contenido |
|---|---|---|
| `/calculadora/` | panel | Resumen de la última corrida, KPIs, botón recalcular |
| `grilla/` · `grilla/excel/` | grilla | Grilla principal §8 con filtros y exportación |
| `articulo/<code>/` · `…/config/` | articulo | Memoria de cálculo, gráficos (consumo, proyección con SS/ROP/máximo), bodegas, historial; edición de E, crítico y mínimos |
| `indicadores/` | indicadores | Escenario actual vs propuesto, exceso, obsolescencia, intervención, impacto |

### 4.2 Gestión (`views_gestion.py`)

| URL | Contenido |
|---|---|
| `solicitudes/`, `generar/`, `exportar/`, `<pk>/`, `<pk>/linea/<lpk>/`, `<pk>/aprobar/`, `<pk>/descartar/` | Solicitudes por proveedor (SPEC-13) |
| `traslados/`, `traslados/excel/` | Traslados por origen → destino |
| `alertas/`, `alertas/<pk>/` | Alertas con estado y comentario (SPEC-15) |
| `eventos/`, `eventos/<pk>/estado/` | Eventos comerciales (SPEC-16) |
| `parametros/`, `parametros/simular/`, `parametros/historial/excel/` | Parámetros (SPEC-14) |
| `proveedores/` | Calendario de compra por proveedor (SPEC-12) |

### 4.3 Fusión del Recomendador (`views_fusion.py`, SPEC-19)

| URL | Contenido |
|---|---|
| `bodegas/`, `bodegas/excel/` | Vista por bodega y zona: riesgo, quiebre real, traslados, espera compra, cobertura |
| `segmentacion/` | Matriz ABC × XYZ con recomendación por celda |
| `guia/` | Glosario en lenguaje simple (`glosario.py`) y uso en 5 pasos |

Subnavegación común: `templates/calculadora/_subnav.html` con `calc_subnav` del context processor
`apps.calculadora.context_processors.calculadora`. Enlace "Calculadora" en `base.html`.
Ayuda en contexto: `{% load calculadora_tags %}{% ayuda 'clave' %}`.

**Fuente única (SPEC-19 §2):** al final de cada corrida `publicacion.publicar()` reescribe
`StockProjection` y `SKUClassification`, así el Dashboard, el Reporte Gerencial, el Asistente
IA y el Recomendador (`/purchasing/`, fuera del menú) muestran los números de la Calculadora.
Hay una sola ficha de artículo, `calculadora:articulo`; `/inventory/sku/<código>/` redirige a ella
y todo recálculo pasa por `servicio.recalcular_red()` (SPEC-20). El motor anterior se ejecuta antes en el pipeline y su resultado se guarda en
`EscenarioActual` (`capturar_escenario_actual()`), que alimenta el panel actual vs propuesto.

## 5. Roles

Grupos Django "Administrador Abastecimiento" (edita parámetros, aprueba) y "Jefe Abastecimiento"
(aprueba solicitudes y eventos); el resto ve y edita líneas. Ver SPEC-14 §3.

## 6. Rendimiento

Corrida completa en SQLite: ~10 s para 18.026 artículos (corrida del 27-oct), incluida la
simulación de ambos escenarios. Escrituras con `bulk_create`; `ResultadoBodega` solo guarda
bodegas con movimiento. La migración a PostgreSQL sigue pendiente (decisión abierta #5).

## 7. Pruebas

| Suite | Cubre |
|---|---|
| `tests/test_calc_golden.py` | Casos 1–5 del documento (SPEC-17) |
| `tests/test_calc_reglas.py` | Redondeo, clasificación, ABC, consumo y atípicos, plazo, compra, red, calendario, motor, parámetros |
| `tests/test_ingestion_and_rop.py` | Pipeline actual (SC, DRP, bodegas) |
| `tests/test_calculadora_servicio.py` | Cargadores, corrida, historial, alertas, simulación |
| `tests/test_calculadora_vistas_*.py`, `tests/test_vistas_fusion.py` | Pantallas |
| `tests/test_fusion.py` | XYZ, histórico, cobertura por bodega, escenario actual y publicación (SPEC-19) |
| `tests/conftest.py` | Parche del test client para Django 5.1 + Python 3.14 |

## 8. Fuera de alcance (por ahora)

Escritura en SAP (Service Layer, U_RPEO, U_CRITICO); clasificación por bodega; correo semanal de
alertas; buzón de eventos; conexión directa a Athena.
