-- ============================================================================
-- PESCO S.A. - CONSULTAS PARA LA CALCULADORA DE COMPRAS (AWS ATHENA / SAP B1)
-- Base de datos: pesco_sbo_pescousd
--
-- ESTADO: BORRADOR del 26-oct-2026. NO VALIDADO en Athena.
-- Origen: Requerimientos_Calculadora_Compras5.docx (secciones 2, 4 y 6).
-- Complementa a consultas_optimizadas_datalake.sql (las 7 consultas actuales NO se tocan:
-- el cargador athena_client.py espera exactamente 7 en ese archivo).
--
-- COMO USARLO MANANA
--   1. Correr primero el bloque 0 (verificar que existen las tablas y sus columnas).
--      Los nombres de columna de abajo son los estandar de SAP B1; si Athena dice
--      COLUMN_NOT_FOUND, ajustar con el resultado del DESCRIBE.
--   2. Cada consulta termina en LIMIT 5 para probar barato. Si el top 5 se ve bien,
--      quitar el LIMIT y exportar completa.
--   3. Guardar cada resultado como TXT en data/ con el nombre indicado en su cabecera.
--
-- DECISIONES YA TOMADAS (ver .specs/06 y .specs/07)
--   * Costo = lastpurprc (no avgprice). Va en la consulta 1 del otro archivo.
--   * Consumo desde movimientos de inventario (OINM), ya agregado por mes: 24 meses de
--     historia por articulo y bodega no se pueden bajar linea a linea.
--   * Solo meses cerrados (se excluye el mes en curso).
--   * Escribir en SAP (Service Layer / campos de usuario) esta DESCARTADO por ahora.
-- ============================================================================


-- ============================================================================
-- 0. VERIFICACION DE TABLAS Y COLUMNAS (correr una por una, resultados chicos)
-- ============================================================================
-- SHOW TABLES IN pesco_sbo_pescousd LIKE 'oinm';
-- SHOW TABLES IN pesco_sbo_pescousd LIKE 'owtq';
-- SHOW TABLES IN pesco_sbo_pescousd LIKE 'ooat';
-- SHOW TABLES IN pesco_sbo_pescousd LIKE 'ocrd';
-- SHOW TABLES IN pesco_sbo_pescousd LIKE 'owhs';
-- DESCRIBE pesco_sbo_pescousd.oinm;
-- DESCRIBE pesco_sbo_pescousd.ooat;
-- DESCRIBE pesco_sbo_pescousd.oat1;
-- DESCRIBE pesco_sbo_pescousd.owtq;
-- DESCRIBE pesco_sbo_pescousd.wtq1;
-- DESCRIBE pesco_sbo_pescousd.oitm;      -- buscar: cardcode, minordrqty, ordrmulti, purpackun, invntryuom, u_critico


-- ============================================================================
-- 8. CONSUMO MENSUAL POR ARTICULO Y BODEGA (24 meses cerrados)       [Req. 4.1]
-- Archivo de salida: data/Consumo Mensual.txt
-- Objetivo: consumo_mes_1..24, meses_con_consumo_12m, consumo_promedio_mes,
--           variacion_consumo, mayor_consumo_mes, graficos venta vs OF.
-- Fuente: OINM (movimientos de inventario). Un movimiento de inventario no se duplica
--   entre entrega y factura (una factura copiada desde entrega no mueve stock).
-- TransType usados (VALIDAR contra el informe de auditoria de stock de B1):
--   15 = Entrega de venta (ODLN)          13 = Factura de venta que mueve stock (OINV)
--   14 = Nota de credito de venta (ORIN)  16 = Devolucion de venta (ORDN)
--   60 = Salida de mercancia (OIGE), incluye emisiones a OF
--   NO se incluyen: 67 (traslados entre bodegas, no son consumo), 59 (entradas),
--   20/21/18/19 (compras).
-- cantidad_neta = salidas - entradas, en positivo cuando hay consumo. Las devoluciones
--   restan en el mes en que ocurren (el documento pide el mes del movimiento original:
--   PENDIENTE de decidir, ver .specs/00_PENDIENTES.md).
-- origen: VENTA / SALIDA. La separacion SALIDA = OF vs otras salidas (mermas, ajustes)
--   requiere IGE1.basetype = 202 (ver consulta 8b).
-- Filtros: solo articulos que gestionan inventario (invntitem = Y), meses cerrados.
-- ============================================================================
SELECT
    m.itemcode                                           AS codigo_sku,
    m.warehouse                                          AS bodega,
    SUBSTR(CAST(m.docdate AS VARCHAR), 1, 7)             AS mes,
    CASE WHEN m.transtype IN (13, 14, 15, 16) THEN 'VENTA'
         WHEN m.transtype = 60                THEN 'SALIDA'
         ELSE 'OTRO' END                                 AS origen,
    CAST(SUM(COALESCE(m.outqty, 0) - COALESCE(m.inqty, 0)) AS DECIMAL(14, 2)) AS cantidad_neta
FROM pesco_sbo_pescousd.oinm m
INNER JOIN pesco_sbo_pescousd.oitm t
    ON t.itemcode = m.itemcode
WHERE m.transtype IN (13, 14, 15, 16, 60)
  AND t.invntitem = 'Y'
  AND SUBSTR(CAST(m.docdate AS VARCHAR), 1, 10) >= CAST(DATE_ADD('month', -24, DATE_TRUNC('month', CURRENT_DATE)) AS VARCHAR)
  AND SUBSTR(CAST(m.docdate AS VARCHAR), 1, 10) <  CAST(DATE_TRUNC('month', CURRENT_DATE) AS VARCHAR)
GROUP BY
    m.itemcode,
    m.warehouse,
    SUBSTR(CAST(m.docdate AS VARCHAR), 1, 7),
    CASE WHEN m.transtype IN (13, 14, 15, 16) THEN 'VENTA'
         WHEN m.transtype = 60                THEN 'SALIDA'
         ELSE 'OTRO' END
HAVING SUM(COALESCE(m.outqty, 0) - COALESCE(m.inqty, 0)) <> 0
LIMIT 5;   -- QUITAR para carga completa


-- ============================================================================
-- 8b. (OPCIONAL) SALIDAS DE MERCANCIA A OF, POR MES                  [Req. 4.1 y graficos]
-- Archivo de salida: data/Consumo OF Mensual.txt
-- Separa las emisiones a Orden de Fabricacion (IGE1.basetype = 202) del resto de las
-- salidas de mercancia. Sirve para (a) graficos venta vs OF y (b) cuadrar contra la
-- consulta 8: SALIDA(8) = OF(8b) + otras salidas.
-- ============================================================================
SELECT
    l.itemcode                                           AS codigo_sku,
    l.whscode                                            AS bodega,
    SUBSTR(CAST(h.docdate AS VARCHAR), 1, 7)             AS mes,
    CAST(SUM(l.quantity) AS DECIMAL(14, 2))              AS cantidad_of
FROM pesco_sbo_pescousd.oige h
INNER JOIN pesco_sbo_pescousd.ige1 l
    ON l.docentry = h.docentry
WHERE l.basetype = 202
  AND h.canceled = 'N'
  AND SUBSTR(CAST(h.docdate AS VARCHAR), 1, 10) >= CAST(DATE_ADD('month', -24, DATE_TRUNC('month', CURRENT_DATE)) AS VARCHAR)
  AND SUBSTR(CAST(h.docdate AS VARCHAR), 1, 10) <  CAST(DATE_TRUNC('month', CURRENT_DATE) AS VARCHAR)
GROUP BY
    l.itemcode,
    l.whscode,
    SUBSTR(CAST(h.docdate AS VARCHAR), 1, 7)
LIMIT 5;   -- QUITAR para carga completa


-- ============================================================================
-- 9. PLAZO REAL DE ENTREGA POR OC RECIBIDA (24 meses)                [Req. 4.2]
-- Archivo de salida: data/Plazos de Entrega OC.txt
-- Objetivo: dias_entrega_oc = fecha entrada de mercancia - fecha OC, por linea recibida.
--   La plataforma calcula dias_entrega_promedio y variacion_entrega_dias por articulo
--   (y proveedor). Si hay menos de 3 OC usa OITM.leadtime.
-- Enlace recepcion -> OC: pdn1.basetype = 22 (OC), baseentry = docentry de la OC,
--   baseline = linea de la OC.
-- Reglas del documento (seccion 9): excluir recepcion sin OC, OC anulada o con cantidad 0;
--   plazo negativo o > 365 dias = error de dato (se excluye y se alerta: lo hace la
--   plataforma; aqui se entrega el dato crudo con dias_entrega para poder contarlos).
-- PENDIENTE: OC con recepciones parciales (varias entradas por linea). Esta consulta
--   entrega una fila por recepcion; la plataforma decide usar la primera o la ultima.
-- ============================================================================
SELECT
    o.docnum                                             AS nro_oc,
    l.itemcode                                           AS codigo_sku,
    o.cardcode                                           AS codigo_proveedor,
    COALESCE(NULLIF(l.whscode, ''), '013-PP')            AS bodega_oc,
    SUBSTR(CAST(o.docdate AS VARCHAR), 1, 10)            AS fecha_oc,
    SUBSTR(CAST(COALESCE(l.shipdate, o.docduedate) AS VARCHAR), 1, 10) AS fecha_comprometida,
    gr.docnum                                            AS nro_entrada,
    SUBSTR(CAST(gr.docdate AS VARCHAR), 1, 10)           AS fecha_entrada,
    DATE_DIFF('day', CAST(o.docdate AS DATE), CAST(gr.docdate AS DATE)) AS dias_entrega,
    CAST(l.quantity AS DECIMAL(12, 2))                   AS cantidad_oc,
    CAST(gl.quantity AS DECIMAL(12, 2))                  AS cantidad_recibida
FROM pesco_sbo_pescousd.opdn gr
INNER JOIN pesco_sbo_pescousd.pdn1 gl
    ON gl.docentry = gr.docentry
   AND gl.basetype = 22
INNER JOIN pesco_sbo_pescousd.por1 l
    ON l.docentry = gl.baseentry
   AND l.linenum  = gl.baseline
INNER JOIN pesco_sbo_pescousd.opor o
    ON o.docentry = l.docentry
WHERE gr.canceled = 'N'
  AND o.canceled  = 'N'
  AND l.quantity > 0
  AND SUBSTR(CAST(gr.docdate AS VARCHAR), 1, 10) >= CAST(DATE_ADD('month', -24, CURRENT_DATE) AS VARCHAR)
LIMIT 5;   -- QUITAR para carga completa


-- ============================================================================
-- 10. PARAMETROS DE COMPRA DEL ARTICULO (complemento del maestro)    [Req. 2, 4.2, 4.6]
-- Archivo de salida: data/Parametros de Compra.txt
-- El maestro (consulta 1 del otro archivo) NO se modifica: esta consulta aporta lo que
-- falta para el calculo. Si algun nombre de columna no existe, ver el DESCRIBE del bloque 0.
--   proveedor_preferido -> agrupar compras por proveedor
--   min_compra / multiplo -> redondeo de cantidad_sugerida
--   u_critico (campo de usuario) NO existe todavia en SAP: la marca es_critico se
--   administra en la plataforma por ahora.
-- ============================================================================
SELECT
    t0.itemcode                                          AS codigo_sku,
    COALESCE(t0.cardcode, '')                            AS proveedor_preferido,
    COALESCE(t0.leadtime, 0)                             AS lead_time_maestro,
    CAST(COALESCE(t0.minordrqty, 0) AS DECIMAL(12, 2))   AS min_compra,
    CAST(COALESCE(t0.ordrmulti, 0) AS DECIMAL(12, 2))    AS multiplo_compra,
    CAST(COALESCE(t0.purpackun, 0) AS DECIMAL(12, 2))    AS unidades_por_paquete,
    COALESCE(t0.invntryuom, '')                          AS unidad_medida,
    t0.frozenfor                                         AS congelado,
    t0.validfor                                          AS vigente
FROM pesco_sbo_pescousd.oitm t0
WHERE t0.itemcode IS NOT NULL
  AND t0.itemcode <> ''
  AND t0.invntitem = 'Y'
LIMIT 5;   -- QUITAR para carga completa


-- ============================================================================
-- 11. PROVEEDORES                                                     [Req. 2, 6]
-- Archivo de salida: data/Proveedores.txt
-- Objetivo: agrupar solicitudes por proveedor y separar nacional / importado (pais).
-- ============================================================================
SELECT
    c.cardcode                                           AS codigo_proveedor,
    c.cardname                                           AS nombre_proveedor,
    COALESCE(c.country, '')                              AS pais,
    c.frozenfor                                          AS congelado
FROM pesco_sbo_pescousd.ocrd c
WHERE c.cardtype = 'S'
LIMIT 5;   -- QUITAR para carga completa


-- ============================================================================
-- 12. BODEGAS (OWHS)                                                  [Req. 2]
-- Archivo de salida: data/Bodegas.txt
-- Objetivo: nombres reales de bodega y marca de inactiva. El tipo central / Santiago /
--   sucursal / transito / consignacion se define en la plataforma (apps/data_ingestion/
--   warehouses.py), no en SAP.
-- ============================================================================
SELECT
    w.whscode                                            AS codigo_bodega,
    w.whsname                                            AS nombre_bodega,
    w.inactive                                           AS inactiva
FROM pesco_sbo_pescousd.owhs w
LIMIT 5;   -- QUITAR para carga completa


-- ============================================================================
-- 13. SOLICITUDES DE TRASLADO ABIERTAS (OWTQ / WTQ1)                  [Req. 2, 4.6]
-- Archivo de salida: data/Traslados Abiertos.txt
-- Objetivo: en_transito hacia cada bodega. OJO: hoy el stock en las bodegas de transito
--   (T013-002, etc.) ya entra por OITW y se acredita a la bodega destino. Esta consulta
--   es para VALIDAR que no se esta duplicando o perdiendo transito (una solicitud abierta
--   puede estar ya reflejada como onorder en la bodega T). Revisar antes de sumarla.
-- ============================================================================
SELECT
    q.docnum                                             AS nro_solicitud_traslado,
    SUBSTR(CAST(q.docdate AS VARCHAR), 1, 10)            AS fecha_solicitud,
    l.itemcode                                           AS codigo_sku,
    l.fromwhscod                                         AS bodega_origen,
    l.whscode                                            AS bodega_destino,
    CAST(l.quantity AS DECIMAL(12, 2))                   AS cantidad_solicitada,
    CAST(l.openqty AS DECIMAL(12, 2))                    AS cantidad_pendiente
FROM pesco_sbo_pescousd.owtq q
INNER JOIN pesco_sbo_pescousd.wtq1 l
    ON l.docentry = q.docentry
WHERE q.docstatus = 'O'
  AND l.linestatus = 'O'
  AND l.openqty > 0
LIMIT 5;   -- QUITAR para carga completa


-- ============================================================================
-- 14. ACUERDOS GLOBALES (CONTRATOS) VIGENTES                          [Req. 2, 6]
-- Archivo de salida: data/Acuerdos Globales.txt
-- Objetivo: asociar cada linea de solicitud de compra a su contrato (OOAT.number y linea),
--   valorizar con el precio del acuerdo y validar saldo (plan - acumulado).
--   Si hay mas de un acuerdo para el articulo, la plataforma toma el de menor precio.
-- Estados y columnas de OOAT / OAT1 varian por version de B1: confirmar con el DESCRIBE
--   del bloque 0 antes de filtrar por status.
-- ============================================================================
SELECT
    a.number                                             AS nro_acuerdo,
    a.bpcode                                             AS codigo_proveedor,
    SUBSTR(CAST(a.startdate AS VARCHAR), 1, 10)          AS fecha_inicio,
    SUBSTR(CAST(a.enddate AS VARCHAR), 1, 10)            AS fecha_termino,
    a.status                                             AS estado,
    l.agrlinenum                                         AS linea_acuerdo,
    l.itemcode                                           AS codigo_sku,
    CAST(l.plannedqty AS DECIMAL(14, 2))                 AS cantidad_plan,
    CAST(l.cumqty AS DECIMAL(14, 2))                     AS cantidad_acumulada,
    CAST(l.unitprice AS DECIMAL(14, 4))                  AS precio_unitario
FROM pesco_sbo_pescousd.ooat a
INNER JOIN pesco_sbo_pescousd.oat1 l
    ON l.agrno = a.absid
WHERE l.itemcode IS NOT NULL
LIMIT 5;   -- QUITAR para carga completa
