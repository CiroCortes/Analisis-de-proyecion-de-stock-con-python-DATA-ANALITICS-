# SPEC-24: Analizar artículos (vista tipo Slim4)

Fecha: 28-oct-2026. Origen: reunión S&OP del 28-oct. Abastecimiento mostró la pantalla
"Vista rápida: Clasificaciones > Analizar artículos" de Slim4 y pidió replicarla; Producción pidió
ver Santiago también por bodega (013-PS y 013-PP rotan distinto).
Código: `apps/calc/prevision.py`, `apps/calculadora/analisis.py`, `views_fusion.analizar*`,
`templates/calculadora/analizar.html`. Tests: `tests/test_analizar.py`.

---

## 1. Tres ventanas

1. **Listado** de la ubicación elegida, ordenable por cualquier columna (por defecto, meses con
   consumo) y recorrible con el mouse o con las flechas ↑ ↓.
2. **Gráfico** del artículo seleccionado en esa ubicación: 12 meses de demanda real (azul) y 12 de
   previsión (amarillo), con demanda media, tendencia, meses con demanda y previsión total.
3. **Mismo artículo en todas las ubicaciones**: al pinchar una fila el gráfico cambia a esa ubicación.

Columnas: demanda media, a pedir, stock, por recibir, por entregar, consumo 12 meses, meses con
consumo, costo y stock valorizado. Excel del listado con la previsión de 12 meses.

## 2. Ubicaciones

| Ubicación | Consumo | Posición (stock, recibir, entregar) | A pedir |
|---|---|---|---|
| Santiago (todas) | todo lo que cae en el nodo 013 | nodo 013 de la última corrida | compra de la red (llega a Santiago) |
| Bodega 013-xx | solo esa bodega | métricas de inventario de la bodega | — (detalle; la compra es del nodo) |
| Sucursal | su bodega | nodo de la última corrida | faltante del nodo (traslado o espera compra) |

Así se cumplen ambos pedidos: el cálculo sigue con Santiago unificado (SPEC-21) y cada 013-xx se ve
por separado.

## 3. Previsión v1

- Demanda media = promedio de 12 meses con los atípicos recortados (la misma del cálculo, SPEC-10 §1).
- Tendencia = pendiente de la recta sobre esos 12 meses, acotada para que el último mes previsto no se
  aleje más de un 50% de la demanda media.
- Previsión del mes k = media + tendencia × distancia al centro de la historia, nunca negativa.
- **No es estacional.** Una v2 estacional requiere 24 meses confiables de OINM (ver SPEC-22 §4).

Validación con la foto de Slim4 (31601019 LIMPIA CONTACTOS), demanda media / stock / venta 12 m /
meses: Antofagasta 5,56·21·69·12 en Slim4 vs 5,83·23·70·12 aquí; 013-PS 6,28·24·87·12 vs
7,00·24·84·12; 013-PP 4,08·18·49·8 vs 5,42·18·65·8.
