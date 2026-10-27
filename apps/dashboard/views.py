import os
import json
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.db.models import Sum, Count, Q, Avg, Max, F
from django.http import JsonResponse
from django.conf import settings
from apps.inventory.models import ProductSKU, StockProjection, Warehouse, InventoryMetric, Category, SKUClassification, GoodsReceipt


def _apply_filters(queryset, request):
    """Aplica filtros de Grupo, Bodega, Segmento S&OP (Pañol vs Repuestos), Clase ABC y Política Sí/No Stock."""
    category_filter = request.GET.get('category', '').strip()
    include_all_groups = request.GET.get('include_all_groups', '').strip() == '1'
    warehouse_filter = request.GET.get('warehouse', '').strip()
    segment_filter = request.GET.get('segment', '').strip()
    abc_filter = request.GET.get('abc', '').strip()
    policy_filter = request.GET.get('policy', '').strip()

    if category_filter:
        queryset = queryset.filter(product__category__code=category_filter)
    elif not include_all_groups:
        # Por defecto, procesar únicamente los grupos activos configurados
        queryset = queryset.filter(product__category__is_active=True, product__is_active=True)

    if warehouse_filter:
        queryset = queryset.filter(warehouse__code=warehouse_filter)
    if segment_filter:
        queryset = queryset.filter(product__classification__segment=segment_filter)
    if abc_filter:
        queryset = queryset.filter(product__classification__abc_class=abc_filter)
    if policy_filter:
        queryset = queryset.filter(product__classification__stock_policy=policy_filter)

    return queryset, {
        'category': category_filter,
        'include_all_groups': include_all_groups,
        'warehouse': warehouse_filter,
        'segment': segment_filter,
        'abc': abc_filter,
        'policy': policy_filter,
    }


@login_required
def dashboard_home_view(request):
    categories = Category.objects.filter(productsku__isnull=False).distinct().order_by('name')
    warehouses = Warehouse.objects.filter(is_active=True).order_by('code')
    inactive_groups_count = Category.objects.filter(is_active=False).count()

    projections = StockProjection.objects.select_related('product', 'warehouse', 'product__category', 'product__classification').all()
    projections, f = _apply_filters(projections, request)

    sku_qs = ProductSKU.objects.filter(is_active=True)
    if f['category']:
        sku_qs = sku_qs.filter(category__code=f['category'])
    elif not f['include_all_groups']:
        sku_qs = sku_qs.filter(category__is_active=True)

    if f['segment']:
        sku_qs = sku_qs.filter(classification__segment=f['segment'])
    if f['abc']:
        sku_qs = sku_qs.filter(classification__abc_class=f['abc'])
    if f['policy']:
        sku_qs = sku_qs.filter(classification__stock_policy=f['policy'])

    total_skus = sku_qs.count()
    total_critical_skus = projections.filter(urgency_level='URGENTE').values('product').distinct().count()
    total_shortage_usd = float(projections.aggregate(total=Sum('shortage_usd'))['total'] or 0)
    total_suggested_buy = projections.aggregate(total=Sum('suggested_buy_units'))['total'] or 0

    # Desglose S&OP Slim4
    total_panol = sku_qs.filter(classification__segment='PANOL').count()
    total_repuestos = sku_qs.filter(classification__segment='REPUESTOS').count()
    total_si_stock = sku_qs.filter(classification__stock_policy='SI_STOCK').count()
    total_no_stock = sku_qs.filter(classification__stock_policy='NO_STOCK').count()
    total_inmovilizados = sku_qs.filter(classification__is_inmovilizado=True).count()
    total_nuevos = sku_qs.filter(classification__is_new=True).count()

    wh_stats = []
    target_warehouses = warehouses.filter(code=f['warehouse']) if f['warehouse'] else warehouses
    for wh in target_warehouses:
        wh_proj = projections.filter(warehouse=wh)
        wh_crit = wh_proj.filter(urgency_level='URGENTE').count()
        wh_usd = float(wh_proj.aggregate(total=Sum('shortage_usd'))['total'] or 0)
        wh_stats.append({
            'code': wh.code,
            'name': wh.name,
            'critical_count': wh_crit,
            'urgente_count': wh_crit,
            'shortage_usd': wh_usd,
        })

    top_critical_items = (
        projections.filter(urgency_level='URGENTE')
        .order_by('-shortage_usd')
        .select_related('product', 'warehouse', 'product__category', 'product__classification')[:15]
    )

    context = {
        'total_skus': total_skus,
        'total_critical_skus': total_critical_skus,
        'total_urgente_skus': total_critical_skus,
        'total_shortage_usd': total_shortage_usd,
        'total_suggested_buy': total_suggested_buy,
        'total_panol': total_panol,
        'total_repuestos': total_repuestos,
        'total_si_stock': total_si_stock,
        'total_no_stock': total_no_stock,
        'total_inmovilizados': total_inmovilizados,
        'total_nuevos': total_nuevos,
        'wh_stats': wh_stats,
        'top_critical_items': top_critical_items,
        'categories': categories,
        'warehouses': warehouses,
        'inactive_groups_count': inactive_groups_count,
        'include_all_groups': f['include_all_groups'],
        'selected_category': f['category'],
        'selected_warehouse': f['warehouse'],
        'selected_segment': f['segment'],
        'selected_abc': f['abc'],
        'selected_policy': f['policy'],
    }
    return render(request, 'dashboard/home.html', context)


@login_required
def analytics_view(request):
    """Vista de Analítica S&OP con filtros de Segmento (Pañol vs Repuestos), ABC y Bodega."""
    categories = Category.objects.filter(productsku__isnull=False).distinct().order_by('name')
    warehouses = Warehouse.objects.filter(is_active=True).order_by('code')
    inactive_groups_count = Category.objects.filter(is_active=False).count()

    projections = StockProjection.objects.select_related('product', 'warehouse', 'product__category', 'product__classification').all()
    projections, f = _apply_filters(projections, request)

    sku_qs = ProductSKU.objects.filter(is_active=True)
    if f['category']:
        sku_qs = sku_qs.filter(category__code=f['category'])
    elif not f['include_all_groups']:
        sku_qs = sku_qs.filter(category__is_active=True)

    if f['segment']:
        sku_qs = sku_qs.filter(classification__segment=f['segment'])
    if f['abc']:
        sku_qs = sku_qs.filter(classification__abc_class=f['abc'])
    if f['policy']:
        sku_qs = sku_qs.filter(classification__stock_policy=f['policy'])

    total_skus = sku_qs.count()
    total_shortage_usd = float(projections.aggregate(t=Sum('shortage_usd'))['t'] or 0)
    total_urgentes     = projections.filter(urgency_level='URGENTE').values('product').distinct().count()
    total_medios       = projections.filter(urgency_level='MEDIO').values('product').distinct().count()
    total_normales     = projections.filter(urgency_level='NORMAL').values('product').distinct().count()
    total_sugerido     = projections.aggregate(t=Sum('suggested_buy_units'))['t'] or 0

    # Métricas Slim4
    total_panol = sku_qs.filter(classification__segment='PANOL').count()
    total_repuestos = sku_qs.filter(classification__segment='REPUESTOS').count()
    total_si_stock = sku_qs.filter(classification__stock_policy='SI_STOCK').count()

    context = {
        'total_skus': total_skus,
        'total_shortage_usd': total_shortage_usd,
        'total_urgentes': total_urgentes,
        'total_criticos': total_urgentes,
        'total_medios': total_medios,
        'total_normales': total_normales,
        'total_sugerido': total_sugerido,
        'total_panol': total_panol,
        'total_repuestos': total_repuestos,
        'total_si_stock': total_si_stock,
        'categories': categories,
        'warehouses': warehouses,
        'inactive_groups_count': inactive_groups_count,
        'include_all_groups': f['include_all_groups'],
        'selected_category': f['category'],
        'selected_warehouse': f['warehouse'],
        'selected_segment': f['segment'],
        'selected_abc': f['abc'],
        'selected_policy': f['policy'],
    }
    return render(request, 'dashboard/analytics.html', context)


# ── API Endpoints para Chart.js (filtrables dinámicamente) ──────────────────

@login_required
def api_chart_urgency_distribution(request):
    """Distribución de urgencias por bodega → Stacked Bar Chart."""
    projections = StockProjection.objects.all()
    projections, f = _apply_filters(projections, request)

    warehouses = Warehouse.objects.filter(is_active=True).order_by('code')
    if f['warehouse']:
        warehouses = warehouses.filter(code=f['warehouse'])

    labels = []
    urgente_data, medio_data, normal_data = [], [], []

    for wh in warehouses:
        proj_wh = projections.filter(warehouse=wh)
        labels.append(wh.code)
        urgente_data.append(proj_wh.filter(urgency_level='URGENTE').count())
        medio_data.append(proj_wh.filter(urgency_level='MEDIO').count())
        normal_data.append(proj_wh.filter(urgency_level='NORMAL').count())

    return JsonResponse({
        'labels': labels,
        'datasets': [
            {'label': 'URGENTE', 'data': urgente_data, 'backgroundColor': '#ef4444', 'hidden': False},
            {'label': 'MEDIO',   'data': medio_data,   'backgroundColor': '#f59e0b', 'hidden': False},
            {'label': 'NORMAL',  'data': normal_data,  'backgroundColor': '#10b981', 'hidden': True},
        ]
    })


@login_required
def api_chart_shortage_usd_by_warehouse(request):
    """Quiebre total en USD por bodega → Horizontal Bar."""
    projections = StockProjection.objects.all()
    projections, f = _apply_filters(projections, request)

    warehouses = Warehouse.objects.filter(is_active=True).order_by('code')
    if f['warehouse']:
        warehouses = warehouses.filter(code=f['warehouse'])

    labels, data, colors = [], [], []
    palette = ['#0099DE','#0077B6','#00B4D8','#48CAE4','#90E0EF','#e03131','#f59e0b','#10b981','#7c3aed']

    for i, wh in enumerate(warehouses):
        usd = float(projections.filter(warehouse=wh).aggregate(t=Sum('shortage_usd'))['t'] or 0)
        labels.append(wh.code)
        data.append(round(usd, 2))
        colors.append(palette[i % len(palette)])

    return JsonResponse({
        'labels': labels,
        'datasets': [{'label': 'Quiebre USD', 'data': data, 'backgroundColor': colors}]
    })


@login_required
def api_chart_top_shortage_skus(request):
    """Top 15 SKUs con mayor quiebre valorizado en USD."""
    projections = StockProjection.objects.filter(shortage_usd__gt=0)
    projections, f = _apply_filters(projections, request)

    top = (projections
           .order_by('-shortage_usd')
           .select_related('product')[:15])

    labels = [f"{p.product.code}" for p in top]
    data   = [float(p.shortage_usd) for p in top]
    urgencies = [p.urgency_level for p in top]
    colors = ['#ef4444' if u == 'URGENTE' else '#f59e0b' for u in urgencies]

    return JsonResponse({
        'labels': labels,
        'datasets': [{'label': 'Quiebre USD', 'data': data, 'backgroundColor': colors}]
    })


@login_required
def api_chart_coverage_histogram(request):
    """Histograma de días de cobertura."""
    projections = StockProjection.objects.all()
    projections, f = _apply_filters(projections, request)

    buckets = {
        '0 días (Sin Stock)': 0,
        '1-7 días': 0,
        '8-30 días': 0,
        '31-60 días': 0,
        '61-90 días': 0,
        '91-180 días': 0,
        '> 180 días': 0,
    }
    all_proj = projections.values_list('coverage_days', flat=True)
    for days in all_proj:
        if days == 0:
            buckets['0 días (Sin Stock)'] += 1
        elif days <= 7:
            buckets['1-7 días'] += 1
        elif days <= 30:
            buckets['8-30 días'] += 1
        elif days <= 60:
            buckets['31-60 días'] += 1
        elif days <= 90:
            buckets['61-90 días'] += 1
        elif days <= 180:
            buckets['91-180 días'] += 1
        else:
            buckets['> 180 días'] += 1

    bg = ['#ef4444','#f59e0b','#fb923c','#facc15','#a3e635','#34d399','#0099DE']
    return JsonResponse({
        'labels': list(buckets.keys()),
        'datasets': [{'label': 'Cantidad de Registros', 'data': list(buckets.values()), 'backgroundColor': bg}]
    })


@login_required
def api_chart_risk_matrix(request):
    """Matriz de riesgo: disp_future vs ROP por bodega."""
    projections = StockProjection.objects.filter(rop__gt=0)
    projections, f = _apply_filters(projections, request)

    warehouses = Warehouse.objects.filter(is_active=True)
    if f['warehouse']:
        warehouses = warehouses.filter(code=f['warehouse'])

    datasets = []
    palette = ['#0099DE','#ef4444','#f59e0b','#10b981','#7c3aed','#e03131','#00B4D8','#facc15','#fb923c']

    for i, wh in enumerate(warehouses):
        points = (projections
                  .filter(warehouse=wh)
                  .select_related('product')
                  .values('rop', 'shortage_units', 'urgency_level')[:300])

        scatter = [{'x': float(p['rop']), 'y': float(p['shortage_units'])} for p in points]
        datasets.append({
            'label': wh.code,
            'data': scatter,
            'backgroundColor': palette[i % len(palette)] + 'aa',
            'pointRadius': 4,
        })

    return JsonResponse({'datasets': datasets})


# ═══════════════════════════════════════════════════════════════════════════════
# FASE 3 — REPORTE EJECUTIVO GERENCIAL (solicitud Gisella Guillen)
# Módulos: 1+2 (gráficos lado a lado), 3 (quiebres), 4 ($ pedido), 5 (ranking
#          SKUs pedido más caros), 6 (ranking solicitantes — pendiente de datos)
# ═══════════════════════════════════════════════════════════════════════════════

import datetime
from decimal import Decimal
from apps.inventory.models import ProductionOrderMovement, SalesOrderMovement


@login_required
def executive_report_view(request):
    """
    Vista del Reporte Ejecutivo Gerencial para Gisella Guillen.
    Aplica la segmentación de grupos activos/bloqueados y filtros S&OP.
    """
    categories = Category.objects.filter(productsku__isnull=False).distinct().order_by('name')
    warehouses = Warehouse.objects.filter(is_active=True).order_by('code')
    inactive_groups_count = Category.objects.filter(is_active=False).count()

    projections = StockProjection.objects.select_related('product', 'warehouse', 'product__category', 'product__classification').all()
    projections, f = _apply_filters(projections, request)

    # ── Módulo 3: SKUs en quiebre activo filtrados por grupos activos y filtros ─
    skus_quiebre = (
        projections
        .filter(shortage_units__gt=0)
        .order_by('-shortage_units', '-shortage_usd')[:50]
    )

    quiebre_list = []
    for p in skus_quiebre:
        dpd = float(getattr(p.product, 'classification', None) and
                    p.product.classification.avg_daily_demand or 0)
        dias = int(p.shortage_units / dpd) if dpd > 0 else 0
        quiebre_list.append({
            'sku': p.product.code,
            'desc': p.product.description[:60],
            'bodega': p.warehouse.code if p.warehouse else '—',
            'shortage_units': p.shortage_units,
            'shortage_usd': float(p.shortage_usd),
            'dias_quiebre': dias,
            'urgency': p.urgency_level,
            'repo': getattr(getattr(p.product, 'classification', None), 'repo_category', '—'),
        })
    quiebre_list.sort(key=lambda x: x['dias_quiebre'], reverse=True)

    # ── Módulo 5: Ranking materiales a pedido (P) filtrados por grupos activos ─
    sku_qs = ProductSKU.objects.filter(is_active=True)
    if f['category']:
        sku_qs = sku_qs.filter(category__code=f['category'])
    elif not f['include_all_groups']:
        sku_qs = sku_qs.filter(category__is_active=True)

    if f['segment']:
        sku_qs = sku_qs.filter(classification__segment=f['segment'])
    if f['abc']:
        sku_qs = sku_qs.filter(classification__abc_class=f['abc'])
    if f['policy']:
        sku_qs = sku_qs.filter(classification__stock_policy=f['policy'])

    repo_p_skus = (
        sku_qs
        .filter(classification__repo_category='P')
        .select_related('classification', 'category')
        .order_by('-unit_cost_usd')[:100]
    )

    pedido_ranking = []
    for sku in repo_p_skus:
        stock_total = (
            InventoryMetric.objects
            .filter(product=sku)
            .aggregate(t=Sum('stock_physical'))['t'] or 0
        )
        valor_total = float(sku.unit_cost_usd or 0) * stock_total
        pedido_ranking.append({
            'sku': sku.code,
            'desc': sku.description[:60],
            'costo_usd': float(sku.unit_cost_usd or 0),
            'stock_total': stock_total,
            'valor_total': valor_total,
            'categoria': sku.category.name if sku.category else '—',
        })
    pedido_ranking.sort(key=lambda x: x['valor_total'], reverse=True)

    # ── KPIs resumen sobre el conjunto filtrado ───────────────────────────────
    total_skus_urgentes = projections.filter(urgency_level='URGENTE').values('product').distinct().count()
    total_quiebre_usd   = float(projections.aggregate(t=Sum('shortage_usd'))['t'] or 0)
    total_repo_r        = sku_qs.filter(classification__repo_category='R').count()
    total_repo_p        = sku_qs.filter(classification__repo_category='P').count()
    total_repo_o        = sku_qs.filter(classification__repo_category='O').count()

    valor_inventario_pedido = sum(r['valor_total'] for r in pedido_ranking)

    context = {
        'warehouses': warehouses,
        'categories': categories,
        'inactive_groups_count': inactive_groups_count,
        'include_all_groups': f['include_all_groups'],
        'selected_category': f['category'],
        'selected_warehouse': f['warehouse'],
        'selected_segment': f['segment'],
        'selected_abc': f['abc'],
        'selected_policy': f['policy'],
        'quiebre_list': quiebre_list,
        'pedido_ranking': pedido_ranking[:30],
        'total_skus_urgentes': total_skus_urgentes,
        'total_skus_criticos': total_skus_urgentes,
        'total_quiebre_usd': total_quiebre_usd,
        'total_repo_r': total_repo_r,
        'total_repo_p': total_repo_p,
        'total_repo_o': total_repo_o,
        'valor_inventario_pedido': valor_inventario_pedido,
    }
    return render(request, 'dashboard/executive_report.html', context)


from django.db.models.functions import TruncMonth

@login_required
def api_disponibilidad_historica(request):
    """
    Gráfico 1: % Nivel de Servicio (Fill Rate) Mensual por Sucursal.
    Fórmula: (OF + PC Cerradas) / (OF + PC Totales) * 100
    Optimizada con TruncMonth para cargar en milisegundos.
    """
    projections = StockProjection.objects.all()
    projections, f = _apply_filters(projections, request)

    warehouses = Warehouse.objects.filter(is_active=True).order_by('code')
    if f['warehouse']:
        warehouses = warehouses.filter(code=f['warehouse'])

    today = datetime.date.today()
    meses_dt = [today.replace(day=1) - datetime.timedelta(days=i * 30) for i in range(11, -1, -1)]
    meses_dt = [d.replace(day=1) for d in meses_dt] # Normalizar al primer día
    meses_str = [f"{d.year}-{d.month:02d}" for d in meses_dt]

    palette = ['#0099DE', '#ef4444', '#f59e0b', '#10b981', '#7c3aed',
               '#e03131', '#00B4D8', '#facc15', '#fb923c']
    datasets = []

    valid_sku_codes = set(projections.values_list('product__code', flat=True).distinct())

    # Pre-calcular agregaciones globales por bodega y mes
    # OFs
    of_agg = ProductionOrderMovement.objects.filter(
        product_id__in=valid_sku_codes,
        start_date__gte=today - datetime.timedelta(days=365)
    ).annotate(
        month=TruncMonth('start_date')
    ).values('warehouse', 'month').annotate(
        total=Count('id'),
        cerradas=Count('id', filter=Q(status__icontains='cerrad'))
    )

    # PCs
    pc_agg = SalesOrderMovement.objects.filter(
        product_id__in=valid_sku_codes,
        emission_date__gte=today - datetime.timedelta(days=365)
    ).annotate(
        month=TruncMonth('emission_date')
    ).values('warehouse', 'month').annotate(
        total=Count('id'),
        cerradas=Count('id', filter=Q(status__icontains='cerrad'))
    )

    # Preparamos las llaves de agrupación. Si es 013-*, va a "Santiago (013)". Si no, va por su código.
    group_keys = set()
    for w in warehouses:
        if w.code.startswith('013'):
            group_keys.add('Santiago (013)')
        else:
            group_keys.add(w.code)

    # Organizar en memoria por Grupos
    data_by_group = {g: {m: {'t': 0, 'c': 0} for m in meses_str} for g in group_keys}

    def get_group(wh_code):
        wh_code = wh_code.upper()
        if wh_code.startswith('013') or wh_code.startswith('13') or 'T013' in wh_code:
            return 'Santiago (013)'
            
        best_match = None
        for w in warehouses:
            w_norm = w.code.lstrip('0') or '0'
            wh_norm = wh_code.lstrip('0') or '0'
            
            if wh_code == w.code or wh_norm == w_norm:
                return w.code
                
            if w.code in wh_code:
                if not best_match or len(w.code) > len(best_match):
                    best_match = w.code
        return best_match

    for item in of_agg:
        wh_code = item['warehouse'].strip()
        month_dt = item['month']
        if month_dt and wh_code:
            group = get_group(wh_code)
            if group and group in data_by_group:
                m_str = f"{month_dt.year}-{month_dt.month:02d}"
                if m_str in data_by_group[group]:
                    data_by_group[group][m_str]['t'] += item['total']
                    data_by_group[group][m_str]['c'] += item['cerradas']

    for item in pc_agg:
        wh_code = item['warehouse'].strip()
        month_dt = item['month']
        if month_dt and wh_code:
            group = get_group(wh_code)
            if group and group in data_by_group:
                m_str = f"{month_dt.year}-{month_dt.month:02d}"
                if m_str in data_by_group[group]:
                    data_by_group[group][m_str]['t'] += item['total']
                    data_by_group[group][m_str]['c'] += item['cerradas']

    for idx, (group_name, meses_data) in enumerate(data_by_group.items()):
        data = []
        has_any_data = False
        for mes in meses_str:
            t = meses_data[mes]['t']
            c = meses_data[mes]['c']
            if t > 0:
                data.append(round((c / t * 100), 1))
                has_any_data = True
            else:
                data.append(None)

        if not has_any_data:
            continue

        color = palette[idx % len(palette)]
        datasets.append({
            'label': group_name,
            'data': data,
            'borderColor': color,
            'backgroundColor': color + '22',
            'tension': 0.3,
            'fill': False,
            'pointRadius': 4,
            'spanGaps': True,
        })

    return JsonResponse({'labels': meses_str, 'datasets': datasets})

@login_required
def api_inventario_historico(request):
    """
    Gráfico 2: Monto Total de Inventario (USD) global de la compañía reconstruido hacia atrás.
    Inventario(Mes Anterior) = Inventario(Mes Actual) - Ingresos(Mes Actual) + Salidas(Mes Actual)
    """
    projections = StockProjection.objects.all()
    projections, f = _apply_filters(projections, request)

    # Solo usaremos códigos válidos para mantener congruencia de filtros
    valid_sku_codes = set(projections.values_list('product__code', flat=True).distinct())

    # 1. Obtener la foto actual de inventario (Gran Total Compañía filtrado)
    inventario_actual_usd = float(
        InventoryMetric.objects
        .filter(product_id__in=valid_sku_codes)
        .aggregate(t=Sum(F('stock_physical') * F('product__unit_cost_usd')))['t'] or 0
    )

    today = datetime.date.today()
    meses = []
    # Generamos la lista de meses (del más antiguo al más reciente)
    for i in range(11, -1, -1):
        d = today.replace(day=1) - datetime.timedelta(days=i * 30)
        meses.append(f"{d.year}-{d.month:02d}")
        
    # Inicializamos diccionarios para agrupar Ingresos y Salidas por mes
    ingresos_por_mes = {mes: 0.0 for mes in meses}
    salidas_por_mes = {mes: 0.0 for mes in meses}

    # -- Agrupar Entradas (GoodsReceipt) --
    entradas = GoodsReceipt.objects.filter(
        product_id__in=valid_sku_codes,
        posting_date__gte=today - datetime.timedelta(days=365)
    ).values('posting_date').annotate(
        total_usd=Sum(F('quantity') * F('product__unit_cost_usd'))
    )
    
    for e in entradas:
        if e['posting_date']:
            key = f"{e['posting_date'].year}-{e['posting_date'].month:02d}"
            if key in ingresos_por_mes:
                ingresos_por_mes[key] += float(e['total_usd'] or 0)

    # -- Agrupar Salidas OF --
    ofs = ProductionOrderMovement.objects.filter(
        product_id__in=valid_sku_codes,
        status__icontains='cerrada',
        start_date__gte=today - datetime.timedelta(days=365)
    ).values('start_date').annotate(
        total_usd=Sum(F('quantity_delivered') * F('product__unit_cost_usd'))
    )
    for of in ofs:
        if of['start_date']:
            key = f"{of['start_date'].year}-{of['start_date'].month:02d}"
            if key in salidas_por_mes:
                salidas_por_mes[key] += float(of['total_usd'] or 0)

    # -- Agrupar Salidas PC --
    pcs = SalesOrderMovement.objects.filter(
        product_id__in=valid_sku_codes,
        status__icontains='cerrado',
        emission_date__gte=today - datetime.timedelta(days=365)
    ).values('emission_date').annotate(
        total_usd=Sum(F('quantity') * F('product__unit_cost_usd'))
    )
    for pc in pcs:
        if pc['emission_date']:
            key = f"{pc['emission_date'].year}-{pc['emission_date'].month:02d}"
            if key in salidas_por_mes:
                salidas_por_mes[key] += float(pc['total_usd'] or 0)

    # 2. Reconstruir hacia atrás
    valores_reconstruidos = []
    valor_acumulado = inventario_actual_usd
    
    # Recorremos de derecha a izquierda (del presente al pasado)
    for mes in reversed(meses):
        valores_reconstruidos.insert(0, round(valor_acumulado, 2))
        # Para el mes anterior: Valor Anterior = Valor Actual - Entradas(mes) + Salidas(mes)
        valor_acumulado = valor_acumulado - ingresos_por_mes[mes] + salidas_por_mes[mes]
        if valor_acumulado < 0:
            valor_acumulado = 0.0

    datasets = [{
        'label': 'Total Compañía (USD)',
        'data': valores_reconstruidos,
        'borderColor': '#10b981',
        'backgroundColor': '#10b98122',
        'tension': 0.3,
        'fill': True,
        'pointRadius': 4,
    }]

    return JsonResponse({
        'labels': meses,
        'datasets': datasets,
        '_nota': 'Curva reconstruida matemáticamente usando Inventario Actual - Entradas + Salidas.',
    })


@login_required
def api_quiebres_por_dias(request):
    """
    Módulo 3 (versión JSON): Top 20 SKUs en quiebre respetando filtros S&OP.
    """
    projections = StockProjection.objects.filter(shortage_units__gt=0)
    projections, f = _apply_filters(projections, request)

    top = (
        projections
        .select_related('product', 'warehouse', 'product__classification')
        .order_by('-shortage_units')[:40]
    )

    resultado = []
    for p in top:
        dpd = float(getattr(getattr(p.product, 'classification', None), 'avg_daily_demand', 0) or 0)
        dias = int(p.shortage_units / dpd) if dpd > 0 else p.shortage_units
        resultado.append({
            'sku': p.product.code,
            'desc': p.product.description[:40],
            'bodega': p.warehouse.code if p.warehouse else '—',
            'dias': dias,
            'shortage_usd': float(p.shortage_usd),
            'urgency': p.urgency_level,
        })

    resultado.sort(key=lambda x: x['dias'], reverse=True)
    top20 = resultado[:20]

    return JsonResponse({
        'labels': [f"{r['sku']} ({r['bodega']})" for r in top20],
        'datasets': [{
            'label': 'Días en Quiebre Estimados',
            'data': [r['dias'] for r in top20],
            'backgroundColor': [
                '#ef4444' if r['urgency'] == 'URGENTE' else '#f59e0b'
                for r in top20
            ],
            'borderRadius': 6,
        }],
        'detail': top20,
    })


@login_required
def api_materiales_pedido_tendencia(request):
    """
    Gráfico 4: Evolución mensual de materiales a pedido (tipo P) filtrado por grupos activos.
    """
    projections = StockProjection.objects.all()
    projections, f = _apply_filters(projections, request)
    valid_sku_codes = set(projections.values_list('product__code', flat=True).distinct())

    today = datetime.date.today()
    meses_dt = []
    for i in range(11, -1, -1):
        d = today.replace(day=1) - datetime.timedelta(days=i * 30)
        meses_dt.append(d)

    labels = [f"{d.year}-{d.month:02d}" for d in meses_dt]

    of_data = []
    pc_data = []
    for d in meses_dt:
        of_mes = (
            ProductionOrderMovement.objects
            .filter(
                product_id__in=valid_sku_codes,
                end_date__year=d.year,
                end_date__month=d.month,
            )
            .aggregate(t=Sum('quantity_delivered'))['t'] or 0
        )
        pc_mes = (
            SalesOrderMovement.objects
            .filter(
                product_id__in=valid_sku_codes,
                delivery_date__year=d.year,
                delivery_date__month=d.month,
            )
            .aggregate(t=Sum('quantity'))['t'] or 0
        )
        of_data.append(int(of_mes))
        pc_data.append(int(pc_mes))

    return JsonResponse({
        'labels': labels,
        'datasets': [
            {
                'label': 'Consumo OFs (unidades)',
                'data': of_data,
                'borderColor': '#7c3aed',
                'backgroundColor': '#7c3aed22',
                'tension': 0.3,
                'fill': True,
                'yAxisID': 'y',
            },
            {
                'label': 'Despacho PCs (unidades)',
                'data': pc_data,
                'borderColor': '#0099DE',
                'backgroundColor': '#0099DE22',
                'tension': 0.3,
                'fill': True,
                'yAxisID': 'y',
            },
        ]
    })
