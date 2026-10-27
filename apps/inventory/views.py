from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.db import transaction
from django.db.models import Sum, Count, Q
from django.core.paginator import Paginator

from .models import ProductSKU, InventoryMetric, StockProjection, Warehouse, Category
from .stock_actual_models import StockActual, CargaStockActual



@login_required
def sku_detail_view(request, code):
    import json
    import datetime
    from collections import defaultdict

    sku = get_object_or_404(
        ProductSKU.objects.select_related('category', 'classification'),
        code=code
    )
    metrics = InventoryMetric.objects.filter(product=sku).select_related('warehouse').order_by('warehouse__code')
    projections = StockProjection.objects.filter(product=sku).select_related('warehouse', 'transfer_source_warehouse').order_by('warehouse__code')
    classification = getattr(sku, 'classification', None)

    # Movimientos históricos tabulares (OFs Cerradas y Pedidos Clientes Cerrados)
    of_movements = sku.of_movements.filter(status='Cerrada').order_by('-end_date')[:25]
    sales_movements = sku.sales_movements.filter(status='Cerrado').order_by('-delivery_date')[:25]

    # ── AGREGACIÓN MENSUAL PARA CHART.JS (Requerimiento Minuta 21/10/2026) ────
    today = datetime.date.today()
    meses_nombres = ['', 'Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun', 'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic']

    # 1. Últimos 12 meses históricos en orden cronológico
    month_keys = []
    monthly_labels = []
    for i in range(11, -1, -1):
        year = today.year
        month = today.month - i
        while month <= 0:
            month += 12
            year -= 1
        m_key = f"{year}-{month:02d}"
        month_keys.append((year, month, m_key))
        monthly_labels.append(f"{meses_nombres[month]} {year}")

    start_date = datetime.date(month_keys[0][0], month_keys[0][1], 1)

    of_by_month = defaultdict(float)
    pc_by_month = defaultdict(float)

    # Consumos de taller en OFs
    for m in sku.of_movements.filter(status='Cerrada', end_date__gte=start_date):
        if m.end_date:
            key = f"{m.end_date.year}-{m.end_date.month:02d}"
            of_by_month[key] += float(m.quantity_delivered or 0)

    # Ventas/despachos en Pedidos de Clientes
    for s in sku.sales_movements.filter(status='Cerrado', delivery_date__gte=start_date):
        if s.delivery_date:
            key = f"{s.delivery_date.year}-{s.delivery_date.month:02d}"
            pc_by_month[key] += float(s.quantity or 0)

    chart_of_data = [round(of_by_month[k[2]], 1) for k in month_keys]
    chart_pc_data = [round(pc_by_month[k[2]], 1) for k in month_keys]
    chart_hist_total = [round(chart_of_data[idx] + chart_pc_data[idx], 1) for idx in range(len(month_keys))]

    # 2. Proyección futura a 6 meses (Forecast mensual)
    avg_m = float(classification.avg_monthly_consumption or 0) if classification else (sum(chart_hist_total) / 12.0)
    future_labels = []
    for j in range(1, 7):
        year = today.year
        month = today.month + j
        while month > 12:
            month -= 12
            year += 1
        future_labels.append(f"{meses_nombres[month]} {year} (P)")

    all_labels = monthly_labels + future_labels
    hist_combined = chart_hist_total + [None] * 6
    proj_combined = [None] * (len(month_keys) - 1) + [chart_hist_total[-1] if chart_hist_total else avg_m] + [round(avg_m, 1)] * 6

    # Lead time efectivo (+2 días logística recepción)
    sap_lt = sku.lead_time_days or 30
    eff_lt = sap_lt + 2

    rop_val = classification.rop_statistical if classification else 0
    ss_val = classification.safety_stock_statistical if classification else 0

    context = {
        'sku': sku,
        'classification': classification,
        'metrics': metrics,
        'projections': projections,
        'of_movements': of_movements,
        'sales_movements': sales_movements,
        # Variables de Lead Time logístico
        'sap_lead_time': sap_lt,
        'effective_lead_time': eff_lt,
        # Variables para Chart.js
        'chart_labels_json': json.dumps(all_labels),
        'chart_of_json': json.dumps(chart_of_data + [None] * 6),
        'chart_pc_json': json.dumps(chart_pc_data + [None] * 6),
        'chart_hist_json': json.dumps(hist_combined),
        'chart_proj_json': json.dumps(proj_combined),
        'chart_rop': rop_val,
        'chart_safety_stock': ss_val,
        'chart_avg_monthly': round(avg_m, 1),
    }
    return render(request, 'inventory/sku_detail.html', context)


# ─── STOCK ACTUAL DE BODEGAS SAP (adaptado de CiroCortes/sistemaPedidosPesco) ───

@login_required
def cargar_stock_actual(request):
    """Redirecciona a la consulta de stock actual (la ingesta se gestiona en Sincronizar Datos)."""
    return redirect('inventory:consultar_stock_actual')


@login_required
def consultar_stock_actual(request):
    """Consulta paginada del stock actual por codigo/descripcion/bodega."""
    query = request.GET.get('q', '')
    bodega = request.GET.get('bodega', '')

    qs = StockActual.objects.all().order_by('codigo', 'bodega')
    if query:
        qs = qs.filter(Q(codigo__icontains=query) | Q(descripcion__icontains=query))
    if bodega:
        qs = qs.filter(bodega=bodega)

    paginator = Paginator(qs, 50)
    page_obj = paginator.get_page(request.GET.get('page'))
    bodegas = StockActual.objects.values_list('bodega', 'bodega_nombre').distinct().order_by('bodega')

    context = {
        'page_obj': page_obj,
        'query': query,
        'bodega_seleccionada': bodega,
        'bodegas': bodegas,
        'total_resultados': paginator.count,
    }
    return render(request, 'inventory/consultar_stock_actual.html', context)


@login_required
def configuracion_view(request):
    """
    Centro Maestro de Configuración y Alcance S&OP.
    Pestaña 1: Bodegas Operativas a Auditar (Warehouses en S&OP / DRP).
    Pestaña 2: Grupos de Materiales (Categorías SAP).
    Pestaña 3: Tipos y Clases de SKU (Próximo paso).
    """
    active_tab = request.GET.get('tab', 'bodegas')

    if request.method == 'POST':
        action = request.POST.get('action')

        # ── ACCIONES DE BODEGAS ────────────────────────────────────────────────
        if action == 'toggle_warehouse':
            wh_code = request.POST.get('warehouse_code')
            wh = Warehouse.objects.filter(code=wh_code).first()
            if wh and not wh.is_physical:
                messages.warning(request, f"La bodega {wh.code} no es física (tránsito, consignación o no conforme) y no se puede activar.")
            elif wh:
                wh.is_active = not wh.is_active
                wh.save(update_fields=['is_active'])
                if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                    return JsonResponse({'status': 'ok', 'code': wh.code, 'is_active': wh.is_active})
                messages.success(request, f"Bodega '{wh.code} - {wh.name}' {'activada para S&OP' if wh.is_active else 'excluida de auditoría'}.")
            return redirect(f"{request.path}?tab=bodegas")

        elif action == 'save_warehouses':
            active_codes = {c for c in request.POST.getlist('active_warehouses') if Warehouse(code=c).is_physical}
            with transaction.atomic():
                Warehouse.objects.all().update(is_active=False)
                if active_codes:
                    Warehouse.objects.filter(code__in=active_codes).update(is_active=True)
            messages.success(request, f"Se guardó la configuración de bodegas: {len(active_codes)} bodegas activas para auditoría S&OP.")
            return redirect(f"{request.path}?tab=bodegas")

        elif action == 'preset_warehouses_operational':
            # Todas las bodegas fisicas de Santiago (013-xx) y las 5 sucursales
            codes = [w.code for w in Warehouse.objects.all() if w.zone]
            with transaction.atomic():
                Warehouse.objects.all().update(is_active=False)
                Warehouse.objects.filter(code__in=codes).update(is_active=True)
            messages.success(request, f"Preset aplicado: {len(codes)} bodegas físicas activadas (Santiago + Sucursales). Tránsito, consignación y no conformes quedan fuera.")
            return redirect(f"{request.path}?tab=bodegas")

        elif action == 'preset_warehouses_all':
            codes = [w.code for w in Warehouse.objects.all() if w.is_physical]
            Warehouse.objects.filter(code__in=codes).update(is_active=True)
            messages.success(request, f"{len(codes)} bodegas físicas activadas para auditoría S&OP (tránsito, consignación y no conformes no se activan).")
            return redirect(f"{request.path}?tab=bodegas")

        elif action == 'preset_warehouses_stgo':
            codes = [w.code for w in Warehouse.objects.all() if w.is_santiago]
            with transaction.atomic():
                Warehouse.objects.all().update(is_active=False)
                Warehouse.objects.filter(code__in=codes).update(is_active=True)
            messages.success(request, f"Preset aplicado: {len(codes)} bodegas físicas de Santiago activadas.")
            return redirect(f"{request.path}?tab=bodegas")

        elif action == 'recalculate_sop':
            from .classification_engine import run_classification_engine
            try:
                run_classification_engine()
                messages.success(request, "¡Motor S&OP recalculado exitosamente! Las proyecciones y recomendaciones de compra reflejan las bodegas y grupos seleccionados.")
            except Exception as e:
                messages.error(request, f"Error al ejecutar motor S&OP: {str(e)}")
            return redirect(f"{request.path}?tab={active_tab}")

        # ── ACCIONES DE GRUPOS DE MATERIALES (CATEGORÍAS) ──────────────────────
        elif action == 'toggle_single':
            category_code = request.POST.get('category_code')
            cat = Category.objects.filter(code=category_code).first()
            if cat:
                cat.is_active = not cat.is_active
                cat.save(update_fields=['is_active'])
                if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                    return JsonResponse({'status': 'ok', 'code': cat.code, 'is_active': cat.is_active})
                messages.success(request, f"Grupo '{cat.name}' {'activado' if cat.is_active else 'desactivado'}.")
            return redirect(f"{request.path}?tab=grupos")

        elif action == 'save_all':
            active_codes = set(request.POST.getlist('active_categories'))
            with transaction.atomic():
                Category.objects.all().update(is_active=False)
                if active_codes:
                    Category.objects.filter(code__in=active_codes).update(is_active=True)
            messages.success(request, f"Se guardó la configuración: {len(active_codes)} grupos activos.")
            return redirect(f"{request.path}?tab=grupos")

        elif action == 'preset_all':
            Category.objects.all().update(is_active=True)
            messages.success(request, "Todos los grupos fueron activados para S&OP.")
            return redirect(f"{request.path}?tab=grupos")

        elif action == 'preset_none':
            Category.objects.all().update(is_active=False)
            messages.warning(request, "Todos los grupos fueron desactivados.")
            return redirect(f"{request.path}?tab=grupos")

        elif action == 'preset_recommended':
            from .group_types import assign_group_types
            with transaction.atomic():
                assign_group_types(force=True)
            active_count = Category.objects.filter(is_active=True).count()
            messages.success(request, f"Recomendación aplicada: {active_count} grupos se abastecen y {Category.objects.count() - active_count} quedan excluidos (equipos terminados, servicios y gastos).")
            return redirect(f"{request.path}?tab=grupos")

        elif action == 'set_tipo':
            from .group_types import TIPOS
            tipo = request.POST.get('tipo')
            activar = request.POST.get('estado') == 'activar'
            if tipo in TIPOS:
                n = Category.objects.filter(tipo=tipo).update(is_active=activar)
                messages.success(request, f"{n} grupos de tipo '{TIPOS[tipo][0]}' {'activados' if activar else 'excluidos'}.")
            return redirect(f"{request.path}?tab=grupos")

    # ── CARGA DE DATOS PARA GET ────────────────────────────────────────────────
    search_q = request.GET.get('q', '').strip()

    # 1. BODEGAS
    stock_by_bodega = {
        row['bodega']: {
            'skus': row['skus'],
            'total_disp': row['total_disp'] or 0,
            'total_fisico': row['total_fisico'] or 0
        }
        for row in StockActual.objects.values('bodega').annotate(
            skus=Count('id'),
            total_disp=Sum('stock_disponible'),
            total_fisico=Sum('total')
        )
    }

    warehouses_qs = Warehouse.objects.all().order_by('-is_active', 'code')
    if search_q and active_tab == 'bodegas':
        warehouses_qs = warehouses_qs.filter(Q(code__icontains=search_q) | Q(name__icontains=search_q))

    warehouses_list = []
    total_audited_stock = 0
    for w in warehouses_qs:
        stk_info = stock_by_bodega.get(w.code, {})
        w.sku_count = stk_info.get('skus', 0)
        w.stock_disponible = stk_info.get('total_disp', 0)
        w.stock_fisico = stk_info.get('total_fisico', 0)
        w.is_stgo = w.is_santiago
        if w.is_active:
            total_audited_stock += w.stock_disponible
        warehouses_list.append(w)

    total_warehouses = Warehouse.objects.count()
    active_warehouses_count = Warehouse.objects.filter(is_active=True).count()
    inactive_warehouses_count = total_warehouses - active_warehouses_count

    # 2. CATEGORÍAS (grupos de articulos SAP)
    from .group_types import TIPOS
    categories = Category.objects.annotate(
        sku_count=Count('productsku', distinct=True),
        serv_count=Count('productsku', filter=Q(productsku__gestiona_inventario=False), distinct=True),
    ).order_by('name')

    if search_q and active_tab == 'grupos':
        categories = categories.filter(Q(name__icontains=search_q) | Q(code__icontains=search_q))

    # Stock valorizado y SKUs con stock por grupo (bodegas operativas)
    stock_by_cat = {}
    if active_tab == 'grupos':
        per_sku = {}
        for pid, cid, stk, cost in InventoryMetric.objects.values_list(
                'product_id', 'product__category_id', 'stock_physical', 'product__unit_cost_usd'):
            d = per_sku.setdefault(pid, [cid, 0.0, float(cost or 0)])
            d[1] += float(stk or 0)
        for cid, stk, cost in per_sku.values():
            if stk > 0:
                e = stock_by_cat.setdefault(cid, {'skus': 0, 'valor': 0.0})
                e['skus'] += 1
                e['valor'] += stk * cost

    categories = list(categories)
    for c in categories:
        info = stock_by_cat.get(c.id, {})
        c.skus_con_stock = info.get('skus', 0)
        c.valor_stock = info.get('valor', 0.0)
        label, abastece, _ = TIPOS.get(c.tipo, ('Sin clasificar', True, ''))
        c.tipo_label = label
        c.recomendado_activo = abastece

    total_categories = Category.objects.count()
    active_categories_count = Category.objects.filter(is_active=True).count()
    inactive_categories_count = total_categories - active_categories_count

    # Resumen por tipo + alcance en SKUs / USD
    tipos_resumen = []
    if active_tab == 'grupos':
        agg = {}
        for c in categories:
            t = agg.setdefault(c.tipo or 'REVISAR', {'grupos': 0, 'activos': 0, 'skus': 0, 'valor': 0.0})
            t['grupos'] += 1; t['activos'] += c.is_active; t['skus'] += c.sku_count; t['valor'] += c.valor_stock
        for k, (label, abastece, desc) in TIPOS.items():
            if k in agg:
                tipos_resumen.append({'key': k, 'label': label, 'abastece': abastece, 'desc': desc, **agg[k]})
    skus_en_alcance = sum(c.sku_count - c.serv_count for c in categories if c.is_active)
    skus_total = sum(c.sku_count for c in categories)
    valor_en_alcance = sum(c.valor_stock for c in categories if c.is_active)
    valor_excluido = sum(c.valor_stock for c in categories if not c.is_active)

    # 3. TIPOS Y CLASES DE SKU (PREVIEW DEL SIGUIENTE PASO)
    top_clases = (
        ProductSKU.objects.exclude(clase='')
        .values('clase')
        .annotate(sku_count=Count('code'))
        .order_by('-sku_count')[:15]
    )
    top_familias = (
        ProductSKU.objects.exclude(familia='')
        .values('familia')
        .annotate(sku_count=Count('code'))
        .order_by('-sku_count')[:15]
    )
    sap_cats = (
        ProductSKU.objects.exclude(sap_categoria='')
        .values('sap_categoria')
        .annotate(sku_count=Count('code'))
        .order_by('-sku_count')[:15]
    )

    context = {
        'active_tab': active_tab,
        'search_q': search_q,
        # Bodegas
        'warehouses': warehouses_list,
        'total_warehouses': total_warehouses,
        'active_warehouses_count': active_warehouses_count,
        'inactive_warehouses_count': inactive_warehouses_count,
        'total_audited_stock': total_audited_stock,
        # Grupos
        'categories': categories,
        'total_categories': total_categories,
        'active_categories_count': active_categories_count,
        'inactive_categories_count': inactive_categories_count,
        'tipos_resumen': tipos_resumen,
        'skus_en_alcance': skus_en_alcance,
        'skus_total': skus_total,
        'valor_en_alcance': valor_en_alcance,
        'valor_excluido': valor_excluido,
        # Tipos SKU (Próximo paso)
        'top_clases': top_clases,
        'top_familias': top_familias,
        'sap_cats': sap_cats,
    }
    return render(request, 'inventory/configurar_grupos.html', context)


# Alias para retrocompatibilidad
configurar_grupos_view = configuracion_view

