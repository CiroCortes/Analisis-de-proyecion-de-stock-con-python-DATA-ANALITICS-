-- =============================================
-- CONSULTA SQL #1
-- =============================================
ite3

-- =============================================
-- CONSULTA SQL #2
-- =============================================
SELECT 
    WhsCode AS CodigoAlmacen,
    WhsName AS NombreAlmacen,
    City AS Ciudad
FROM pesco_sbo_pescousd.owhs
WHERE Inactive = 'N'  -- Filtramos para que solo traiga los almacenes activos
ORDER BY WhsCode ASC;

-- =============================================
-- CONSULTA SQL #3
-- =============================================
SELECT 
    T0.ItemCode AS item_code,
    T0.ItemName AS item_name,
    T0.OnHand AS stock,
    T0.AvgPrice AS costo_un,
    T0.CardCode AS card_code,               -- Proveedor predeterminado (código)
    T0.BuyUnitMsr AS unidad_compra,         -- Unidad de medida de compra (ej: UN, CJ, MT)
    T0.NumInBuy AS articulos_por_paquete,   -- Factor de conversión
    T0.PurPackUn AS cantidad_por_paquete,
    T0.MinOrdrQty AS pedido_minimo,         -- Cantidad mínima de pedido
    T0.OrdrMulti AS pedido_multiplo,        -- Múltiplo de pedido
    T0.LeadTime AS tiempo_entrega_dias,     -- Tiempo lead
    T0.PrchseItem AS es_comprable,          -- 'Y' si es artículo de compra
    T0.frozenFor AS esta_inactivo,          -- 'Y' si está inactivo
    T0.PrcrmntMtd AS metodo_aprovisionamiento, -- 'B' (Buy/Comprar) o 'M' (Make/Fabricar)
    -- Campos de Usuario / Taxonomía PESCO (Panel lateral)
    T0.U_OrigenArt AS origen_articulo,      -- Nacional / Importado
    T0.U_Clase AS clase,
    T0.U_Familia AS familia,
    T0.U_SubFamilia AS subfamilia,
    T0.U_Modelo AS modelo,
    T0.U_Categoria AS categoria
FROM pesco_sbo_pescousd.oitm T0
WHERE T0.PrchseItem = 'Y'                  -- Solo artículos marcados como de compra
  AND T0.frozenFor = 'N';                  -- Solo artículos activos

-- =============================================
-- CONSULTA SQL #4
-- =============================================
SELECT 
    T0.CardCode AS card_code,              -- Código Proveedor SAP (ej: P76123456-7)
    T0.CardName AS razon_social,          -- Nombre / Razón Social
    T0.CardType AS tipo_socio,            -- 'S' = Proveedor (Supplier)
    T0.Country AS pais,                   -- 'CL' u otros
    T0.Currency AS moneda,                -- 'CLP', 'USD', 'EUR'
    T0.frozenFor AS esta_inactivo         -- 'N' = Activo
FROM pesco_sbo_pescousd.ocrd T0
WHERE T0.CardType = 'S'                  -- Solo Proveedores
  AND T0.frozenFor = 'N';                -- Solo Activos

-- =============================================
-- CONSULTA SQL #5
-- =============================================
SELECT * 
FROM pesco_sbo_pescousd.oitm 
LIMIT 1;

-- =============================================
-- CONSULTA SQL #6
-- =============================================
SHOW COLUMNS IN pesco_sbo_pescousd.oitm;

-- =============================================
-- CONSULTA SQL #7
-- =============================================
SELECT 
    T0.ItemCode AS item_code,
    T0.ItemName AS item_name,
    T0.OnHand AS stock,
    T0.AvgPrice AS costo_un,
    T0.CardCode AS card_code,               -- Proveedor predeterminado (código)
    T0.BuyUnitMsr AS unidad_compra,         -- Unidad de medida de compra
    T0.NumInBuy AS articulos_por_paquete,   -- Factor de conversión
    T0.PurPackUn AS cantidad_por_paquete,
    T0.MinOrdrQty AS pedido_minimo,         -- Cantidad mínima de pedido
    T0.OrdrMulti AS pedido_multiplo,        -- Múltiplo de pedido
    T0.LeadTime AS tiempo_entrega_dias,     -- Tiempo lead
    T0.PrchseItem AS es_comprable,          -- 'Y'
    T0.frozenFor AS esta_inactivo,          -- 'N'
    T0.PrcrmntMtd AS metodo_aprovisionamiento
FROM pesco_sbo_pescousd.oitm T0
WHERE T0.PrchseItem = 'Y'
  AND T0.frozenFor = 'N';

-- =============================================
-- CONSULTA SQL #8
-- =============================================
SELECT 
    T0.itemcode AS item_code,
    T0.itemname AS item_name,
    T0.onhand AS stock,
    T0.avgprice AS costo_un,
    T0.cardcode AS card_code,               -- Proveedor predeterminado
    T0.buyunitmsr AS unidad_compra,         -- Unidad de medida de compra (ej: UN)
    T0.numinbuy AS articulos_por_paquete,   -- Conversión
    T0.purpackun AS cantidad_por_paquete,
    T0.minordrqty AS pedido_minimo,
    T0.ordrmulti AS pedido_multiplo,
    T0.leadtime AS tiempo_entrega_dias,
    T0.prchseitem AS es_comprable,
    T0.frozenfor AS esta_inactivo,
    T0.prcrmntmtd AS metodo_aprovisionamiento,
    -- Campos Taxonómicos y de Negocio PESCO (los reales de Rodrigo):
    T0.u_origin AS origen_articulo,        -- N = Nacional, I = Importado
    T0.u_currency AS moneda,
    T0.u_rhclse AS clase,
    T0.u_rhfamilia AS familia,
    T0.u_rhsubfam AS subfamilia,
    T0.u_rhmodelo AS modelo,
    T0.u_rhcategoria AS categoria,
    T0.u_rhresponsable AS responsable
FROM pesco_sbo_pescousd.oitm T0
WHERE T0.prchseitem = 'Y'
  AND T0.frozenfor = 'N';

-- =============================================
-- CONSULTA SQL #9
-- =============================================
SELECT 
    T0.cardcode AS card_code,              -- Código Proveedor SAP
    T0.cardname AS razon_social,          -- Razón Social
    T0.cardtype AS tipo_socio,            -- 'S' = Proveedor
    T0.country AS pais,                   -- País
    T0.currency AS moneda,                -- Moneda
    T0.frozenfor AS esta_inactivo         -- Inactivo
FROM pesco_sbo_pescousd.ocrd T0
WHERE T0.cardtype = 'S'
  AND T0.frozenfor = 'N';

-- =============================================
-- CONSULTA SQL #10
-- =============================================
T0.onhand AS stock

-- =============================================
-- CONSULTA SQL #11
-- =============================================
-- 1. Órdenes de Fabricación Abiertas (Pesco)
SELECT 
    docentry,
    docnum AS of_numero,
    itemcode AS producto_a_fabricar,
    status AS estado_of,
    postdate AS fecha_creacion,
    duedate AS fecha_vencimiento,
    warehouse AS almacen_destino,
    u_proyecto AS proyecto_asociado
FROM pesco_sbo_pescousd.owor
WHERE status IN ('P', 'R')
ORDER BY docentry DESC;

-- 2. Pedidos de Clientes Abiertos
SELECT 
    docentry,
    docnum AS pedido_numero,
    cardcode AS cliente_codigo,
    cardname AS cliente_nombre,
    docdate AS fecha_pedido,
    doctotal AS total_pedido
FROM pesco_sbo_pescousd.ordr
WHERE docstatus = 'O'
ORDER BY docentry DESC;

-- =============================================
-- CONSULTA SQL #12
-- =============================================
SELECT 
    'PC' AS tipo_documento,
    CAST(t0.docnum AS VARCHAR) AS doc_numero,
    t0.cardcode AS cliente_codigo,
    t0.cardname AS cliente_nombre,
    t0.docdate AS fecha_documento,
    COALESCE(t1.project, '') AS proyecto_codigo,
    t1.itemcode AS item_code,
    t1.dscription AS item_name,
    t1.quantity AS cantidad_pedida,
    t1.openqty AS cantidad_pendiente,
    t1.whscode AS almacen_destino
FROM pesco_sbo_pescousd.ordr t0
INNER JOIN pesco_sbo_pescousd.rdr1 t1 
    ON t0.docentry = t1.docentry
WHERE t0.docstatus = 'O'       -- Pedido Abierto en Cabecera
  AND t1.linestatus = 'O'      -- Línea Abierta pendiente
  AND t1.itemcode IS NOT NULL
  AND t1.itemcode <> ''
ORDER BY t0.docnum DESC, t1.linenum ASC;

-- =============================================
-- CONSULTA SQL #13
-- =============================================
SELECT 
    'OF' AS tipo_documento,
    CAST(t0.docnum AS VARCHAR) AS doc_numero,
    '' AS cliente_codigo,
    CONCAT('Fabricación: ', t0.itemcode) AS cliente_nombre,
    t0.postdate AS fecha_documento,
    COALESCE(t0.u_proyecto, '') AS proyecto_codigo,
    t1.itemcode AS item_code,
    '' AS item_name,
    t1.plannedqty AS cantidad_pedida,
    (t1.plannedqty - t1.issuedqty) AS cantidad_pendiente,
    t1.warenhouse AS almacen_destino
FROM pesco_sbo_pescousd.owor t0
INNER JOIN pesco_sbo_pescousd.wor1 t1 
    ON t0.docentry = t1.docentry
WHERE t0.status IN ('P', 'R')  -- Planificada o Liberada
  AND t1.itemcode IS NOT NULL
  AND t1.itemcode <> ''
  AND (t1.plannedqty - t1.issuedqty) > 0
ORDER BY t0.docnum DESC;

-- =============================================
-- CONSULTA SQL #14
-- =============================================
SELECT 
    -- 1. DATOS DE LA SOLICITUD DE COMPRA (SC ORIGEN)
    PRQ.[DocEntry]                          AS [DocEntry SC],
    PRQ.[DocNum]                            AS [Nro SC SAP],
    CONVERT(VARCHAR(10), PRQ.[DocDate], 103) AS [Fec. Solicitud],
    ISNULL(PRQ.[ReqName], USR_PRQ.[U_NAME]) AS [Solicitante],
    USR_PRQ.[U_NAME]                        AS [Digitador SC],

    -- 2. ARTÍCULO Y CENTROS DE COSTO
    PRQ_L.[ItemCode]                        AS [Codi
<truncated 3310 bytes>
pDate], OC.[DocDueDate])) <= 3 AND ISNULL(OC_L.[OpenQty], 1) > 0 THEN 'AMARILLO (Urgente)'
        WHEN OC.[DocNum] IS NOT NULL AND DATEDIFF(DAY, GETDATE(), ISNULL(OC_L.[ShipDate], OC.[DocDueDate])) <= 7 AND ISNULL(OC_L.[OpenQty], 1) > 0 THEN 'AMARILLO (Próxima)'
        WHEN OC.[DocNum] IS NOT NULL THEN 'VERDE (En Plazo)'
        ELSE 'AZUL (En Cotización)'
    END AS [Semaforo Entrega]

FROM OPRQ PRQ
-- Líneas de la Solicitud de Compra
INNER JOIN PRQ1 PRQ_L ON PRQ.[DocEntry] = PRQ_L.[DocEntry]
LEFT JOIN OUSR USR_PRQ ON PRQ.[UserSign] = USR_PRQ.[USERID]

-- Trazabilidad hacia Líneas de Orden de Compra (BaseType = 147 es Solicitud de Compra)
LEFT JOIN POR1 OC_L ON OC_L.[BaseType] = 147 
                   AND OC_L.[BaseEntry] = PRQ_L.[DocEntry] 
                   AND OC_L.[BaseLine] = PRQ_L.[LineNum]
LEFT JOIN OPOR OC ON OC_L.[DocEntry] = OC.[DocEntry]
LEFT JOIN OUSR USR_OC ON OC.[UserSign] = USR_OC.[USERID]
LEFT JOIN OCRD PROV ON OC.[CardCode] = PROV.[CardCode]

-- Trazabilidad hacia Entrada de Mercancías (BaseType = 22 es Orden de Compra)
LEFT JOIN PDN1 PDN_L ON PDN_L.[BaseType] = 22 
                    AND PDN_L.[BaseEntry] = OC_L.[DocEntry] 
                    AND PDN_L.[BaseLine] = OC_L.[LineNum]
LEFT JOIN OPDN OPDN ON PDN_L.[DocEntry] = OPDN.[DocEntry]
LEFT JOIN OWHS WHS ON ISNULL(PDN_L.[WhsCode], PRQ_L.[WhsCode]) = WHS.[WhsCode]

WHERE 
    -- Filtro de tiempo: por ejemplo últimos 120 días de solicitudes (ajustable según necesidad)
    PRQ.[DocDate] >= DATEADD(DAY, -120, GETDATE())
    AND (OC.[CardCode] IS NULL OR RIGHT(OC.[CardCode], 2) <> 'PE')

ORDER BY 
    PRQ.[DocDate] DESC,
    PRQ.[DocNum] DESC,
    PRQ_L.[LineNum] ASC
FOR BROWSE

-- =============================================
-- CONSULTA SQL #15
-- =============================================
SELECT 
    -- 1. SOLICITUD DE COMPRA (SC ORIGEN)
    prq.docentry                                    AS docentry_sc,
    prq.docnum                                      AS nro_sc_sap,
    CAST(prq.docdate AS DATE)                       AS fec_solicitud,
    COALESCE(prq.reqname, usr_prq.u_name)           AS solicitante,
    usr_prq.u_name                                  AS digitador_sc,

    -- 2. ARTÍCULO Y CENTROS DE COSTO
    prq_l.itemcode                                  AS codigo_articulo,
    prq_l.dscription                              
<truncated 2830 bytes>
 CURRENT_DATE AND COALESCE(oc_l.openqty, 1) > 0 THEN 'ROJO (Atrasada)'
        WHEN oc.docnum IS NOT NULL AND DATE_DIFF('day', CURRENT_DATE, CAST(COALESCE(oc_l.shipdate, oc.docduedate) AS DATE)) <= 3 AND COALESCE(oc_l.openqty, 1) > 0 THEN 'AMARILLO (Urgente)'
        WHEN oc.docnum IS NOT NULL AND DATE_DIFF('day', CURRENT_DATE, CAST(COALESCE(oc_l.shipdate, oc.docduedate) AS DATE)) <= 7 AND COALESCE(oc_l.openqty, 1) > 0 THEN 'AMARILLO (Proxima)'
        WHEN oc.docnum IS NOT NULL THEN 'VERDE (En Plazo)'
        ELSE 'AZUL (En Cotizacion)'
    END AS semaforo_entrega

FROM oprq prq
INNER JOIN prq1 prq_l ON prq.docentry = prq_l.docentry
LEFT JOIN ousr usr_prq ON prq.usersign = usr_prq.userid

-- Cruce a Líneas de Orden de Compra (BaseType = 147 es Solicitud de Compra)
LEFT JOIN por1 oc_l ON oc_l.basetype = 147 
                   AND oc_l.baseentry = prq_l.docentry 
                   AND oc_l.baseline = prq_l.linenum
LEFT JOIN opor oc ON oc_l.docentry = oc.docentry
LEFT JOIN ousr usr_oc ON oc.usersign = usr_oc.userid
LEFT JOIN ocrd prov ON oc.cardcode = prov.cardcode

-- Cruce a Entrada de Mercancías en Operaciones (BaseType = 22 es Orden de Compra)
LEFT JOIN pdn1 pdn_l ON pdn_l.basetype = 22 
                    AND pdn_l.baseentry = oc_l.docentry 
                    AND pdn_l.baseline = oc_l.linenum
LEFT JOIN opdn opdn ON pdn_l.docentry = opdn.docentry
LEFT JOIN owhs whs ON COALESCE(pdn_l.whscode, prq_l.whscode) = whs.whscode

WHERE 
    CAST(prq.docdate AS DATE) >= DATE_ADD('day', -120, CURRENT_DATE)
    AND (oc.cardcode IS NULL OR oc.cardcode NOT LIKE '%PE')

ORDER BY 
    fec_solicitud DESC,
    nro_sc_sap DESC,
    prq_l.linenum ASC

-- =============================================
-- CONSULTA SQL #16
-- =============================================
SELECT table_schema, table_name 
FROM information_schema.tables 
WHERE lower(table_name) LIKE '%por%' 
   OR lower(table_name) LIKE '%prq%' 
   OR lower(table_name) LIKE '%pdn%'
   OR lower(table_name) LIKE '%ordr%'
ORDER BY table_schema, table_name;

-- =============================================
-- CONSULTA SQL #17
-- =============================================
SELECT 
    -- 1. S
<truncated 179 bytes>
], 103) AS [Fec. Solicitud],
    ISNULL(PRQ.[ReqName], USR_PRQ.[U_NAME]) AS [Solicitante],
    PRQ_L.[ItemCode]                        AS [Codigo],
    PRQ_L.[Dscription]                      AS [Descripcion],
    PRQ_L.[Quantity]                        AS [Cant. Solicitada SC],

    -- 2. ORDEN DE COMPRA
    OC.[DocNum]                             AS [Nro OC SAP],
    CONVERT(VARCHAR(10), OC.[DocDate], 103) AS [Fec. Emision OC],
    OC.[CardName]                           AS [Proveedor],
    CONVERT(VARCHAR(10), ISNULL(OC_L.[ShipDate], OC.[DocDueDate]), 103) AS [Fec. Entrega Comprometida],
    DATEDIFF(DAY, GETDATE(), ISNULL(OC_L.[ShipDate], OC.[DocDueDate]))   AS [Dias para Entrega],
    OC_L.[OpenQty]                          AS [Cant. Pendiente OC],

    -- 3. ENTRADA DE MERCANCÍAS (OPERACIONES)
    OPDN.[DocNum]                           AS [Nro Recepcion Bodega],
    CONVERT(VARCHAR(10), OPDN.[DocDate], 103) AS [Fec. Ingreso Operaciones],
    PDN_L.[Quantity]                        AS [Cant. Recepcionada Bodega],
    WHS.[WhsName]                           AS [Bodega]

FROM OPRQ PRQ
INNER JOIN PRQ1 PRQ_L ON PRQ.[DocEntry] = PRQ_L.[DocEntry]
LEFT JOIN OUSR USR_PRQ ON PRQ.[UserSign] = USR_PRQ.[USERID]

LEFT JOIN POR1 OC_L ON OC_L.[BaseType] = 147 
                   AND OC_L.[BaseEntry] = PRQ_L.[DocEntry] 
                   AND OC_L.[BaseLine] = PRQ_L.[LineNum]
LEFT JOIN OPOR OC ON OC_L.[DocEntry] = OC.[DocEntry]

LEFT JOIN PDN1 PDN_L ON PDN_L.[BaseType] = 22 
                    AND PDN_L.[BaseEntry] = OC_L.[DocEntry] 
                    AND PDN_L.[BaseLine] = OC_L.[LineNum]
LEFT JOIN OPDN OPDN ON PDN_L.[DocEntry] = OPDN.[DocEntry]
LEFT JOIN OWHS WHS ON ISNULL(PDN_L.[WhsCode], PRQ_L.[WhsCode]) = WHS.[WhsCode]

WHERE PRQ.[DocDate] >= DATEADD(DAY, -120, GETDATE())
ORDER BY PRQ.[DocDate] DESC;

-- =============================================
-- CONSULTA SQL #18
-- =============================================
SELECT 
    -- 1. SOLICITUD DE COMPRA (SC ORIGEN)
    prq.docentry                                    AS docentry_sc,
    prq.docnum                                      AS nro_sc_sap,
    substr(cast(prq.docdate as varchar), 1, 10)     AS fec_solicitud,
    coalesce(prq.reqname, '')                       AS solicitante,

    -- 2. ARTÍCULO Y CENTROS DE COSTO
    prq_l.itemcode                                  AS codigo_articulo,
    prq_l.dscription                                AS descripcion_articulo,
    prq_l.quantity                                  AS cant_solicitada_sc,
    prq_l.whscode                                   AS cod_bodega_solicitada,
    prq_l.ocrcode                                   AS area,
    prq_l.ocrcode2                                  AS centro_costo,

    -- 3. ORDEN DE COMPRA (OC) - [NULL si compras aún no la genera]
    oc.docentry                                     AS docentry_oc,
    oc.docnum                                       AS nro_oc_sap,
    substr(cast(oc.docdate as varchar), 1, 10)      AS fec_emision_oc,
    oc.cardcode                                     AS cod_proveedor,
    oc.cardname                                     AS razon_social_proveedor,

    -- Fechas de Entrega y Métricas de la OC
    substr(cast
<truncated 1672 bytes>
  CASE
        WHEN oc.docnum IS NOT NULL AND date(substr(cast(coalesce(oc_l.shipdate, oc.docduedate) as varchar), 1, 10)) < current_date AND coalesce(oc_l.openqty, 1) > 0 THEN 'ROJO (Atrasada)'
        WHEN oc.docnum IS NOT NULL AND date_diff('day', current_date, date(substr(cast(coalesce(oc_l.shipdate, oc.docduedate) as varchar), 1, 10))) <= 3 AND coalesce(oc_l.openqty, 1) > 0 THEN 'AMARILLO (Urgente)'
        WHEN oc.docnum IS NOT NULL AND date_diff('day', current_date, date(substr(cast(coalesce(oc_l.shipdate, oc.docduedate) as varchar), 1, 10))) <= 7 AND coalesce(oc_l.openqty, 1) > 0 THEN 'AMARILLO (Proxima)'
        WHEN oc.docnum IS NOT NULL THEN 'VERDE (En Plazo)'
        ELSE 'AZUL (En Cotizacion)'
    END AS semaforo_entrega

FROM pesco_sbo_pescousd.oprq prq
INNER JOIN pesco_sbo_pescousd.prq1 prq_l 
    ON prq.docentry = prq_l.docentry

-- Cruce nativo a Orden de Compra (BaseType = 147 es Solicitud de Compra)
LEFT JOIN pesco_sbo_pescousd.por1 oc_l 
    ON oc_l.basetype = 147 
   AND oc_l.baseentry = prq_l.docentry 
   AND oc_l.baseline = prq_l.linenum
LEFT JOIN pesco_sbo_pescousd.opor oc 
    ON oc_l.docentry = oc.docentry

-- Cruce nativo a Entrada de Mercancías (BaseType = 22 es Orden de Compra)
LEFT JOIN pesco_sbo_pescousd.pdn1 pdn_l 
    ON pdn_l.basetype = 22 
   AND pdn_l.baseentry = oc_l.docentry 
   AND pdn_l.baseline = oc_l.linenum
LEFT JOIN pesco_sbo_pescousd.opdn opdn 
    ON pdn_l.docentry = opdn.docentry

WHERE 
    substr(cast(prq.docdate as varchar), 1, 10) >= cast(date_add('day', -180, current_date) as varchar)
    AND (oc.cardcode IS NULL OR oc.cardcode NOT LIKE '%PE')

ORDER BY 
    fec_solicitud DESC,
    nro_sc_sap DESC,
    prq_l.linenum ASC
LIMIT 100;

-- =============================================
-- CONSULTA SQL #19
-- =============================================
SELECT docnum, docdate, reqname FROM pesco_sbo_pescousd.oprq LIMIT 5;

-- =============================================
-- CONSULTA SQL #20
-- =============================================
SELECT 
    prq.docentry AS docentry_sc,
    prq.docnum AS nro_sc_sap,
    substr(cast(prq.docdate AS varchar), 1, 10) AS fec_solicitud,
    coalesce(prq.reqname, '') AS solicitante,
    prq_l.itemcode AS codigo_articulo,
    prq_l.dscription AS descripcion_articulo,
    prq_l.quantity AS cant_solicitada_sc,
    prq_l.whscode AS cod_bodega_solicitada,
    prq_l.ocrcode AS area,
    prq_l.ocrcode2 AS centro_costo,
    oc.docentry AS docentry_oc,
    oc.docnum AS nro_oc_sap,
    substr(cast(oc.docdate AS varchar), 1, 10) AS fec_emision_oc,
    oc.cardcode AS cod_proveedor,
    oc.cardname AS razon_social_proveedor,
    substr(cast(coalesce(oc_l.shipdate, oc.docduedate) AS varchar), 1, 10) AS fec_entrega_comprometida,
    date_diff('day', current_date, date(substr(cast(coalesce(oc_l.shipdate, oc.docduedate) AS varchar), 1, 10))) AS dias_para_entrega,
    oc_l.quan
<truncated 68 bytes>
c_l.currency AS moneda_oc,
    oc_l.price AS precio_unitario,
    opdn.docnum AS nro_entrada_mercancias,
    substr(cast(opdn.docdate AS varchar), 1, 10) AS fec_ingreso_operaciones,
    pdn_l.quantity AS cant_recepcionada_bodega,
    pdn_l.whscode AS bodega_recepcion,
    CASE 
        WHEN pdn_l.docentry IS NOT NULL AND coalesce(oc_l.openqty, 0) = 0 THEN '4. EN BODEGA (Completa)'
        WHEN pdn_l.docentry IS NOT NULL AND coalesce(oc_l.openqty, 0) > 0 THEN '4. EN BODEGA (Parcial)'
        WHEN oc.docnum IS NOT NULL AND date(substr(cast(coalesce(oc_l.shipdate, oc.docduedate) AS varchar), 1, 10)) < current_date THEN '3. EN TRANSITO (Atrasada)'
        WHEN oc.docnum IS NOT NULL THEN '3. EN TRANSITO (En Fecha)'
        WHEN prq.docstatus = 'O' AND oc.docnum IS NULL THEN '2. EN COMPRAS (Sin OC aun)'
        WHEN prq.docstatus = 'C' AND oc.docnum IS NULL THEN 'CANCELADA / CERRADA'
        ELSE 'EN GESTION'
    END AS estado_traza_solicitante
FROM pesco_sbo_pescousd.oprq prq
INNER JOIN pesco_sbo_pescousd.prq1 prq_l 
    ON prq.docentry = prq_l.docentry
LEFT JOIN pesco_sbo_pescousd.por1 oc_l 
    ON cast(oc_l.basetype as varchar) = '147' 
   AND oc_l.baseentry = prq_l.docentry 
   AND oc_l.baseline = prq_l.linenum
LEFT JOIN pesco_sbo_pescousd.opor oc 
    ON oc_l.docentry = oc.docentry
LEFT JOIN pesco_sbo_pescousd.pdn1 pdn_l 
    ON cast(pdn_l.basetype as varchar) = '22' 
   AND pdn_l.baseentry = oc_l.docentry 
   AND pdn_l.baseline = oc_l.linenum
LEFT JOIN pesco_sbo_pescousd.opdn opdn 
    ON pdn_l.docentry = opdn.docentry
WHERE substr(cast(prq.docdate AS varchar), 1, 10) >= cast(date_add('day', -180, current_date) AS varchar)
ORDER BY fec_solicitud DESC, nro_sc_sap DESC
LIMIT 50;

-- =============================================
-- CONSULTA SQL #21
-- =============================================
SELECT 
    -- 1. SOLICITUD DE COMPRA (SC)
    prq.docentry AS docentry_sc,
    prq.docnum AS nro_sc_sap,
    substr(cast(prq.docdate AS varchar), 1, 10) AS fec_solicitud,
    coalesce(prq.reqname, 'No especificado') AS solicitante,
    prq_l.ocrcode AS area,
    prq_l.ocrcode2 AS centro_costo,
    prq_l.whscode AS bodega_solicitada,

    -- 2. ARTÍCULO
    prq_l.itemcode AS codigo_articulo,
    prq_l.dscription AS descripcion_articulo,
    prq_l.quantity AS cant_solicitada_sc,

    -- 3. ORDEN DE COMPRA (OC)
    oc.docentry AS docentry_oc,
    oc.docnum AS nro_oc_sap,
    substr(cast(oc.docdate AS varchar), 1, 10) AS fec_emision_oc,
    oc.cardcode AS cod_proveedor,
    oc.cardname AS razon_social_proveedor,
    substr(cast(coalesce(oc_l.shipdate, oc.docduedate) AS varchar), 1, 10) AS fec_entrega_comprometida,
    oc_l.quantity AS cant_pedida_oc,
    oc_l.openqty AS cant_pendiente_oc,
    oc_l.price AS precio_unitario,
    oc_l.currency AS moneda_oc,

    -- 4. ENTRADA DE MERCANCÍAS EN BODEGA (OPDN)
    opdn.docnum AS nro_entrada_mercancias,
    substr(cast(opdn.docda
<truncated 2126 bytes>
S NOT NULL THEN 'EN TRANSITO (En Fecha)'
        WHEN prq.docstatus = 'O' AND oc.docnum IS NULL THEN 'EN COMPRAS (Sin OC aun)'
        WHEN prq.docstatus = 'C' AND oc.docnum IS NULL THEN 'CANCELADA / CERRADA'
        ELSE 'EN GESTION'
    END AS estado_traza

FROM pesco_sbo_pescousd.oprq prq
INNER JOIN pesco_sbo_pescousd.prq1 prq_l 
    ON prq.docentry = prq_l.docentry

LEFT JOIN pesco_sbo_pescousd.por1 oc_l 
    ON cast(oc_l.basetype as varchar) = '147' 
   AND oc_l.baseentry = prq_l.docentry 
   AND oc_l.baseline = prq_l.linenum
LEFT JOIN pesco_sbo_pescousd.opor oc 
    ON oc_l.docentry = oc.docentry

LEFT JOIN pesco_sbo_pescousd.pdn1 pdn_l 
    ON cast(pdn_l.basetype as varchar) = '22' 
   AND pdn_l.baseentry = oc_l.docentry 
   AND pdn_l.baseline = oc_l.linenum
LEFT JOIN pesco_sbo_pescousd.opdn opdn 
    ON pdn_l.docentry = opdn.docentry

WHERE substr(cast(prq.docdate AS varchar), 1, 4) = '2026'

ORDER BY prq.docdate DESC, prq.docnum DESC;

