-- ============================================================================
-- PESCO S.A. - CONSULTAS OFICIALES DEL DATALAKE (AWS ATHENA / SAP B1)
-- Base de datos: pesco_sbo_pescousd
-- Version: 28-oct-2026. Es el UNICO archivo de consultas de la plataforma.
--
-- COMO EXPORTAR (DBeaver)
--   1. Copiar UNA consulta (desde SELECT hasta el punto y coma) y ejecutarla.
--   2. Clic derecho en el resultado > Exportar datos > formato "TXT".
--      Dejar marcado: mostrar cabecera (nombres de columna) y delimitador "|".
--   3. Nombre del archivo = el indicado en "ARCHIVO:" de su cabecera, tal cual (con tildes).
--   4. Carpeta de destino: la carpeta data/ del proyecto.
--   5. Repetir con todas. Al final, en la plataforma: Sincronizar.
--
-- REGLAS
--   * No agregar, quitar ni reordenar columnas: la plataforma las lee por posicion.
--   * Para probar barato, agregar LIMIT 5 antes del punto y coma y luego quitarlo.
--   * Si una consulta falla con COLUMN_NOT_FOUND, ver el ANEXO (DESCRIBE) al final.
--   * La linea "-- ARCHIVO:" la usa tambien el conector automatico (manage.py sync_datalake):
--     no borrarla ni cambiarla.
--
-- PRIORIDAD
--   1 a 9   IMPRESCINDIBLES (sin ellas el calculo es provisional)
--   15 y 16 IMPRESCINDIBLES desde el 28-oct (notas de credito y compromisos con responsable)
--   10 a 12 RECOMENDADAS   (proveedor, minimo/multiplo, contratos)
--   13 y 14 OPCIONALES
--
-- DECISIONES (ver .specs/07 y .specs/08)
--   * Costo = lastpurprc en USD (no avgprice).
--   * Consumo desde movimientos de inventario (OINM), agregado por mes, solo meses cerrados.
--   * Escribir en SAP esta descartado por ahora.
-- ============================================================================


-- ============================================================================
-- 1. MAESTRO DE ARTICULOS Y COSTOS                                  [IMPRESCINDIBLE]
-- ARCHIVO: Maestro de Artículos & Costos.txt
-- Catalogo, costo unitario USD, lead time del maestro, taxonomia y grupo SAP.
-- ============================================================================
SELECT
    t0.itemcode                                          AS codigo_sku,
    t0.itemname                                          AS descripcion,
    -- Costo Pesco = precio de ultima compra (lastpurprc), llevado a USD.
    -- Si la moneda no es USD se convierte con el ultimo tipo de cambio de ORTT;
    -- si no hay ultima compra se usa avgprice como respaldo.
    CAST(COALESCE(NULLIF(
        CASE WHEN COALESCE(t0.lastpurcur, '') IN ('', 'USD') THEN t0.lastpurprc
             ELSE t0.lastpurprc * fx.rate END, 0), t0.avgprice, 0.0) AS DECIMAL(18, 4)) AS costo_unitario_usd,
    COALESCE(t0.leadtime, 30)                           AS lead_time_dias,
    COALESCE(t0.u_rhclse, '')                           AS clase,
    COALESCE(t0.u_rhfamilia, '')                        AS familia,
    COALESCE(t0.u_rhsubfam, '')                         AS subfamilia,
    COALESCE(t0.u_rhmodelo, '')                         AS modelo,
    COALESCE(t0.u_rhcategoria, 'General Pesco')         AS categoria_sop,
    SUBSTR(CAST(t0.createdate AS VARCHAR), 1, 10)       AS fec_creacion_sap,
    t0.prchseitem                                       AS es_comprable,
    CAST(t0.itmsgrpcod AS VARCHAR)                      AS cod_grupo,
    COALESCE(g.itmsgrpnam, '')                          AS nombre_grupo,
    t0.invntitem                                        AS gestiona_inventario, -- N = servicio/gasto
    t0.sellitem                                         AS es_vendible
FROM pesco_sbo_pescousd.oitm t0
LEFT JOIN (
    -- Ultimo tipo de cambio por moneda (ORTT: rate = unidades de USD por 1 unidad de moneda)
    SELECT currency, MAX_BY(rate, ratedate) AS rate
    FROM pesco_sbo_pescousd.ortt
    GROUP BY currency
) fx ON fx.currency = t0.lastpurcur
LEFT JOIN pesco_sbo_pescousd.oitb g ON g.itmsgrpcod = t0.itmsgrpcod
WHERE t0.frozenfor = 'N'
  AND t0.itemcode IS NOT NULL
  AND t0.itemcode <> '';


-- ============================================================================
-- 2. STOCK FISICO POR BODEGA                                        [IMPRESCINDIBLE]
-- ARCHIVO: Stock Físico por Bodega.txt
-- Stock, comprometido y pedido por bodega (incluye bodegas de transito T*).
-- ============================================================================
SELECT
    t0.itemcode                                          AS codigo_sku,
    t0.whscode                                           AS codigo_bodega,
    CAST(COALESCE(t0.onhand, 0) AS BIGINT)              AS stock_fisico,
    CAST(COALESCE(t0.iscommited, 0) AS BIGINT)          AS compromisos_sap,
    CAST(COALESCE(t0.onorder, 0) AS BIGINT)             AS transito_oc_sap
FROM pesco_sbo_pescousd.oitw t0
WHERE (COALESCE(t0.onhand, 0) > 0
    OR COALESCE(t0.iscommited, 0) > 0
    OR COALESCE(t0.onorder, 0) > 0)
  AND t0.itemcode IS NOT NULL;


-- ============================================================================
-- 3. ORDENES DE FABRICACION (OF)                                    [IMPRESCINDIBLE]
-- ARCHIVO: Órdenes de Fabricación (OF).txt
-- a) Abiertas (P/R): compromisos.  b) Cerradas del ultimo ano: consumo de respaldo.
-- ============================================================================
SELECT
    t0.docnum                                            AS of_numero,
    t1.itemcode                                          AS codigo_componente,
    COALESCE(t1.warehouse, t0.warehouse)                 AS bodega_consumo,
    t0.status                                            AS estado_of, -- P=Planificada, R=Liberada, L=Cerrada
    SUBSTR(CAST(t0.postdate AS VARCHAR), 1, 10)          AS fecha_creacion,
    SUBSTR(CAST(COALESCE(t0.closedate, t0.duedate) AS VARCHAR), 1, 10) AS fecha_cierre_o_venc,
    CAST(t1.plannedqty AS DECIMAL(18, 2))                AS cantidad_planificada,
    CAST(t1.issuedqty AS DECIMAL(18, 2))                 AS cantidad_consumida_real,
    CAST(GREATEST(0, t1.plannedqty - t1.issuedqty) AS DECIMAL(18, 2)) AS cantidad_pendiente_comprometida
FROM pesco_sbo_pescousd.owor t0
INNER JOIN pesco_sbo_pescousd.wor1 t1
    ON t0.docentry = t1.docentry
WHERE (
    (t0.status IN ('P', 'R') AND (t1.plannedqty - t1.issuedqty) > 0)
    OR
    (t0.status = 'L' AND SUBSTR(CAST(COALESCE(t0.closedate, t0.postdate) AS VARCHAR), 1, 10) >= CAST(DATE_ADD('year', -1, CURRENT_DATE) AS VARCHAR))
)
AND t1.itemcode IS NOT NULL;


-- ============================================================================
-- 4. PEDIDOS DE CLIENTES (PC)                                       [IMPRESCINDIBLE]
-- ARCHIVO: Pedidos de Clientes (PC).txt
-- a) Abiertos: compromisos de entrega.  b) Cerrados del ultimo ano: consumo de respaldo.
-- ============================================================================
SELECT
    t0.docnum                                            AS pedido_numero,
    t1.itemcode                                          AS codigo_sku,
    t1.whscode                                           AS bodega_despacho,
    t0.cardcode                                          AS codigo_cliente,
    COALESCE(t0.cardname, 'Cliente Directo')             AS nombre_cliente,
    t0.docstatus                                         AS estado_pedido, -- O=Abierto, C=Cerrado
    SUBSTR(CAST(t0.docdate AS VARCHAR), 1, 10)           AS fecha_emision,
    SUBSTR(CAST(COALESCE(t1.shipdate, t0.docduedate) AS VARCHAR), 1, 10) AS fecha_entrega,
    CAST(t1.quantity AS DECIMAL(18, 2))                  AS cantidad_solicitada,
    CAST(COALESCE(t1.openqty, 0) AS DECIMAL(18, 2))      AS cantidad_pendiente_despacho
FROM pesco_sbo_pescousd.ordr t0
INNER JOIN pesco_sbo_pescousd.rdr1 t1
    ON t0.docentry = t1.docentry
WHERE (
    (t0.docstatus = 'O' AND t1.linestatus = 'O' AND t1.openqty > 0)
    OR
    (t0.docstatus = 'C' AND SUBSTR(CAST(t0.docdate AS VARCHAR), 1, 10) >= CAST(DATE_ADD('year', -1, CURRENT_DATE) AS VARCHAR))
)
AND t1.itemcode IS NOT NULL;


-- ============================================================================
-- 5. ORDENES DE COMPRA (OC) EN TRANSITO                             [IMPRESCINDIBLE]
-- ARCHIVO: Órdenes de Compra en Tránsito (OC).txt
-- Todas las lineas de OC abiertas (lo que viene en camino). Reunion 28-oct: se quito el corte de
-- 180 dias; las OC antiguas a pre-bodegas (000-xxx) quedaban fuera. La antiguedad la informa la plataforma.
-- Se excluyen proveedores internos terminados en PE.
-- ============================================================================
SELECT
    oc.docnum                                            AS nro_oc_sap,
    COALESCE(oc_l.whscode, '013-PP')                     AS bodega_destino,
    oc_l.itemcode                                        AS codigo_sku,
    oc.cardcode                                          AS codigo_proveedor,
    oc.cardname                                          AS nombre_proveedor,
    SUBSTR(CAST(oc.docdate AS VARCHAR), 1, 10)           AS fecha_emision_oc,
    SUBSTR(CAST(COALESCE(oc_l.shipdate, oc.docduedate) AS VARCHAR), 1, 10) AS fecha_llegada_estimada,
    CAST(oc_l.quantity AS DECIMAL(18, 2))                AS cantidad_comprada,
    CAST(oc_l.openqty AS DECIMAL(18, 2))                 AS cantidad_en_transito_pendiente
FROM pesco_sbo_pescousd.opor oc
INNER JOIN pesco_sbo_pescousd.por1 oc_l
    ON oc.docentry = oc_l.docentry
WHERE oc.docstatus = 'O'
  AND oc_l.linestatus = 'O'
  AND oc_l.openqty > 0
  AND (oc.cardcode IS NULL OR oc.cardcode NOT LIKE '%PE');


-- ============================================================================
-- 6. SOLICITUDES DE COMPRA (SC) ABIERTAS                            [IMPRESCINDIBLE]
-- ARCHIVO: Solicitudes de Compra (SC).txt
-- Pedidos de compra aun sin OC. Una SC convertida en OC cierra su linea: no se duplica con la 5.
-- ============================================================================
SELECT
    prq.docnum                                           AS nro_sc_sap,
    COALESCE(NULLIF(prq_l.whscode, ''), '013-PP')        AS bodega_solicitada,
    prq_l.itemcode                                       AS codigo_sku,
    SUBSTR(CAST(prq.docdate AS VARCHAR), 1, 10)          AS fecha_solicitud,
    CAST(prq_l.quantity AS DECIMAL(18, 2))               AS cantidad_solicitada,
    CAST(prq_l.openqty AS DECIMAL(18, 2))                AS cantidad_pendiente_sc
FROM pesco_sbo_pescousd.oprq prq
INNER JOIN pesco_sbo_pescousd.prq1 prq_l
    ON prq.docentry = prq_l.docentry
WHERE prq.docstatus = 'O'
  AND prq_l.linestatus = 'O'
  AND prq_l.openqty > 0
  AND prq_l.itemcode IS NOT NULL
  AND SUBSTR(CAST(prq.docdate AS VARCHAR), 1, 10) >= CAST(DATE_ADD('day', -180, CURRENT_DATE) AS VARCHAR);


-- ============================================================================
-- 7. ENTRADAS DE MERCANCIAS                                         [IMPRESCINDIBLE]
-- ARCHIVO: Entradas de Mercancias (EM).txt
-- Recepciones de compra de los 12 meses cerrados + mes en curso: ingresos del dashboard,
-- inventario historico del articulo y proveedor de respaldo.
-- ============================================================================
SELECT
    gr.docnum                                            AS nro_documento,
    gr_l.itemcode                                        AS codigo_sku,
    SUBSTR(CAST(gr.docdate AS VARCHAR), 1, 10)           AS fecha_contabilizacion,
    gr.cardcode                                          AS codigo_proveedor,
    gr.cardname                                          AS nombre_proveedor,
    CAST(gr_l.quantity AS DECIMAL(18, 2))                AS cantidad,
    CAST(gr_l.linetotal AS DECIMAL(18, 2))               AS total_linea
FROM pesco_sbo_pescousd.opdn gr
INNER JOIN pesco_sbo_pescousd.pdn1 gr_l
    ON gr.docentry = gr_l.docentry
WHERE gr.canceled = 'N'
  AND gr_l.itemcode IS NOT NULL
  AND gr_l.quantity > 0
  AND SUBSTR(CAST(gr.docdate AS VARCHAR), 1, 10) >= CAST(DATE_ADD('month', -13, DATE_TRUNC('month', CURRENT_DATE)) AS VARCHAR);


-- ============================================================================
-- 8. CONSUMO MENSUAL POR ARTICULO Y BODEGA (24 meses cerrados)      [IMPRESCINDIBLE]
-- ARCHIVO: Consumo Mensual.txt
-- LA MAS IMPORTANTE: sin ella el consumo se reconstruye (provisional) desde PC y OF.
-- Es la mas pesada (24 meses de OINM): probar primero con LIMIT 5.
-- TransType (validar contra el informe de auditoria de stock de B1):
--   15 Entrega de venta · 13 Factura que mueve stock · 14 Nota de credito ·
--   16 Devolucion de venta · 60 Salida de mercancia (incluye emisiones a OF).
--   No se incluyen 67 (traslados), 59 (entradas) ni 18/19/20/21 (compras).
-- cantidad_neta = salidas - entradas (devoluciones restan en el mes en que ocurren).
-- origen 'NC' (28-oct, SPEC-22): las notas de credito van aparte; la plataforma las reemplaza por la
-- consulta 15, que las resta en la bodega y el mes de su factura de origen.
-- ============================================================================
SELECT
    m.itemcode                                           AS codigo_sku,
    m.warehouse                                          AS bodega,
    SUBSTR(CAST(m.docdate AS VARCHAR), 1, 7)             AS mes,
    CASE WHEN m.transtype = 14                THEN 'NC'
         WHEN m.transtype IN (13, 15, 16)     THEN 'VENTA'
         WHEN m.transtype = 60                THEN 'SALIDA'
         ELSE 'OTRO' END                                 AS origen,
    CAST(SUM(COALESCE(m.outqty, 0) - COALESCE(m.inqty, 0)) AS DECIMAL(18, 2)) AS cantidad_neta
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
    CASE WHEN m.transtype = 14                THEN 'NC'
         WHEN m.transtype IN (13, 15, 16)     THEN 'VENTA'
         WHEN m.transtype = 60                THEN 'SALIDA'
         ELSE 'OTRO' END
HAVING SUM(COALESCE(m.outqty, 0) - COALESCE(m.inqty, 0)) <> 0;


-- ============================================================================
-- 9. PLAZOS REALES DE ENTREGA POR OC RECIBIDA (24 meses)            [IMPRESCINDIBLE]
-- ARCHIVO: Plazos de Entrega OC.txt
-- Una fila por recepcion ligada a su OC (pdn1.basetype = 22). La plataforma calcula el plazo
-- promedio y su variacion por articulo; con menos de 3 OC usa el lead time del maestro.
-- Recepciones parciales: la plataforma usa la PRIMERA entrada de cada linea de OC.
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
    CAST(l.quantity AS DECIMAL(18, 2))                   AS cantidad_oc,
    CAST(gl.quantity AS DECIMAL(18, 2))                  AS cantidad_recibida
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
  AND SUBSTR(CAST(gr.docdate AS VARCHAR), 1, 10) >= CAST(DATE_ADD('month', -24, CURRENT_DATE) AS VARCHAR);


-- ============================================================================
-- 10. PARAMETROS DE COMPRA DEL ARTICULO                             [RECOMENDADA]
-- ARCHIVO: Parametros de Compra.txt
-- Proveedor preferido, minimo y multiplo de compra, unidad de medida.
-- Sin ella el proveedor se deduce de la ultima entrada u OC y no hay minimo ni multiplo.
-- ============================================================================
SELECT
    t0.itemcode                                          AS codigo_sku,
    COALESCE(t0.cardcode, '')                            AS proveedor_preferido,
    COALESCE(t0.leadtime, 0)                             AS lead_time_maestro,
    CAST(COALESCE(t0.minordrqty, 0) AS DECIMAL(18, 2))   AS min_compra,
    CAST(COALESCE(t0.ordrmulti, 0) AS DECIMAL(18, 2))    AS multiplo_compra,
    CAST(COALESCE(t0.purpackun, 0) AS DECIMAL(18, 2))    AS unidades_por_paquete,
    COALESCE(t0.invntryuom, '')                          AS unidad_medida,
    t0.frozenfor                                         AS congelado,
    t0.validfor                                          AS vigente
FROM pesco_sbo_pescousd.oitm t0
WHERE t0.itemcode IS NOT NULL
  AND t0.itemcode <> ''
  AND t0.invntitem = 'Y';


-- ============================================================================
-- 11. PROVEEDORES                                                   [RECOMENDADA]
-- ARCHIVO: Proveedores.txt
-- Nombre y pais (nacional / importado) para agrupar las solicitudes de compra.
-- ============================================================================
SELECT
    c.cardcode                                           AS codigo_proveedor,
    c.cardname                                           AS nombre_proveedor,
    COALESCE(c.country, '')                              AS pais,
    c.frozenfor                                          AS congelado
FROM pesco_sbo_pescousd.ocrd c
WHERE c.cardtype = 'S';


-- ============================================================================
-- 12. ACUERDOS GLOBALES (CONTRATOS)                                 [RECOMENDADA]
-- ARCHIVO: Acuerdos Globales.txt
-- Contrato, precio y saldo por articulo. Con mas de un acuerdo se toma el de menor precio.
-- El precio de OAT1 viene en la moneda del acuerdo (en general CLP): se lleva a USD con el
-- ultimo tipo de cambio de ORTT, igual que el costo de la consulta 1. Las columnas 11 y 12
-- (moneda y precio original) son de control.
-- ============================================================================
SELECT
    a.number                                             AS nro_acuerdo,
    a.bpcode                                             AS codigo_proveedor,
    SUBSTR(CAST(a.startdate AS VARCHAR), 1, 10)          AS fecha_inicio,
    SUBSTR(CAST(a.enddate AS VARCHAR), 1, 10)            AS fecha_termino,
    a.status                                             AS estado,
    l.agrlinenum                                         AS linea_acuerdo,
    l.itemcode                                           AS codigo_sku,
    -- OAT1.planqty NO se puede leer: el catalogo del Datalake la declara DECIMAL(12,6) y hay
    -- acuerdos con 500.000.000 (no caben) -> Athena falla al leerla aunque se haga CAST.
    -- Mientras el equipo de datos no amplie el tipo en Glue, va en 0: la plataforma entiende
    -- "sin cantidad planificada" y no controla saldo (precio y contrato si se usan).
    CAST(0 AS DECIMAL(18, 2))                            AS cantidad_plan,
    CAST(l.cumqty AS DECIMAL(18, 2))                     AS cantidad_acumulada,
    CAST(CASE WHEN COALESCE(l.currency, '') IN ('', 'USD') THEN l.unitprice
              ELSE l.unitprice * fx.rate END AS DECIMAL(18, 4))  AS precio_unitario_usd,
    COALESCE(l.currency, '')                             AS moneda,
    CAST(l.unitprice AS DECIMAL(18, 4))                  AS precio_moneda_original
FROM pesco_sbo_pescousd.ooat a
INNER JOIN pesco_sbo_pescousd.oat1 l
    ON l.agrno = a.absid
LEFT JOIN (
    SELECT currency, MAX_BY(rate, ratedate) AS rate
    FROM pesco_sbo_pescousd.ortt
    GROUP BY currency
) fx ON fx.currency = l.currency
WHERE l.itemcode IS NOT NULL;


-- ============================================================================
-- 13. SALIDAS DE MERCANCIA A OF POR MES                             [OPCIONAL]
-- ARCHIVO: Consumo OF Mensual.txt
-- Separa las emisiones a Orden de Fabricacion (ige1.basetype = 202) del resto de salidas
-- de la consulta 8 (graficos venta vs fabricacion).
-- ============================================================================
SELECT
    l.itemcode                                           AS codigo_sku,
    l.whscode                                            AS bodega,
    SUBSTR(CAST(h.docdate AS VARCHAR), 1, 7)             AS mes,
    CAST(SUM(l.quantity) AS DECIMAL(18, 2))              AS cantidad_of
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
    SUBSTR(CAST(h.docdate AS VARCHAR), 1, 7);


-- ============================================================================
-- 14. BODEGAS                                                       [OPCIONAL]
-- ARCHIVO: Bodegas.txt
-- Nombres reales de bodega. El tipo y la zona se definen en la plataforma.
-- ============================================================================
SELECT
    w.whscode                                            AS codigo_bodega,
    w.whsname                                            AS nombre_bodega,
    w.inactive                                           AS inactiva
FROM pesco_sbo_pescousd.owhs w;


-- ============================================================================
-- 15. NOTAS DE CREDITO DE CLIENTE CON SU DOCUMENTO DE ORIGEN (24 meses) [IMPRESCINDIBLE]
-- ARCHIVO: Notas de Credito.txt
-- Reunion 28-oct: se factura en una sucursal, se despacha desde otra y se emite una NC.
-- La NC debe restar el consumo en la bodega y el mes de la factura/entrega ORIGINAL,
-- no donde se registro la NC (a veces 013-NC, que esta excluida).
-- tipo_origen: 13 = factura, 15 = entrega, -1 = sin documento base.
-- sin_movimiento_stock = 'Y': NC solo financiera (no devolvio unidades a bodega).
-- ============================================================================
SELECT
    nc.docnum                                            AS nc_numero,
    l.itemcode                                           AS codigo_sku,
    l.whscode                                            AS bodega_nc,
    SUBSTR(CAST(nc.docdate AS VARCHAR), 1, 10)           AS fecha_nc,
    CAST(l.quantity AS DECIMAL(18, 2))                   AS cantidad,
    CAST(l.basetype AS VARCHAR)                          AS tipo_origen,
    COALESCE(fl.whscode, el.whscode)                     AS bodega_origen,
    SUBSTR(CAST(COALESCE(f.docdate, e.docdate) AS VARCHAR), 1, 10) AS fecha_origen,
    COALESCE(f.docnum, e.docnum)                         AS numero_origen,
    l.noinvtrymv                                         AS sin_movimiento_stock
FROM pesco_sbo_pescousd.orin nc
INNER JOIN pesco_sbo_pescousd.rin1 l
    ON nc.docentry = l.docentry
INNER JOIN pesco_sbo_pescousd.oitm t
    ON t.itemcode = l.itemcode
LEFT JOIN pesco_sbo_pescousd.inv1 fl
    ON CAST(l.basetype AS VARCHAR) = '13' AND fl.docentry = l.baseentry AND fl.linenum = l.baseline
LEFT JOIN pesco_sbo_pescousd.oinv f
    ON f.docentry = fl.docentry
LEFT JOIN pesco_sbo_pescousd.dln1 el
    ON CAST(l.basetype AS VARCHAR) = '15' AND el.docentry = l.baseentry AND el.linenum = l.baseline
LEFT JOIN pesco_sbo_pescousd.odln e
    ON e.docentry = el.docentry
WHERE nc.canceled = 'N'
  AND t.invntitem = 'Y'
  AND SUBSTR(CAST(nc.docdate AS VARCHAR), 1, 10) >= CAST(DATE_ADD('month', -24, DATE_TRUNC('month', CURRENT_DATE)) AS VARCHAR);


-- ============================================================================
-- 16. COMPROMISOS ABIERTOS CON RESPONSABLE (PC y OF)                 [IMPRESCINDIBLE]
-- ARCHIVO: Compromisos Abiertos.txt
-- Para el informe de antiguedad de compromisos abiertos (Contraloria): quien lo emitio,
-- cliente y referencia. No reemplaza a las consultas 3 y 4.
-- referencia: PC = OC del cliente (numatcard); OF = articulo fabricado.
-- ============================================================================
SELECT
    'PC'                                                 AS tipo,
    t0.docnum                                            AS numero,
    t1.itemcode                                          AS codigo_sku,
    t1.whscode                                           AS bodega,
    SUBSTR(CAST(t0.docdate AS VARCHAR), 1, 10)           AS fecha_emision,
    SUBSTR(CAST(COALESCE(t1.shipdate, t0.docduedate) AS VARCHAR), 1, 10) AS fecha_entrega,
    t0.cardcode                                          AS codigo_cliente,
    t0.cardname                                          AS nombre_cliente,
    s.slpname                                            AS responsable,
    t0.numatcard                                         AS referencia,
    CAST(t1.openqty AS DECIMAL(18, 2))                   AS cantidad_pendiente
FROM pesco_sbo_pescousd.ordr t0
INNER JOIN pesco_sbo_pescousd.rdr1 t1
    ON t0.docentry = t1.docentry
LEFT JOIN pesco_sbo_pescousd.oslp s
    ON s.slpcode = t0.slpcode
WHERE t0.docstatus = 'O' AND t1.linestatus = 'O' AND t1.openqty > 0
  AND t1.itemcode IS NOT NULL
UNION ALL
SELECT
    'OF',
    w.docnum,
    w1.itemcode,
    COALESCE(w1.warehouse, w.warehouse),
    SUBSTR(CAST(w.postdate AS VARCHAR), 1, 10),
    SUBSTR(CAST(w.duedate AS VARCHAR), 1, 10),
    w.cardcode,
    c.cardname,
    u.u_name,
    w.itemcode,
    CAST(GREATEST(0, w1.plannedqty - w1.issuedqty) AS DECIMAL(18, 2))
FROM pesco_sbo_pescousd.owor w
INNER JOIN pesco_sbo_pescousd.wor1 w1
    ON w.docentry = w1.docentry
LEFT JOIN pesco_sbo_pescousd.ocrd c
    ON c.cardcode = w.cardcode
LEFT JOIN pesco_sbo_pescousd.ousr u
    ON u.userid = w.usersign
WHERE w.status IN ('P', 'R') AND (w1.plannedqty - w1.issuedqty) > 0
  AND w1.itemcode IS NOT NULL;


-- ============================================================================
-- ANEXO. VERIFICACION DE COLUMNAS (solo si una consulta da COLUMN_NOT_FOUND)
-- Quitar el "--" de la linea a revisar y ejecutarla sola.
-- ============================================================================
-- DESCRIBE pesco_sbo_pescousd.oinm;
-- DESCRIBE pesco_sbo_pescousd.oitm;
-- DESCRIBE pesco_sbo_pescousd.ooat;
-- DESCRIBE pesco_sbo_pescousd.oat1;
-- DESCRIBE pesco_sbo_pescousd.ige1;
-- DESCRIBE pesco_sbo_pescousd.rin1;   -- consulta 15: basetype, baseentry, baseline, noinvtrymv
-- DESCRIBE pesco_sbo_pescousd.dln1;
-- DESCRIBE pesco_sbo_pescousd.oslp;   -- consulta 16
-- DESCRIBE pesco_sbo_pescousd.ousr;   -- consulta 16 (si no existe: reemplazar u.u_name por CAST(w.usersign AS VARCHAR) y quitar el JOIN)
