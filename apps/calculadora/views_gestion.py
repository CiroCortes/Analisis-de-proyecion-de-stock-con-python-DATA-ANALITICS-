"""Vistas de gestion de la Calculadora (SPEC-18 §4.2): solicitudes de compra, traslados,
alertas, eventos comerciales, parametros y calendario de proveedores.

La logica de negocio vive en solicitudes.py, parametros.py y apps.calc; aqui solo se leen
los formularios, se llama a esas funciones y se arma el contexto de las pantallas.
"""
import datetime
from collections import OrderedDict

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Case, CharField, Count, F, FloatField, IntegerField, Max, Min, Q, Sum, Value, When
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.calc import calendario
from apps.calc.params import CATALOGO, DEFAULTS, GENERAL, tipo_de, validar
from apps.inventory.models import ProductSKU, Warehouse

from . import parametros as par
from . import solicitudes as sol
from .excel import respuesta_excel
from .models import (Alerta, CompromisoDetalle, Corrida, EventoComercial, LineaSolicitud, OCAbierta, ParametroCambio, ParametroValor, Proveedor,
                     ResultadoArticulo, SolicitudCompra, TrasladoSugerido)


def _volver(request, defecto):
    """Redirige a `next` si es una ruta interna; si no, al destino por defecto."""
    destino = request.POST.get('next') or request.GET.get('next') or ''
    if destino.startswith('/') and not destino.startswith('//'):
        return redirect(destino)
    return redirect(defecto)


def _mes(texto):
    """'2026-11' (input type=month) -> date(2026, 11, 1)."""
    try:
        return datetime.date(int(texto[:4]), int(texto[5:7]), 1)
    except (TypeError, ValueError, IndexError):
        return None


# ── Solicitudes de compra ─────────────────────────────────────────────────────

@login_required
def solicitudes(request):
    qs = SolicitudCompra.objects.select_related('proveedor', 'aprobada_por').annotate(
        n_lineas=Count('lineas', filter=~Q(lineas__estado=LineaSolicitud.DESCARTADA)),
        n_sin_contrato=Count('lineas', filter=Q(lineas__sin_contrato=True)),
        n_saldo=Count('lineas', filter=Q(lineas__saldo_insuficiente=True)),
        n_duplicadas=Count('lineas', filter=Q(lineas__duplicada_reciente=True)),
        n_excepciones=Count('lineas', filter=Q(lineas__excepcion=True)),
        orden_estado=Case(
            When(estado=SolicitudCompra.BORRADOR, then=Value(0)),
            When(estado=SolicitudCompra.APROBADA, then=Value(1)),
            When(estado=SolicitudCompra.EXPORTADA, then=Value(2)),
            default=Value(3), output_field=IntegerField(),
        ),
    ).prefetch_related('lineas')

    f = {k: request.GET.get(k, '').strip() for k in ('estado', 'tipo', 'proveedor', 'fecha')}
    if f['estado']:
        qs = qs.filter(estado=f['estado'])
    if f['tipo']:
        qs = qs.filter(tipo=f['tipo'])
    if f['proveedor']:
        qs = qs.filter(Q(proveedor__codigo__icontains=f['proveedor']) | Q(proveedor__nombre__icontains=f['proveedor']))
    if f['fecha']:
        qs = qs.filter(fecha=f['fecha'])
    qs = qs.order_by('orden_estado', '-fecha', 'proveedor_id')

    paginator = Paginator(qs, 50)
    page_obj = paginator.get_page(request.GET.get('page'))

    grupos = OrderedDict()
    for s in page_obj.object_list:
        grupos.setdefault(s.get_estado_display(), []).append(s)

    dia_compra = (ResultadoArticulo.objects.filter(es_dia_compra=True, proveedor__isnull=False)
                  .values('proveedor_id', 'proveedor__nombre')
                  .annotate(n=Count('pk'), n_comprar=Count('pk', filter=Q(comprar=True)),
                            valor=Sum('valor_sugerido', filter=Q(comprar=True)))
                  .filter(n_comprar__gt=0).order_by('-valor'))
    excepciones = ResultadoArticulo.objects.filter(excepcion=True, cantidad_excepcion__gt=0)
    conteo_estados = dict(SolicitudCompra.objects.values_list('estado').annotate(n=Count('pk')))
    estados = SolicitudCompra._meta.get_field('estado').choices

    return render(request, 'calculadora/solicitudes.html', {
        'page_obj': page_obj, 'grupos': grupos, 'f': f,
        'estados': estados,
        'resumen_estados': [(c, e, conteo_estados.get(c, 0)) for c, e in estados],
        'tipos': SolicitudCompra._meta.get_field('tipo').choices,
        'dia_compra': dia_compra[:30], 'n_dia_compra': dia_compra.count(),
        'n_excepciones': excepciones.count(),
        'n_excepciones_sin_proveedor': excepciones.filter(proveedor__isnull=True).count(),
        'conteo_estados': conteo_estados,
        'hoy': timezone.localdate(),
    })


@login_required
@require_POST
def solicitudes_generar(request):
    proveedor = request.POST.get('proveedor', '').strip() or None
    creadas = sol.generar(usuario=request.user, proveedor=proveedor)
    if creadas:
        n_lineas = sum(s.lineas.count() for s in creadas)
        messages.success(request, f'Se armaron {len(creadas)} solicitudes con {n_lineas} lineas. Revisalas y apruebalas.')
    else:
        messages.success(request, 'No hay articulos para comprar hoy (ni dia de compra ni excepciones con proveedor).')
    return _volver(request, reverse('calculadora:solicitudes'))


@login_required
def solicitudes_exportar(request):
    qs = SolicitudCompra.objects.select_related('proveedor')
    ids = [int(x) for x in request.GET.get('ids', '').split(',') if x.strip().isdigit()]
    if ids:
        qs = qs.filter(pk__in=ids)
    else:
        qs = qs.filter(estado=request.GET.get('estado') or SolicitudCompra.APROBADA)
    lista = list(qs)
    filas = sol.filas_exportacion(lista)
    if not filas:
        messages.error(request, 'No hay lineas para exportar con ese filtro.')
        return redirect('calculadora:solicitudes')
    sol.marcar_exportadas(lista)
    return respuesta_excel(f'solicitudes_compra_{timezone.localdate():%Y%m%d}.xlsx', filas, 'Solicitudes')


@login_required
def solicitud_detalle(request, pk):
    s = get_object_or_404(SolicitudCompra.objects.select_related('proveedor', 'creada_por', 'aprobada_por'), pk=pk)
    lineas = list(s.lineas.select_related('product').order_by('-excepcion', 'urgencia', 'product_id'))
    activas = [l for l in lineas if l.estado != LineaSolicitud.DESCARTADA]
    return render(request, 'calculadora/solicitud_detalle.html', {
        's': s, 'lineas': lineas,
        'valor_total': sum(l.valor for l in activas),
        'n_activas': len(activas),
        'hay_duplicadas': any(l.duplicada_reciente for l in activas),
        'n_sin_contrato': sum(1 for l in activas if l.sin_contrato),
        'n_saldo': sum(1 for l in activas if l.saldo_insuficiente),
        'editable': s.estado == SolicitudCompra.BORRADOR,
        'puede_aprobar': par.puede_aprobar(request.user),
    })


@login_required
@require_POST
def solicitud_linea(request, pk, lpk):
    linea = get_object_or_404(LineaSolicitud.objects.select_related('solicitud'), pk=lpk, solicitud_id=pk)
    try:
        sol.editar_linea(linea, request.POST.get('cantidad', '').replace(',', '.') or 0,
                         request.POST.get('motivo', ''), request.user)
        messages.success(request, f'Linea {linea.product_id} actualizada.')
    except ValueError as exc:
        messages.error(request, f'{linea.product_id}: {exc}')
    return redirect('calculadora:solicitud_detalle', pk=pk)


@login_required
@require_POST
def solicitud_aprobar(request, pk):
    s = get_object_or_404(SolicitudCompra, pk=pk)
    if not par.puede_aprobar(request.user):
        messages.error(request, 'Solo el Jefe o el Administrador de Abastecimiento pueden aprobar solicitudes.')
        return redirect('calculadora:solicitud_detalle', pk=pk)
    duplicadas = s.lineas.filter(duplicada_reciente=True).exclude(estado=LineaSolicitud.DESCARTADA).exists()
    if duplicadas and request.POST.get('confirmar_duplicadas') != '1':
        messages.error(request, 'Hay articulos con otra solicitud abierta de los ultimos 15 dias: '
                                'revisalos y marca la confirmacion antes de aprobar.')
        return redirect('calculadora:solicitud_detalle', pk=pk)
    try:
        sol.aprobar(s, request.user)
        messages.success(request, f'Solicitud {s.pk} aprobada. Ya cuenta como transito en el proximo calculo.')
    except ValueError as exc:
        messages.error(request, str(exc))
    return redirect('calculadora:solicitud_detalle', pk=pk)


@login_required
@require_POST
def solicitud_descartar(request, pk):
    s = get_object_or_404(SolicitudCompra, pk=pk)
    motivo = request.POST.get('motivo', '').strip()
    if not motivo:
        messages.error(request, 'Indica el motivo para descartar la solicitud.')
        return redirect('calculadora:solicitud_detalle', pk=pk)
    try:
        sol.descartar(s, request.user, motivo)
        messages.success(request, f'Solicitud {s.pk} descartada.')
    except ValueError as exc:
        messages.error(request, str(exc))
    return redirect('calculadora:solicitud_detalle', pk=pk)


# ── Traslados ────────────────────────────────────────────────────────────────

def _traslados_filtrados(request):
    qs = TrasladoSugerido.objects.select_related('product', 'origen', 'destino')
    f = {k: request.GET.get(k, '').strip() for k in ('origen', 'destino', 'urgencia', 'search')}
    if f['origen']:
        qs = qs.filter(origen__code=f['origen'])
    if f['destino']:
        qs = qs.filter(destino__code=f['destino'])
    if f['urgencia']:
        qs = qs.filter(urgencia=f['urgencia'])
    if f['search']:
        qs = qs.filter(Q(product__code__icontains=f['search']) | Q(product__description__icontains=f['search']))
    return qs.order_by('origen__code', 'destino__code', '-cantidad'), f


@login_required
def traslados(request):
    qs, f = _traslados_filtrados(request)
    filas = list(qs)
    grupos = OrderedDict()
    for t in filas:
        g = grupos.setdefault((t.origen.code, t.destino.code), {'origen': t.origen, 'destino': t.destino,
                                                                 'filas': [], 'unidades': 0, 'urgentes': 0})
        g['filas'].append(t)
        g['unidades'] += t.cantidad
        g['urgentes'] += t.urgencia == 'URGENTE'
    codigos = TrasladoSugerido.objects.values_list('origen__code', 'destino__code')
    return render(request, 'calculadora/traslados.html', {
        'grupos': list(grupos.values()), 'f': f,
        'total_lineas': len(filas), 'total_unidades': sum(t.cantidad for t in filas),
        'total_urgentes': sum(1 for t in filas if t.urgencia == 'URGENTE'),
        'origenes': sorted({o for o, _ in codigos}), 'destinos': sorted({d for _, d in codigos}),
    })


@login_required
def traslados_excel(request):
    qs, _ = _traslados_filtrados(request)
    filas = [{
        'Origen': t.origen.code, 'Destino': t.destino.code, 'Articulo': t.product_id,
        'Descripcion': t.product.description, 'Cantidad': t.cantidad, 'Urgencia': t.urgencia, 'Estado': t.estado,
    } for t in qs]
    return respuesta_excel(f'traslados_sugeridos_{timezone.localdate():%Y%m%d}.xlsx', filas, 'Traslados')


# ── Antiguedad de compromisos abiertos (SPEC-23 §3) ─────────────────────────

TRAMOS = [('0-3', '0 a 3 meses'), ('3-6', '3 a 6 meses'), ('6-12', '6 a 12 meses'), ('12+', 'Más de 12 meses')]


def _tramo_expr(hoy):
    from .servicio import _restar_meses
    c3, c6, c12 = (_restar_meses(hoy, m) for m in (3, 6, 12))
    return Case(When(fecha_emision__gte=c3, then=Value('0-3')), When(fecha_emision__gte=c6, then=Value('3-6')),
                When(fecha_emision__gte=c12, then=Value('6-12')), default=Value('12+'), output_field=CharField())


def _compromisos_filtrados(request):
    f = {k: request.GET.get(k, '').strip() for k in ('tipo', 'tramo', 'nodo', 'responsable', 'search')}
    qs = CompromisoDetalle.objects.annotate(
        tramo=_tramo_expr(timezone.localdate()),
        valor=F('cantidad') * F('costo_unitario'))
    if f['tipo']:
        qs = qs.filter(tipo=f['tipo'])
    if f['tramo']:
        qs = qs.filter(tramo=f['tramo'])
    if f['nodo']:
        qs = qs.filter(nodo=f['nodo'])
    if f['responsable']:
        qs = qs.filter(responsable=f['responsable'])
    if f['search']:
        qs = qs.filter(Q(numero=f['search'].replace('.', '').replace(',', '')) | Q(codigo_sku__icontains=f['search'])
                       | Q(nombre_cliente__icontains=f['search']) | Q(referencia__icontains=f['search']))
    return qs, f


def _documentos(qs):
    return (qs.values('tipo', 'numero')
            .annotate(emision=Min('fecha_emision'), entrega=Max('fecha_entrega'), cliente=Max('nombre_cliente'),
                      responsable_doc=Max('responsable'), referencia_doc=Max('referencia'), nodo_doc=Max('nodo'),
                      tramo_doc=Max('tramo'), lineas=Count('pk'), unidades=Sum('cantidad'),
                      valor_doc=Sum('valor', output_field=FloatField()))
            .order_by('emision', 'numero'))


@login_required
def compromisos(request):
    qs, f = _compromisos_filtrados(request)
    hoy = timezone.localdate()
    resumen = {(r['tramo'], r['tipo']): r for r in qs.values('tramo', 'tipo').annotate(
        lineas=Count('pk'), documentos=Count('numero', distinct=True), unidades=Sum('cantidad'),
        valor_t=Sum('valor', output_field=FloatField()))}
    tabla = []
    for clave, etiqueta in TRAMOS:
        fila = {'clave': clave, 'etiqueta': etiqueta}
        for tipo in ('PC', 'OF'):
            fila[tipo] = resumen.get((clave, tipo))
        fila['valor'] = sum((fila[t] or {}).get('valor_t') or 0 for t in ('PC', 'OF'))
        tabla.append(fila)
    total_valor = sum(t['valor'] for t in tabla)
    for t in tabla:
        t['pct'] = 100 * t['valor'] / total_valor if total_valor else 0

    responsables = list(qs.values('responsable').annotate(
        documentos=Count('numero', distinct=True), lineas=Count('pk'),
        valor_r=Sum('valor', output_field=FloatField()),
        valor_12=Sum(Case(When(tramo='12+', then=F('valor')), default=Value(0.0), output_field=FloatField())),
    ).order_by('-valor_12', '-valor_r')[:15])

    page_obj = Paginator(_documentos(qs), 50).get_page(request.GET.get('page'))
    for d in page_obj.object_list:
        d['dias'] = (hoy - d['emision']).days if d['emision'] else None
    params = request.GET.copy()
    params.pop('page', None)

    # Cuanto cambia la compra sugerida segun la base de compromisos (calculo hibrido, SPEC-23 §2)
    corrida = Corrida.objects.filter(estado=Corrida.OK).first()
    res = corrida.resumen if corrida else {}
    impacto = None
    if res.get('valor_otra_base') is not None:
        recientes = res.get('solo_compromisos_recientes', False)
        impacto = {'recientes': recientes,
                   'todos': res['valor_otra_base'] if recientes else res.get('valor_sugerido', 0),
                   'solo_recientes': res.get('valor_sugerido', 0) if recientes else res['valor_otra_base']}
        impacto['diferencia'] = impacto['todos'] - impacto['solo_recientes']

    base = CompromisoDetalle.objects
    return render(request, 'calculadora/compromisos.html', {
        'f': f, 'tabla': tabla, 'total_valor': total_valor, 'tramos': TRAMOS, 'responsables': responsables,
        'page_obj': page_obj, 'query': params.urlencode(), 'impacto': impacto,
        'nodos': sorted(n for n in base.values_list('nodo', flat=True).distinct() if n),
        'lista_responsables': sorted(r for r in base.values_list('responsable', flat=True).distinct() if r),
        'hay_datos': base.exists(),
    })


@login_required
def compromisos_excel(request):
    qs, _ = _compromisos_filtrados(request)
    hoy = timezone.localdate()
    etiquetas = dict(TRAMOS)
    filas = [{
        'Tipo': d['tipo'], 'Numero': d['numero'], 'Emision': d['emision'],
        'Dias abierto': (hoy - d['emision']).days if d['emision'] else '',
        'Antiguedad': etiquetas.get(d['tramo_doc'], ''), 'Entrega comprometida': d['entrega'],
        'Nodo': 'Santiago' if d['nodo_doc'] == '013' else d['nodo_doc'], 'Cliente': d['cliente'],
        'Responsable': d['responsable_doc'], 'Referencia': d['referencia_doc'], 'Lineas': d['lineas'],
        'Unidades pendientes': round(d['unidades'] or 0, 2), 'Valor USD': round(d['valor_doc'] or 0, 2),
    } for d in _documentos(qs)]
    return respuesta_excel(f'compromisos_abiertos_{hoy:%Y%m%d}.xlsx', filas, 'Compromisos abiertos')


# ── Alertas ──────────────────────────────────────────────────────────────────

@login_required
def alertas(request):
    f = {k: request.GET.get(k, '').strip() for k in ('tipo', 'estado', 'severidad', 'search', 'vigente')}
    if 'vigente' not in request.GET:
        f['vigente'] = '1'
    base = Alerta.objects.select_related('product')
    if f['vigente'] == '1':
        base = base.filter(vigente=True)
    elif f['vigente'] == '0':
        base = base.filter(vigente=False)
    if f['estado']:
        base = base.filter(estado=f['estado'])
    else:
        base = base.exclude(estado=Alerta.RESUELTA)
    if f['severidad']:
        base = base.filter(severidad=f['severidad'])
    if f['search']:
        base = base.filter(Q(product__code__icontains=f['search']) | Q(product__description__icontains=f['search'])
                           | Q(mensaje__icontains=f['search']) | Q(proveedor_codigo__icontains=f['search']))

    etiquetas = dict(Alerta.TIPOS)
    conteo = [{'tipo': t, 'etiqueta': etiquetas.get(t, t), 'n': n}
              for t, n in base.values_list('tipo').annotate(n=Count('pk')).order_by('-n')]
    qs = base.filter(tipo=f['tipo']) if f['tipo'] else base
    orden = Case(When(severidad='ALTA', then=Value(0)), When(severidad='MEDIA', then=Value(1)),
                 default=Value(2), output_field=IntegerField())
    qs = qs.annotate(orden=orden).order_by('orden', '-creada_en')
    page_obj = Paginator(qs, 50).get_page(request.GET.get('page'))

    params = request.GET.copy()
    params.pop('page', None)
    return render(request, 'calculadora/alertas.html', {
        'page_obj': page_obj, 'f': f, 'conteo': conteo, 'total': base.count(),
        'tipos': Alerta.TIPOS, 'estados': Alerta._meta.get_field('estado').choices,
        'severidades': ('ALTA', 'MEDIA', 'BAJA'),
        'query_sin_pagina': params.urlencode(),
    })


@login_required
@require_POST
def alerta_actualizar(request, pk):
    a = get_object_or_404(Alerta, pk=pk)
    estado = request.POST.get('estado', a.estado)
    if estado in dict(Alerta._meta.get_field('estado').choices):
        a.estado = estado
    a.responsable = request.POST.get('responsable', a.responsable).strip()[:100]
    a.comentario = request.POST.get('comentario', a.comentario).strip()
    a.save(update_fields=['estado', 'responsable', 'comentario', 'actualizada_en'])
    messages.success(request, 'Alerta actualizada.')
    return _volver(request, reverse('calculadora:alertas'))


# ── Eventos comerciales ──────────────────────────────────────────────────────

def _crear_evento(request):
    """Valida el formulario y crea el evento propuesto. Devuelve (evento, errores)."""
    p = request.POST
    errores = []
    codigo = p.get('product', '').strip()
    familia = p.get('familia', '').strip()
    producto = None
    if codigo:
        producto = ProductSKU.objects.filter(code=codigo).first()
        if not producto:
            errores.append(f'El articulo {codigo} no existe.')
    elif not familia:
        errores.append('Indica un articulo o una familia (grupo SAP).')
    inicio, fin = _mes(p.get('mes_inicio', '')), _mes(p.get('mes_fin', ''))
    if not inicio or not fin:
        errores.append('Indica el mes de inicio y de termino.')
    elif fin < inicio:
        errores.append('El mes de termino es anterior al de inicio.')
    tipo = p.get('tipo', EventoComercial.ALZA)
    if tipo not in (EventoComercial.ALZA, EventoComercial.BAJA, EventoComercial.REEMPLAZO):
        errores.append('Tipo de evento no valido.')
    try:
        cantidad = float((p.get('cantidad_adicional') or '0').replace(',', '.'))
        porcentaje = float((p.get('porcentaje') or '0').replace(',', '.'))
    except ValueError:
        errores.append('Cantidad y porcentaje deben ser numeros.')
        cantidad = porcentaje = 0
    if cantidad < 0 or porcentaje < 0:
        errores.append('Cantidad y porcentaje no pueden ser negativos (usa el tipo "Baja").')
    if tipo != EventoComercial.REEMPLAZO and cantidad <= 0 and porcentaje <= 0:
        errores.append('Indica la cantidad adicional o el porcentaje.')
    if not p.get('comentario', '').strip():
        errores.append('Describe el negocio en el comentario (quien, que y cuando).')
    if errores:
        return None, errores
    ev = EventoComercial.objects.create(
        product=producto, familia=familia[:100], bodega=p.get('bodega', '').strip()[:20], tipo=tipo,
        cantidad_adicional=cantidad, porcentaje=porcentaje, mes_inicio=inicio, mes_fin=fin,
        comentario=p.get('comentario', '').strip(), adjunto=request.FILES.get('adjunto'), autor=request.user,
    )
    return ev, []


@login_required
def eventos(request):
    if request.method == 'POST':
        ev, errores = _crear_evento(request)
        if errores:
            for e in errores:
                messages.error(request, e)
        else:
            messages.success(request, f'Evento registrado como propuesto (#{ev.pk}). Debe aprobarlo el Jefe de '
                                      'Abastecimiento y luego recalcular para que afecte la compra.')
        return redirect('calculadora:eventos')

    qs = EventoComercial.objects.select_related('product', 'autor', 'aprobado_por')
    estado = request.GET.get('estado', '').strip()
    if estado:
        qs = qs.filter(estado=estado)
    search = request.GET.get('search', '').strip()
    if search:
        qs = qs.filter(Q(product__code__icontains=search) | Q(familia__icontains=search) | Q(comentario__icontains=search))
    page_obj = Paginator(qs, 50).get_page(request.GET.get('page'))
    hoy = timezone.localdate()
    return render(request, 'calculadora/eventos.html', {
        'page_obj': page_obj, 'estado': estado, 'search': search,
        'estados': EventoComercial._meta.get_field('estado').choices,
        'tipos': EventoComercial._meta.get_field('tipo').choices,
        'bodegas': [w for w in Warehouse.objects.filter(is_active=True).order_by('code') if w.zone],
        'puede_aprobar': par.puede_aprobar(request.user),
        'mes_actual': hoy.strftime('%Y-%m'),
        'pendientes': EventoComercial.objects.filter(estado=EventoComercial.PROPUESTO).count(),
    })


@login_required
@require_POST
def evento_estado(request, pk):
    ev = get_object_or_404(EventoComercial, pk=pk)
    if not par.puede_aprobar(request.user):
        messages.error(request, 'Solo el Jefe o el Administrador de Abastecimiento aprueban eventos comerciales.')
        return redirect('calculadora:eventos')
    accion = request.POST.get('accion')
    if accion == 'aprobar':
        ev.estado = EventoComercial.APROBADO
    elif accion == 'rechazar':
        ev.estado = EventoComercial.RECHAZADO
    else:
        messages.error(request, 'Accion no valida.')
        return redirect('calculadora:eventos')
    ev.aprobado_por = request.user
    ev.save(update_fields=['estado', 'aprobado_por'])
    messages.success(request, f'Evento #{ev.pk} {ev.get_estado_display().lower()}. '
                              'Recalcula la Calculadora para ver el efecto.')
    return redirect('calculadora:eventos')


# ── Parametros ───────────────────────────────────────────────────────────────

_NIVEL_AYUDA = {
    'FAMILIA': 'Codigo de grupo SAP (ej. 101)',
    'PROVEEDOR': 'Codigo de proveedor SAP',
    'ARTICULO': 'Codigo de articulo',
    'BODEGA': 'Codigo de bodega (ej. 013-PP)',
}


def _filas_parametros():
    excepciones = {}
    generales = {}
    for v in ParametroValor.objects.order_by('nivel', 'ambito'):
        if v.nivel == GENERAL:
            generales[v.clave] = v.valor
        else:
            excepciones.setdefault(v.clave, []).append(v)
    filas = []
    for clave, (etiqueta, niveles, minimo, maximo) in CATALOGO.items():
        defecto = getattr(DEFAULTS, clave)
        es_bool = tipo_de(clave) is bool
        filas.append({
            'clave': clave, 'etiqueta': etiqueta, 'niveles': niveles, 'minimo': minimo, 'maximo': maximo,
            'defecto': defecto, 'valor': par.valor_actual(clave) if clave in generales else defecto,
            'modificado': clave in generales and str(par.valor_actual(clave)) != str(defecto),
            'es_bool': es_bool, 'excepciones': excepciones.get(clave, []),
        })
    return filas


def _contexto_parametros(request, **extra):
    ctx = {
        'filas': _filas_parametros(),
        'cambios': ParametroCambio.objects.select_related('usuario')[:100],
        'puede_editar': par.puede_editar(request.user),
        'nivel_ayuda': _NIVEL_AYUDA,
    }
    ctx.update(extra)
    return ctx


@login_required
def parametros(request):
    if request.method == 'POST':
        if not par.puede_editar(request.user):
            messages.error(request, 'Solo el Administrador de Abastecimiento puede cambiar parametros.')
            return redirect('calculadora:parametros')
        p = request.POST
        clave, nivel, ambito = p.get('clave', ''), p.get('nivel', GENERAL), p.get('ambito', '').strip()
        if clave not in CATALOGO:
            messages.error(request, 'Parametro desconocido.')
            return redirect('calculadora:parametros')
        valor = None if p.get('accion') == 'borrar' else p.get('valor', '')
        try:
            nuevo = par.guardar(clave, valor, request.user, nivel=nivel, ambito=ambito if nivel != GENERAL else '',
                                motivo=p.get('motivo', ''))
            etiqueta = CATALOGO[clave][0]
            if valor is None:
                messages.success(request, f'{etiqueta}: se quito el valor de {nivel.lower()} {ambito}'.strip() + '.')
            else:
                messages.success(request, f'{etiqueta} = {nuevo} ({nivel.lower()}{" " + ambito if ambito else ""}). '
                                          'El proximo calculo usa el valor nuevo.')
        except ValueError as exc:
            messages.error(request, str(exc))
        return redirect(reverse('calculadora:parametros') + f'#p-{clave}')
    return render(request, 'calculadora/parametros.html', _contexto_parametros(request))


@login_required
@require_POST
def parametros_simular(request):
    """Simula un cambio de un parametro general sin guardar: corre el calculo con y sin el
    valor nuevo y muestra la diferencia (documento §7, 'Simulacion')."""
    from .servicio import ejecutar_corrida
    clave, valor = request.POST.get('clave', ''), request.POST.get('valor', '')
    try:
        nuevo = validar(clave, valor)
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect('calculadora:parametros')
    base = ejecutar_corrida(guardar=False)
    con_cambio = ejecutar_corrida(guardar=False, extra_general={clave: nuevo})
    metricas = []
    for k, etiqueta, dinero in (('valor_stock_maximo', 'Valor del stock maximo', True),
                                ('valor_sugerido', 'Valor a comprar', True),
                                ('comprar', 'Articulos que entran en la compra de hoy', False),
                                ('necesita_compra', 'Articulos bajo su umbral de compra', False),
                                ('excepciones', 'Compras fuera de calendario', False),
                                ('urgentes', 'Articulos urgentes', False)):
        a, b = base.get(k, 0), con_cambio.get(k, 0)
        metricas.append({'etiqueta': etiqueta, 'antes': a, 'despues': b, 'diferencia': b - a, 'dinero': dinero,
                         'pct': round(100 * (b - a) / a, 1) if a else None})
    simulacion = {'clave': clave, 'etiqueta': CATALOGO[clave][0], 'actual': par.valor_actual(clave),
                  'nuevo': nuevo, 'metricas': metricas}
    return render(request, 'calculadora/parametros.html', _contexto_parametros(request, simulacion=simulacion))


@login_required
def parametros_historial_excel(request):
    filas = [{
        'Fecha': timezone.localtime(c.fecha).strftime('%Y-%m-%d %H:%M'), 'Parametro': c.clave,
        'Descripcion': CATALOGO.get(c.clave, (c.clave,))[0], 'Nivel': c.nivel, 'Aplica a': c.ambito,
        'Valor anterior': c.valor_anterior, 'Valor nuevo': c.valor_nuevo,
        'Usuario': c.usuario.get_username() if c.usuario else '', 'Motivo': c.motivo,
    } for c in ParametroCambio.objects.select_related('usuario')]
    return respuesta_excel(f'cambios_parametros_{timezone.localdate():%Y%m%d}.xlsx', filas, 'Cambios')


# ── Proveedores y calendario de compra ───────────────────────────────────────

def _guardar_proveedor(request):
    p = request.POST
    prov = Proveedor.objects.filter(codigo=p.get('codigo', '')).first()
    if not prov:
        messages.error(request, 'Proveedor no encontrado.')
        return
    frecuencia = p.get('frecuencia_compra_dias', '').strip()
    ancla = p.get('fecha_ancla', '').strip()
    try:
        frecuencia = int(frecuencia) if frecuencia else None
        if frecuencia is not None and not 1 <= frecuencia <= 180:
            raise ValueError
    except ValueError:
        messages.error(request, f'{prov.codigo}: la frecuencia debe ser un numero de dias entre 1 y 180.')
        return
    try:
        ancla = datetime.date.fromisoformat(ancla) if ancla else None
    except ValueError:
        messages.error(request, f'{prov.codigo}: fecha de compra no valida.')
        return
    prov.frecuencia_compra_dias = frecuencia
    prov.fecha_ancla = ancla
    prov.comprador = p.get('comprador', '').strip()[:100]
    prov.save(update_fields=['frecuencia_compra_dias', 'fecha_ancla', 'comprador'])
    messages.success(request, f'Calendario de {prov.nombre or prov.codigo} actualizado. Se aplica en el proximo calculo.')


@login_required
def proveedores(request):
    if request.method == 'POST':
        if not par.puede_editar(request.user):
            messages.error(request, 'Solo el Administrador de Abastecimiento puede cambiar el calendario de proveedores.')
        else:
            _guardar_proveedor(request)
        return _volver(request, reverse('calculadora:proveedores'))

    qs = Proveedor.objects.annotate(
        n_articulos=Count('resultadoarticulo', distinct=True),
        n_comprar=Count('resultadoarticulo', filter=Q(resultadoarticulo__necesita_compra=True), distinct=True),
    )
    search = request.GET.get('search', '').strip()
    if search:
        qs = qs.filter(Q(codigo__icontains=search) | Q(nombre__icontains=search) | Q(comprador__icontains=search))
    solo_activos = request.GET.get('todos') != '1'
    oc_por_prov = dict(OCAbierta.objects.exclude(proveedor_codigo='').values_list('proveedor_codigo')
                       .annotate(n=Count('pk')))
    if solo_activos:
        qs = qs.filter(Q(n_articulos__gt=0) | Q(codigo__in=list(oc_por_prov)))
    qs = qs.order_by('-n_comprar', '-n_articulos', 'nombre')
    page_obj = Paginator(qs, 50).get_page(request.GET.get('page'))

    resolutor = par.Resolutor()
    hoy = timezone.localdate()
    filas = []
    for prov in page_obj.object_list:
        frecuencia = prov.frecuencia_compra_dias or resolutor.para(proveedor=prov.codigo).frecuencia_compra_dias
        ancla = prov.fecha_ancla or calendario.ancla_por_defecto(prov.codigo, frecuencia)
        proxima = calendario.proxima_fecha_compra(hoy, frecuencia, ancla)
        filas.append({'p': prov, 'frecuencia': frecuencia, 'ancla': ancla, 'ancla_definida': bool(prov.fecha_ancla),
                      'proxima': proxima, 'es_hoy': proxima == hoy, 'n_oc': oc_por_prov.get(prov.codigo, 0)})
    return render(request, 'calculadora/proveedores.html', {
        'page_obj': page_obj, 'filas': filas, 'search': search, 'todos': not solo_activos,
        'puede_editar': par.puede_editar(request.user), 'hoy': hoy,
        'frecuencia_general': resolutor.general.frecuencia_compra_dias,
    })
