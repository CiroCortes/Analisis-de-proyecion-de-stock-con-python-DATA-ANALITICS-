# SPEC-34: Santiago por bodega en el menú Bodegas

Fecha: 3-nov-2026. Origen: reunión 28-oct (ver Santiago por bodega) y SPEC-21 (Santiago es un solo nodo).
Código: `apps/calculadora/analisis.py` (`santiago_por_bodega`, `resumen_santiago_por_bodega`),
`apps/calculadora/views_fusion.py` (`bodegas`, `bodegas_excel`), `templates/calculadora/bodegas.html`.
Tests: `tests/test_spec34.py`.

---

## 1. Qué cambia

El cálculo **sigue tratando a Santiago como un solo nodo** (SPEC-21): la acción, la compra y los traslados
se deciden para todas las 013-xx juntas. Lo nuevo es **ver** la posición propia de cada bodega de Santiago:

- **Resumen por nodo:** bajo la fila de Santiago, una fila por 013-xx con artículos, faltantes locales,
  faltante valorizado, stock valorizado y cobertura mediana. Dice "parte de Santiago": no son nodos.
- **Selector de bodega:** las 013-xx aparecen bajo Santiago. Al elegir una, la grilla muestra por artículo:
  stock, por llegar (OC + transferencias + SC si cuentan), comprometido (PC y OF de esa bodega),
  disponible, faltante local, consumo de 12 meses cerrados, cobertura y la **acción del nodo Santiago**.
- **Fila de Santiago:** debajo del código, el stock físico de cada 013 cuando hay más de una.
- **Excel:** con una 013-xx elegida, descarga su posición propia; el Excel general agrega la columna
  "Stock por bodega (Santiago)".

## 2. Reglas

- Disponible de la bodega = stock + por llegar − comprometido. Faltante local = lo negativo de eso.
  Un faltante local **no es un quiebre**: se cubre con stock de otra 013 o con la compra de la red.
- Consumo diario = consumo de la bodega en los 12 meses cerrados / 365. Cobertura = disponible / diario.
  Cobertura corta = menor que el plazo total del artículo.
- Por defecto se listan los artículos con faltante local, cobertura corta o acción del nodo; "Ver todo"
  muestra el resto. Orden: faltante USD, faltante, cobertura.
