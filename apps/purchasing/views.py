from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.db.models import Sum, Q
from django.core.paginator import Paginator
from apps.inventory.models import StockProjection, Warehouse, Category


@login_required
def purchasing_list_view(request):
    projections = (
        StockProjection.objects
        .select_related(
            'product', 'warehouse',
            'product__category', 'product__classification',
            'transfer_source_warehouse',
        )
        .all()
    )

    # ── Filtros estándar ──────────────────────────────────────────────────────
    selected_wh        = request.GET.get('warehouse', '').strip()
    selected_urgency   = request.GET.get('urgency', '').strip()
    selected_category  = request.GET.get('category', '').strip()
    include_all_groups = request.GET.get('include_all_groups', '').strip() == '1'
    search_query       = request.GET.get('search', '').strip()

    # ── Filtros Slim4 ─────────────────────────────────────────────────────────
    selected_segment     = request.GET.get('segment', '').strip()
    selected_abc         = request.GET.get('abc', '').strip()
    selected_policy      = request.GET.get('policy', '').strip()
    filter_inmovilizado  = request.GET.get('inmovilizado', '').strip()
    filter_nuevo         = request.GET.get('nuevo', '').strip()

    # ── Filtros REPO y Acción DRP (nuevos) ───────────────────────────────────
    selected_repo   = request.GET.get('repo', '').strip()    # R / E / P / O
    selected_action = request.GET.get('action', '').strip()  # COMPRAR / TRASLADAR / MIXTO

    # ── Aplicar filtros ───────────────────────────────────────────────────────
    if selected_wh:
        projections = projections.filter(warehouse__code=selected_wh)
    if selected_urgency:
        projections = projections.filter(urgency_level=selected_urgency)

    if selected_category:
        projections = projections.filter(product__category__code=selected_category)
    elif not include_all_groups:
        projections = projections.filter(product__category__is_active=True)

    if search_query:
        projections = projections.filter(
            Q(product__code__icontains=search_query) |
            Q(product__description__icontains=search_query)
        )

    # Filtros Slim4
    if selected_segment:
        projections = projections.filter(product__classification__segment=selected_segment)
    if selected_abc:
        projections = projections.filter(product__classification__abc_class=selected_abc)
    if selected_policy:
        projections = projections.filter(product__classification__stock_policy=selected_policy)
    if filter_inmovilizado == '1':
        projections = projections.filter(product__classification__is_inmovilizado=True)
    if filter_nuevo == '1':
        projections = projections.filter(product__classification__is_new=True)

    # Filtros REPO
    if selected_repo:
        projections = projections.filter(product__classification__repo_category=selected_repo)
    if selected_action:
        projections = projections.filter(action_type=selected_action)

    # ── KPIs sobre el conjunto filtrado ──────────────────────────────────────
    total_items           = projections.count()
    total_shortage_usd    = float(projections.aggregate(t=Sum('shortage_usd'))['t'] or 0)
    total_suggested_units = projections.aggregate(t=Sum('suggested_buy_units'))['t'] or 0
    urgentes_count        = projections.filter(urgency_level='URGENTE').count()
    si_stock_count        = projections.filter(product__classification__stock_policy='SI_STOCK').count()

    # KPIs REPO
    repo_r_count = projections.filter(product__classification__repo_category='R').count()
    repo_e_count = projections.filter(product__classification__repo_category='E').count()
    repo_p_count = projections.filter(product__classification__repo_category='P').count()
    repo_o_count = projections.filter(product__classification__repo_category='O').count()

    # KPIs Acciones DRP
    action_comprar_count   = projections.filter(action_type='COMPRAR').count()
    action_trasladar_count = projections.filter(action_type='TRASLADAR').count()
    action_mixto_count     = projections.filter(action_type='MIXTO').count()

    projections = projections.order_by('-shortage_usd', '-suggested_buy_units')

    # ── Paginación ────────────────────────────────────────────────────────────
    paginator   = Paginator(projections, 50)
    page_number = request.GET.get('page')
    page_obj    = paginator.get_page(page_number)

    warehouses           = Warehouse.objects.filter(is_active=True).order_by('code')
    categories           = Category.objects.filter(productsku__isnull=False).distinct().order_by('name')
    inactive_groups_count = Category.objects.filter(is_active=False).count()

    context = {
        'page_obj': page_obj,
        'projections': page_obj.object_list,
        'warehouses': warehouses,
        'categories': categories,
        'inactive_groups_count': inactive_groups_count,
        'include_all_groups': include_all_groups,
        # Filtros activos (para mantener estado del formulario)
        'selected_wh': selected_wh,
        'selected_urgency': selected_urgency,
        'selected_category': selected_category,
        'search_query': search_query,
        'selected_segment': selected_segment,
        'selected_abc': selected_abc,
        'selected_policy': selected_policy,
        'filter_inmovilizado': filter_inmovilizado,
        'filter_nuevo': filter_nuevo,
        'selected_repo': selected_repo,
        'selected_action': selected_action,
        # KPIs estándar
        'total_items': total_items,
        'total_shortage_usd': total_shortage_usd,
        'total_suggested_units': total_suggested_units,
        'urgentes_count': urgentes_count,
        'criticos_count': urgentes_count,
        'si_stock_count': si_stock_count,
        # KPIs REPO
        'repo_r_count': repo_r_count,
        'repo_e_count': repo_e_count,
        'repo_p_count': repo_p_count,
        'repo_o_count': repo_o_count,
        # KPIs Acciones DRP
        'action_comprar_count': action_comprar_count,
        'action_trasladar_count': action_trasladar_count,
        'action_mixto_count': action_mixto_count,
    }
    return render(request, 'purchasing/list.html', context)
