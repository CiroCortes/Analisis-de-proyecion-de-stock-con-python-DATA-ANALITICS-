# SPEC-14: Parámetros Configurables

Documento fuente: §7. Código: `apps/calc/params.py` (catálogo, valores iniciales, validación),
`apps/calculadora/parametros.py` (niveles, guardado, registro). Pantalla: `/calculadora/parametros/`.

---

## 1. Catálogo

Ningún valor de negocio está escrito en las fórmulas: todas leen un `Params`.
G = general, F = familia, P = proveedor, A = artículo, B = bodega.

| Clave | Etiqueta | Inicial | Rango | Niveles |
|---|---|---|---|---|
| nivel_servicio_a / _b / _c | Nivel de servicio A / B / C | 0,97 / 0,95 / 0,90 | 0,80–0,995 | G F A |
| nivel_servicio_critico | Mínimo críticos y pañol | 0,97 | 0,80–0,995 | G |
| dias_recepcion | Días de recepción | 2 | 0–60 | G B |
| frecuencia_compra_dias | Frecuencia de compra | 15 | 1–180 | G P (y `Proveedor.frecuencia_compra_dias`) |
| meses_cobertura | Cobertura sobre el punto de pedido | 3 | 0–24 | G F A |
| meses_minimo_compra | Meses mínimos por compra | 1 | 0–12 | G F A |
| umbral_plazo_largo_dias | Umbral plazo corto / largo | 60 | 1–365 | G F |
| meses_piso_ss_corto / _largo | Piso SS | 2 / 4 | 0–12 | G F A |
| salidas_extra | Salidas extra R-Intermitente | 1 | 0–12 | G F A |
| meses_historia_consumo | Historia de consumo | 12 | 6–24 | G |
| meses_historia_oc | Historia de OC | 24 | 6–36 | G |
| min_oc_plazo_real | Mínimo de OC para plazo real | 3 | 1–20 | G |
| variacion_entrega_defecto | Variación de entrega por defecto | 0,25 | 0–1 | G |
| multiplicador_atipico | Tope de mes atípico | 3 | 1–10 | G |
| umbral_r / umbral_r_regular | Meses con consumo para R / R-Regular | 3 / 9 | 1–12 | G |
| nuevo_meses_repuestos / _panol | Antigüedad para Nuevo | 8 / 4 | 0–36 | G |
| inmovilizado_meses_repuestos / _panol | Meses para Inmovilizado | 24 / 12 | 6–60 | G |
| corte_abc_a / corte_abc_b | Cortes ABC | 0,80 / 0,15 | 0,5–0,95 / 0,01–0,45 | G |
| p_solo_con_compromiso | P exige PC u OF abierto | Sí | sí/no | G |
| horizonte_proyeccion_dias | Horizonte proyección | 120 | 30–365 | G |
| alerta_bajo_ss_dias | Alerta bajo SS proyectado | 15 | 1–90 | G |
| alerta_contrato_vence_dias | Alerta contrato por vencer | 60 | 1–365 | G |
| alerta_sobrestock_meses | Sobrestock: meses sobre el máximo | 3 | 0–24 | G |

`recortar_atipicos` (sí) existe en `Params` pero no está en el catálogo editable.
Mínimo declarado E, crítico, mínimo de nuevo y proveedor alternativo son datos por artículo
(`ArticuloConfig`), no parámetros.

## 2. Niveles y resolución (`Resolutor`)

- Prioridad: GENERAL < FAMILIA / BODEGA < PROVEEDOR < ARTÍCULO. Manda el más específico.
- **Familia = grupo de artículos SAP** (`sap_group_code`, o el código de categoría). Decisión
  abierta #6 (alternativa: `u_rhfamilia`).
- Bodega: el cálculo de la red usa la bodega 013-PP (recepción en la central).
- Un valor guardado que no convierte se ignora. Se cachea un `Params` por combinación.

## 3. Roles

| Grupo Django | Puede |
|---|---|
| Administrador Abastecimiento | Editar parámetros; aprobar solicitudes y eventos |
| Jefe Abastecimiento | Aprobar solicitudes y eventos |
| Resto (comprador) | Ver; editar líneas de solicitudes |

Superusuario puede todo. Funciones: `puede_editar`, `puede_aprobar`.

## 4. Guardado, registro y simulación

- `guardar(clave, valor, usuario, nivel, ámbito, motivo)`: valida rango y nivel permitido
  (`validar`), exige ámbito fuera de GENERAL, `valor` vacío borra la excepción del nivel.
- Todo cambio deja un `ParametroCambio` (usuario, fecha, parámetro, nivel, ámbito, anterior,
  nuevo, motivo). Consultable y exportable a Excel (`/calculadora/parametros/historial/excel/`).
- **Simulación**: `ejecutar_corrida(guardar=False, extra_general={clave: valor})` recalcula todo
  en memoria con el valor propuesto y devuelve el resumen (incluye `valor_stock_maximo`) para
  mostrar la diferencia antes de guardar. Solo simula valores generales.
- El siguiente cálculo usa el valor nuevo (no hay que reiniciar nada).
