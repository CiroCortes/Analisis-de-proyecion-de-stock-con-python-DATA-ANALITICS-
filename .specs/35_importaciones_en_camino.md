# SPEC-35: Importaciones en camino (proveedores extranjeros y facturas de reserva)

Fecha: 3-nov-2026. Origen: revisión del artículo 36274254 (cilindro HIAB, RPTS. EQ. IZAJE).
Código: `data/consultas_datalake.sql` (consultas 5 y 9), `apps/calculadora/cargadores.py`,
`apps/calculadora/models.py` (`OCAbierta`), ficha del artículo y Analizar. Tests: `tests/test_spec35.py`.

---

## 1. Hallazgo

En Analizar, el 36274254 aparecía **sin OC abiertas**. En SAP, el mapa de relaciones muestra una importación
grande y vigente de HIAB FINLAND OY (`0000000370PE`):

```
Pedido (OC) 2610008  ──►  Factura de reserva de acreedores 74500 (abierta, PO 2610008/09/11/12)
                     ──►  Entradas de mercancías (parciales)  ──►  Precio de entrega
```

Hay dos causas, y cada una basta para que la importación no se vea:

1. **El filtro `cardcode NOT LIKE '%PE'` de la consulta 5.** Se escribió creyendo que `PE` marcaba a los
   proveedores internos. En el maestro de proveedores, `P` es proveedor nacional (~4.600, Chile) y **`PE` es
   proveedor extranjero** (243: US 75, CN 58, BR 16, IT 9…). El filtro dejaba fuera **todas las importaciones**.
   Las empresas del grupo (Pesco Perú, Pesco Rental, Pesco Producción…) no se reconocen por el sufijo.
2. **La factura de reserva.** En las importaciones, Compras pasa la OC (PO) a una factura de reserva de
   acreedores, y desde ella se hace la entrada de mercancías. Al copiarse, la línea de la OC queda cerrada:
   lo pendiente vive en la factura (`opch.isins = 'Y'`), no en `por1`. Aunque se quitara el filtro, esas
   unidades seguirían sin verse.

Tampoco funcionaba el respaldo con lo pedido en SAP (`OITW.OnOrder`): las líneas de la factura van a
pre-bodegas (`000`, `000-002`, `000-010`, `000-022`), y el respaldo solo funciona en bodegas que son nodo.

**Efecto colateral en el plazo.** La consulta 9 (plazos reales) solo unía las entradas hechas desde la OC
(`pdn1.basetype = 22`). Las de importación se hacen desde la factura (`basetype = 18`): de **6.653** líneas de
entrada de proveedores extranjeros, solo **52** llegaban a los plazos. Para el resto se usaba el lead time del
maestro (70 días para el 36274254).

## 2. Impacto (TXT del 2-nov, solo categorías activas)

`OITW.OnOrder` menos las líneas de OC cargadas: **819 artículos, 14.750 u, USD 2,4 M** que SAP marca como
pedidos y la Calculadora no ve. Para esos artículos puede sugerir comprar lo que ya viene en camino.

El "Pedido SAP sin OC (USD 133 mil)" del SPEC-31 y del pendiente #34 se explicó como "proveedores internos";
la explicación era equivocada: eran importaciones.

## 3. Regla

**Consulta 5 (en camino) = a) + b):**

- a) Líneas de OC abiertas (`opor`/`por1`, sin filtro de proveedor, sin canceladas).
- b) Líneas de facturas de reserva abiertas (`opch.isins = 'Y'`, no canceladas, `linestatus = 'O'`).
  Pendiente = cantidad facturada − lo recibido desde esa línea (`pdn1.basetype = 18`, entradas no canceladas).
  Se calcula así, y no con `pch1.openqty`, para no depender de cómo SAP usa ese campo en una factura.
- `nro_oc_sap` es la OC de origen (la que sigue Compras). Para b) la fecha de emisión es la de la OC, y se
  agregan dos columnas: `tipo_documento` (`OC` o `FR`) y `nro_documento` (número de la factura).
- No hay doble conteo: lo que se copia a la factura descuenta el pendiente de la línea de OC.

**Consulta 9 (plazos) = entradas desde la OC + entradas desde la factura de reserva**, enlazadas a la OC de
origen. La exportación ya las trae (de 52 a 11.134 filas de importación).

**Pero la plataforma no usa las entradas a pre-bodega (`000-xxx`) para medir plazo.** El 99 % de las
entradas de importación (10.787) entran a una pre-bodega, y esa entrada marca el **embarque**, no la llegada
(SPEC-22: el stock de pre-bodega va en camino). Medidas así, las importaciones daban plazos imposibles:
HIAB (Finlandia) 16 días de mediana, todas las importaciones 30. Con ese plazo el SS y el punto de pedido de
las importaciones quedaban cortos. Mientras no se mida hasta la llegada a la bodega destino (traslado
desde la pre-bodega, §5), rige el lead time del maestro, como antes. La carga registra cuántas entradas
se dejaron fuera.

**Plataforma:** `OCAbierta` guarda `tipo_documento` y `nro_documento`. La ficha muestra
"OC 2610008 · FR 74500 · importación" y la bodega de SAP cuando es una pre-bodega. Un TXT antiguo de
9 columnas se sigue leyendo (todo como OC).

## 4. Validación (exportación del 3-nov, 12:39–12:43; corrida 37 contra la 35)

- **36274254:** OC 2610008 · FR 74500, 1 u en camino de 000-022 a 002-02. Disponible futuro −2 → −1
  (2 OF comprometidas, 0 en stock, 1 en camino); sugiere 3 u (antes 4).
- Consulta 5: 3.124 líneas de OC y **900 de facturas de reserva** (402 artículos).

| | Corrida 35 | Corrida 37 | Diferencia |
|---|---|---|---|
| En camino visible (USD) | 0,50 M | 1,84 M | **+1,34 M** |
| Artículos que necesitan compra | 1.061 | 885 | −176 |
| Compra sugerida (USD) | 4,24 M | 3,55 M | **−0,69 M** |
| Stock de seguridad (USD) | 2,51 M | 2,51 M | 0 (plazos sin cambio, §3) |

186 artículos dejan de necesitar compra (USD 498 mil) porque lo que faltaba ya venía importado: 31203614
(USD 97 mil), 29202081 (93 mil), 36275050 (39 mil)… 10 artículos pasan a necesitar compra (USD 3 mil).

**Lo que queda de "pedido SAP sin OC": 309 artículos, USD 1,26 M** (antes 819 y USD 2,4 M), el 82 % en la
bodega 013. Los más grandes son kits y equipos que se arman en Pesco (KIT BARRENO HIAB 36274821, USD 468 mil;
KIT SISTEMA RRC 36278005; butaca de paramédico 32010492) y los códigos genéricos 4999990xxx (pendiente #32).
Hipótesis: `OnOrder` también suma lo que van a producir las órdenes de fabricación, y la consulta 3 trae los
componentes de la OF, no el producto. Para confirmarlo, en Athena:

```sql
SELECT t0.docnum, t0.itemcode, t0.warehouse, t0.status, t0.plannedqty, t0.cmpltqty
FROM pesco_sbo_pescousd.owor t0
WHERE t0.status IN ('P', 'R') AND t0.itemcode IN ('36274821', '36278005', '32010492');
```

Si se confirma, agregar lo que producen las OF abiertas como entrada con fecha, junto con un spec.

## 5. Siguiente paso: plazo real de las importaciones

Medir desde la OC hasta la **llegada a la bodega destino**: el traslado (`owtr`/`wtr1`) desde la pre-bodega
`000-xxx` a la bodega final. El traslado no se enlaza con la OC, así que hay que asociarlo por artículo y
fecha (el primer traslado después de la entrada a la pre-bodega). Spec aparte.

## 6. Fuera de alcance

- La lista de reportes exportables desde el sistema (OC con plazo atípico, PC/OF antiguos, pedido SAP sin
  OC): spec aparte. Hoy esos Excel se generan con scripts sueltos y no se pueden volver a sacar desde la
  plataforma.
