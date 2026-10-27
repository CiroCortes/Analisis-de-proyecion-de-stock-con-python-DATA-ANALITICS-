-- ============================================================================
-- PESCO S.A. - CONSULTAS OPTIMIZADAS PARA DATALAKE (AWS ATHENA / SAP B1)
-- Base de datos: pesco_sbo_pescousd
-- Diseñadas para: MÍNIMO CONSUMO DE DATOS (BAJO COSTO EN ATHENA) Y MÁXIMA VELOCIDAD
--
-- Exportar desde DBeaver como TXT (tabla con pipes |, con cabecera) a data/ con estos nombres:
--   1 -> Maestro de Artículos & Costos.txt
--   2 -> Stock Físico por Bodega.txt
--   3 -> Órdenes de Fabricación (OF).txt
--   4 -> Pedidos de Clientes (PC).txt
--   5 -> Órdenes de Compra en Tránsito (OC).txt
--   6 -> Solicitudes de Compra (SC).txt
--   7 -> Entradas de Mercancias (EM).txt
-- No agregar, quitar ni reordenar columnas: la plataforma las lee por posicion.
-- ============================================================================

-- ============================================================================
-- 1. MAESTRO DE ARTÍCULOS & TAXONOMÍA S&OP (ProductSKU)
-- Objetivo: Actualizar catálogo, costos unitarios, lead times y jerarquía
-- Costo: Muy bajo (OITM + OITB; ORTT agrupada por moneda)
-- ============================================================================
SELECT 
    t0.itemcode                                          AS codigo_sku,
    t0.itemname                                          AS descripcion,
    -- Costo Pesco = precio de ultima compra (lastpurprc), llevado a USD.
    -- Si la moneda no es USD se convierte con el ultimo tipo de cambio de ORTT;
    -- si no hay ultima compra se usa avgprice como respaldo.
    CAST(COALESCE(NULLIF(
        CASE WHEN COALESCE(t0.lastpurcur, '') IN ('', 'USD') THEN t0.lastpurprc
             ELSE t0.lastpurprc * fx.rate END, 0), t0.avgprice, 0.0) AS DECIMAL(12, 4)) AS costo_unitario_usd,
    COALESCE(t0.leadtime, 30)                           AS lead_time_dias,
    COALESCE(t0.u_rhclse, '')                           AS clase,
    COALESCE(t0.u_rhfamilia, '')                        AS familia,
    COALESCE(t0.u_rhsubfam, '')                         AS subfamilia,
    COALESCE(t0.u_rhmodelo, '')                         AS modelo,
    COALESCE(t0.u_rhcategoria, 'General Pesco')         AS categoria_sop,
    SUBSTR(CAST(t0.createdate AS VARCHAR), 1, 10)       AS fec_creacion_sap,
    t0.prchseitem                                       AS es_comprable,
    -- Columnas 12-15: grupo de articulos SAP (oitb) y marcas de inventario
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
WHERE t0.frozenfor = 'N'                                -- Solo SKUs activos
  AND t0.itemcode IS NOT NULL
  AND t0.itemcode <> '';


-- ============================================================================
-- 2. STOCK FÍSICO Y POSICIÓN POR BODEGA (InventoryMetric & StockActual)
-- Objetivo: Stock real por cada una de las 9 bodegas operativas y tránsitos (T*)
-- Costo: Mínimo. Filtra solo registros con movimiento (> 0), eliminando filas muertas.
-- ============================================================================
SELECT 
    t0.itemcode                                          AS codigo_sku,
    t0.whscode                                           AS codigo_bodega,
    CAST(COALESCE(t0.onhand, 0) AS INTEGER)              AS stock_fisico,
    CAST(COALESCE(t0.iscommited, 0) AS INTEGER)          AS compromisos_sap,
    CAST(COALESCE(t0.onorder, 0) AS INTEGER)             AS transito_oc_sap
FROM pesco_sbo_pescousd.oitw t0
WHERE (COALESCE(t0.onhand, 0) > 0 
    OR COALESCE(t0.iscommited, 0) > 0 
    OR COALESCE(t0.onorder, 0) > 0)
  AND t0.itemcode IS NOT NULL;


-- ============================================================================
-- 3. ÓRDENES DE FABRICACIÓN (OF) - COMPROMISOS ABIERTOS Y CONSUMO REAL
-- Objetivo: 
--   a) Compromisos futuros de fabricación (Status P/R)
--   b) Historial de consumo real de taller/producción (Status Cerrada último año)
-- Costo: Acotado por Status y ventana de tiempo de 365 días.
-- Corrección: t1.warehouse (sin 'n') y casting robusto para CURRENT_DATE en Athena.
-- ============================================================================
SELECT 
    t0.docnum                                            AS of_numero,
    t1.itemcode                                          AS codigo_componente,
    COALESCE(t1.warehouse, t0.warehouse)                 AS bodega_consumo,
    t0.status                                            AS estado_of, -- P=Planificada, R=Liberada, L=Cerrada
    SUBSTR(CAST(t0.postdate AS VARCHAR), 1, 10)          AS fecha_creacion,
    SUBSTR(CAST(COALESCE(t0.closedate, t0.duedate) AS VARCHAR), 1, 10) AS fecha_cierre_o_venc,
    CAST(t1.plannedqty AS DECIMAL(12, 2))                AS cantidad_planificada,
    CAST(t1.issuedqty AS DECIMAL(12, 2))                 AS cantidad_consumida_real,
    CAST(GREATEST(0, t1.plannedqty - t1.issuedqty) AS DECIMAL(12, 2)) AS cantidad_pendiente_comprometida
FROM pesco_sbo_pescousd.owor t0
INNER JOIN pesco_sbo_pescousd.wor1 t1 
    ON t0.docentry = t1.docentry
WHERE (
    -- Abiertas: compromisos actuales
    (t0.status IN ('P', 'R') AND (t1.plannedqty - t1.issuedqty) > 0)
    OR
    -- Cerradas: historial de consumo real del último año (para cálculo REPO y DPD)
    (t0.status = 'L' AND SUBSTR(CAST(COALESCE(t0.closedate, t0.postdate) AS VARCHAR), 1, 10) >= CAST(DATE_ADD('year', -1, CURRENT_DATE) AS VARCHAR))
)
AND t1.itemcode IS NOT NULL;


-- ============================================================================
-- 4. PEDIDOS DE CLIENTES (PC) - VENTAS HISTÓRICAS Y COMPROMISOS PENDIENTES
-- Objetivo:
--   a) Compromisos comerciales pendientes de entrega (DocStatus O)
--   b) Ventas reales cerradas último año para frecuencia de rotación
-- Costo: Bajo. Filtra líneas con producto y rango de fechas de 1 año móvil.
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
    CAST(t1.quantity AS DECIMAL(12, 2))                  AS cantidad_solicitada,
    CAST(COALESCE(t1.openqty, 0) AS DECIMAL(12, 2))      AS cantidad_pendiente_despacho
FROM pesco_sbo_pescousd.ordr t0
INNER JOIN pesco_sbo_pescousd.rdr1 t1 
    ON t0.docentry = t1.docentry
WHERE (
    -- Pedidos Abiertos pendientes
    (t0.docstatus = 'O' AND t1.linestatus = 'O' AND t1.openqty > 0)
    OR
    -- Pedidos Cerrados último año (demanda histórica)
    (t0.docstatus = 'C' AND SUBSTR(CAST(t0.docdate AS VARCHAR), 1, 10) >= CAST(DATE_ADD('year', -1, CURRENT_DATE) AS VARCHAR))
)
AND t1.itemcode IS NOT NULL;


-- ============================================================================
-- 5. ÓRDENES DE COMPRA (OC) EN TRÁNSITO
-- Objetivo: Saber qué viene en camino a cada bodega para no sobrecomprar
-- (Las Solicitudes de Compra abiertas van en la consulta 6)
-- Costo: Mínimo. Solo documentos abiertos de los últimos 180 días.
-- ============================================================================
SELECT 
    oc.docnum                                            AS nro_oc_sap,
    COALESCE(oc_l.whscode, '013-PP')                     AS bodega_destino,
    oc_l.itemcode                                        AS codigo_sku,
    oc.cardcode                                          AS codigo_proveedor,
    oc.cardname                                          AS nombre_proveedor,
    SUBSTR(CAST(oc.docdate AS VARCHAR), 1, 10)           AS fecha_emision_oc,
    SUBSTR(CAST(COALESCE(oc_l.shipdate, oc.docduedate) AS VARCHAR), 1, 10) AS fecha_llegada_estimada,
    CAST(oc_l.quantity AS DECIMAL(12, 2))                AS cantidad_comprada,
    CAST(oc_l.openqty AS DECIMAL(12, 2))                 AS cantidad_en_transito_pendiente
FROM pesco_sbo_pescousd.opor oc
INNER JOIN pesco_sbo_pescousd.por1 oc_l 
    ON oc.docentry = oc_l.docentry
WHERE oc.docstatus = 'O'                                -- Solo OCs abiertas
  AND oc_l.linestatus = 'O'                             -- Solo líneas pendientes
  AND oc_l.openqty > 0
  AND SUBSTR(CAST(oc.docdate AS VARCHAR), 1, 10) >= CAST(DATE_ADD('day', -180, CURRENT_DATE) AS VARCHAR)
  AND (oc.cardcode IS NULL OR oc.cardcode NOT LIKE '%PE');


-- ============================================================================
-- 6. SOLICITUDES DE COMPRA (SC) ABIERTAS
-- Objetivo: Pipeline de compra aún sin OC. Suma al Disponible Futuro:
--   disp_future = stock + SC + OC - PC - OF
-- Una SC que ya se convirtió en OC cierra su línea (linestatus 'C'), por lo que
-- no se duplica con la consulta 5.
-- Archivo de salida esperado: data/Solicitudes de Compra (SC).txt
-- ============================================================================
SELECT
    prq.docnum                                           AS nro_sc_sap,
    COALESCE(NULLIF(prq_l.whscode, ''), '013-PP')        AS bodega_solicitada,
    prq_l.itemcode                                       AS codigo_sku,
    SUBSTR(CAST(prq.docdate AS VARCHAR), 1, 10)          AS fecha_solicitud,
    CAST(prq_l.quantity AS DECIMAL(12, 2))               AS cantidad_solicitada,
    CAST(prq_l.openqty AS DECIMAL(12, 2))                AS cantidad_pendiente_sc
FROM pesco_sbo_pescousd.oprq prq
INNER JOIN pesco_sbo_pescousd.prq1 prq_l
    ON prq.docentry = prq_l.docentry
WHERE prq.docstatus = 'O'
  AND prq_l.linestatus = 'O'
  AND prq_l.openqty > 0
  AND prq_l.itemcode IS NOT NULL
  AND SUBSTR(CAST(prq.docdate AS VARCHAR), 1, 10) >= CAST(DATE_ADD('day', -180, CURRENT_DATE) AS VARCHAR);


-- ============================================================================
-- 7. ENTRADAS DE MERCANCIAS (GoodsReceipt) - 12 MESES CERRADOS + MES EN CURSO
-- Objetivo: Ingresos mensuales valorizados del dashboard (reemplaza ENTRADA MERCANCIAS.xlsx),
--   inventario historico del detalle de la Calculadora y proveedor de respaldo por articulo
-- Modelo destino: inventory.GoodsReceipt (document_number, product, quantity,
--                 posting_date, supplier_name, total_lines_cost)
-- Archivo de salida esperado: data/Entradas de Mercancias (EM).txt
-- Nota: OPDN/PDN1 = Entrada de mercancias de compras. Si el Excel original
-- provenia de OIGN/IGN1 (entrada de inventario), avisar para cambiar tablas.
-- ============================================================================
SELECT
    gr.docnum                                            AS nro_documento,
    gr_l.itemcode                                        AS codigo_sku,
    SUBSTR(CAST(gr.docdate AS VARCHAR), 1, 10)           AS fecha_contabilizacion,
    gr.cardcode                                          AS codigo_proveedor,
    gr.cardname                                          AS nombre_proveedor,
    CAST(gr_l.quantity AS DECIMAL(12, 2))                AS cantidad,
    CAST(gr_l.linetotal AS DECIMAL(14, 2))               AS total_linea
FROM pesco_sbo_pescousd.opdn gr
INNER JOIN pesco_sbo_pescousd.pdn1 gr_l
    ON gr.docentry = gr_l.docentry
WHERE gr.canceled = 'N'
  AND gr_l.itemcode IS NOT NULL
  AND gr_l.quantity > 0
  AND SUBSTR(CAST(gr.docdate AS VARCHAR), 1, 10) >= CAST(DATE_ADD('month', -13, DATE_TRUNC('month', CURRENT_DATE)) AS VARCHAR);
