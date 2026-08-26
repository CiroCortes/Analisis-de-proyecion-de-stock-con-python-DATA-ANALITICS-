import os
import json
import tempfile
import shutil
import pandas as pd
import numpy as np
from decimal import Decimal
from django.db import transaction
from django.conf import settings
from apps.inventory.models import Category, Warehouse, ProductSKU, InventoryMetric, StockProjection
from apps.inventory.stock_actual_models import StockActual

# ── Configuración Oficial de las 9 Bodegas del Stock Proyectado SAP ──────────
# 4 Bodegas Operativas Santiago + 5 Sucursales Regionales
WAREHOUSE_METADATA = {
    '013-PP':  {
        'name': '013-PP - Pañol Producción Stgo',
        'stock_aliases':  ['Stock 013-PP', '013-PP'],
        'sc_aliases':     ['013-PP.SC', 'SC'],
        'oc_aliases':     ['013-PP.OC-PO', '013-PP.OC - PO', 'OC-PO', 'OC - PO'],
        'pc_aliases':     ['013-PP.Comp.PC', 'Comp.PC'],
        'of_aliases':     ['013-PP.Comp.OF', 'Comp.OF'],
        'today_aliases':  ['013-PP.Disponible Hoy', 'Disponible Hoy'],
        'future_aliases': ['013-PP.Disponible Futuro', 'Disponible Futuro'],
    },
    '013-PS':  {
        'name': '013-PS - Pañol Servicios Stgo',
        'stock_aliases':  ['Stock 013-PS', '013-PS'],
        'sc_aliases':     ['013-PS.SC'],
        'oc_aliases':     ['013-PS.OC-PO', '013-PS.OC - PO'],
        'pc_aliases':     ['013-PS.Comp.PC'],
        'of_aliases':     ['013-PS.Comp.OF'],
        'today_aliases':  ['013-PS.Disponible Hoy'],
        'future_aliases': ['013-PS.Disponible Futuro'],
    },
    '013-07':  {
        'name': '013-07 - Stgo Ambulancia',
        'stock_aliases':  ['Stock 013-07', '013-07'],
        'sc_aliases':     ['013-07.SC'],
        'oc_aliases':     ['013-07.OC-PO', '013-07.OC - PO'],
        'pc_aliases':     ['013-07.Comp.PC'],
        'of_aliases':     ['013-07.Comp.OF'],
        'today_aliases':  ['013-07.Disponible Hoy'],
        'future_aliases': ['013-07.Disponible Futuro'],
    },
    '013-09':  {
        'name': '013-09 - Stgo Semiremolque',
        'stock_aliases':  ['Stock 013-09', '013-09'],
        'sc_aliases':     ['013-09.SC'],
        'oc_aliases':     ['013-09.OC-PO', '013-09.OC - PO'],
        'pc_aliases':     ['013-09.Comp.PC'],
        'of_aliases':     ['013-09.Comp.OF'],
        'today_aliases':  ['013-09.Disponible Hoy'],
        'future_aliases': ['013-09.Disponible Futuro'],
    },
    '002-02':  {
        'name': '002-02 - Sucursal Antofagasta',
        'stock_aliases':  ['Stock Antofagasta', 'Stock 002-02', '002-02'],
        'sc_aliases':     ['002-02.SC'],
        'oc_aliases':     ['002-02.OC-PO', '002-02.OC - PO'],
        'pc_aliases':     ['002-02.Comp.PC'],
        'of_aliases':     ['002-02.Comp.OF'],
        'today_aliases':  ['002-02.Disponible Hoy'],
        'future_aliases': ['002-02.Disponible Futuro'],
    },
    '002':     {
        'name': '002 - Sucursal Calama',
        'stock_aliases':  ['Stock Calama', 'Stock 002', 'Stock 2', '002', '2'],
        'sc_aliases':     ['002.SC', '2.SC'],
        'oc_aliases':     ['002.OC-PO', '002.OC - PO', '2.OC-PO', '2.OC - PO'],
        'pc_aliases':     ['002.Comp.PC', '2.Comp.PC'],
        'of_aliases':     ['002.Comp.OF', '2.Comp.OF'],
        'today_aliases':  ['002.Disponible Hoy', '2.Disponible Hoy'],
        'future_aliases': ['002.Disponible Futuro', '2.Disponible Futuro'],
    },
    '003':     {
        'name': '003 - Sucursal Copiapó',
        'stock_aliases':  ['Stock Copiapo', 'Stock Copiapó', 'Stock 003', 'Stock 3', '003', '3'],
        'sc_aliases':     ['003.SC', '3.SC'],
        'oc_aliases':     ['003.OC-PO', '003.OC - PO', '3.OC-PO', '3.OC - PO'],
        'pc_aliases':     ['003.Comp.PC', '3.Comp.PC'],
        'of_aliases':     ['003.Comp.OF', '3.Comp.OF'],
        'today_aliases':  ['003.Disponible Hoy', '3.Disponible Hoy'],
        'future_aliases': ['003.Disponible Futuro', '3.Disponible Futuro'],
    },
    '008':     {
        'name': '008 - Sucursal Los Ángeles',
        'stock_aliases':  ['Stock Los Angeles', 'Stock Los Ángeles', 'Stock 008', 'Stock 8', '008', '8'],
        'sc_aliases':     ['008.SC', '8.SC'],
        'oc_aliases':     ['008.OC-PO', '008.OC - PO', '8.OC-PO', '8.OC - PO'],
        'pc_aliases':     ['008.Comp.PC', '8.Comp.PC'],
        'of_aliases':     ['008.Comp.OF', '8.Comp.OF'],
        'today_aliases':  ['008.Disponible Hoy', '8.Disponible Hoy'],
        'future_aliases': ['008.Disponible Futuro', '8.Disponible Futuro'],
    },
    '010':     {
        'name': '010 - Sucursal Puerto Montt',
        'stock_aliases':  ['Stock Puerto Montt', 'Stock Pto Montt', 'Stock 010', 'Stock 10', '010', '10'],
        'sc_aliases':     ['010.SC', '10.SC'],
        'oc_aliases':     ['010.OC-PO', '010.OC - PO', '10.OC-PO', '10.OC - PO'],
        'pc_aliases':     ['010.Comp.PC', '10.Comp.PC'],
        'of_aliases':     ['010.Comp.OF', '10.Comp.OF'],
        'today_aliases':  ['010.Disponible Hoy', '10.Disponible Hoy'],
        'future_aliases': ['010.Disponible Futuro', '10.Disponible Futuro'],
    },
}
ALLOWED_WAREHOUSES = list(WAREHOUSE_METADATA.keys())

TRANSIT_WAREHOUSE_PREFIX = 'T'


def update_progress_tracker(current, total, status="processing"):
    percent = round((current / total) * 100, 1) if total > 0 else 0
    progress_data = {"current": current, "total": total, "percent": percent, "status": status}
    interval = max(100, int(total * 0.05))
    if current % interval == 0 or current == total or current == 0:
        print(f"[BULK ETL PESCO] Ingestados: {current}/{total} ({percent}%)", flush=True)
    try:
        progress_file = os.path.join(settings.MEDIA_ROOT, "upload_progress.json")
        os.makedirs(settings.MEDIA_ROOT, exist_ok=True)
        with open(progress_file, "w") as f:
            json.dump(progress_data, f)
    except Exception:
        pass


def _read_excel_safe(file_path_or_buffer):
    """Lee Excel manejando bloqueos de archivo de Windows/OneDrive."""
    if isinstance(file_path_or_buffer, str) and os.path.exists(file_path_or_buffer):
        try:
            return pd.read_excel(file_path_or_buffer)
        except PermissionError:
            temp_path = os.path.join(tempfile.gettempdir(), "temp_stock_ingest.xlsx")
            shutil.copyfile(file_path_or_buffer, temp_path)
            df = pd.read_excel(temp_path)
            try:
                os.remove(temp_path)
            except Exception:
                pass
            return df
    return pd.read_excel(file_path_or_buffer)


def get_num_val_tuple(row_tuple, idx):
    if idx is not None and idx < len(row_tuple):
        val = row_tuple[idx]
        try:
            if pd.isna(val):
                return 0
            return int(float(val))
        except (ValueError, TypeError):
            return 0
    return 0


def parse_and_ingest_excel(file_path_or_buffer):
    """
    Ingesta ultra-rápida multi-bodega con itertuples() y bulk_create.
    Extrae pipeline de supply y demanda específica por cada una de las 9 bodegas.
    """
    df = _read_excel_safe(file_path_or_buffer)

    df_clean = df.copy()
    for col in df_clean.columns:
        if df_clean[col].dtype == object or str(df_clean[col].dtype).startswith('string'):
            df_clean[col] = df_clean[col].fillna('')
        else:
            df_clean[col] = df_clean[col].fillna(0)

    # ── Crear/recuperar bodegas con nombres descriptivos ──────────────────────
    warehouse_objs = {}
    for wh_code in ALLOWED_WAREHOUSES:
        meta = WAREHOUSE_METADATA.get(wh_code, {})
        wh_name = meta.get('name', f'Bodega {wh_code}')
        wh_obj, created = Warehouse.objects.get_or_create(
            code=wh_code,
            defaults={'name': wh_name, 'is_active': True}
        )
        if not created and wh_obj.name != wh_name and meta.get('name'):
            wh_obj.name = wh_name
            wh_obj.save(update_fields=['name'])
        warehouse_objs[wh_code] = wh_obj

    # ── Mapeo de índices de columnas ─────────────────────────────────────────
    columns = list(df_clean.columns)
    col_indices = {str(col).strip(): idx for idx, col in enumerate(columns)}

    sku_col_idx     = col_indices.get('Codigo', col_indices.get('Código', 0))
    desc_col_idx    = col_indices.get('Nombre', col_indices.get('Descripcion', 1))
    grupo_col_idx   = col_indices.get('Grupo Articulo')
    rop_sap_idx     = col_indices.get('Punto de Reorden')
    lead_time_idx   = col_indices.get('Lead Time')
    maximo_idx      = col_indices.get('Maximo')
    minimo_idx      = col_indices.get('Minimo')
    stock_total_idx = col_indices.get('Stock Total')

    # Pre-calcular mapeo de columnas para cada bodega
    def find_first_col(aliases):
        for a in aliases:
            if a in col_indices:
                return col_indices[a]
        return None

    wh_column_map = {}
    for wh_code, meta in WAREHOUSE_METADATA.items():
        wh_column_map[wh_code] = {
            'stock':  find_first_col(meta.get('stock_aliases', [])),
            'sc':     find_first_col(meta.get('sc_aliases', [])),
            'oc':     find_first_col(meta.get('oc_aliases', [])),
            'pc':     find_first_col(meta.get('pc_aliases', [])),
            'of':     find_first_col(meta.get('of_aliases', [])),
            'today':  find_first_col(meta.get('today_aliases', [])),
            'future': find_first_col(meta.get('future_aliases', [])),
        }

    # Costo: buscar columnas de precio opcionales
    cost_col_idx = None
    for cname, cidx in col_indices.items():
        c_lower = cname.lower()
        if any(k in c_lower for k in ['costo', 'precio', 'valor unitario', 'unit cost', 'precio$']):
            cost_col_idx = cidx
            break

    # ── Pre-cargar stock físico de StockActual ───
    stock_actual_map = {}
    try:
        for item in StockActual.objects.exclude(bodega__startswith=TRANSIT_WAREHOUSE_PREFIX).values('codigo', 'bodega', 'stock_disponible'):
            c = str(item['codigo']).strip()
            b = str(item['bodega']).strip()
            q = item['stock_disponible'] or 0
            stock_actual_map[(c, b)] = stock_actual_map.get((c, b), 0) + q
            if b == '2': stock_actual_map[(c, '002')] = stock_actual_map.get((c, '002'), 0) + q
            if b == '3': stock_actual_map[(c, '003')] = stock_actual_map.get((c, '003'), 0) + q
            if b == '8': stock_actual_map[(c, '008')] = stock_actual_map.get((c, '008'), 0) + q
            if b == '10': stock_actual_map[(c, '010')] = stock_actual_map.get((c, '010'), 0) + q
            if b == '002-02': stock_actual_map[(c, '002-02')] = stock_actual_map.get((c, '002-02'), 0) + q
    except Exception as e:
        print(f"[BULK ETL PESCO] Aviso al leer StockActual: {e}", flush=True)

    # ── Pre-cargar stock de tránsito inter-sucursal (T*) ─────────
    transit_stock_map = {}
    try:
        transit_qs = (
            StockActual.objects
            .filter(bodega__startswith=TRANSIT_WAREHOUSE_PREFIX)
            .values('codigo', 'stock_disponible')
        )
        for row in transit_qs:
            codigo = str(row['codigo']).strip()
            transit_stock_map[codigo] = transit_stock_map.get(codigo, 0) + (row['stock_disponible'] or 0)
    except Exception as e:
        print(f"[BULK ETL PESCO] No se pudo leer transito inter-sucursal: {e}", flush=True)

    total_rows = len(df_clean)
    print(f"\n[BULK ETL PESCO] INICIANDO INGESTA MULTI-BODEGA DE {total_rows} FILAS...", flush=True)
    update_progress_tracker(0, total_rows, "processing")

    # ── Fase 1: Leer todas las filas con itertuples ──────────────────────────
    sku_row_map = {}

    for row in df_clean.itertuples(index=False, name=None):
        raw_code = str(row[sku_col_idx]).strip() if sku_col_idx < len(row) else ''
        if not raw_code or raw_code == '0' or raw_code.lower() == 'nan':
            continue

        desc     = str(row[desc_col_idx]).strip()[:250] if desc_col_idx is not None and desc_col_idx < len(row) else f'SKU {raw_code}'
        grupo    = str(row[grupo_col_idx]).strip()[:100] if grupo_col_idx is not None and grupo_col_idx < len(row) else 'General'
        rop_sap  = get_num_val_tuple(row, rop_sap_idx)
        lead_t   = get_num_val_tuple(row, lead_time_idx) or 30
        maximo   = get_num_val_tuple(row, maximo_idx)
        minimo   = get_num_val_tuple(row, minimo_idx)
        stk_tot  = get_num_val_tuple(row, stock_total_idx)
        cost_usd = 0.0
        if cost_col_idx is not None and cost_col_idx < len(row):
            try:
                cost_usd = max(0.0, float(row[cost_col_idx]))
            except (ValueError, TypeError):
                cost_usd = 0.0

        sku_row_map[raw_code] = (desc, grupo, rop_sap, lead_t, maximo, minimo, stk_tot, cost_usd, row)

    # ── Fase 2: Upsert de Categorías por Grupo ───────────────────────────────
    grupos_unicos = {data[1] for data in sku_row_map.values() if data[1] and data[1] != 'General'}
    category_map = {}
    for grupo in grupos_unicos:
        cat, _ = Category.objects.get_or_create(
            code=f'GRP-{grupo[:80]}',
            defaults={'name': grupo, 'gerencia': 'Gerencia Repuestos PESCO'}
        )
        category_map[grupo] = cat
    cat_general, _ = Category.objects.get_or_create(
        code='CAT-GENERAL',
        defaults={'name': 'Repuestos Generales', 'gerencia': 'Gerencia Repuestos PESCO'}
    )

    # ── Fase 3: Upsert masivo de SKUs ────────────────────────────────────────
    existing_products = {p.code: p for p in ProductSKU.objects.filter(code__in=sku_row_map.keys())}
    products_to_create = []
    products_to_update = []

    for code, (desc, grupo, rop_sap, lead_t, maximo, minimo, stk_tot, cost_usd, _) in sku_row_map.items():
        cat = category_map.get(grupo, cat_general)
        existing = existing_products.get(code)
        final_cost = Decimal(str(cost_usd)) if cost_usd > 0 else (existing.unit_cost_usd if existing else Decimal('0'))

        p = ProductSKU(
            code=code,
            description=desc,
            category=cat,
            unit_cost_usd=final_cost,
            lead_time_days=int(lead_t) if lead_t > 0 else 30,
            is_active=True
        )
        if existing:
            products_to_update.append(p)
        else:
            products_to_create.append(p)

    with transaction.atomic():
        if products_to_create:
            ProductSKU.objects.bulk_create(products_to_create, batch_size=5000, ignore_conflicts=True)
        if products_to_update:
            ProductSKU.objects.bulk_update(
                products_to_update,
                ['description', 'category', 'unit_cost_usd', 'lead_time_days'],
                batch_size=5000
            )

    all_products = {p.code: p for p in ProductSKU.objects.filter(code__in=sku_row_map.keys())}

    # ── Fase 4: Preparar Métricas y Proyecciones Multi-Bodega ────────────────
    metrics_to_create = []
    projections_to_create = []

    with transaction.atomic():
        InventoryMetric.objects.filter(product__code__in=sku_row_map.keys()).delete()
        StockProjection.objects.filter(product__code__in=sku_row_map.keys()).delete()

    for idx, (code, (desc, grupo, rop_sap, lead_t, maximo, minimo, stk_tot, cost_usd, row)) in enumerate(sku_row_map.items(), start=1):
        product_obj = all_products.get(code)
        if not product_obj:
            continue

        cost_decimal = product_obj.unit_cost_usd

        for wh_code, wh_obj in warehouse_objs.items():
            col_map = wh_column_map.get(wh_code, {})

            # 1. Stock Físico
            stock_physical = get_num_val_tuple(row, col_map['stock'])
            if stock_physical == 0:
                db_stock = stock_actual_map.get((code, wh_code), 0)
                if db_stock > 0:
                    stock_physical = db_stock

            # 2. Pipeline de Compras y Compromisos por bodega
            sc_val          = get_num_val_tuple(row, col_map['sc'])
            oc_po_val       = get_num_val_tuple(row, col_map['oc'])
            comp_pc_val     = get_num_val_tuple(row, col_map['pc'])
            comp_of_val     = get_num_val_tuple(row, col_map['of'])
            disp_today_val  = get_num_val_tuple(row, col_map['today'])

            # 3. Disponible Futuro
            if col_map['future'] is not None:
                final_disp_future = get_num_val_tuple(row, col_map['future'])
            else:
                final_disp_future = stock_physical + sc_val + oc_po_val - comp_pc_val - comp_of_val

            # Si es 013-PP, sumar tránsito inter-sucursal (T*)
            if wh_code == '013-PP':
                stock_transito_inter = transit_stock_map.get(code, 0)
                final_disp_future += stock_transito_inter
            else:
                stock_transito_inter = 0

            metrics_to_create.append(InventoryMetric(
                product=product_obj,
                warehouse=wh_obj,
                stock_physical=stock_physical,
                sc_qty=sc_val,
                oc_po_qty=oc_po_val,
                comp_pc_qty=comp_pc_val,
                comp_of_qty=comp_of_val,
                disp_today=disp_today_val,
                disp_future=final_disp_future,
                stock_transito_inter=stock_transito_inter,
            ))

            # ── Lógica ROP y Sugerido por Bodega ─────────────────────────────
            demand_monthly = comp_pc_val + comp_of_val
            dpd = demand_monthly / 30.0

            if wh_code == '013-PP' and rop_sap > 0:
                rop = rop_sap
                safety_stock = max(0, rop - int(np.ceil(dpd * int(lead_t))))
            elif demand_monthly > 0:
                safety_stock = int(np.ceil(dpd * 7.0))
                rop = int(np.ceil((dpd * int(lead_t)) + safety_stock))
            else:
                rop = 0
                safety_stock = 0

            # ── Quiebre y urgencia ───────────────────────────────────────────
            shortage_units = 0
            suggested_buy  = 0
            urgency        = 'NORMAL'

            if final_disp_future < rop:
                suggested_buy = max(0, rop - final_disp_future)
                if final_disp_future <= 0:
                    urgency        = 'URGENTE'
                    shortage_units = max(0, rop - final_disp_future)
                else:
                    urgency        = 'MEDIO'
                    shortage_units = rop - final_disp_future

            shortage_usd  = Decimal(str(shortage_units)) * cost_decimal
            coverage_days = int(final_disp_future / dpd) if dpd > 0 and final_disp_future > 0 else 0

            projections_to_create.append(StockProjection(
                product=product_obj,
                warehouse=wh_obj,
                rop=rop,
                safety_stock=safety_stock,
                coverage_days=coverage_days,
                shortage_units=shortage_units,
                shortage_usd=shortage_usd,
                suggested_buy_units=suggested_buy,
                urgency_level=urgency,
            ))

        interval = max(100, int(total_rows * 0.05))
        if idx % interval == 0 or idx == len(sku_row_map):
            update_progress_tracker(idx, total_rows, "processing")

    # ── Fase 5: Volcado masivo final ─────────────────────────────────────────
    print("[BULK ETL PESCO] Volcando metricas y proyecciones...", flush=True)
    with transaction.atomic():
        InventoryMetric.objects.bulk_create(metrics_to_create, batch_size=10000)
        StockProjection.objects.bulk_create(projections_to_create, batch_size=10000)

    update_progress_tracker(total_rows, total_rows, "completed")
    print(f"[BULK ETL PESCO] INGESTA MULTI-BODEGA FINALIZADA: {len(sku_row_map)} SKUs | {len(projections_to_create)} registros bodega\n", flush=True)

    return len(sku_row_map)
