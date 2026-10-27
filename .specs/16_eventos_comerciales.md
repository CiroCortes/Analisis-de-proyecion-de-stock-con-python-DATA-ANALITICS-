# SPEC-16: Eventos Comerciales

Documento fuente: §4.7. Código: `EventoComercial` (`apps/calculadora/models.py`),
`servicio._ajuste_y_meses_evento`, `alertas.generar`. Pantalla: `/calculadora/eventos/`.

---

## 1. Registro

| Campo | Uso |
|---|---|
| product / familia | Artículo, o familia = grupo SAP (código o nombre) si `product` vacío |
| bodega | Informativo (el cálculo es de red) |
| tipo | ALZA, BAJA, REEMPLAZO |
| cantidad_adicional | Unidades adicionales en **todo** el período |
| porcentaje | % sobre el consumo promedio (alternativa a la cantidad) |
| mes_inicio, mes_fin | Vigencia en meses (inclusive) |
| comentario, adjunto | Texto, correo, PDF (`media/eventos/`) |
| autor, aprobado_por, estado | PROPUESTO → APROBADO / RECHAZADO |

Solo los **aprobados** afectan el cálculo. Aprueba el Jefe o el Administrador de Abastecimiento
(SPEC-14 §3).

## 2. Efecto en el cálculo

- Ajuste mensual de cada evento vigente en el mes en curso:
  `cantidad_adicional ÷ meses de vigencia`, o `promedio × porcentaje ÷ 100`. BAJA resta.
  Los eventos del artículo y de su familia se suman.
- `consumo_promedio_ajustado = consumo_promedio_mes + ajuste` (mínimo 0) se usa en punto de pedido
  y stock máximo. El stock de seguridad, la variación y el historial **no cambian**.
- Los meses de historia cubiertos por un evento no se marcan atípicos ni cuentan para el mayor
  consumo de intermitentes.
- Una excepción con ajuste > 0 (sin otra causa previa) tiene causa `EVENTO`.
- REEMPLAZO se trata como alza; el traspaso de historia entre códigos se registra en
  `Equivalencia` (la historia del antiguo se suma al nuevo).

## 3. Alertas

- Pendiente de aprobación → `EVENTO_COMERCIAL` (MEDIA).
- Aprobado, vencido, con cantidad: si el consumo real del período < 50% de lo anunciado →
  `EVENTO_COMERCIAL` (BAJA).

## 4. Fase 2

Buzón de correo que crea eventos propuestos a partir de los mails reenviados (no implementado).
