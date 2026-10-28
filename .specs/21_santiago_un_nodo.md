# SPEC-21: Santiago como un solo stock, protección simétrica y decisión de compra

Fecha: 28-oct-2026. Origen: revisión con el desarrollador (experiencia en logística de Pesco) y
el encargado de repuestos (usuario de Slim4). Reemplaza SPEC-11 §4 (reparto) y ajusta SPEC-07 §4–5.
Código: `apps/calc/red.py`, `apps/calc/politica.py`, `apps/calculadora/servicio.py`,
`apps/calculadora/publicacion.py`, `apps/calculadora/views_planificacion.py`.
Tests: `tests/test_calc_red_nodos.py`, `tests/test_santiago_nodo.py`, caso 4 en `test_calc_golden.py`.

---

## 1. Cómo opera Santiago (relevado el 28-oct)

- Las bodegas `013-xx` están **físicamente juntas**. El recolector de una OF va a la 013-03, 013-PS,
  013-PP… y **consume directamente desde ahí**. Ir a otra 013-xx no es un traslado.
- Lo que sale de la 013-PP es lo que los informes registran para OF.
- **Ventas de Santiago**: todo PC sale por la `013`. El encargado de distribución pide a las bodegas
  y despacha desde la 013. Las sucursales despachan desde su propia bodega.
- Lo que **llega de regiones** pasa del tránsito a la `013` y se consume desde ahí.
- Datos 12 meses (27-oct): la 013-PP registra el 50% de las salidas a OF, pero solo el 8% de los
  artículos con stock (la 013-03 el 33%). El 30% de los artículos con consumo sale de 2 o más
  bodegas. 401 de 509 traslados sugeridos (27.067 de 27.650 u) eran internos de Santiago, casi todos
  hacia 013-PP: **ficticios**.

## 2. Regla: Santiago es un solo nodo

- `red.agrupar_santiago()` suma todas las bodegas de Santiago en un nodo con código **`013`**
  (en SAP "Bodega Central"): stock, tránsito, compromisos, consumo; fecha de compromiso = la más
  cercana. Guarda `componentes` = stock físico por bodega (vista informativa y guía de picking).
- El stock de la **`013` a secas** se suma al nodo (antes se descartaba como "de paso"). Se lee de
  `StockActual`; sus compromisos ya vienen de las líneas de PC/OF (no se suman dos veces).
- Las solicitudes aprobadas de la plataforma suman al tránsito del nodo Santiago.
- **No hay traslados entre bodegas de Santiago.** Solo Santiago ↔ sucursales.
- La compra de la red **no cambia**: ya se calculaba con el total de la red.
- `commitment_bodega` / `purchase_bodega` siguen igual (las usa el motor anterior); para la
  Calculadora cualquier bodega de Santiago, la 013 o consignación cae en el mismo nodo.

## 3. Regla: protección simétrica

Ningún nodo entrega lo que necesita para sí mismo, en ambos sentidos (Santiago → sucursal y
sucursal → Santiago):

```
protegido = comprometido + consumo_diario_del_nodo × dias_reserva_traslado
libre     = MAX(0; stock_fisico − protegido)      -> solo esto se sugiere trasladar
retenido  = MIN(stock_fisico; protegido)          -> se muestra, no se sugiere
```

- `dias_reserva_traslado`: parámetro general, **15 días** por defecto (= ciclo de compra: el nodo
  guarda su consumo hasta la siguiente reposición). Editable con registro (SPEC-14). Decisión abierta.
- Si jefatura decide mover stock retenido, es decisión de la operación. La compra de la red ya
  cubre la reposición: mover stock entre nodos no cambia el total de la red.

## 4. Reparto (`red.distribuir`, recibe nodos)

| Solicitante | Necesidad | Donantes |
|---|---|---|
| Sucursal | `faltante = MAX(0; −disponible)`: lo que realmente le falta | Libre de Santiago |
| Santiago | `faltante = MAX(0; −disponible)` | Libre de las sucursales, mayor primero |

- El faltante ya no cuenta dos veces el compromiso (corregido el 28-oct, SPEC-11 §3.1).
- Prioridad entre solicitantes: igual que antes (urgentes, fecha comprometida, código).
- Lo no cubierto queda en ESPERA COMPRA. `retenido_en` lista los donantes con stock retenido
  (para que jefatura decida). `sucursales_con_stock` (alerta TRASLADO_SUCURSALES) usa el libre.
- Traslados entre sucursales: no se sugieren (sin cambio).
- Un traslado desde Santiago lleva `desde`: de qué bodegas 013-xx sacarlo (mayor stock primero).

### 4.1 Caso 4 del documento

002 con comprometido 1 y disponible −1; 013-03 con 2. Documento: traslado 013-03 → 002 por 2.
Ahora: traslado **Santiago (013) → 002 por 1, desde 013-03: 1** (le falta 1; el 2 del documento cuenta
dos veces el compromiso). TRASLADAR, sin compra.

## 5. Decisión de compra en la ficha (sugerencia del encargado de repuestos)

Sección "¿Comprar todo de una vez?" en `calculadora:articulo`:

1. **Consumo por nodo, mes a mes** (Santiago + sucursales, 12 meses cerrados): promedio, meses con
   consumo y meses atípicos (> `multiplicador_atipico` × promedio del nodo, misma regla del consumo).
2. **Compra en meses** = cantidad sugerida ÷ consumo mensual usado.
3. **Compra mínima** = `cantidad_minima(punto_pedido − disponible)` (`politica.compra_hasta_punto_pedido`):
   llega a la siguiente compra con el stock de seguridad, porque el punto de pedido ya incluye el
   consumo del plazo más el ciclo de revisión. Respeta mínimo de meses, MinOrdrQty y múltiplo.
   El documento manda comprar **hasta el máximo**: la sugerida no cambia; la mínima es información
   para el comprador.
4. **Santiago por bodega** (informativo): stock físico de cada 013-xx y de la 013.

## 6. Persistencia

- `ResultadoBodega`: una fila por nodo (Santiago = bodega `013`). Nuevos: `protegido`,
  `retenido_en`, `componentes`. `excedente` = libre.
- `TrasladoSugerido.detalle_origen`: [[bodega, cantidad]] para traslados desde Santiago.
- `StockProjection` (Dashboard): Santiago se publica en la bodega `013`.

## 7. Fuera de alcance

- `SolicitudCompra.bodega_entrega` sigue en 013-PP (bodega de entrega para la exportación a SAP).
  Los datos muestran que el 63% de las OC abiertas se postean en la 013: confirmar con Compras.
- El motor anterior (`classification_engine`) no cambia.
