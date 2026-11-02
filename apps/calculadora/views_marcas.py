"""Pantallas de SPEC-31: marcas de gestion (equipos de gerencia y excluidos del calculo) y ABC
por venta. La logica de las marcas vive en marcas.py; la del ABC en apps.calc.clasificacion."""
from collections import defaultdict

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone

from apps.calc.clasificacion import clases_abc, es_candidato_gerencia
from apps.data_ingestion.warehouses import nodo_red, nodos_red, nombre_nodo
from apps.inventory.models import ProductSKU

from . import marcas
from .models import ArticuloConfig, CargaDatos, ResultadoArticulo, VentaMensual
from .parametros import Resolutor, puede_editar
from .servicio import meses_cerrados

TABS = [('gerencia', 'Equipos de gerencia'), ('excluir', 'Excluir del cálculo')]


def _volver(request):
    destino = request.POST.get('next') or ''
    if destino.startswith('/') and not destino.startswith('//'):
        return redirect(destino)
    return redirect(reverse('calculadora:marcas'))


def _guardar(request):
    """Aplica la accion del formulario. Devuelve el mensaje de exito o lanza ValueError."""
    post = request.POST
    accion = post.get('accion')
    if accion == 'plan':
        producto = ProductSKU.objects.get(code=post.get('codigo', ''))
        cfg = marcas.config_de(producto)
        marcas.aplicar_plan(cfg, post.get('plan_gerencia') == 'on', marcas.unidades_desde_texto(post.get('plan_unidades')),
                            marcas.mes_desde_texto(post.get('plan_hasta')))
        cfg.actualizado_por = request.user
        cfg.save()
        return f'{producto.code}: plan de gerencia {"guardado" if cfg.plan_gerencia else "quitado"}.'
    if accion in ('excluir', 'incluir'):
        codigos = [c for c in post.getlist('codigos') if c]
        if not codigos:
            raise ValueError('Selecciona al menos un artículo')
        excluir = accion == 'excluir'
        motivo, nota = post.get('motivo_exclusion', ''), post.get('nota')
        n = 0
        for producto in ProductSKU.objects.filter(code__in=codigos):
            cfg = marcas.config_de(producto)
            marcas.aplicar_exclusion(cfg, excluir, motivo, nota if excluir and nota else None)
            cfg.actualizado_por = request.user
            cfg.save()
            n += 1
        return f'{n} artículo(s) {"excluidos del cálculo" if excluir else "vuelven al cálculo"}.'
    raise ValueError('Acción desconocida')


@login_required
def marcas_view(request):
    if request.method == 'POST':
        if not puede_editar(request.user):
            messages.error(request, 'Solo el Administrador de Abastecimiento puede cambiar las marcas.')
        else:
            try:
                messages.success(request, _guardar(request) + ' Se aplica en el próximo cálculo (Hoy → Recalcular).')
            except (ValueError, ProductSKU.DoesNotExist) as exc:
                messages.error(request, str(exc) if isinstance(exc, ValueError) else 'Artículo no encontrado.')
        return _volver(request)

    tab = request.GET.get('tab', 'gerencia')
    tab = tab if tab in dict(TABS) else 'gerencia'
    params = Resolutor().general
    configs = {c.product_id: c for c in ArticuloConfig.objects.filter(Q(plan_gerencia=True) | Q(excluir_calculo=True))}
    contexto = {'tab': tab, 'tabs': TABS, 'puede_editar': puede_editar(request.user), 'params': params,
                'motivos': ArticuloConfig.MOTIVOS_EXCLUSION, 'n_gerencia': sum(c.plan_gerencia for c in configs.values()),
                'n_excluidos': sum(c.excluir_calculo for c in configs.values())}
    resultados = ResultadoArticulo.objects.select_related('product')
    if tab == 'gerencia':
        marcados = [c for c, cfg in configs.items() if cfg.plan_gerencia]
        filas = []
        for r in resultados.filter(Q(costo_unitario__gte=params.umbral_costo_equipo_usd) | Q(product_id__in=marcados)):
            cfg = configs.get(r.product_id)
            marcado = bool(cfg and cfg.plan_gerencia)
            if not marcado and not es_candidato_gerencia(r.costo_unitario, r.meses_con_consumo_12m, params):
                continue
            filas.append({'r': r, 'cfg': cfg, 'marcado': marcado, 'consumo12': sum(r.consumo_meses[-12:] or [])})
        filas.sort(key=lambda f: (not f['marcado'], -f['r'].valor_sugerido, -f['r'].costo_unitario))
        contexto.update(filas=filas, valor_candidatos=sum(f['r'].valor_sugerido for f in filas if not f['marcado']))
    else:
        f = {k: request.GET.get(k, '').strip() for k in ('search', 'segmento', 'grupo', 'ver')}
        qs = resultados
        if f['ver'] == 'excluidos':
            qs = qs.filter(product_id__in=[c for c, cfg in configs.items() if cfg.excluir_calculo])
        if f['search']:
            qs = qs.filter(Q(product__code__icontains=f['search']) | Q(product__description__icontains=f['search']))
        if f['segmento']:
            qs = qs.filter(segmento=f['segmento'])
        if f['grupo']:
            qs = qs.filter(product__sap_group_code=f['grupo'])
        qs = qs.order_by('-valor_sugerido', 'product__code')
        page_obj = Paginator(qs, 100).get_page(request.GET.get('page'))
        params_url = request.GET.copy()
        params_url.pop('page', None)
        contexto.update(f=f, page_obj=page_obj, configs=configs, query_sin_pagina=params_url.urlencode(),
                        total_filtro=page_obj.paginator.count)
    return render(request, 'calculadora/marcas.html', contexto)


def ventas_por_articulo(nodo='', hoy=None):
    """sku -> venta neta USD de los ultimos 12 meses cerrados, de la red o de un nodo (SPEC-31 §4)."""
    hoy = hoy or timezone.localdate()
    meses = meses_cerrados(hoy, 12)
    ventas = defaultdict(float)
    for sku, bodega, monto in VentaMensual.objects.filter(mes__gte=meses[0], mes__lte=meses[-1]).values_list(
            'product_id', 'bodega', 'monto_usd'):
        if not nodo or nodo_red(bodega) == nodo:
            ventas[sku] += monto
    return ventas


@login_required
def abc_venta(request):
    nodo = request.GET.get('nodo', '').strip()
    nodos = dict(nodos_red())
    nodo = nodo if nodo in nodos else ''
    params = Resolutor().general
    excluidos = set(ArticuloConfig.objects.filter(excluir_calculo=True).values_list('product_id', flat=True))
    ventas = {s: v for s, v in ventas_por_articulo(nodo).items() if s not in excluidos}
    clases = clases_abc(ventas, params) if ventas else {}
    total = sum(v for v in ventas.values() if v > 0)
    resultados = {r.product_id: r for r in ResultadoArticulo.objects.filter(product_id__in=list(ventas))
                  .select_related('product')}
    filas, acumulado, resumen = [], 0.0, {c: [0, 0.0] for c in 'ABC'}
    for sku, venta in sorted(ventas.items(), key=lambda kv: -kv[1]):
        if venta <= 0:
            continue
        acumulado += venta
        clase = clases.get(sku, 'C')
        resumen[clase][0] += 1
        resumen[clase][1] += venta
        filas.append({'sku': sku, 'r': resultados.get(sku), 'venta': venta, 'clase': clase,
                      'participacion': venta / total if total else 0, 'acumulado': acumulado / total if total else 0})
    ultima = CargaDatos.objects.filter(tabla='ventas').first()
    page_obj = Paginator(filas, 100).get_page(request.GET.get('page'))
    return render(request, 'calculadora/abc_venta.html', {
        'page_obj': page_obj, 'nodo': nodo, 'nodo_nombre': nombre_nodo(nodo) if nodo else 'Toda la red',
        'nodos': nodos_red(), 'total': total, 'resumen': [(c, n, v) for c, (n, v) in resumen.items()],
        'ultima_carga': ultima, 'sin_datos': not filas, 'params': params,
    })
