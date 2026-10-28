import os
import sys
import datetime
from decimal import Decimal
from collections import defaultdict
from django.db import transaction
from apps.inventory.models import (
    ProductSKU, Category, Warehouse, InventoryMetric,
    ProductionOrderMovement, SalesOrderMovement, StockProjection,
    SKUClassification, GoodsReceipt
)
from apps.inventory.stock_actual_models import StockActual
from apps.data_ingestion.warehouses import (WAREHOUSE_NAMES, commitment_bodega, prebodega_destino, purchase_bodega,
                                            transit_destination)


def _sin_tildes(nombre):
    import unicodedata
    return ''.join(c for c in unicodedata.normalize('NFKD', nombre) if not unicodedata.combining(c)).lower()


def find_data_file(long_name, alt_name, data_dir=None):
    """Devuelve el archivo mas reciente entre el nombre largo (sin importar tildes ni
    mayusculas: 'Stock Fisico por Bodega.txt' vale), el nombre de tabla (oitm.txt) y las
    variantes que genera el task (oitm_oitb.txt, oitw-1793....txt).
    Si no existe ninguno devuelve la ruta del nombre largo (el cargador avisa)."""
    import glob
    if data_dir is None:
        from django.conf import settings
        data_dir = os.path.join(settings.BASE_DIR, 'data')
    stem = alt_name[:-4]
    buscado = _sin_tildes(long_name)
    cands = [os.path.join(data_dir, f) for f in os.listdir(data_dir) if _sin_tildes(f) == buscado] \
        if os.path.isdir(data_dir) else []
    cands += glob.glob(os.path.join(data_dir, glob.escape(stem) + '*.txt'))
    cands = [c for c in cands if os.path.exists(c)]
    if not cands:
        return os.path.join(data_dir, long_name)
    return max(cands, key=os.path.getmtime)


def parse_date(val_str):
    if val_str and len(val_str) >= 10:
        try:
            return datetime.datetime.strptime(val_str[:10], '%Y-%m-%d').date()
        except ValueError:
            return None
    return None


def iter_txt_rows(file_path, min_cols):
    """Filas de un TXT del Datalake (formato tabla con pipes), sin cabecera ni separadores."""
    with open(file_path, 'r', encoding='utf-8', errors='replace') as fp:
        fp.readline()
        fp.readline()
        for line in fp:
            line_str = line.strip()
            if not line_str or line_str.startswith('|---'):
                continue
            cols = _parse_pipe_line(line_str)
            if len(cols) >= min_cols:
                yield cols


def _parse_pipe_line(line):
    """Parsea una línea separada por pipes '|' eliminando el inicio y fin."""
    return [p.strip() for p in line.strip().split('|')[1:-1]]


def _clean_num(val_str, default=0.0):
    """Limpia números con comas de miles (ej: '2,301,711' o '3,386.57')."""
    if not val_str:
        return default
    try:
        cleaned = val_str.replace(',', '').strip()
        return float(cleaned)
    except (ValueError, TypeError):
        return default


def ensure_warehouses():
    """
    Garantiza que existan las bodegas operativas oficiales. Crea las faltantes (activas)
    y no altera el estado activo/inactivo de las existentes.
    """
    for code, name in WAREHOUSE_NAMES.items():
        wh, created = Warehouse.objects.get_or_create(code=code, defaults={'name': name, 'is_active': True})
        if not created and wh.name != name:
            wh.name = name
            wh.save(update_fields=['name'])


def ingest_datalake_maestro(file_path):
    """
    Ingesta o actualiza el catálogo maestro de SKUs desde el archivo TXT de Athena.
    Columnas: codigo_sku, descripcion, costo_unitario_usd, lead_time_dias, clase,
              familia, subfamilia, modelo, categoria_sop, fec_creacion_sap, es_comprable
    """
    print(f"\n[DATALAKE] 1/5 Instando Maestro de Artículos & Costos: {file_path}", flush=True)
    if not os.path.exists(file_path):
        print(f"  [ERROR] Archivo no encontrado: {file_path}", flush=True)
        return 0

    categories_cache = {c.name: c for c in Category.objects.all()}
    existing_products = {p.code: p for p in ProductSKU.objects.all()}

    products_to_create = []
    products_to_update = []
    vistos = set()
    created_cats = 0

    with open(file_path, 'r', encoding='utf-8', errors='replace') as fp:
        h_line = fp.readline()
        sep_line = fp.readline()
        n_cols = max(len(_parse_pipe_line(h_line)), 11)

        for line in fp:
            line_str = line.strip()
            if not line_str or line_str.startswith('|---'):
                continue

            cols = _parse_pipe_line(line_str)
            if len(cols) < n_cols:
                continue

            raw_code = cols[0]
            if not raw_code or raw_code == '0':
                continue

            # Descripciones con pipes '|': la descripcion absorbe las columnas sobrantes
            n_tail = n_cols - 2
            if len(cols) > n_cols:
                desc = '|'.join(cols[1:len(cols) - n_tail])[:250]
                tail = cols[len(cols) - n_tail:]
            else:
                desc = cols[1][:250]
                tail = cols[2:]

            cost_usd = _clean_num(tail[0])
            lead_time = int(_clean_num(tail[1], 30))
            clase = tail[2][:100]
            familia = tail[3][:100]
            subfamilia = tail[4][:100]
            modelo = tail[5][:100]
            sap_cat = tail[6][:100] or 'General Pesco'
            fec_str = tail[7]
            es_comprable = tail[8].upper() == 'Y'
            # Columnas nuevas (opcionales): grupo SAP (oitb) y marcas de inventario
            grp_cod = tail[9][:20] if n_tail > 9 else ''
            grp_nom = tail[10][:150].replace('PA�OL', 'PAÑOL') if n_tail > 10 else ''
            gestiona_inv = tail[11].upper() != 'N' if n_tail > 11 else True
            es_vendible = tail[12].upper() != 'N' if n_tail > 12 else True
            # El grupo SAP (con nombre) es la categoria visible en Configuracion
            cat_name = grp_nom or sap_cat

            # Parse fecha
            fec_creacion = None
            if len(fec_str) >= 10:
                try:
                    fec_creacion = datetime.datetime.strptime(fec_str[:10], '%Y-%m-%d').date()
                except ValueError:
                    pass

            # Cargar o crear categoría
            cat_obj = categories_cache.get(cat_name)
            if not cat_obj and cat_name:
                cat_obj, created = Category.objects.get_or_create(
                    code=f"GRP-{(grp_cod or cat_name)[:80]}" if grp_nom else f"GRP-{cat_name[:80]}",
                    defaults={'name': cat_name, 'gerencia': 'Gerencia Repuestos PESCO'}
                )
                categories_cache[cat_name] = cat_obj
                if created:
                    created_cats += 1

            vistos.add(raw_code)
            cost_dec = Decimal(str(round(cost_usd, 2)))
            existing = existing_products.get(raw_code)

            p = ProductSKU(
                code=raw_code,
                description=desc or f'SKU {raw_code}',
                category=cat_obj,
                unit_cost_usd=cost_dec if cost_dec > 0 else (existing.unit_cost_usd if existing else Decimal('0.00')),
                lead_time_days=lead_time if lead_time > 0 else 30,
                clase=clase,
                familia=familia,
                subfamilia=subfamilia,
                modelo=modelo,
                sap_categoria=sap_cat,
                sap_group_code=grp_cod,
                sap_group_name=grp_nom,
                gestiona_inventario=gestiona_inv,
                es_vendible=es_vendible,
                fec_creacion_sap=fec_creacion or (existing.fec_creacion_sap if existing else None),
                is_active=gestiona_inv  # servicios/gastos (invntitem = 'N') quedan fuera del S&OP
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
                ['description', 'category', 'unit_cost_usd', 'lead_time_days', 'clase',
                 'familia', 'subfamilia', 'modelo', 'sap_categoria', 'sap_group_code', 'sap_group_name',
                 'gestiona_inventario', 'es_vendible', 'fec_creacion_sap', 'is_active'],
                batch_size=5000
            )

    # Categorias nuevas reciben tipo y estado recomendado; se retiran las que quedaron sin SKUs
    from apps.inventory.group_types import assign_group_types
    # El codigo de categoria pasa a ser el codigo de grupo SAP (GRP-101); asi se ve y se ordena como en SAP
    for cat in Category.objects.all():
        sap_cod = (ProductSKU.objects.filter(category=cat).exclude(sap_group_code='')
                   .values_list('sap_group_code', flat=True).first())
        nuevo_code = f"GRP-{sap_cod}" if sap_cod else None
        if nuevo_code and cat.code != nuevo_code and not Category.objects.filter(code=nuevo_code).exists():
            cat.code = nuevo_code
            cat.save(update_fields=['code'])
    # El maestro solo trae SKUs vigentes (frozenfor = 'N'): lo que no viene queda inactivo
    obsoletos = ProductSKU.objects.exclude(code__in=vistos).filter(is_active=True).update(is_active=False)
    nuevos_tipos = assign_group_types()
    vacias, _ = Category.objects.filter(productsku__isnull=True).delete()
    print(f"  [OK] Grupos SAP clasificados: {nuevos_tipos}; grupos sin SKUs retirados: {vacias}; SKUs fuera del maestro desactivados: {obsoletos}.", flush=True)

    total_skus = len(products_to_create) + len(products_to_update)
    print(f"  [OK] Maestro actualizado: {len(products_to_create)} creados, {len(products_to_update)} actualizados.", flush=True)
    return total_skus


def ingest_datalake_stock_fisico(file_path):
    """
    Ingesta el stock físico y disponible por bodega desde Stock Físico por Bodega.txt.
    Actualiza StockActual (todas las bodegas y tránsitos T*) y la tabla InventoryMetric.
    """
    print(f"\n[DATALAKE] 2/5 Instando Stock Físico por Bodega: {file_path}", flush=True)
    if not os.path.exists(file_path):
        print(f"  [ERROR] Archivo no encontrado: {file_path}", flush=True)
        return 0

    all_skus = set(ProductSKU.objects.values_list('code', flat=True))
    warehouses_db = {w.code: w for w in Warehouse.objects.all()}

    # Guardar en StockActual (visión global de las 63 bodegas)
    stock_actual_objs = []
    # Mapeo temporal para InventoryMetric (solo bodegas operativas)
    # (sku, wh_code) -> {stock: X, comp: Y, onorder: Z}
    metrics_map = defaultdict(lambda: {'stock': 0, 'comp': 0, 'onorder': 0})
    transito_inter = defaultdict(int)  # (sku, bodega destino) -> unidades en camino

    with open(file_path, 'r', encoding='utf-8', errors='replace') as fp:
        fp.readline()
        fp.readline()

        for line in fp:
            line_str = line.strip()
            if not line_str or line_str.startswith('|---'):
                continue

            cols = _parse_pipe_line(line_str)
            if len(cols) < 5:
                continue

            sku = cols[0]
            wh_code = cols[1]
            stk_fis = int(_clean_num(cols[2]))
            comp = int(_clean_num(cols[3]))
            onorder = int(_clean_num(cols[4]))

            # Bodegas de transito T<origen>-<destino>: lo que hay (o esta solicitado) va en camino
            # al destino y se suma a su disponible futuro. La 013 a secas se excluye de los calculos.
            dest = transit_destination(wh_code)
            if dest:
                transito_inter[(sku, dest)] += stk_fis + onorder
            # Pre-bodegas (SPEC-22 §2): su stock va en camino al destino; lo pedido ya viene
            # en las lineas de OC, que purchase_bodega acredita al mismo destino
            pre = prebodega_destino(wh_code)
            if pre and stk_fis > 0:
                transito_inter[(sku, pre)] += stk_fis

            # Objeto StockActual
            stock_actual_objs.append(StockActual(
                codigo=sku,
                bodega=wh_code,
                bodega_nombre=f"Bodega {wh_code}",
                stock_disponible=stk_fis,
                stock_reservado=comp,
            ))

            # Si la bodega está registrada en el motor S&OP
            if wh_code in warehouses_db and sku in all_skus:
                metrics_map[(sku, wh_code)]['stock'] += stk_fis
                metrics_map[(sku, wh_code)]['comp'] += comp
                metrics_map[(sku, wh_code)]['onorder'] += onorder

    # Actualizar StockActual masivamente
    with transaction.atomic():
        StockActual.objects.all().delete()
        StockActual.objects.bulk_create(stock_actual_objs, batch_size=5000)

    print(f"  [OK] StockActual registrado: {len(stock_actual_objs)} registros en 63 bodegas SAP.", flush=True)
    return metrics_map, transito_inter


def ingest_datalake_ofs(file_path):
    """
    Ingesta Órdenes de Fabricación (OF).
    - Cerradas (Status L): se guardan en ProductionOrderMovement (historial de consumo real de taller).
    - Abiertas (Status P, R): se totalizan como compromisos de OF activos por bodega.
    """
    print(f"\n[DATALAKE] 3/5 Instando Órdenes de Fabricación (OF): {file_path}", flush=True)
    if not os.path.exists(file_path):
        print(f"  [ERROR] Archivo no encontrado: {file_path}", flush=True)
        return {}

    all_skus = set(ProductSKU.objects.values_list('code', flat=True))
    of_movements_to_create = []
    comp_of_by_sku_wh = defaultdict(int)

    with open(file_path, 'r', encoding='utf-8', errors='replace') as fp:
        fp.readline()
        fp.readline()

        for line in fp:
            line_str = line.strip()
            if not line_str or line_str.startswith('|---'):
                continue

            cols = _parse_pipe_line(line_str)
            if len(cols) < 9:
                continue

            of_num = cols[0].replace(',', '')
            sku = cols[1]
            wh_code = commitment_bodega(cols[2] or '013-PP')  # 013 (posteo Santiago) -> 013-PP
            estado = cols[3]
            f_crea_str = cols[4]
            f_end_str = cols[5]
            plan_qty = _clean_num(cols[6])
            real_qty = _clean_num(cols[7])
            pend_qty = _clean_num(cols[8])

            if sku not in all_skus:
                continue

            f_crea = None
            if len(f_crea_str) >= 10:
                try:
                    f_crea = datetime.datetime.strptime(f_crea_str[:10], '%Y-%m-%d').date()
                except ValueError:
                    pass

            f_end = None
            if len(f_end_str) >= 10:
                try:
                    f_end = datetime.datetime.strptime(f_end_str[:10], '%Y-%m-%d').date()
                except ValueError:
                    pass

            # OFs Cerradas (L) -> Historial de consumo
            if estado == 'L':
                if real_qty > 0 or plan_qty > 0:
                    of_movements_to_create.append(ProductionOrderMovement(
                        of_number=of_num,
                        product_id=sku,
                        quantity_delivered=Decimal(str(round(real_qty if real_qty > 0 else plan_qty, 2))),
                        warehouse=wh_code,
                        start_date=f_crea,
                        end_date=f_end or f_crea,
                        status='Cerrada'
                    ))
            # OFs Abiertas (P o R) -> Compromisos activos
            elif estado in ('P', 'R') and pend_qty > 0:
                comp_of_by_sku_wh[(sku, wh_code)] += int(round(pend_qty))

    with transaction.atomic():
        ProductionOrderMovement.objects.all().delete()
        ProductionOrderMovement.objects.bulk_create(of_movements_to_create, batch_size=5000)

    print(f"  [OK] Movimientos OF Cerradas guardados: {len(of_movements_to_create)}.", flush=True)
    print(f"  [OK] Compromisos OF Abiertas mapeados: {len(comp_of_by_sku_wh)} combinaciones SKU-Bodega.", flush=True)
    return comp_of_by_sku_wh


def ingest_datalake_pedidos(file_path):
    """
    Ingesta Pedidos de Clientes (PC).
    - Cerrados (Status C): se guardan en SalesOrderMovement (historial de salidas a clientes).
    - Abiertos (Status O): se totalizan como compromisos de PC activos por bodega.
    """
    print(f"\n[DATALAKE] 4/5 Instando Pedidos de Clientes (PC): {file_path}", flush=True)
    if not os.path.exists(file_path):
        print(f"  [ERROR] Archivo no encontrado: {file_path}", flush=True)
        return {}

    all_skus = set(ProductSKU.objects.values_list('code', flat=True))
    sales_movements_to_create = []
    comp_pc_by_sku_wh = defaultdict(int)

    with open(file_path, 'r', encoding='utf-8', errors='replace') as fp:
        fp.readline()
        fp.readline()

        for line in fp:
            line_str = line.strip()
            if not line_str or line_str.startswith('|---'):
                continue

            cols = _parse_pipe_line(line_str)
            if len(cols) < 10:
                continue

            ped_num = cols[0].replace(',', '')
            sku = cols[1]
            wh_code = commitment_bodega(cols[2] or '013')  # 013 (posteo Santiago) -> 013-PP
            cliente_cod = cols[3]
            cliente_nom = cols[4][:200]
            estado = cols[5]
            f_emi_str = cols[6]
            f_ent_str = cols[7]
            sol_qty = _clean_num(cols[8])
            pend_qty = _clean_num(cols[9])

            if sku not in all_skus:
                continue

            f_emi = None
            if len(f_emi_str) >= 10:
                try:
                    f_emi = datetime.datetime.strptime(f_emi_str[:10], '%Y-%m-%d').date()
                except ValueError:
                    pass

            f_ent = None
            if len(f_ent_str) >= 10:
                try:
                    f_ent = datetime.datetime.strptime(f_ent_str[:10], '%Y-%m-%d').date()
                except ValueError:
                    pass

            # Pedidos Cerrados (C) -> Demanda real histórica
            if estado == 'C':
                if sol_qty > 0:
                    sales_movements_to_create.append(SalesOrderMovement(
                        order_number=ped_num,
                        product_id=sku,
                        quantity=Decimal(str(round(sol_qty, 2))),
                        warehouse=wh_code,
                        emission_date=f_emi,
                        delivery_date=f_ent or f_emi,
                        status='Cerrado',
                        client_name=cliente_nom or 'Cliente Directo'
                    ))
            # Pedidos Abiertos (O) -> Compromisos comerciales activos
            elif estado == 'O' and pend_qty > 0:
                comp_pc_by_sku_wh[(sku, wh_code)] += int(round(pend_qty))

    with transaction.atomic():
        SalesOrderMovement.objects.all().delete()
        SalesOrderMovement.objects.bulk_create(sales_movements_to_create, batch_size=5000)

    print(f"  [OK] Movimientos PC Cerrados guardados: {len(sales_movements_to_create)}.", flush=True)
    print(f"  [OK] Compromisos PC Abiertos mapeados: {len(comp_pc_by_sku_wh)} combinaciones SKU-Bodega.", flush=True)
    return comp_pc_by_sku_wh


def ingest_datalake_ocs(file_path):
    """
    Ingesta Órdenes de Compra en Tránsito (OC).
    Totaliza las unidades en camino a cada bodega.
    """
    print(f"\n[DATALAKE] 5/5 Instando Órdenes de Compra en Tránsito (OC): {file_path}", flush=True)
    if not os.path.exists(file_path):
        print(f"  [ERROR] Archivo no encontrado: {file_path}", flush=True)
        return {}

    all_skus = set(ProductSKU.objects.values_list('code', flat=True))
    oc_transito_by_sku_wh = defaultdict(int)

    with open(file_path, 'r', encoding='utf-8', errors='replace') as fp:
        fp.readline()
        fp.readline()

        for line in fp:
            line_str = line.strip()
            if not line_str or line_str.startswith('|---'):
                continue

            cols = _parse_pipe_line(line_str)
            if len(cols) < 9:
                continue

            wh_code = purchase_bodega(cols[1])
            sku = cols[2]
            cant_transito = _clean_num(cols[8])

            if sku in all_skus and cant_transito > 0:
                oc_transito_by_sku_wh[(sku, wh_code)] += int(round(cant_transito))

    print(f"  [OK] OC en Tránsito mapeadas: {len(oc_transito_by_sku_wh)} combinaciones SKU-Bodega.", flush=True)
    return oc_transito_by_sku_wh


def ingest_datalake_scs(file_path):
    """
    Ingesta Solicitudes de Compra (SC) abiertas, aun sin OC.
    Columnas: nro_sc_sap, bodega_solicitada, codigo_sku, fecha_solicitud,
              cantidad_solicitada, cantidad_pendiente_sc
    Si el archivo no existe devuelve {} (SC = 0) y lo informa.
    """
    print(f"\n[DATALAKE] Solicitudes de Compra (SC) abiertas: {file_path}", flush=True)
    if not os.path.exists(file_path):
        print("  [AVISO] Archivo de SC no encontrado: SC = 0 en el Disponible Futuro. "
              "Ejecutar la consulta 6 de consultas_datalake.sql.", flush=True)
        return {}

    all_skus = set(ProductSKU.objects.values_list('code', flat=True))
    sc_by_sku_wh = defaultdict(int)

    with open(file_path, 'r', encoding='utf-8', errors='replace') as fp:
        fp.readline()
        fp.readline()

        for line in fp:
            line_str = line.strip()
            if not line_str or line_str.startswith('|---'):
                continue

            cols = _parse_pipe_line(line_str)
            if len(cols) < 6:
                continue

            wh_code = purchase_bodega(cols[1])
            sku = cols[2]
            cant_pendiente = _clean_num(cols[5])

            if sku in all_skus and cant_pendiente > 0:
                sc_by_sku_wh[(sku, wh_code)] += int(round(cant_pendiente))

    print(f"  [OK] SC abiertas mapeadas: {len(sc_by_sku_wh)} combinaciones SKU-Bodega.", flush=True)
    return sc_by_sku_wh


def ingest_datalake_entradas(file_path):
    """
    Ingesta Entradas de Mercancias (consulta 7) en GoodsReceipt: ingresos del dashboard e
    inventario historico del detalle de la Calculadora. Reemplaza la carga anterior.
    Columnas: nro_documento, codigo_sku, fecha_contabilizacion, codigo_proveedor,
              nombre_proveedor, cantidad, total_linea
    Si el archivo no existe se conservan las entradas ya cargadas.
    """
    print(f"\n[DATALAKE] Entradas de Mercancias: {file_path}", flush=True)
    if not os.path.exists(file_path):
        print("  [AVISO] Archivo de entradas no encontrado: se conservan las ya cargadas. "
              "Ejecutar la consulta 7 de consultas_datalake.sql.", flush=True)
        return 0

    all_skus = set(ProductSKU.objects.values_list('code', flat=True))
    filas = []
    for cols in iter_txt_rows(file_path, 7):
        sku, cantidad = cols[1], _clean_num(cols[5])
        if sku not in all_skus or cantidad <= 0:
            continue
        filas.append(GoodsReceipt(
            document_number=cols[0].replace(',', ''), product_id=sku, quantity=cantidad,
            posting_date=parse_date(cols[2]), supplier_name=cols[4][:200],
            total_lines_cost=_clean_num(cols[6]),
        ))

    with transaction.atomic():
        GoodsReceipt.objects.all().delete()
        GoodsReceipt.objects.bulk_create(filas, batch_size=5000)
    print(f"  [OK] Entradas de mercancias cargadas: {len(filas)} lineas.", flush=True)
    return len(filas)


def run_full_datalake_pipeline():
    """
    Ejecuta el pipeline completo desde los 5 archivos TXT exportados del Datalake.
    1. Maestro de Artículos
    2. Stock Físico por Bodega
    3. Órdenes de Fabricación
    4. Pedidos de Clientes
    5. Órdenes de Compra en Tránsito (+ SC abiertas, opcional)
    6. Cálculo de InventoryMetric (Disponible Futuro)
    7. Motor de Clasificación S&OP (REPO + DRP Santiago vs Sucursales)
    """
    _find_file = find_data_file

    f_maestro = _find_file('Maestro de Artículos & Costos.txt', 'oitm.txt')
    f_stock   = _find_file('Stock Físico por Bodega.txt', 'oitw.txt')
    f_ofs     = _find_file('Órdenes de Fabricación (OF).txt', 'owor_wor1.txt')
    f_pedidos = _find_file('Pedidos de Clientes (PC).txt', 'ordr_rdr1.txt')
    f_ocs     = _find_file('Órdenes de Compra en Tránsito (OC).txt', 'opor_por1.txt')
    f_scs     = _find_file('Solicitudes de Compra (SC).txt', 'oprq_prq1.txt')
    f_ems     = _find_file('Entradas de Mercancias (EM).txt', 'opdn_pdn1.txt')

    print("=" * 70, flush=True)
    print("[DATALAKE] INICIANDO SINCRONIZACION OFICIAL DESDE DATALAKE PESCO (TXT)", flush=True)
    print("=" * 70, flush=True)

    ensure_warehouses()

    # 1. Maestro
    total_skus = ingest_datalake_maestro(f_maestro)

    # 2. Stock Físico
    metrics_map, transito_inter = ingest_datalake_stock_fisico(f_stock)

    # 3. OFs
    comp_of_map = ingest_datalake_ofs(f_ofs)

    # 4. Pedidos
    comp_pc_map = ingest_datalake_pedidos(f_pedidos)

    # 5. OCs
    oc_transito_map = ingest_datalake_ocs(f_ocs)

    # 5b. SC abiertas
    sc_map = ingest_datalake_scs(f_scs)

    # 5c. Entradas de mercancias (ingresos del dashboard e inventario historico)
    ingest_datalake_entradas(f_ems)

    # 6. Consolidar InventoryMetric para las Bodegas Operativas Activas
    print("\n[DATALAKE] Consolidando métricas de inventario multi-bodega...", flush=True)
    warehouses_db = {w.code: w for w in Warehouse.objects.filter(is_active=True) if w.zone}
    active_skus = set(ProductSKU.objects.values_list('code', flat=True))

    all_keys = set()
    all_keys.update(metrics_map.keys())
    all_keys.update(comp_of_map.keys())
    all_keys.update(comp_pc_map.keys())
    all_keys.update(oc_transito_map.keys())
    all_keys.update(sc_map.keys())
    all_keys.update(transito_inter.keys())

    metrics_to_create = []
    for sku, wh_code in all_keys:
        wh_obj = warehouses_db.get(wh_code)
        if not wh_obj or sku not in active_skus:
            continue

        stk_raw = metrics_map.get((sku, wh_code), {})
        fisico = stk_raw.get('stock', 0)
        
        # Compromisos: preferir el desglose detallado de OF/PC abiertas si existe, o el de SAP
        comp_of = comp_of_map.get((sku, wh_code), 0)
        comp_pc = comp_pc_map.get((sku, wh_code), 0)
        if comp_of == 0 and comp_pc == 0:
            comp_pc = stk_raw.get('comp', 0)

        # Tránsito: preferir el de OCs abiertas o el de SAP
        transito_oc = oc_transito_map.get((sku, wh_code), 0)
        if transito_oc == 0:
            transito_oc = stk_raw.get('onorder', 0)

        sc_qty = sc_map.get((sku, wh_code), 0)

        # Tránsito inter-sucursal (T*): se acredita a la bodega destino
        t_inter = transito_inter.get((sku, wh_code), 0)

        # Disponibilidades
        disp_today = fisico - comp_of - comp_pc
        disp_future = fisico + sc_qty + transito_oc + t_inter - comp_of - comp_pc

        metrics_to_create.append(InventoryMetric(
            product_id=sku,
            warehouse=wh_obj,
            stock_physical=fisico,
            sc_qty=sc_qty,
            oc_po_qty=transito_oc,
            comp_pc_qty=comp_pc,
            comp_of_qty=comp_of,
            disp_today=disp_today,
            disp_future=disp_future,
            stock_transito_inter=t_inter
        ))

    with transaction.atomic():
        InventoryMetric.objects.all().delete()
        InventoryMetric.objects.bulk_create(metrics_to_create, batch_size=5000)

    print(f"  [OK] InventoryMetric consolidado: {len(metrics_to_create)} registros.", flush=True)

    # 7-8. Motor anterior (escenario actual de los indicadores) + Calculadora de Compras, que
    #      carga sus datos y publica encima (SPEC-19 §2)
    print("\n[DATALAKE] Ejecutando motor anterior y Calculadora de Compras...", flush=True)
    from apps.calculadora.servicio import recalcular_red
    corrida = recalcular_red(recargar=True)
    print(f"  [OK] Corrida {corrida.pk}: {corrida.resumen}", flush=True)

    print("\n" + "=" * 70, flush=True)
    print("[DATALAKE] SINCRONIZACION COMPLETADA CON EXITO", flush=True)
    print("=" * 70, flush=True)
    return True
