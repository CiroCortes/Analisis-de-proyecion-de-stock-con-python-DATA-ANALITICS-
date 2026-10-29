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
    """Panel S&OP (SPEC-28): cifras de la ultima corrida de la Calculadora, en USD."""
    from django.urls import reverse
    from . import panel
    filtros = {c: request.GET.get(c, '').strip() for c in ('grupo', 'letra', 'abc')}
    corrida = panel.ultima_corrida()
    datos = panel.indicadores(corrida, filtros) if corrida else None
    evolucion = panel.evolucion()
    grafico = {
        'nodos': {'labels': [n['nombre'] for n in datos['nodos']], 'faltante': [round(n['faltante_usd']) for n in datos['nodos']]} if datos else {},
        'cobertura': {'labels': [c['tramo'] for c in datos['cobertura']], 'articulos': [c['articulos'] for c in datos['cobertura']]} if datos else {},
        'evolucion': {'labels': [f"{e['fecha']:%d-%m %H:%M} · #{e['id']}" for e in evolucion],
                      'compra': [round(e['compra_hoy_usd']) for e in evolucion]},
    }
    return render(request, 'dashboard/home.html', {
        'corrida': corrida, 'datos': datos, 'filtros': filtros, 'hay_filtros': any(filtros.values()),
        'grupos': Category.objects.filter(is_active=True, productsku__isnull=False).distinct().order_by('name'),
        'letras': panel.LETRAS, 'cargas': panel.cargas_recientes(), 'grafico': grafico,
        'url_articulo': reverse('calculadora:articulo', args=['__SKU__']),
    })


@login_required
def analytics_view(request):
    """Analitica se fusiono en el Panel S&OP (SPEC-28); la URL antigua sigue funcionando."""
    from django.shortcuts import redirect
    from django.urls import reverse
    qs = request.META.get('QUERY_STRING', '')
    return redirect(reverse('dashboard:home') + (f'?{qs}' if qs else ''))


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
            'label': 'Días de demanda faltante',
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
