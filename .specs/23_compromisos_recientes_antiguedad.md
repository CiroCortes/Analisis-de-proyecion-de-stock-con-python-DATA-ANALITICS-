# SPEC-23: Compromisos recientes (cálculo híbrido) e informe de antigüedad

Fecha: 28-oct-2026. Origen: reunión S&OP del 28-oct. Consulta 16 (nueva).
Código: `apps/calc/params.py`, `apps/calculadora/servicio.py`, `apps/calculadora/cargadores.py`,
`apps/calculadora/views_gestion.py`. Tests: `tests/test_compromisos_recientes.py`.

---

## 1. Problema

Hay PC y OF abiertos desde 2023 que nadie cerró. Todo compromiso abierto se descuenta del
disponible y empuja compras y traslados.

Datos al 28-oct. Sobre el total de PC/OF abiertos, el volumen antiguo parece enorme (PC con más de
12 meses: 21.556 u), pero casi todo es de grupos fuera del alcance (RETAIL: 21.399 u) o servicios de
OF (montajes). **En los artículos que planifica la Calculadora** el efecto es acotado:

| | Total abierto | Más de 3 meses | Más de 12 meses |
|---|---|---|---|
| PC | 9.581 u | 568 u en 172 líneas (6%) | 3 u |
| OF | 93.740 u | 7.100 u en 365 líneas (8%) | 173 u |

Con solo compromisos recientes la compra sugerida baja de USD 4,06 M a USD 3,92 M (−3,6%); cambia
la compra de 177 de los 352 artículos con compromisos antiguos.

Abastecimiento propone considerar solo los compromisos de los últimos 3 meses móviles; Producción
indica que proyecta a 2–3 meses. La limpieza de fondo se hará con Contraloría.

## 2. Regla: cálculo híbrido

Se cargan **todos** los compromisos, como hoy. Dos parámetros generales (auditados):

| Clave | Valor por defecto | Significado |
|---|---|---|
| `solo_compromisos_recientes` | No | Sí: el cálculo descuenta solo los compromisos recientes |
| `meses_compromisos_recientes` | 3 | Antigüedad máxima (por fecha de emisión) de un compromiso "reciente" |

- Con `solo_compromisos_recientes`, los compromisos emitidos antes de `hoy − N meses` no se descuentan del
  disponible de su bodega ni entran a la proyección.
- La corrida calcula **siempre las dos bases** para los artículos con compromisos antiguos y guarda
  la cantidad sugerida de la otra base. La grilla y la ficha muestran ambas: así se ve cuánto
  pesan los pedidos antiguos sin cambiar de modo.
- Las solicitudes de compra usan la base elegida.

## 3. Informe de antigüedad de compromisos abiertos

Pantalla `/calculadora/compromisos/` con exportación a Excel, para Contraloría y jefaturas.
Fuente: consulta 16 (PC y OF abiertos con responsable, cliente y referencia).

- **Tramos** por fecha de emisión: 0–3, 3–6, 6–12 y más de 12 meses.
- **Resumen** por tramo y tipo (líneas, documentos, unidades, valor USD a `lastpurprc`).
- **Por responsable** (vendedor del PC o usuario que creó la OF) y por bodega.
- **Detalle por documento**: número, tipo, emisión, días abierto, cliente, responsable,
  referencia, líneas, unidades, valor.
- Filtros: tipo, tramo, nodo (Santiago o sucursal), responsable, cliente.
- El informe muestra todos los compromisos, sin importar la base del cálculo.
- Solo artículos del alcance de la Calculadora (activos, de grupos activos). Los servicios de OF
  (montajes, servicios de terceros) se excluyen: con su "costo" el total llegaba a USD 3.430 M,
  contra USD 1,27 M de los artículos que sí se planifican.
