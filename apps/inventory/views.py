from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.db import transaction
from django.db.models import Sum, Count, Q
from django.core.paginator import Paginator

from django.utils import timezone

from apps.calculadora.parametros import puede_editar
from apps.data_ingestion.warehouses import (NO_CUENTA, NODO_SANTIAGO, STOCK, TRANSITO, TRATAMIENTOS, nodos_red,
                                            nombre_nodo, tratamiento_por_defecto)

from .models import ProductSKU, InventoryMetric, Warehouse, Category
from .stock_actual_models import StockActual, CargaStockActual



@login_required
def sku_detail_view(request, code):
    """Ficha unica del articulo: la de la Calculadora (SPEC-20). Se conserva la URL para
    enlaces y marcadores antiguos."""
    return redirect('calculadora:articulo', code=code)


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


def _stock_alcance_por_bodega():
    """bodega -> (unidades, USD) de stock en articulos del alcance (activos de grupos activos)."""
    costo = dict(ProductSKU.objects.filter(is_active=True, category__is_active=True)
                 .values_list('code', 'unit_cost_usd'))
    out = {}
    for sku, bodega, q in StockActual.objects.filter(stock_disponible__gt=0).values_list(
            'codigo', 'bodega', 'stock_disponible'):
        if sku in costo:
            u, usd = out.get(bodega, (0, 0.0))
            out[bodega] = (u + q, usd + q * float(costo[sku] or 0))
    return out


def _decorar_tratamiento(w, alcance):
    """Atributos de la fila de la bodega: como la usa el calculo (SPEC-27)."""
    tipo, nodo, motivo, manual = w.tratamiento_efectivo
    w.trat_tipo, w.trat_nodo, w.trat_motivo, w.trat_manual = tipo, nodo, motivo, manual
    w.trat_nodo_nombre = nombre_nodo(nodo)
    w.u_alcance, w.usd_alcance = alcance
    if tipo == STOCK:
        w.trat_texto = f'Stock de {w.trat_nodo_nombre}'
    elif tipo == TRANSITO:
        w.trat_texto = f'En camino a {w.trat_nodo_nombre}'
    else:
        w.trat_texto = 'No cuenta'
    # Las bodegas de la red se excluyen o incluyen; la 013 es el propio nodo Santiago
    w.trat_editable = w.code != NODO_SANTIAGO
    auto_tipo, auto_nodo, _ = tratamiento_por_defecto(w.code, w.is_active)
    w.trat_auto = {STOCK: f'Stock de {nombre_nodo(auto_nodo)}', TRANSITO: f'En camino a {nombre_nodo(auto_nodo)}'}.get(
        auto_tipo, 'No cuenta')
    w.trat_valor = (f'{tipo}|{nodo}' if manual else '') if not w.es_de_red else (STOCK if w.is_active else NO_CUENTA)


def _guardar_tratamiento(request):
    """POST AJAX: cambia el tratamiento de una bodega. Valor '' (automatico), 'TIPO|NODO' o, en
    bodegas de la red, STOCK / NO_CUENTA (equivale a incluir o excluir)."""
    if not puede_editar(request.user):
        return JsonResponse({'status': 'error', 'mensaje': 'No tienes permiso para cambiar bodegas'}, status=403)
    w = Warehouse.objects.filter(code=request.POST.get('warehouse_code', '')).first()
    valor = request.POST.get('valor', '').strip()
    motivo = request.POST.get('motivo', '').strip()[:200]
    if not w or w.code == NODO_SANTIAGO:
        return JsonResponse({'status': 'error', 'mensaje': 'Bodega no editable'}, status=400)
    validos_nodo = dict(nodos_red())
    if w.es_de_red:
        if valor not in (STOCK, NO_CUENTA):
            return JsonResponse({'status': 'error', 'mensaje': 'Opción no válida'}, status=400)
        w.is_active = valor == STOCK
    elif valor:
        tipo, _, nodo = valor.partition('|')
        if tipo == NO_CUENTA:
            nodo = ''
        elif tipo not in (STOCK, TRANSITO) or nodo not in validos_nodo:
            return JsonResponse({'status': 'error', 'mensaje': 'Opción no válida'}, status=400)
        w.tratamiento, w.nodo_destino, w.motivo = tipo, nodo, motivo
    else:
        w.tratamiento, w.nodo_destino, w.motivo = '', '', ''
    w.modificado_por, w.modificado_en = request.user, timezone.now()
    w.save(update_fields=['is_active', 'tratamiento', 'nodo_destino', 'motivo', 'modificado_por', 'modificado_en'])
    _decorar_tratamiento(w, (0, 0.0))
    return JsonResponse({'status': 'ok', 'code': w.code, 'texto': w.trat_texto, 'tipo': w.trat_tipo,
                         'motivo': w.trat_motivo, 'manual': w.trat_manual,
                         'quien': f'{request.user.get_username()} · {timezone.localtime(w.modificado_en):%d-%m %H:%M}'})


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

        elif action == 'set_tratamiento':
            return _guardar_tratamiento(request)

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
            from apps.calculadora.servicio import recalcular_red
            try:
                recalcular_red(usuario=request.user)
                messages.success(request, "¡S&OP recalculado! La Calculadora, el Dashboard y el Reporte Gerencial reflejan las bodegas y grupos seleccionados.")
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

    # Tratamiento de cada bodega en el calculo y su stock valorizado en el alcance (SPEC-27)
    valor_alcance = _stock_alcance_por_bodega()
    warehouses_list = []
    resumen_trat = {STOCK: [0, 0.0], TRANSITO: [0, 0.0], NO_CUENTA: [0, 0.0]}
    for w in warehouses_qs:
        stk_info = stock_by_bodega.get(w.code, {})
        w.sku_count = stk_info.get('skus', 0)
        w.stock_disponible = stk_info.get('total_disp', 0)
        w.stock_fisico = stk_info.get('total_fisico', 0)
        w.is_stgo = w.is_santiago
        _decorar_tratamiento(w, valor_alcance.get(w.code, (0, 0.0)))
        resumen_trat[w.trat_tipo][0] += 1
        resumen_trat[w.trat_tipo][1] += w.usd_alcance
        warehouses_list.append(w)
    orden = {STOCK: 0, TRANSITO: 1, NO_CUENTA: 2}
    warehouses_list.sort(key=lambda w: (orden[w.trat_tipo], -w.usd_alcance, w.code))

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
        'total_warehouses': len(warehouses_list),
        'resumen_trat': resumen_trat,
        'nodos_red': nodos_red(),
        'tratamientos': TRATAMIENTOS,
        'puede_editar_bodegas': puede_editar(request.user),
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

