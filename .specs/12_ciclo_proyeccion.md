# SPEC-12: Ciclo de Compra, Proyección Diaria y Compras Fuera de Calendario

Documento fuente: §4.6.1, §4.6.2. Código: `apps/calc/calendario.py`, `apps/calc/proyeccion.py`,
`apps/calc/motor.py`. Tests: `TestCaso5FueraDeCalendario`, `TestCalendario`, `TestMotor`.

---

## 1. Calendario por proveedor

- Cada proveedor tiene `frecuencia_compra_dias` (por defecto el parámetro, 15) y una `fecha_ancla`
  (un día de compra). Los siguientes: ancla + n × frecuencia.
- Un día de compra en sábado o domingo pasa al lunes.
- Sin ancla definida: `ancla_por_defecto` = 5-ene-2026 (lunes) + (CRC32 del código de proveedor
  mód frecuencia) días, llevado a hábil. Es estable y reparte proveedores en distintos días.
  Artículos sin proveedor usan su propio código.
- `proxima_fecha_compra(hoy)` = primer día de compra ≥ hoy; `es_dia_compra` = es hoy.
- Se configura en la pantalla Proveedores (`/calculadora/proveedores/`) o en el admin.

## 2. Proyección diaria (`proyectar`)

Día 1 = mañana; horizonte 120 días (`horizonte_proyeccion_dias`).

```
stock_proyectado[d] = stock físico de la red − consumo_diario × d
                      − compromisos con fecha ≤ d + llegadas con fecha ≤ d
```

- Compromisos (PC/OF abiertos): día = fecha − hoy; vencidos o sin fecha → día 1; más allá del
  horizonte no cuentan.
- Llegada de OC (`dia_llegada_oc`): fecha comprometida + recepción; si ya pasó, hoy + recepción y
  la OC queda **atrasada**.
- Solicitudes de la plataforma aprobadas (o exportadas después de la última carga del TXT de SC):
  llegan en hoy + plazo total, y se suman al tránsito de 013-PP (§5 del documento: se cuentan al
  crearlas, sin esperar la carga desde SAP).
- Las SC de SAP no tienen fecha: cuentan en el disponible, no en la serie.
- Solo se proyectan métodos GENERAL, INTERMITENTE y NUEVO con consumo o compromisos.

## 3. Excepción (`evaluar_excepcion`)

| Campo | Cálculo |
|---|---|
| dia_quiebre | Primer día con stock proyectado < 0 |
| dia_bajo_ss | Primer día con stock proyectado < SS |
| dia_llegada_posible | días a la próxima compra + REDONDEAR.MAS(plazo + recepción) |
| excepcion | dia_quiebre < dia_llegada_posible **y no es día de compra** |
| dias_quiebre_inevitable | MAX(0; plazo + recepción − dia_quiebre) |

- El día de compra del proveedor no hay excepción: el artículo entra en la compra normal (el
  quiebre inevitable se informa igual).
- Cantidad de la excepción: la `cantidad_sugerida` si existe; si no, `cantidad_minima` sobre
  MAX(máximo − disponible; −mínimo de la serie).
- `cantidad_a_comprar` del resultado = sugerida si `comprar`, o la de la excepción.

### 3.1 Causa (para el indicador de intervención)

En orden: `OC_ATRASADA` (alguna OC vencida) → `PEDIDO` (compromiso antes del quiebre de al menos un
mes de consumo) → `EVENTO` (ajuste comercial > 0) → `DATO_FALTANTE` (sin costo o sin plazo) →
`CONSUMO`.

## 4. Observaciones

- Un artículo con disponible ≤ 0 quiebra el día 1: fuera del día de compra siempre es excepción.
  Corrida del 27-oct con consumo provisional PC/OF: 409 excepciones.
- **Doble conteo corregido el 28-oct**: el documento descontaba consumo diario **y** compromisos, pero
  el consumo de OINM ya incluye las ventas y las salidas a OF. Ahora cada día se descuenta
  `MAX(consumo_diario × día; compromisos acumulados)`: un pedido grande adelanta el quiebre solo en
  lo que supera al consumo esperado. Datos reales: excepciones 427 → 393, sugerido USD 4,52 M → 4,25 M.
  Caso 5 corregido (quiebre día 13, no 5). Hay que corregir el caso 5 en el documento.
