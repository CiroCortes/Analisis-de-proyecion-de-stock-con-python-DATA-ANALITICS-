import datetime
import math
from decimal import Decimal
from collections import defaultdict
from django.db import transaction
from django.db.models import Max
from apps.inventory.models import (
    ProductSKU, ProductionOrderMovement,
    SalesOrderMovement, SKUClassification
)

PANOL_CLASSES = {
    'mat.e ins. uso var. en taller',
    'mat. e ins. usado en prod.',
    'perneria',
    'herramientas',
    'epp',
    'otros insumos',
    'ferreteria',
    'material menor',
}


def run_classification_engine():
    """
    Ejecuta el Motor de Clasificacion S&OP de Pesco (Slim4 + REPO).
    Calcula:
      1. Segmento (Panol vs Repuestos y Accesorios)
      2. Clasificacion ABC por meses activos en ano movil (A: 9-12m, B: 5-8m, C: 1-4m, D: 0m)
      3. Articulos Nuevos (< 8 meses para Repuestos, < 4 meses para Panol)
      4. Inmovilizados / Obsoletos (D sin salidas en 24m para Repuestos, 12m para Panol)
      5. Regla Si/No Stock (Casos 1, 2, 3)
      6. Nivel de Servicio (95% para Panol con Z=1.65) y DPD Real.
      -- NUEVO (REPO PESCO) -----------------------------------------------------
      7. Clasificacion REPO: R (VB) / E (V1) / P (PD) / O (ND)
         R = 2+ meses con consumo en el ano movil
         E = Panol critico 95% con politica SI_STOCK pero sin llegar a R
         P = Tiene OF o PC activa aunque no rote
         O = Sin movimiento > 12 meses y sin OF/PC activa
      8. ROP Estadistico = Stock Minimo + Stock de Seguridad
         Stock Minimo    = (LT_meses + 0.25) x consumo_promedio_mensual
         Stock Seguridad = sqrt(LT_meses) x desv_estandar_mensual x Z
         Stock Maximo    = ROP + (3 meses x consumo_promedio_mensual)
    """
    print("\n[MOTOR SLIM4+REPO PESCO] Iniciando Clasificacion S&OP de Inventarios...", flush=True)

    # 1. Determinar fecha de referencia (hoy o fecha máxima no futura)
    today = datetime.date.today()
    max_of_date = ProductionOrderMovement.objects.filter(end_date__lte=today).aggregate(m=Max('end_date'))['m']
    max_pc_date = SalesOrderMovement.objects.filter(delivery_date__lte=today).aggregate(m=Max('delivery_date'))['m']
    
    valid_dates = [d for d in [max_of_date, max_pc_date, today] if d is not None]
    reference_date = min(today, max(valid_dates)) if valid_dates else today
    print(f"[MOTOR SLIM4+REPO PESCO] Fecha de Referencia: {reference_date}", flush=True)

    one_year_ago   = reference_date - datetime.timedelta(days=365)
    six_months_ago = reference_date - datetime.timedelta(days=180)
    two_years_ago  = reference_date - datetime.timedelta(days=730)

    # 2. Agrupar movimientos de OFs (Consumo en Producción)
    print("[MOTOR SLIM4+REPO PESCO] Analizando historial de OFs Cerradas...", flush=True)
    of_months_1y   = defaultdict(set)       # sku -> set of (year, month)
    of_trans_1y    = defaultdict(int)       # sku -> count
    of_trans_6m    = defaultdict(int)       # sku -> count
    of_trans_2y    = defaultdict(int)       # sku -> count
    of_demand_1y   = defaultdict(float)     # sku -> total units
    of_monthly_qty = defaultdict(lambda: defaultdict(float))  # sku -> {(y,m): qty}

    of_qs = (
        ProductionOrderMovement.objects
        .filter(end_date__gte=two_years_ago)
        .values_list('product_id', 'quantity_delivered', 'end_date')
    )
    for sku, qty, f_end in of_qs:
        if not f_end:
            continue
        q = float(qty or 0)
        of_trans_2y[sku] += 1

        if f_end >= one_year_ago:
            of_months_1y[sku].add((f_end.year, f_end.month))
            of_trans_1y[sku] += 1
            of_demand_1y[sku] += q
            of_monthly_qty[sku][(f_end.year, f_end.month)] += q

        if f_end >= six_months_ago:
            of_trans_6m[sku] += 1

    # OFs con estado distinto de Cerrada
    of_open_skus = set(
        ProductionOrderMovement.objects
        .exclude(status='Cerrada')
        .values_list('product_id', flat=True)
    )

    # 3. Agrupar movimientos de Pedidos de Clientes (Ventas Despachadas)
    print("[MOTOR SLIM4+REPO PESCO] Analizando historial de Pedidos Clientes Cerrados...", flush=True)
    pc_months_1y   = defaultdict(set)       # sku -> set of (year, month)
    pc_trans_1y    = defaultdict(int)       # sku -> count
    pc_trans_6m    = defaultdict(int)       # sku -> count
    pc_trans_2y    = defaultdict(int)       # sku -> count
    pc_demand_1y   = defaultdict(float)     # sku -> total units
    pc_monthly_qty = defaultdict(lambda: defaultdict(float))

    pc_qs = (
        SalesOrderMovement.objects
        .filter(delivery_date__gte=two_years_ago)
        .values_list('product_id', 'quantity', 'delivery_date')
    )
    for sku, qty, f_ent in pc_qs:
        if not f_ent:
            continue
        q = float(qty or 0)
        pc_trans_2y[sku] += 1

        if f_ent >= one_year_ago:
            pc_months_1y[sku].add((f_ent.year, f_ent.month))
            pc_trans_1y[sku] += 1
            pc_demand_1y[sku] += q
            pc_monthly_qty[sku][(f_ent.year, f_ent.month)] += q

        if f_ent >= six_months_ago:
            pc_trans_6m[sku] += 1

    # PCs con estado distinto de Cerrado
    pc_open_skus = set(
        SalesOrderMovement.objects
        .exclude(status='Cerrado')
        .values_list('product_id', flat=True)
    )

    # 4. Clasificar todos los SKUs de la Base de Datos
    print("[MOTOR SLIM4+REPO PESCO] Aplicando Matriz Slim4 + REPO sobre catalogo maestro...", flush=True)
    all_skus = (
        ProductSKU.objects
        .select_related('category')
        .all()
    )

    classifications_to_save = []
    stats = {
        'total': 0, 'panol': 0, 'repuestos': 0,
        'A': 0, 'B': 0, 'C': 0, 'D': 0,
        'si_stock': 0, 'no_stock': 0,
        'nuevos': 0, 'inmovilizados': 0,
        'repo_R': 0, 'repo_E': 0, 'repo_P': 0, 'repo_O': 0,
    }

    for p in all_skus:
        stats['total'] += 1
        sku = p.code

        # ── 1. Segmentación ────────────────────────────────────────────────
        clase_clean = (p.clase or '').strip().lower()
        cat_sap = (p.sap_categoria or '').strip().lower()
        grp_name = (p.category.name if p.category else '').upper()

        if clase_clean in PANOL_CLASSES or 'pañol' in cat_sap or 'paol' in cat_sap or grp_name.startswith('PAÑOL') or grp_name.startswith('PAOL'):
            segment = 'PANOL'
            stats['panol'] += 1
        else:
            segment = 'REPUESTOS'
            stats['repuestos'] += 1

        # ── 2. Meses con movimiento en año móvil ─────────────────────────────
        distinct_months = of_months_1y.get(sku, set()).union(pc_months_1y.get(sku, set()))
        active_months = len(distinct_months)

        total_trans_1y  = of_trans_1y.get(sku, 0) + pc_trans_1y.get(sku, 0)
        total_trans_6m  = of_trans_6m.get(sku, 0) + pc_trans_6m.get(sku, 0)
        total_trans_2y  = of_trans_2y.get(sku, 0) + pc_trans_2y.get(sku, 0)
        total_demand_1y = of_demand_1y.get(sku, 0.0) + pc_demand_1y.get(sku, 0.0)
        avg_dpd = total_demand_1y / 365.0

        # ── 3. Clasificación ABC ─────────────────────────────────────────────
        if active_months >= 9:
            abc = 'A'; stats['A'] += 1
        elif active_months >= 5:
            abc = 'B'; stats['B'] += 1
        elif active_months >= 1:
            abc = 'C'; stats['C'] += 1
        else:
            abc = 'D'; stats['D'] += 1

        # ── 4. Artículo Nuevo ────────────────────────────────────────────────
        is_new = False
        if p.fec_creacion_sap:
            days_since_creation = (reference_date - p.fec_creacion_sap).days
            if segment == 'REPUESTOS' and days_since_creation <= 240:
                is_new = True; stats['nuevos'] += 1
            elif segment == 'PANOL' and days_since_creation <= 120:
                is_new = True; stats['nuevos'] += 1

        # ── 5. Inmovilizado / Obsoleto ───────────────────────────────────────
        is_inmovilizado = False
        if not is_new and abc == 'D':
            if segment == 'REPUESTOS' and total_trans_2y == 0:
                is_inmovilizado = True; stats['inmovilizados'] += 1
            elif segment == 'PANOL' and total_trans_1y == 0:
                is_inmovilizado = True; stats['inmovilizados'] += 1

        # ── 6. Regla Sí / No Stock ──────────────────────────────────────────
        if segment == 'REPUESTOS':
            if is_new:
                policy = 'SI_STOCK'
                reason = 'Articulo Nuevo (< 8 meses de creacion en SAP)'
            elif is_inmovilizado:
                policy = 'NO_STOCK'
                reason = 'Inmovilizado / Obsoleto (Sin movimientos en 2 anos)'
            elif total_trans_1y > 2 and total_trans_6m >= 1:
                policy = 'SI_STOCK'
                reason = 'Caso 1: > 2 trans/ano y >= 1 en ultimos 6 meses'
            elif total_trans_1y > 2 and total_trans_6m == 0:
                policy = 'NO_STOCK'
                reason = 'Caso 2: Demanda Apagada (0 transacciones en 6 meses)'
            else:
                policy = 'NO_STOCK'
                reason = 'Caso 3: Baja Frecuencia (<= 2 trans/ano, compra a pedido)'

            if abc == 'A':
                svc_level, z = Decimal('0.90'), Decimal('1.28')
            elif abc == 'B':
                svc_level, z = Decimal('0.85'), Decimal('1.04')
            elif abc == 'C':
                svc_level, z = Decimal('0.80'), Decimal('0.84')
            else:
                svc_level, z = Decimal('0.50'), Decimal('0.00')
        else:
            svc_level = Decimal('0.95')
            z = Decimal('1.65')

            if is_new:
                policy = 'SI_STOCK'
                reason = 'Panol Nuevo (< 4 meses de creacion en SAP)'
            elif is_inmovilizado:
                policy = 'NO_STOCK'
                reason = 'Inmovilizado Panol (Sin salidas en ultimos 12 meses)'
            elif total_trans_1y >= 2 or grp_name.startswith('PAÑOL') or grp_name.startswith('PAOL'):
                policy = 'SI_STOCK'
                reason = 'Panol Operativo 95% (>= 2 rotaciones/ano o insumo critico de taller)'
            else:
                policy = 'NO_STOCK'
                reason = 'Panol Esporadico (< 2 rotaciones/ano, reposicion bajo OF)'

        if policy == 'SI_STOCK':
            stats['si_stock'] += 1
        else:
            stats['no_stock'] += 1

        # ── 7. Clasificación REPO PESCO ──────────────────────────────────────
        has_active_of_or_pc = (sku in of_open_skus) or (sku in pc_open_skus)
        consumption_freq_12m = active_months

        if consumption_freq_12m >= 2:
            repo = 'R'; repo_src = 'VB'
            stats['repo_R'] += 1
        elif segment == 'PANOL' and svc_level >= Decimal('0.95') and policy == 'SI_STOCK':
            repo = 'E'; repo_src = 'V1'
            stats['repo_E'] += 1
        elif has_active_of_or_pc:
            repo = 'P'; repo_src = 'PD'
            stats['repo_P'] += 1
        else:
            repo = 'O'; repo_src = 'ND'
            stats['repo_O'] += 1

        # ── 8. ROP Estadístico ────────────────────────────────────────────────
        rop_stat = ss_stat = st_min = st_max = 0
        avg_monthly = std_monthly = Decimal('0.00')

        if repo in ('R', 'E') and total_demand_1y > 0:
            monthly_values = []
            for i in range(12):
                dt = reference_date.replace(day=1) - datetime.timedelta(days=i * 30)
                key = (dt.year, dt.month)
                qty = of_monthly_qty.get(sku, {}).get(key, 0.0) + pc_monthly_qty.get(sku, {}).get(key, 0.0)
                monthly_values.append(qty)

            n = len(monthly_values)
            avg_m = sum(monthly_values) / n if n > 0 else 0.0
            std_m = math.sqrt(sum((v - avg_m) ** 2 for v in monthly_values) / (n - 1)) if n > 1 else 0.0

            lt_meses = max(float(p.lead_time_days or 0), 1) / 30.0
            z_f = float(z)

            st_min_f = (lt_meses + 0.25) * avg_m
            ss_f     = math.sqrt(lt_meses) * std_m * z_f
            rop_f    = math.ceil(st_min_f + ss_f)
            st_max_f = rop_f + (3.0 * avg_m)

            rop_stat    = max(0, int(rop_f))
            ss_stat     = max(0, int(math.ceil(ss_f)))
            st_min      = max(0, int(math.ceil(st_min_f)))
            st_max      = max(0, int(math.ceil(st_max_f)))
            avg_monthly = Decimal(str(round(avg_m, 2)))
            std_monthly = Decimal(str(round(std_m, 2)))

        classifications_to_save.append(SKUClassification(
            product=p,
            segment=segment,
            abc_class=abc,
            active_months_count=active_months,
            annual_transactions_count=total_trans_1y,
            transactions_last_6m=total_trans_6m,
            is_new=is_new,
            is_inmovilizado=is_inmovilizado,
            stock_policy=policy,
            stock_policy_reason=reason,
            service_level=svc_level,
            z_factor=z,
            annual_demand_units=Decimal(str(round(total_demand_1y, 2))),
            avg_daily_demand=Decimal(str(round(avg_dpd, 4))),
            repo_category=repo,
            repo_source_code=repo_src,
            consumption_freq_12m=consumption_freq_12m,
            rop_statistical=rop_stat,
            safety_stock_statistical=ss_stat,
            stock_min_statistical=st_min,
            stock_max_statistical=st_max,
            avg_monthly_consumption=avg_monthly,
            std_monthly_consumption=std_monthly,
            has_active_of_or_pc=has_active_of_or_pc,
        ))

    # 5. Volcado masivo
    print("[MOTOR SLIM4+REPO PESCO] Guardando clasificaciones en Base de Datos...", flush=True)
    with transaction.atomic():
        SKUClassification.objects.all().delete()
        SKUClassification.objects.bulk_create(classifications_to_save, batch_size=5000)

    total = stats['total'] or 1
    print("\n" + "="*65)
    print("      RESUMEN EJECUTIVO MOTOR S&OP (SLIM4 + REPO PESCO)")
    print("="*65)
    print(f"  * Total SKUs Evaluados:          {stats['total']:>10,d}")
    print(f"    - Segmento Repuestos:          {stats['repuestos']:>10,d} ({stats['repuestos']/total*100:.1f}%)")
    print(f"    - Segmento Panol (95% Svc):    {stats['panol']:>10,d} ({stats['panol']/total*100:.1f}%)")
    print("-" * 65)
    print("  * Clasificacion ABC (Ano Movil):")
    print(f"    - Clase A (9 a 12 meses):      {stats['A']:>10,d} ({stats['A']/total*100:.1f}%)")
    print(f"    - Clase B (5 a 8 meses):       {stats['B']:>10,d} ({stats['B']/total*100:.1f}%)")
    print(f"    - Clase C (1 a 4 meses):       {stats['C']:>10,d} ({stats['C']/total*100:.1f}%)")
    print(f"    - Clase D (Sin movimiento):    {stats['D']:>10,d} ({stats['D']/total*100:.1f}%)")
    print("-" * 65)
    print("  * Politicas de Abastecimiento:")
    print(f"    - SI STOCK (Reorden Activo):   {stats['si_stock']:>10,d} ({stats['si_stock']/total*100:.1f}%)")
    print(f"    - NO STOCK (A Pedido/Apagado): {stats['no_stock']:>10,d} ({stats['no_stock']/total*100:.1f}%)")
    print(f"    - Articulos Nuevos:            {stats['nuevos']:>10,d}")
    print(f"    - Inmovilizados / Obsoletos:   {stats['inmovilizados']:>10,d}")
    print("-" * 65)
    print("  * Clasificacion REPO PESCO (Dinamica Mensual):")
    print(f"    - R Rotacion  (VB):            {stats['repo_R']:>10,d} ({stats['repo_R']/total*100:.1f}%)")
    print(f"    - E Estrategico (V1):          {stats['repo_E']:>10,d} ({stats['repo_E']/total*100:.1f}%)")
    print(f"    - P A Pedido  (PD):            {stats['repo_P']:>10,d} ({stats['repo_P']/total*100:.1f}%)")
    print(f"    - O Obsoleto  (ND):            {stats['repo_O']:>10,d} ({stats['repo_O']/total*100:.1f}%)")
    print("="*65 + "\n", flush=True)

    # 6. Ejecutar Motor DRP de Proyección y Balanceo de Inventario
    drp_stats = run_drp_engine()
    stats.update(drp_stats)

    return stats


def run_drp_engine():
    """
    Motor DRP (Distribution Requirements Planning) de Abastecimiento y Balanceo.
    Regla Híbrida:
      1. Si SAP trae ROP manual (> 0) en el Excel, se respeta ese valor.
      2. Si el Excel viene vacío o en 0:
         - Aplica automáticamente el ROP Estadístico (rop_statistical) a la bodega central (013-PP)
           para materiales R (Rotación) y E (Estratégico).
         - Para materiales P (A Pedido), ROP = compromisos activos (OF + PC).
         - Para materiales O (Obsoleto), ROP = 0 (bloqueo de compra).
      3. Balanceo DRP:
         - Si una sucursal en regiones tiene déficit (disp_future < ROP):
           Revisa si las bodegas de Santiago (013-*) tienen stock disponible.
           * Si Santiago tiene stock -> Acción: TRASLADAR desde Santiago (no compra a proveedor).
           * Si Santiago no tiene stock -> Acción: COMPRAR a proveedor externo.
           * Si Santiago cubre solo una parte -> Acción: MIXTO (Traslado + Compra).
    """
    from apps.inventory.models import Warehouse, InventoryMetric, StockProjection

    print("[MOTOR DRP PESCO] Iniciando Motor DRP de Balanceo y Proyecciones...", flush=True)

    warehouses = list(Warehouse.objects.filter(is_active=True).order_by('code'))
    wh_by_id = {w.id: w for w in warehouses}
    wh_by_code = {w.code: w for w in warehouses}

    # Identificar bodegas de Santiago (donantes potenciales)
    stgo_codes = {'013-PP', '013-PS', '013-07', '013-09'}
    stgo_wh_ids = {w.id for w in warehouses if w.code in stgo_codes}
    central_pp_wh = wh_by_code.get('013-PP')

    # Cargar clasificaciones en memoria por product_id (que es el code del SKU)
    classif_map = {
        c.product_id: c
        for c in SKUClassification.objects.all()
    }

    # Cargar todos los productos con costo (la PK de ProductSKU es 'code')
    products = list(ProductSKU.objects.all().values('code', 'unit_cost_usd'))
    prod_map = {p['code']: p for p in products}

    # Cargar métricas de inventario agrupadas por product_id -> {wh_id: metric_dict}
    print("[MOTOR DRP PESCO] Cargando metricas de inventario por bodega...", flush=True)
    metrics_qs = InventoryMetric.objects.all().values(
        'product_id', 'warehouse_id', 'stock_physical', 'disp_future',
        'comp_pc_qty', 'comp_of_qty', 'sc_qty', 'oc_po_qty'
    )
    metrics_by_prod = defaultdict(dict)
    for m in metrics_qs:
        metrics_by_prod[m['product_id']][m['warehouse_id']] = m

    # Cargar proyecciones existentes para respetar cualquier ROP manual fijado en SAP
    existing_projs_qs = StockProjection.objects.all().values('id', 'product_id', 'warehouse_id', 'rop')
    existing_rop_map = {
        (p['product_id'], p['warehouse_id']): p['rop']
        for p in existing_projs_qs
    }

    projections_to_save = []
    drp_stats = {
        'total_projections': 0,
        'action_comprar': 0,
        'action_trasladar': 0,
        'action_mixto': 0,
        'action_ninguna': 0,
        'total_shortage_usd': Decimal('0.00'),
    }

    print("[MOTOR DRP PESCO] Calculando ROP hibrido y balanceo Santiago vs Sucursales...", flush=True)

    for p_code, p_info in prod_map.items():
        classif = classif_map.get(p_code)
        cost_usd = Decimal(str(p_info['unit_cost_usd'] or 0))
        metrics_dict = metrics_by_prod.get(p_code, {})
        dpd = float(classif.avg_daily_demand or 0) if classif else 0.0

        # ── Paso A: Determinar ROP meta por bodega ─────────────────────────────
        rop_by_wh = {}
        for wh in warehouses:
            m = metrics_dict.get(wh.id, {})
            comp_local = (m.get('comp_pc_qty', 0) or 0) + (m.get('comp_of_qty', 0) or 0)
            manual_rop = existing_rop_map.get((p_code, wh.id), 0)

            if manual_rop > 0:
                # 1. Respetar ROP manual explícito de SAP si venía en el Excel
                target_rop = manual_rop
            elif classif:
                if classif.repo_category in ('R', 'E') and classif.rop_statistical > 0:
                    if wh.code == '013-PP':
                        # Asignar ROP Estadístico automático a la bodega central
                        target_rop = classif.rop_statistical
                    elif comp_local > 0:
                        # Si una sucursal tiene compromisos locales, su ROP mínimo es lo comprometido
                        target_rop = comp_local
                    else:
                        target_rop = 0
                elif classif.repo_category == 'P':
                    # A Pedido: reorden = solo lo comprometido en OF / PC
                    target_rop = comp_local
                else:
                    # Obsoleto / Sin movimiento: no recomprar
                    target_rop = 0
            else:
                target_rop = 0

            rop_by_wh[wh.id] = target_rop

        # ── Paso B: Determinar excedente disponible en Santiago ───────────────
        stgo_surplus_pool = {}
        for stgo_id in stgo_wh_ids:
            m = metrics_dict.get(stgo_id, {})
            disp_f = m.get('disp_future', 0) or 0
            target_r = rop_by_wh.get(stgo_id, 0)
            # Excedente = lo que sobra por encima del ROP de la bodega de Santiago
            # Si el ROP es 0 en esa bodega satélite de Santiago, todo el stock físico/futuro es transferible
            surplus = max(0, disp_f - target_r) if target_r > 0 else max(0, disp_f)
            if surplus > 0:
                stgo_surplus_pool[stgo_id] = surplus

        # ── Paso C: Balancear y asignar acciones (Trasladar vs Comprar) ────────
        for wh in warehouses:
            drp_stats['total_projections'] += 1
            m = metrics_dict.get(wh.id, {})
            disp_fut = m.get('disp_future', 0) or 0
            target_rop = rop_by_wh.get(wh.id, 0)
            deficit = max(0, target_rop - disp_fut)
            is_stgo_wh = wh.id in stgo_wh_ids

            action = 'NINGUNA'
            sug_transfer = 0
            sug_buy = 0
            source_wh = None

            if deficit > 0:
                if not is_stgo_wh:
                    # ── Déficit en Sucursal (Regiones): primero buscar en Santiago ──
                    if stgo_surplus_pool:
                        # Elegir la bodega de Santiago con más excedente
                        best_stgo_id = max(stgo_surplus_pool, key=stgo_surplus_pool.get)
                        available_qty = stgo_surplus_pool[best_stgo_id]

                        if available_qty >= deficit:
                            # Santiago cubre el 100% del requerimiento
                            action = 'TRASLADAR'
                            sug_transfer = deficit
                            sug_buy = 0
                            source_wh = wh_by_id.get(best_stgo_id)
                            stgo_surplus_pool[best_stgo_id] -= deficit
                            if stgo_surplus_pool[best_stgo_id] <= 0:
                                del stgo_surplus_pool[best_stgo_id]
                        else:
                            # Santiago cubre una parte; comprar el resto
                            action = 'MIXTO'
                            sug_transfer = available_qty
                            sug_buy = deficit - available_qty
                            source_wh = wh_by_id.get(best_stgo_id)
                            del stgo_surplus_pool[best_stgo_id]
                    else:
                        # No hay stock en Santiago: comprar directo a proveedor
                        action = 'COMPRAR'
                        sug_buy = deficit
                        sug_transfer = 0

                else:
                    # ── Déficit en Bodega Central Santiago ──
                    # Revisar si OTRA bodega de Santiago tiene excedente para moverlo internamente
                    other_stgo_pool = {wid: q for wid, q in stgo_surplus_pool.items() if wid != wh.id and q > 0}
                    if other_stgo_pool:
                        best_other_id = max(other_stgo_pool, key=other_stgo_pool.get)
                        avail = other_stgo_pool[best_other_id]
                        if avail >= deficit:
                            action = 'TRASLADAR'
                            sug_transfer = deficit
                            sug_buy = 0
                            source_wh = wh_by_id.get(best_other_id)
                            stgo_surplus_pool[best_other_id] -= deficit
                            if stgo_surplus_pool[best_other_id] <= 0:
                                del stgo_surplus_pool[best_other_id]
                        else:
                            action = 'MIXTO'
                            sug_transfer = avail
                            sug_buy = deficit - avail
                            source_wh = wh_by_id.get(best_other_id)
                            del stgo_surplus_pool[best_other_id]
                    else:
                        action = 'COMPRAR'
                        sug_buy = deficit
                        sug_transfer = 0

                # Nivel de urgencia
                urgency = 'URGENTE' if disp_fut <= 0 else 'MEDIO'
                shortage_units = deficit
                shortage_usd = Decimal(str(deficit)) * cost_usd

                if action == 'COMPRAR':
                    drp_stats['action_comprar'] += 1
                elif action == 'TRASLADAR':
                    drp_stats['action_trasladar'] += 1
                elif action == 'MIXTO':
                    drp_stats['action_mixto'] += 1

                drp_stats['total_shortage_usd'] += shortage_usd

            else:
                action = 'NINGUNA'
                sug_buy = 0
                sug_transfer = 0
                urgency = 'NORMAL'
                shortage_units = 0
                shortage_usd = Decimal('0.00')
                drp_stats['action_ninguna'] += 1

            cov_days = int(disp_fut / dpd) if dpd > 0 and disp_fut > 0 else 0
            safety_stk = classif.safety_stock_statistical if (classif and wh.code == '013-PP') else 0

            projections_to_save.append(StockProjection(
                product_id=p_code,
                warehouse=wh,
                rop=target_rop,
                safety_stock=safety_stk,
                coverage_days=cov_days,
                shortage_units=shortage_units,
                shortage_usd=shortage_usd,
                suggested_buy_units=sug_buy,
                suggested_transfer_units=sug_transfer,
                transfer_source_warehouse=source_wh,
                action_type=action,
                urgency_level=urgency,
            ))

    # ── Guardar masivamente en StockProjection ────────────────────────────────
    print("[MOTOR DRP PESCO] Guardando proyecciones y balanceo en Base de Datos...", flush=True)
    with transaction.atomic():
        StockProjection.objects.all().delete()
        StockProjection.objects.bulk_create(projections_to_save, batch_size=5000)

    print("\n" + "="*65)
    print("      RESUMEN EJECUTIVO MOTOR DRP DE BALANCEO Y COMPRAS")
    print("="*65)
    print(f"  * Total Proyecciones Evaluadas:  {drp_stats['total_projections']:>10,d}")
    print(f"    - Accion COMPRAR (Proveedor):  {drp_stats['action_comprar']:>10,d}")
    print(f"    - Accion TRASLADAR (Santiago): {drp_stats['action_trasladar']:>10,d}")
    print(f"    - Accion MIXTA (Traslado+Cmp): {drp_stats['action_mixto']:>10,d}")
    print(f"    - Sin Accion (Stock Seguro):   {drp_stats['action_ninguna']:>10,d}")
    print(f"  * Monto Total Quiebre Calculado: ${drp_stats['total_shortage_usd']:>14,.2f} USD")
    print("="*65 + "\n", flush=True)

    return drp_stats
