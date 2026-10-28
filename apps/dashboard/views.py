import os
import json
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.db.models import Sum, Count, Q, Avg, Max, F
from django.http import JsonResponse
from django.conf import settings
from apps.inventory.models import ProductSKU, StockProjection, Warehouse, InventoryMetric, Category, SKUClassification, GoodsReceipt
from apps.data_ingestion.warehouses import NODO_SANTIAGO, SUCURSAL_CITIES, nodo_red


def _nodos(codigo=''):
    """Nodos de la red como los calcula la Calculadora (SPEC-21): Santiago (todas las 013) y
    cada sucursal. El stock por bodega 013-xx se ve en la Calculadora, no en gerencia."""
    orden = [NODO_SANTIAGO] + list(SUCURSAL_CITIES)
    por_codigo = {w.code: w for w in Warehouse.objects.filter(code__in=orden)}
    nodos = []
    for c in orden:
        w = por_codigo.get(c)
        if w and (not codigo or c == codigo):
            w.label = 'Santiago' if c == NODO_SANTIAGO else f'{SUCURSAL_CITIES[c]} ({c})'
            nodos.append(w)
    return nodos


def _etiqueta_nodo(codigo):
    nodo = nodo_red(codigo)
    if nodo == NODO_SANTIAGO:
        return 'Santiago'
    return f'{SUCURSAL_CITIES[nodo]} ({nodo})' if nodo in SUCURSAL_CITIES else (codigo or '—')


def _ultimos_meses(n=12):
    """Primer dia de los ultimos n meses calendario (incluye el actual), del mas antiguo al mas reciente."""
    hoy = datetime.date.today()
    total = hoy.year * 12 + hoy.month - 1
    return [datetime.date((total - i) // 12, (total - i) % 12 + 1, 1) for i in range(n - 1, -1, -1)]


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
        warehouse_filter = nodo_red(warehouse_filter) or warehouse_filter
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
    warehouses = _nodos()
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
    target_warehouses = _nodos(f['warehouse'])
    for wh in target_warehouses:
        wh_proj = projections.filter(warehouse=wh)
        wh_crit = wh_proj.filter(urgency_level='URGENTE').count()
        wh_usd = float(wh_proj.aggregate(total=Sum('shortage_usd'))['total'] or 0)
        wh_stats.append({
            'code': wh.label,
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
    warehouses = _nodos()
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

    warehouses = _nodos(f['warehouse'])

    labels = []
    urgente_data, medio_data, normal_data = [], [], []

    for wh in warehouses:
        proj_wh = projections.filter(warehouse=wh)
        labels.append(wh.label)
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

    warehouses = _nodos(f['warehouse'])

    labels, data, colors = [], [], []
    palette = ['#0099DE','#0077B6','#00B4D8','#48CAE4','#90E0EF','#e03131','#f59e0b','#10b981','#7c3aed']

    for i, wh in enumerate(warehouses):
        usd = float(projections.filter(warehouse=wh).aggregate(t=Sum('shortage_usd'))['t'] or 0)
        labels.append(wh.label)
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

    warehouses = _nodos(f['warehouse'])

    datasets = []
    palette = ['#0099DE','#ef4444','#f59e0b','#10b981','#7c3aed','#e03131','#00B4D8','#facc15','#fb923c']

    for i, wh in enumerate(warehouses):
        points = (projections
                  .filter(warehouse=wh)
                  .select_related('product')
                  .values('rop', 'shortage_units', 'urgency_level')[:300])

        scatter = [{'x': float(p['rop']), 'y': float(p['shortage_units'])} for p in points]
        datasets.append({
            'label': wh.label,
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
    warehouses = _nodos()
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
            'bodega': _etiqueta_nodo(p.warehouse.code) if p.warehouse else '—',
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
    Grafico 1: % de lineas de PC y OF cumplidas por mes de emision y por nodo.
    = lineas ya cerradas / (cerradas + las que siguen abiertas). Antes se dividian cerradas por
    cerradas (la tabla de movimientos solo guarda cerrados) y siempre daba 100%.
    Los meses recientes salen mas bajos porque sus pedidos todavia estan en curso.
    """
    from apps.calculadora.models import CompromisoAbierto

    projections = StockProjection.objects.all()
    projections, f = _apply_filters(projections, request)
    warehouses = _nodos(f['warehouse'])
    meses_dt = _ultimos_meses(12)
    meses_str = [f"{d.year}-{d.month:02d}" for d in meses_dt]
    desde = meses_dt[0]
    valid_sku_codes = set(projections.values_list('product__code', flat=True).distinct())

    data_by_group = {w.label: {m: {'t': 0, 'c': 0} for m in meses_str} for w in warehouses}

    def sumar(filas, cerradas):
        for wh_code, month_dt, n in filas:
            if not month_dt:
                continue
            grupo = data_by_group.get(_etiqueta_nodo((wh_code or '').strip().upper()))
            m_str = f"{month_dt.year}-{month_dt.month:02d}"
            if grupo is not None and m_str in grupo:
                grupo[m_str]['t'] += n
                if cerradas:
                    grupo[m_str]['c'] += n

    def por_mes(qs, campo_fecha):
        return qs.annotate(month=TruncMonth(campo_fecha)).values('warehouse', 'month').annotate(n=Count('id')) \
                 .values_list('warehouse', 'month', 'n')

    sumar(por_mes(ProductionOrderMovement.objects.filter(product_id__in=valid_sku_codes, start_date__gte=desde),
                  'start_date'), cerradas=True)
    sumar(por_mes(SalesOrderMovement.objects.filter(product_id__in=valid_sku_codes, emission_date__gte=desde),
                  'emission_date'), cerradas=True)
    abiertas = (CompromisoAbierto.objects.filter(product_id__in=valid_sku_codes, fecha_emision__gte=desde)
                .annotate(month=TruncMonth('fecha_emision')).values('bodega', 'month').annotate(n=Count('id'))
                .values_list('bodega', 'month', 'n'))
    sumar(abiertas, cerradas=False)

    palette = ['#0099DE', '#ef4444', '#f59e0b', '#10b981', '#7c3aed', '#e03131']
    datasets = []
    for idx, (group_name, meses_data) in enumerate(data_by_group.items()):
        data = [round(meses_data[m]['c'] / meses_data[m]['t'] * 100, 1) if meses_data[m]['t'] else None
                for m in meses_str]
        if not any(v is not None for v in data):
            continue
        color = palette[idx % len(palette)]
        datasets.append({
            'label': group_name, 'data': data, 'borderColor': color, 'backgroundColor': color + '22',
            'tension': 0.3, 'fill': False, 'pointRadius': 4, 'spanGaps': True,
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
    meses = [f"{d.year}-{d.month:02d}" for d in _ultimos_meses(12)]
        
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
            'bodega': _etiqueta_nodo(p.warehouse.code) if p.warehouse else '—',
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
    meses_dt = _ultimos_meses(12)

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
