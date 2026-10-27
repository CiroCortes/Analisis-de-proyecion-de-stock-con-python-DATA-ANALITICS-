# SPEC-13: Solicitudes de Compra y Acuerdos Globales

Documento fuente: §6, §5 (duplicados). Código: `apps/calculadora/solicitudes.py`.
Pantallas: `/calculadora/solicitudes/`.

---

## 1. Generación (`generar`)

A partir de la última corrida (`ResultadoArticulo` con proveedor):

| Grupo | Origen | Tipo de solicitud |
|---|---|---|
| Del día | `comprar = True` (día de compra del proveedor) | CALENDARIO, cantidad sugerida |
| Excepciones | `excepcion = True`, no del día, cantidad > 0 | EXCEPCION, cantidad de la excepción |
| De pasada | Mismo proveedor de una excepción, `necesita_compra`, sin excepción | Se suman a la EXCEPCION con motivo "Compra de pasada" |

- Una solicitud por proveedor y tipo por día; bodega de entrega 013-PP.
- Regenerar reemplaza los **borradores** del mismo día y proveedor; no toca los aprobados.
- Artículos sin proveedor no entran (alerta `DATOS`).

## 2. Contrato por línea

- `acuerdo_vigente`: acuerdos del proveedor para el artículo con inicio ≤ hoy ≤ término y estado
  no cancelado/terminado; con varios, el de **menor precio**.
- Precio de la línea = precio del acuerdo; sin acuerdo = costo (`lastpurprc`) y `sin_contrato`.
- `saldo_insuficiente` si cantidad > plan − acumulado. Se recalcula al editar.
- Sin contrato o saldo insuficiente → alerta `CONTRATO`.

## 3. Duplicados

`duplicada_reciente` si el artículo tiene otra línea en una solicitud abierta (borrador o aprobada)
de los últimos 15 días. La pantalla debe mostrarla y pedir confirmación al aprobar.

## 4. Edición y aprobación

- Solo se editan solicitudes en BORRADOR. Cambiar la cantidad exige **motivo**; cantidad 0 = línea
  descartada.
- `aprobar`: líneas no descartadas → APROBADA; guarda usuario y fecha. Desde ese momento la
  cantidad cuenta como tránsito en la siguiente corrida (SPEC-12 §2).
- `descartar`: solo abiertas; guarda el motivo.
- Roles (SPEC-14 §3): aprueba "Jefe Abastecimiento" o "Administrador Abastecimiento" (o superusuario).
  La vista aplica el permiso.

## 5. Exportación (en lugar de escribir en SAP)

Escribir en B1 vía Service Layer está **descartado** hasta la habilitación de IT. Se exporta una
planilla (`filas_exportacion`) y las aprobadas pasan a EXPORTADA (`marcar_exportadas`).

| Columna | Contenido |
|---|---|
| Solicitud plataforma, Fecha, Tipo | Identificación |
| Proveedor, Nombre proveedor | CardCode y nombre |
| ItemCode, Descripcion, Quantity | Línea |
| WarehouseCode | 013-PP |
| Price | Precio del acuerdo o costo |
| AgreementNo, AgreementRowNumber | Acuerdo global y línea |
| Motivo, Excepcion, Causa | Revisión |

Las columnas siguen el objeto `PurchaseRequests` de B1; **validar la plantilla DTW con IT**.

## 6. Indicador de intervención (`intervencion_comprador`)

% de líneas cambiadas o descartadas sobre las no borrador, por comprador (quien aprobó) y % de
líneas fuera de calendario por causa (SPEC-15 §3).
