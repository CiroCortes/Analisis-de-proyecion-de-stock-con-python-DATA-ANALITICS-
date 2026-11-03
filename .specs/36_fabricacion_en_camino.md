# SPEC-36: Fabricación en camino (producto de las OF abiertas) y OF antiguas

Fecha: 3-nov-2026. Origen: residuo de "pedido SAP sin OC" que quedó después del SPEC-35.
Código: `data/consultas_datalake.sql` (consulta 5, parte c), `apps/data_ingestion/datalake_ingest.py`
(`corte_of_vigente`, `linea_cuenta`), `apps/calculadora/cargadores.py`, `apps/calculadora/servicio.py`,
`apps/calculadora/alertas.py` (`ofs_antiguas`), `apps/calc/params.py`, ficha y Analizar.
Tests: `tests/test_spec36.py`.

---

## 1. Hallazgo

Después del SPEC-35 quedaban **309 artículos y USD 1,26 M** con "Pedido" en SAP (`OITW.OnOrder`) sin OC ni
factura de reserva, el 82 % en la bodega 013. No son solicitudes de compra (no suman en "Pedido"; 48 de los
309 tienen SC, por USD 12 mil) ni pedidos de cliente (suman en "Comprometido"). La consulta a `owor`
confirmó que son **órdenes de fabricación**: SAP suma en "Pedido" lo que va a producir una OF abierta. La
consulta 3 solo trae los componentes de las OF, no el producto.

Con las cantidades exactas del residuo, y con casos de naturaleza muy distinta:

| Artículo | OF abiertas | Emitidas | Lectura |
|---|---|---|---|
| 36274821 KIT BARRENO HIAB | 15 × 1 u (2308271–285) | 17-08-2023 | OF sin cerrar hace más de 2 años: USD 468 mil "por llegar" que no llegarán |
| 36278005 KIT RRC GRÚA H-188 | 4 × 1 u | nov-2023 | Igual: USD 62 mil |
| 32010492 Butaca paramédico | 70 + 13 u | sep y oct-2026 | Fabricación vigente |
| 4999990001 Entrega materiales pañol | 83 OF × 1 u | sep-2023 a nov-2026 | Código genérico de entrega de materiales: no es un producto (pendiente #32) |

**El dato de SAP es real; lo que falla es el proceso:** las OF que no se terminan ni se anulan siguen
mostrando el producto como pedido.

El maestro tiene el campo método de abastecimiento (`OITM.PrcrmntMtd`), pero todos los artículos tienen
`B` (comprar): no se usa y no sirve para reconocer lo fabricado.

## 2. Regla

- **Consulta 5, parte c):** el producto de cada OF abierta (`owor`, estado P o R, `plannedqty − cmpltqty > 0`),
  con `tipo_documento = 'OF'`, la bodega de la OF, emisión = `postdate` y llegada = `duedate`.
- **Vigencia:** una OF cuenta como en camino solo si se emitió en los últimos `meses_of_vigente` meses
  (parámetro general, **6** por defecto, rango 1–36). Producción proyecta a 2–3 meses (SPEC-23); 6 deja
  margen para una OF atrasada sin contar las de 2023.
- **Las OF antiguas no cuentan** en el disponible ni en la proyección. Se guardan (`OCAbierta.cuenta =
  False`) para la ficha, para Analizar (cuadran el "Pedido" de SAP) y para la alerta.
- **Alerta `OF_ANTIGUA`:** una por artículo, con unidades, número de OF, la más antigua y su valor. **MEDIA**
  si el artículo necesita compra (quien decide debe saber que SAP lo muestra por llegar), **BAJA** si no.
  Mensaje: "Cerrar o anular con Producción".
- **El desglose del en camino** (SPEC-31 §2) tiene el origen "Fabricación (OF)".
- Una OF vencida no se marca como "OC atrasada".
- Las OC antiguas **siguen contando**: el SPEC-33 ya las informa y una OC sí es un compromiso con un tercero.

## 3. Validación (consulta 5 del 3-nov 14:12; corrida 38 contra la 37)

- Consulta 5: 1.391 líneas de OF. Vigentes: 1.017 (160 artículos, 1.269 u). Antiguas: 374 (87 artículos).
- 32010492 (butacas): 83 u en camino por fabricación, no necesita compra.
- 36274821 y 36278005 (kits): no cuentan; alerta OF_ANTIGUA (USD 468 mil y 62 mil). Hay 15 alertas
  OF_ANTIGUA en artículos del cálculo (3 MEDIA); el resto de las OF antiguas son de categorías fuera del alcance.
- **"Pedido SAP sin OC": USD 1,26 M → USD 252 mil** (259 artículos). Lo que queda es menor y disperso.

| | Corrida 37 | Corrida 38 | Diferencia |
|---|---|---|---|
| En camino visible (USD) | 1,84 M | 2,22 M | +0,38 M |
| Compra sugerida (USD) | 3,55 M | 3,31 M | −0,25 M |
| Artículos que necesitan compra | 885 | 880 | −5 |

**Ojo: ~USD 210 mil de la baja son los códigos genéricos 4999990xxx**, cuyas OF de "entrega de materiales"
ahora cuentan como en camino. Esos códigos no son productos y no deberían estar en el cálculo: siguen
sumando **USD 640 mil del sugerido en 23 códigos** (4999990001: 144 u). Marcarlos en Marcas (#32) es lo
que más cambia el sugerido hoy. En artículos reales, el efecto es acotado (kits: ~USD 35 mil).

## 4. Siguiente paso: artículos fabricados

Un kit que se fabrica no se le compra a un proveedor: lo que se compra son sus componentes. Para no
sugerirlo como compra hay que reconocerlo. Como `PrcrmntMtd` no se usa, las señales son:

- tiene lista de materiales de producción (`oitt`, `treetype = 'P'`), o
- fue el producto de una OF en los últimos 24 meses.

Decidir con Ignacio qué hace la herramienta con ellos (sugerir "fabricar" en vez de "comprar", o
excluirlos de la compra y avisar a Producción). Spec aparte. Mientras tanto, los 4999990xxx se marcan en
la pantalla Marcas (#32).
