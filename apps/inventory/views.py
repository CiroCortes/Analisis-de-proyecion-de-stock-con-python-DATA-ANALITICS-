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
    sku = get_object_or_404(
        ProductSKU.objects.select_related('category', 'classification'),
        code=code
    )
    metrics = InventoryMetric.objects.filter(product=sku).select_related('warehouse').order_by('warehouse__code')
    projections = StockProjection.objects.filter(product=sku).select_related('warehouse', 'transfer_source_warehouse').order_by('warehouse__code')
    
    # Movimientos históricos (OFs Cerradas y Pedidos Clientes Cerrados)
    of_movements = sku.of_movements.filter(status='Cerrada').order_by('-end_date')[:25]
    sales_movements = sku.sales_movements.filter(status='Cerrado').order_by('-delivery_date')[:25]

    context = {
        'sku': sku,
        'classification': getattr(sku, 'classification', None),
        'metrics': metrics,
        'projections': projections,
        'of_movements': of_movements,
        'sales_movements': sales_movements,
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
def configurar_grupos_view(request):
    """
    Panel de Configuración de Grupos de Materiales / SKU.
    Permite incluir/excluir grupos por defecto del análisis y sugerencias S&OP.
    """
    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'toggle_single':
            category_code = request.POST.get('category_code')
            cat = Category.objects.filter(code=category_code).first()
            if cat:
                cat.is_active = not cat.is_active
                cat.save(update_fields=['is_active'])
                if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                    return JsonResponse({'status': 'ok', 'code': cat.code, 'is_active': cat.is_active})
                messages.success(request, f"Grupo '{cat.name}' {'activado' if cat.is_active else 'desactivado'}.")
            return redirect('inventory:configurar_grupos')

        elif action == 'save_all':
            active_codes = set(request.POST.getlist('active_categories'))
            with transaction.atomic():
                Category.objects.all().update(is_active=False)
                if active_codes:
                    Category.objects.filter(code__in=active_codes).update(is_active=True)
            messages.success(request, f"Se guardó la configuración: {len(active_codes)} grupos activos.")
            return redirect('inventory:configurar_grupos')

        elif action == 'preset_all':
            Category.objects.all().update(is_active=True)
            messages.success(request, "Todos los grupos fueron activados para S&OP.")
            return redirect('inventory:configurar_grupos')

        elif action == 'preset_none':
            Category.objects.all().update(is_active=False)
            messages.warning(request, "Todos los grupos fueron desactivados.")
            return redirect('inventory:configurar_grupos')

        elif action == 'preset_rpts_panol':
            # Activar solo repuestos y pañol, excluir servicios, camiones y equipos completos
            with transaction.atomic():
                Category.objects.all().update(is_active=True)
                excluded_patterns = ['SERVICIO', 'CHASIS', 'CAMIONES', 'TITANIUM', 'TERCEROS']
                q_exclude = Q()
                for p in excluded_patterns:
                    q_exclude |= Q(name__icontains=p)
                Category.objects.filter(q_exclude).update(is_active=False)
            active_count = Category.objects.filter(is_active=True).count()
            messages.success(request, f"Preset aplicado: {active_count} grupos de Repuestos y Pañol activos (Servicios y Camiones excluidos).")
            return redirect('inventory:configurar_grupos')

    # GET
    search_q = request.GET.get('q', '').strip()
    categories = Category.objects.annotate(
        sku_count=Count('productsku', distinct=True),
        criticos_count=Count('productsku__projections', filter=Q(productsku__projections__urgency_level='CRITICO'), distinct=True),
        total_shortage=Sum('productsku__projections__shortage_usd')
    ).order_by('name')

    if search_q:
        categories = categories.filter(Q(name__icontains=search_q) | Q(code__icontains=search_q))

    total_categories = categories.count()
    active_count = Category.objects.filter(is_active=True).count()
    inactive_count = total_categories - active_count

    context = {
        'categories': categories,
        'search_q': search_q,
        'total_categories': total_categories,
        'active_count': active_count,
        'inactive_count': inactive_count,
    }
    return render(request, 'inventory/configurar_grupos.html', context)

