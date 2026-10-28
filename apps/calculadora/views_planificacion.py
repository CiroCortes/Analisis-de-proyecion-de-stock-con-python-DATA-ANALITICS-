"""Vistas de planificacion de la Calculadora (SPEC-18 §4.1): panel, grilla de compras,
detalle del articulo con la memoria de calculo e indicadores de gestion."""
import json
import math
from collections import defaultdict

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Case, Count, F, FloatField, Q, Sum, When
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.calc import politica as pol
from apps.inventory.models import ProductSKU

from . import cargadores, servicio, solicitudes
from .excel import respuesta_excel
from .models import (Alerta, ArticuloConfig, CargaDatos, CompromisoAbierto, ConsumoMensual, Corrida, EventoComercial,
                     HistorialMensual, OCAbierta, PlazoOC, Proveedor, ResultadoArticulo, TrasladoSugerido)
from .parametros import puede_aprobar, puede_editar

LETRAS = [('R', 'Reposición'), ('E', 'Estratégico'), ('P', 'A pedido'), ('O', 'Obsoleto')]
METODOS = [(pol.GENERAL, 'Fórmula general'), (pol.INTERMITENTE, 'Intermitente'), (pol.NUEVO, 'Nuevo (mínimo manual)'),
           (pol.A_PEDIDO, 'A pedido'), (pol.SIN_COMPRA, 'Sin compra')]
ACCIONES_BODEGA = [('TRASLADAR', 'Trasladar'), ('TRASLADAR_PARCIAL', 'Trasladar parcial'), ('ESPERA_COMPRA', 'Espera compra')]
CAUSAS = {'OC_ATRASADA': 'OC atrasada', 'PEDIDO': 'Pedido nuevo', 'EVENTO': 'Evento comercial',
          'CONSUMO': 'Alza de consumo', 'DATO_FALTANTE': 'Dato faltante'}
ORDENES = {
    'valor': ('-valor_accion', 'Mayor valor a comprar'),
    'urgencia': ('urg_orden', 'Urgencia'),
    'cobertura': ('cobertura_dias', 'Menor cobertura'),
    'disponible': ('disponible_futuro', 'Menor disponible'),
    'consumo': ('-consumo_promedio_mes', 'Mayor consumo'),
    'codigo': ('product__code', 'Código'),
}
FUENTES_BRECHA = ('SIN_ARCHIVO', 'RESPALDO', 'PC_OF', 'SIN_MONEDA')
MESES_ABR = ['ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic']


def _n(x, d=2):
    """Numero en formato chileno (1.234,56) para la memoria de calculo."""
    if x is None:
        return '—'
    s = f'{float(x):,.{d}f}'
    return s.replace(',', 'X').replace('.', ',').replace('X', '.')


def _mes(m):
    return f'{MESES_ABR[m.month - 1]}-{m.strftime("%y")}'


def _anotar_accion(qs):
    cant = Case(When(comprar=True, then=F('cantidad_sugerida')),
                When(excepcion=True, then=F('cantidad_excepcion')), default=0, output_field=FloatField())
    return qs.annotate(cant_accion=cant).annotate(
        valor_accion=F('cant_accion') * F('costo_unitario'),
        urg_orden=Case(When(urgencia='URGENTE', then=0), When(urgencia='MEDIO', then=1), default=2,
                       output_field=FloatField()),
    )


def _sparkline(valores, ancho=84, alto=22):
    valores = [float(v or 0) for v in (valores or [])]
    if not valores or max(valores) <= 0:
        return ''
    tope = max(valores)
    paso = ancho / max(1, len(valores) - 1)
    return ' '.join(f'{i * paso:.1f},{alto - 2 - (v / tope) * (alto - 4):.1f}' for i, v in enumerate(valores))


# ── Panel ─────────────────────────────────────────────────────────────────────

def _ultimas_cargas():
    cargas = {}
    for c in CargaDatos.objects.all()[:300]:
        cargas.setdefault(c.tabla, c)
    return sorted(cargas.values(), key=lambda c: c.tabla)


# Semaforo de datos (SPEC-19 §7.1): nombre legible y que se pierde si la fuente no es real
DATOS_LEGIBLES = {
    'consumo_mensual': ('Consumo mensual', 'el consumo sale de PC y OF cerrados, no del movimiento real de inventario'),
    'plazos_oc': ('Plazos de entrega', 'los plazos son los del maestro de SAP, no los reales de cada proveedor'),
    'acuerdos': ('Acuerdos globales', 'las solicitudes salen sin contrato y valorizadas al último precio'),
    'parametros_compra': ('Parámetros de compra', 'sin mínimo ni múltiplo de compra; el proveedor sale de la última entrada'),
    'oc_abiertas': ('OC abiertas', 'no se ven las llegadas de OC en la proyección'),
    'compromisos': ('Pedidos y OF abiertas', 'la proyección no descuenta los compromisos por fecha'),
    'proveedores': ('Proveedores', 'sin país (nacional / importado)'),
    'bodegas': ('Bodegas', 'nombres de bodega genéricos'),
}


def _semaforo(cargas):
    filas = []
    for c in cargas:
        nombre, impacto = DATOS_LEGIBLES.get(c.tabla, (c.tabla.replace('_', ' ').capitalize(), ''))
        if c.fuente == 'SIN_ARCHIVO':
            color, texto = 'rojo', f'Falta: {impacto}.' if impacto else 'Falta el archivo.'
        elif c.fuente == 'SIN_MONEDA':
            color, texto = 'amarillo', 'Precio de los acuerdos sin moneda: se valoriza al costo. Re-exportar la consulta 12.'
        elif c.fuente in ('RESPALDO', 'PC_OF'):
            color, texto = 'amarillo', f'Provisional: {impacto}.' if impacto else 'Provisional.'
        else:
            color, texto = 'verde', 'Dato real del Datalake.'
        filas.append({'nombre': nombre, 'color': color, 'texto': texto, 'carga': c})
    orden = {'rojo': 0, 'amarillo': 1, 'verde': 2}
    return sorted(filas, key=lambda f: (orden[f['color']], f['nombre']))


def _tarjetas_hoy():
    """Las 4 acciones del dia (SPEC-19 §7.1), con su frase en lenguaje simple."""
    valor = F('cantidad_sugerida') * F('costo_unitario')
    compras = ResultadoArticulo.objects.filter(comprar=True)
    por_prov = compras.filter(proveedor__isnull=False).values('proveedor_id').distinct().count()
    dia = compras.aggregate(n=Count('pk'), usd=Sum(valor, output_field=FloatField()))
    exc = ResultadoArticulo.objects.filter(excepcion=True).aggregate(
        n=Count('pk'), inevitable=Count('pk', filter=Q(dias_quiebre_inevitable__gt=0)),
        usd=Sum(F('cantidad_excepcion') * F('costo_unitario'), output_field=FloatField()))
    tras = TrasladoSugerido.objects.filter(urgencia='URGENTE').aggregate(
        n=Count('pk'), u=Sum('cantidad'), destinos=Count('destino', distinct=True))
    alertas = Alerta.objects.filter(vigente=True, estado=Alerta.NUEVA, severidad='ALTA').count()
    return {'proveedores': por_prov, 'dia': dia, 'exc': exc, 'tras': tras, 'alertas': alertas}


@login_required
def panel(request):
    corrida = Corrida.objects.first()
    ultima_ok = Corrida.objects.filter(estado=Corrida.OK).first()
    resumen = ultima_ok.resumen if ultima_ok else {}
    cargas = _ultimas_cargas()
    tipos = dict(Alerta.TIPOS)
    alertas_tipo = sorted(((tipos.get(t, t), n) for t, n in (resumen.get('alertas') or {}).items()),
                          key=lambda x: -x[1])
    letras = resumen.get('letras') or {}
    top = (_anotar_accion(ResultadoArticulo.objects.filter(
        Q(excepcion=True) | Q(urgencia='URGENTE', necesita_compra=True) | Q(comprar=True)))
        .select_related('product', 'proveedor').order_by('urg_orden', '-valor_accion')[:15])
    top = list(top)
    for r in top:
        r.causa_txt = CAUSAS.get(r.causa_excepcion, r.causa_excepcion)
    return render(request, 'calculadora/panel.html', {
        'corrida': corrida, 'ultima_ok': ultima_ok, 'resumen': resumen,
        'letras': [(k, nombre, letras.get(k, 0)) for k, nombre in LETRAS],
        'cargas': cargas, 'brechas': [c for c in cargas if c.fuente in FUENTES_BRECHA],
        'fuente_provisional': bool(ultima_ok and ultima_ok.fuente_consumo == 'PC_OF'),
        'alertas_tipo': alertas_tipo, 'top': top, 'causas': CAUSAS,
        'hoy': _tarjetas_hoy(), 'semaforo': _semaforo(cargas),
        'puede_correr': request.user.is_staff or puede_aprobar(request.user),
    })


@login_required
@require_POST
def correr(request):
    if not (request.user.is_staff or puede_aprobar(request.user)):
        messages.error(request, 'No tienes permiso para recalcular. Pide la ejecución a Abastecimiento.')
        return redirect('calculadora:panel')
    try:
        if request.POST.get('recargar') == '1':
            cargadores.cargar_todo()
        c = servicio.ejecutar_corrida(usuario=request.user)
        messages.success(request, f'Cálculo terminado en {c.resumen.get("segundos", "?")} s: '
                                  f'{c.resumen.get("articulos", 0)} artículos evaluados.')
    except Exception as exc:  # se muestra al usuario; el detalle queda en la corrida
        messages.error(request, f'El cálculo falló: {exc}')
    return redirect('calculadora:panel')


# ── Grilla ────────────────────────────────────────────────────────────────────

def _filtros(request):
    g = request.GET
    f = {k: g.get(k, '').strip() for k in ('search', 'letra', 'subclase', 'abc', 'xyz', 'urgencia', 'metodo', 'proveedor',
                                          'familia', 'compra', 'bodega_accion', 'orden')}
    for k in ('nuevo', 'inmovilizado', 'critico'):
        f[k] = g.get(k) == '1'
    # "Solo con acción" activo por defecto; el formulario envia todo=1 para verlo todo
    f['todo'] = g.get('todo') == '1'
    return f


def _queryset(f):
    qs = ResultadoArticulo.objects.filter(product__category__is_active=True)
    if f['search']:
        qs = qs.filter(Q(product__code__icontains=f['search']) | Q(product__description__icontains=f['search']))
    for campo in ('letra', 'subclase', 'abc', 'xyz', 'urgencia', 'metodo'):
        if f[campo]:
            qs = qs.filter(**{campo: f[campo]})
    if f['proveedor']:
        qs = qs.filter(Q(proveedor_id=f['proveedor']) | Q(proveedor__nombre__icontains=f['proveedor']))
    if f['familia']:
        qs = qs.filter(Q(product__sap_group_code=f['familia']) | Q(product__category__code=f['familia']))
    compra = f['compra']
    # Desde la Segmentacion (celda ABC-XYZ) se quiere ver la celda completa, no solo lo que tiene accion
    if f['xyz'] and not compra:
        f['todo'] = True
    if compra == 'comprar':
        qs = qs.filter(comprar=True)
    elif compra == 'necesita':
        qs = qs.filter(necesita_compra=True)
    elif compra == 'excepcion':
        qs = qs.filter(excepcion=True)
    elif not f['todo'] and not f['search']:
        qs = qs.filter(Q(necesita_compra=True) | Q(excepcion=True) | Q(bodegas__accion__in=[a for a, _ in ACCIONES_BODEGA]))
    if f['bodega_accion']:
        qs = qs.filter(bodegas__accion=f['bodega_accion'])
    if f['nuevo']:
        qs = qs.filter(es_nuevo=True)
    if f['inmovilizado']:
        qs = qs.filter(es_inmovilizado=True)
    if f['critico']:
        qs = qs.filter(es_critico=True)
    qs = _anotar_accion(qs.distinct())
    orden = ORDENES.get(f['orden'] or 'valor', ORDENES['valor'])[0]
    return qs.order_by(orden, 'product__code')


@login_required
def grilla(request):
    f = _filtros(request)
    qs = _queryset(f)
    kpi = qs.aggregate(n=Count('pk', distinct=True), unidades=Sum('cant_accion'), valor=Sum('valor_accion'),
                       urgentes=Count('pk', filter=Q(urgencia='URGENTE'), distinct=True),
                       excepciones=Count('pk', filter=Q(excepcion=True), distinct=True))
    page = Paginator(qs.select_related('product', 'product__category', 'proveedor'), 50).get_page(request.GET.get('page'))
    for r in page.object_list:
        r.spark = _sparkline(r.consumo_meses)
        r.causa_txt = CAUSAS.get(r.causa_excepcion, r.causa_excepcion)
    params = request.GET.copy()
    params.pop('page', None)
    familias = (ProductSKU.objects.filter(category__is_active=True, resultado_calc__isnull=False)
                .exclude(sap_group_code='').values_list('sap_group_code', 'sap_group_name').distinct().order_by('sap_group_name'))
    return render(request, 'calculadora/grilla.html', {
        'page_obj': page, 'f': f, 'kpi': kpi, 'query': params.urlencode(),
        'letras': LETRAS, 'metodos': METODOS, 'acciones_bodega': ACCIONES_BODEGA,
        'urgencias': ('URGENTE', 'MEDIO', 'NORMAL'),
        'ordenes': [(k, v[1]) for k, v in ORDENES.items()], 'familias': familias,
    })


@login_required
def grilla_excel(request):
    qs = _queryset(_filtros(request)).select_related('product', 'product__category', 'proveedor')
    filas = []
    for r in qs.iterator(chunk_size=2000):
        p = r.product
        filas.append({
            'Artículo': p.code, 'Descripción': p.description, 'Grupo SAP': p.sap_group_name,
            'Proveedor': r.proveedor_id or '', 'Nombre proveedor': r.proveedor.nombre if r.proveedor else '',
            'Letra': r.letra, 'Subclase': r.subclase, 'ABC': r.abc, 'XYZ': r.xyz, 'Crítico': 'Sí' if r.es_critico else '',
            'Nuevo': 'Sí' if r.es_nuevo else '', 'Inmovilizado': 'Sí' if r.es_inmovilizado else '',
            'Consumo promedio mes': round(r.consumo_promedio_mes, 2), 'Variación consumo': round(r.variacion_consumo, 2),
            'Consumo 12 meses': ', '.join(f'{v:g}' for v in r.consumo_meses or []),
            'Días entrega': round(r.dias_entrega_promedio, 1), 'Variación entrega (días)': round(r.variacion_entrega_dias, 1),
            'Origen plazo': r.origen_plazo, 'N° OC': r.n_oc,
            'Factor servicio': r.factor_servicio, 'SS calculado': round(r.ss_calculado, 2), 'Piso SS': round(r.piso_ss, 2),
            'Stock seguridad': r.stock_seguridad, 'Punto de pedido': r.punto_pedido, 'Stock máximo': r.stock_maximo,
            'Stock físico': r.stock_fisico, 'En tránsito': r.en_transito, 'Comprometido': r.comprometido,
            'Disponible futuro': r.disponible_futuro,
            'Cobertura días': round(r.cobertura_dias, 1) if r.cobertura_dias is not None else '',
            'Compra hoy': 'Sí' if r.comprar else '', 'Necesita compra': 'Sí' if r.necesita_compra else '',
            'Excepción': 'Sí' if r.excepcion else '', 'Causa': CAUSAS.get(r.causa_excepcion, r.causa_excepcion),
            'Cantidad a comprar': r.cant_accion, 'Costo unitario USD': r.costo_unitario,
            'Valor USD': round(r.valor_accion or 0, 2), 'Urgencia': r.urgencia,
            'Llegada estimada': r.fecha_llegada_estimada.isoformat() if r.fecha_llegada_estimada else '',
            'Próxima compra': r.proxima_fecha_compra.isoformat() if r.proxima_fecha_compra else '',
            'Quiebre proyectado': r.fecha_quiebre_proyectada.isoformat() if r.fecha_quiebre_proyectada else '',
            'Avisos': '; '.join(r.avisos or []),
        })
    return respuesta_excel('grilla_calculadora.xlsx', filas, 'Grilla')


# ── Detalle del articulo ──────────────────────────────────────────────────────

def _memoria(e, r):
    """Pasos del calculo con la formula y los numeros reemplazados."""
    c, pl, po, co = r.consumo, r.plazo, r.politica, r.compra
    p = e.params
    pasos = []

    def paso(seccion, campo, formula, valor):
        pasos.append({'seccion': seccion, 'campo': campo, 'formula': formula, 'valor': valor})

    n = len(c.meses)
    paso('Consumo', 'meses_con_consumo_12m', f'Meses con consumo > 0 de los últimos {n}', c.meses_con_consumo_12m)
    paso('Consumo', 'consumo_promedio_mes', f'Suma {n} meses ÷ {n} = {_n(c.consumo_total_12m)} ÷ {n}',
         _n(c.consumo_promedio_mes))
    paso('Consumo', 'consumo_diario', f'Suma {n} meses ÷ 365 = {_n(c.consumo_total_12m)} ÷ 365', _n(c.consumo_diario, 3))
    paso('Consumo', 'variacion_consumo', 'DESVEST.M de los meses', _n(c.variacion_consumo))
    paso('Consumo', 'tope_mes_atipico',
         f'{_n(c.consumo_promedio_mes)} + {_n(p.multiplicador_atipico, 0)} × {_n(c.variacion_consumo)}'
         + (f' · meses recortados: {len(c.meses_atipicos)}' if c.meses_atipicos else ''), _n(c.tope_mes_atipico))
    if e.ajuste_comercial:
        paso('Consumo', 'consumo_promedio_ajustado', f'{_n(c.consumo_promedio_mes)} + ajuste {_n(e.ajuste_comercial)}',
             _n(po.consumo_usado))

    origen = 'OC reales' if pl.origen == 'REAL' else 'maestro SAP (menos de 3 OC)'
    paso('Plazo', 'dias_entrega_promedio', f'Promedio de {pl.n_oc} OC' if pl.origen == 'REAL' else 'OITM.LeadTime',
         f'{_n(pl.dias_entrega_promedio, 1)} días ({origen})')
    paso('Plazo', 'variacion_entrega_dias',
         'DESVEST.M de los plazos' if pl.origen == 'REAL' else f'{_n(p.variacion_entrega_defecto * 100, 0)}% del plazo',
         f'{_n(pl.variacion_entrega_dias, 2)} días')
    paso('Plazo', 'plazo_total_meses', f'({_n(pl.dias_entrega_promedio, 1)} + {_n(pl.dias_recepcion, 0)}) ÷ 30',
         _n(pl.plazo_total_meses))

    cl = r.clasificacion
    paso('Clasificación', 'letra', cl.motivo, f'{cl.letra} {cl.subclase.title() if cl.subclase else ""}'.strip())
    paso('Clasificación', 'nivel_servicio', f'Clase {e.abc}' + (' · crítico/pañol: mínimo 97%' if e.es_critico or e.segmento == 'PANOL' else ''),
         f'{_n(r.nivel_servicio * 100, 1)}% → factor {_n(po.factor_servicio)}')

    if po.metodo == pol.GENERAL:
        paso('Política', 'ss_calculado',
             f'{_n(po.factor_servicio)} × RAIZ({_n(pl.plazo_total_meses)} × {_n(c.variacion_consumo)}² + '
             f'{_n(c.consumo_promedio_mes)}² × {_n(pl.variacion_entrega_meses, 3)}²)', _n(po.ss_calculado))
        paso('Política', 'piso_ss', f'{_n(po.meses_piso_ss, 0)} meses × {_n(c.consumo_promedio_mes)} '
             f'(plazo {"≤" if pl.plazo_total_dias <= p.umbral_plazo_largo_dias else ">"} {_n(p.umbral_plazo_largo_dias, 0)} días)',
             _n(po.piso_ss))
        paso('Política', 'stock_seguridad', f'REDONDEAR.MAS(MAX({_n(po.ss_calculado)} ; {_n(po.piso_ss)}))'
             + (f' · mínimo declarado {_n(e.minimo_declarado, 0)}' if e.minimo_declarado and cl.letra == 'E' else ''),
             po.stock_seguridad)
        paso('Política', 'punto_pedido', f'REDONDEAR.MAS({_n(po.consumo_usado)} × ({_n(pl.plazo_total_meses)} + '
             f'{_n(po.meses_revision)}) + {po.stock_seguridad})', po.punto_pedido)
        paso('Política', 'stock_maximo', f'REDONDEAR.MAS({po.punto_pedido} + {_n(p.meses_cobertura, 0)} × {_n(po.consumo_usado)})',
             po.stock_maximo)
    elif po.metodo == pol.INTERMITENTE:
        paso('Política', 'mayor_consumo_mes', 'MAX de los meses, sin atípicos ni meses de evento', _n(c.mayor_consumo_mes))
        paso('Política', 'salidas_en_plazo', f'REDONDEAR.MAS({c.meses_con_consumo_12m} ÷ 12 × {_n(pl.plazo_total_meses)}), mínimo 1',
             po.salidas_en_plazo)
        paso('Política', 'punto_pedido', f'{_n(c.mayor_consumo_mes)} × {po.salidas_en_plazo}', po.punto_pedido)
        paso('Política', 'stock_maximo', f'{po.punto_pedido} + {_n(c.mayor_consumo_mes)} × {p.salidas_extra}', po.stock_maximo)
        paso('Política', 'stock_seguridad', f'{po.punto_pedido} − {_n(c.consumo_promedio_mes)} × {_n(pl.plazo_total_meses)}',
             po.stock_seguridad)
    elif po.metodo == pol.NUEVO:
        paso('Política', 'punto_pedido / stock_maximo', 'Artículo nuevo: mínimo manual (sin historia)', po.stock_maximo)
    elif po.metodo == pol.A_PEDIDO:
        paso('Política', 'cantidad', 'A pedido: se compra lo comprometido que el stock de la red no cubre', '—')
    else:
        paso('Política', 'cantidad', 'Sin compra: obsoleto, bloqueado o sin consumo', '—')

    paso('Compra', 'disponible_futuro', f'{_n(r.stock_fisico, 0)} + {_n(r.en_transito, 0)} − {_n(r.comprometido, 0)}',
         _n(co.disponible_futuro, 0))
    if po.metodo not in (pol.A_PEDIDO, pol.SIN_COMPRA):
        paso('Compra', 'umbral de compra', f'{po.punto_pedido} + {_n(po.consumo_usado)} × {_n(po.meses_revision)}',
             _n(co.umbral_compra))
        paso('Compra', 'comprar', f'{_n(co.disponible_futuro, 0)} ≤ {_n(co.umbral_compra)} y hoy es día de compra',
             'Sí' if co.comprar else ('Necesita, pero no es día de compra' if co.necesita_compra else 'No'))
        paso('Compra', 'faltante', f'{po.stock_maximo} − {_n(co.disponible_futuro, 0)}', _n(co.faltante, 0))
        if co.cantidad_sugerida:
            paso('Compra', 'cantidad_sugerida',
                 f'MAX({_n(co.faltante, 0)} ; {_n(p.meses_minimo_compra, 0)} × {_n(po.consumo_usado)} ; mín. {_n(e.min_compra, 0)})'
                 + (f' al múltiplo {_n(e.multiplo, 0)}' if e.multiplo else ''), co.cantidad_sugerida)
    elif po.metodo == pol.A_PEDIDO:
        paso('Compra', 'cantidad_sugerida', f'MAX(0 ; −({_n(co.disponible_futuro, 0)}))', co.cantidad_sugerida)
    paso('Compra', 'valor_sugerido', f'{co.cantidad_sugerida} × USD {_n(e.costo)}', f'USD {_n(co.valor_sugerido)}')
    paso('Compra', 'urgencia', 'URGENTE si disponible ≤ 0; MEDIO si < SS', co.urgencia)

    ex = r.excepcion
    if ex:
        paso('Proyección', 'fecha_quiebre_proyectada', 'Primer día con stock proyectado < 0',
             f'día {ex.dia_quiebre}' if ex.dia_quiebre else 'Sin quiebre en el horizonte')
        paso('Proyección', 'fecha_llegada_posible', f'Próxima compra en {e.dias_a_proxima_compra} días + '
             f'{_n(pl.dias_entrega_promedio, 0)} + {_n(pl.dias_recepcion, 0)}', f'día {ex.dia_llegada_posible}')
        paso('Proyección', 'excepcion', 'Quiebre antes de la llegada posible (no aplica el día de compra)',
             f'Sí · {CAUSAS.get(r.causa_excepcion, r.causa_excepcion)} · {r.cantidad_excepcion} u' if ex.excepcion else 'No')
        if ex.dias_quiebre_inevitable:
            paso('Proyección', 'dias_quiebre_inevitable', 'Días de quiebre aunque se compre hoy', ex.dias_quiebre_inevitable)
    return pasos


def _grafico_consumo(producto, r, e):
    meses = servicio.meses_cerrados(e.hoy, len(r.consumo.meses))
    indice = {m: i for i, m in enumerate(meses)}
    series = {ConsumoMensual.VENTA: [0.0] * len(meses), ConsumoMensual.OF: [0.0] * len(meses),
              ConsumoMensual.SALIDA: [0.0] * len(meses)}
    for mes, origen, q in ConsumoMensual.objects.filter(product=producto, mes__in=meses).values_list('mes', 'origen', 'cantidad'):
        series.setdefault(origen, [0.0] * len(meses))[indice[mes]] += q
    prom, var = r.consumo.consumo_promedio_mes, r.consumo.variacion_consumo
    return {
        'labels': [_mes(m) for m in meses],
        'venta': [round(v, 2) for v in series[ConsumoMensual.VENTA]],
        'of': [round(v, 2) for v in series[ConsumoMensual.OF]],
        'salida': [round(v, 2) for v in series[ConsumoMensual.SALIDA]],
        'promedio': round(prom, 2), 'banda_alta': round(prom + var, 2), 'banda_baja': round(max(0, prom - var), 2),
        'ajustado': round(r.politica.consumo_usado, 2) if e.ajuste_comercial else None,
    }


def _grafico_linea(producto, r, e):
    """Una linea continua (SPEC-19 §5): 12 cierres de mes reconstruidos + hoy + 120 dias
    proyectados. Indices alineados en todos los datasets; `hoy` marca el divisor."""
    import datetime
    historico = servicio.historico_articulo(producto.code, e.hoy)
    serie = r.serie or []
    n_pasado = len(historico)
    labels = [f'{_mes(m)}' for m, _, _ in historico] + ['hoy']
    labels += [(e.hoy + datetime.timedelta(days=d)).strftime('%d-%m') for d in range(1, len(serie) + 1)]
    total = len(labels)
    hoy_stock = round(r.stock_fisico, 2)
    pasado = [round(s, 2) for _, s, _ in historico] + [hoy_stock] + [None] * len(serie)
    inconsistente = [bool(inc) for _, _, inc in historico] + [False] * (1 + len(serie))
    futuro = [None] * n_pasado + [hoy_stock] + [round(v, 2) for v in serie]
    llegadas, quiebre = [None] * total, [None] * total
    for dia, q in e.llegadas:
        d = max(1, int(dia))
        if d <= len(serie):
            llegadas[n_pasado + d] = round(serie[d - 1], 2)
    if r.excepcion and r.excepcion.dia_quiebre and r.excepcion.dia_quiebre <= len(serie):
        quiebre[n_pasado + r.excepcion.dia_quiebre] = round(serie[r.excepcion.dia_quiebre - 1], 2)
    return {
        'labels': labels, 'pasado': pasado, 'futuro': futuro, 'inconsistente': inconsistente,
        'llegadas': llegadas, 'quiebre': quiebre, 'hoy': n_pasado,
        'ss': r.politica.stock_seguridad, 'rop': r.politica.punto_pedido, 'max': r.politica.stock_maximo,
        'hay_inconsistencia': any(inconsistente),
    }


LETRA_SIMPLE = {
    'R': 'Es un artículo R (se repone solo)',
    'E': 'Es un artículo E (estratégico: se mantiene siempre con su mínimo)',
    'P': 'Es un artículo P (a pedido: solo se compra lo comprometido en pedidos y OF)',
    'O': 'Es un artículo O (no se recompra: no tiene consumo regular ni pedidos abiertos)',
}
XYZ_SIMPLE = {'X': 'su consumo es estable', 'Y': 'su consumo es variable', 'Z': 'su consumo es errático o esporádico'}


def _que_dice(r, e, guardado, proxima, proveedor):
    """2-4 frases en lenguaje simple con la conclusion del calculo (SPEC-19 §5)."""
    frases = []
    letra = LETRA_SIMPLE.get(r.letra, f'Es un artículo {r.letra}')
    detalle = XYZ_SIMPLE.get(r.xyz, '')
    if r.letra in ('R', 'E') and r.clasificacion.subclase == 'INTERMITENTE':
        detalle = 'sale pocas veces al año, en cantidades grandes'
    frases.append(f'{letra}{", y " + detalle if detalle and r.letra != "O" else ""}.')

    co, ex = r.compra, r.excepcion
    prov = (proveedor.nombre or proveedor.codigo) if proveedor else None
    q = r.cantidad_a_comprar
    if not prov and (co.necesita_compra or (ex and ex.excepcion)):
        frases.append('Necesita compra, pero no tiene proveedor asignado: hay que definirlo antes de pedir.')
    if co.comprar:
        frases.append(f'Hoy es día de compra{" de " + prov if prov else ""}: se sugiere comprar {q:g} u '
                      f'(USD {_n(q * e.costo, 0)}) para llegar al máximo de {r.politica.stock_maximo}.')
    elif ex and ex.excepcion:
        fecha_q = (e.hoy + _dias(ex.dia_quiebre)).strftime('%d-%m')
        fecha_l = (e.hoy + _dias(ex.dia_llegada_posible)).strftime('%d-%m')
        texto = (f'Hoy no {"toca comprar a este proveedor" if prov else "es día de compra"}, pero el stock se acaba el {fecha_q}, antes de que llegue la '
                 f'próxima compra normal ({fecha_l}): se sugiere comprar {q:g} u fuera de calendario '
                 f'({CAUSAS.get(r.causa_excepcion, r.causa_excepcion).lower()}).')
        if ex.dias_quiebre_inevitable:
            texto += f' Aun comprando hoy faltaría stock {ex.dias_quiebre_inevitable} días: conviene buscar un traslado o una compra urgente.'
        frases.append(texto)
    elif co.necesita_compra:
        frases.append(f'Está bajo su punto de pedido: entra en la compra del {proxima:%d-%m} por {co.cantidad_sugerida} u.')
    elif r.letra == 'P' and co.cantidad_sugerida:
        frases.append(f'Hay pedidos que el stock no cubre: comprar {co.cantidad_sugerida} u.')
    elif r.politica.stock_maximo > 0:
        txt = f'No necesita compra: el disponible de la red ({co.disponible_futuro:g} u) está sobre el punto de pedido ({r.politica.punto_pedido}).'
        if ex and ex.dia_quiebre:
            txt += f' Al ritmo actual se acabaría el {(e.hoy + _dias(ex.dia_quiebre)):%d-%m}.'
        frases.append(txt)
    else:
        frases.append('No se sugiere compra.')

    if guardado:
        movs = []
        for b in guardado.bodegas.select_related('warehouse').exclude(accion='NINGUNA').order_by('warehouse__code')[:4]:
            if b.accion in ('TRASLADAR', 'TRASLADAR_PARCIAL'):
                origen = ', '.join(f'{_n(qq, 0)} desde {o}' for o, qq in b.origenes)
                movs.append(f'{b.warehouse.code} recibe {origen}' + (' (el resto espera la compra)' if b.accion == 'TRASLADAR_PARCIAL' else ''))
            elif b.accion == 'ESPERA_COMPRA':
                movs.append(f'{b.warehouse.code} espera la compra de la red ({_n(b.espera_compra, 0)} u)')
        if movs:
            frases.append('En bodegas: ' + '; '.join(movs) + '.')
    return frases


def _dias(n):
    import datetime
    return datetime.timedelta(days=int(n or 0))


@login_required
def articulo(request, code):
    producto = get_object_or_404(ProductSKU.objects.select_related('category'), code=code)
    e, r, prov_codigo, proxima = servicio.calcular_detalle(code)
    guardado = ResultadoArticulo.objects.filter(product=producto).select_related('proveedor', 'corrida').first()
    config = ArticuloConfig.objects.filter(product=producto).select_related('proveedor').first()
    proveedor = Proveedor.objects.filter(codigo=prov_codigo).first() if prov_codigo else None
    linea = _grafico_linea(producto, r, e)
    contexto = {
        'p': producto, 'e': e, 'r': r, 'guardado': guardado, 'config': config,
        'proveedor': proveedor,
        'proxima': proxima, 'memoria': _memoria(e, r), 'causas': CAUSAS,
        'que_dice': _que_dice(r, e, guardado, proxima, proveedor),
        'grafico_consumo': json.dumps(_grafico_consumo(producto, r, e)),
        'grafico_linea': json.dumps(linea), 'hay_inconsistencia': linea['hay_inconsistencia'],
        'bodegas': guardado.bodegas.select_related('warehouse').order_by('warehouse__code') if guardado else [],
        'traslados': guardado.traslados.select_related('origen', 'destino') if guardado else [],
        'oc_abiertas': OCAbierta.objects.filter(product=producto).order_by('fecha_comprometida'),
        'compromisos': CompromisoAbierto.objects.filter(product=producto).order_by('fecha')[:100],
        'plazos': PlazoOC.objects.filter(product=producto).order_by('-fecha_entrada')[:30],
        'historial': HistorialMensual.objects.filter(product=producto).order_by('-mes')[:24],
        # Documentos cerrados que respaldan el consumo (traidos de la ficha anterior, SPEC-20 §3)
        'movimientos_pc': producto.sales_movements.filter(status='Cerrado').order_by('-delivery_date')[:25],
        'movimientos_of': producto.of_movements.filter(status='Cerrada').order_by('-end_date')[:25],
        'alertas': Alerta.objects.filter(product=producto, vigente=True),
        'eventos': EventoComercial.objects.filter(product=producto),
        'puede_editar': puede_editar(request.user),
        'meses_consumo': list(zip([_mes(m) for m in servicio.meses_cerrados(e.hoy, len(r.consumo.meses))],
                                  r.consumo.meses_originales)),
    }
    return render(request, 'calculadora/articulo.html', contexto)


def _float(valor):
    try:
        return max(0.0, float(str(valor or '0').replace(',', '.')))
    except ValueError:
        raise ValueError(f'"{valor}" no es un número válido')


@login_required
@require_POST
def articulo_config(request, code):
    producto = get_object_or_404(ProductSKU, code=code)
    if not puede_editar(request.user):
        messages.error(request, 'Solo el administrador de Abastecimiento puede cambiar las marcas del artículo.')
        return redirect('calculadora:articulo', code=code)
    post = request.POST
    try:
        prov_codigo = post.get('proveedor', '').strip()
        proveedor = None
        if prov_codigo:
            proveedor = Proveedor.objects.filter(codigo=prov_codigo).first()
            if not proveedor:
                raise ValueError(f'El proveedor {prov_codigo} no existe')
        cfg, _ = ArticuloConfig.objects.get_or_create(product=producto)
        cfg.es_estrategico = post.get('es_estrategico') == 'on'
        cfg.es_critico = post.get('es_critico') == 'on'
        cfg.minimo_declarado = _float(post.get('minimo_declarado'))
        cfg.minimo_nuevo = _float(post.get('minimo_nuevo'))
        cfg.proveedor = proveedor
        cfg.nota = post.get('nota', '')[:255]
        cfg.actualizado_por = request.user
        cfg.save()
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect('calculadora:articulo', code=code)
    messages.success(request, 'Marcas guardadas. Se aplican en el próximo cálculo (Panel → Recalcular ahora).')
    return redirect('calculadora:articulo', code=code)


# ── Indicadores ───────────────────────────────────────────────────────────────

def _cobertura(grupos):
    """Meses de cobertura ponderados por valor: inventario USD ÷ consumo mensual USD."""
    return [(k, round(v['inv'] / v['cons'], 1) if v['cons'] else None, round(v['inv_act'] / v['cons'], 1) if v['cons'] else None)
            for k, v in sorted(grupos.items())]


def _impacto(familia_filtro, filtros_qs):
    meses = list(HistorialMensual.objects.values_list('mes', flat=True).distinct().order_by('-mes')[:2])
    if len(meses) < 2:
        return {'meses': meses, 'familias': [], 'top': [], 'disponible': False}
    actual, anterior = meses
    productos = set(filtros_qs.values_list('product_id', flat=True))
    previo = dict(HistorialMensual.objects.filter(mes=anterior, product_id__in=productos)
                  .values_list('product_id', 'valor_stock_maximo'))
    por_familia = defaultdict(lambda: [0.0, 0.0])
    deltas = []
    for sku, desc, fam, valor in HistorialMensual.objects.filter(mes=actual, product_id__in=productos).values_list(
            'product_id', 'product__description', 'product__sap_group_name', 'valor_stock_maximo'):
        antes = previo.get(sku, 0.0)
        por_familia[fam or 'Sin grupo'][0] += antes
        por_familia[fam or 'Sin grupo'][1] += valor
        deltas.append((sku, desc, antes, valor, valor - antes))
    familias = sorted(((f, a, b, b - a) for f, (a, b) in por_familia.items()), key=lambda x: -abs(x[3]))[:20]
    top = sorted(deltas, key=lambda x: -abs(x[4]))[:20]
    return {'meses': meses, 'actual': actual, 'anterior': anterior, 'familias': familias, 'top': top, 'disponible': True}


@login_required
def indicadores(request):
    g = request.GET
    f = {k: g.get(k, '').strip() for k in ('familia', 'proveedor', 'letra', 'abc', 'xyz')}
    qs = ResultadoArticulo.objects.filter(product__category__is_active=True)
    if f['xyz']:
        qs = qs.filter(xyz=f['xyz'])
    if f['familia']:
        qs = qs.filter(product__sap_group_code=f['familia'])
    if f['proveedor']:
        qs = qs.filter(Q(proveedor_id=f['proveedor']) | Q(proveedor__nombre__icontains=f['proveedor']))
    if f['letra']:
        qs = qs.filter(letra=f['letra'])
    if f['abc']:
        qs = qs.filter(abc=f['abc'])

    inv = {'prop': [0.0, 0.0, 0.0], 'act': [0.0, 0.0, 0.0]}
    compras = {'prop': [0.0] * 6, 'act': [0.0] * 6}
    quiebre = {k: {'articulos': 0, 'dias': 0, 'valor': 0.0} for k in ('prop', 'act')}
    cob_letra = defaultdict(lambda: {'inv': 0.0, 'inv_act': 0.0, 'cons': 0.0})
    cob_abc = defaultdict(lambda: {'inv': 0.0, 'inv_act': 0.0, 'cons': 0.0})
    por_prov = defaultdict(float)
    exceso, obsoleto = [], []
    campos = ('product_id', 'product__description', 'simulacion', 'costo_unitario', 'consumo_promedio_mes', 'letra',
              'abc', 'proveedor_id', 'proveedor__nombre', 'disponible_futuro', 'stock_maximo', 'stock_fisico',
              'es_inmovilizado')
    for row in qs.values(*campos).iterator(chunk_size=2000):
        costo = row['costo_unitario'] or 0
        sim = row['simulacion'] or {}
        cons = row['consumo_promedio_mes'] or 0
        for esc in ('prop', 'act'):
            s = sim.get(esc)
            if not s:
                continue
            for i, v in enumerate(s.get('inv', [])[:3]):
                inv[esc][i] += v * costo
            for i, v in enumerate(s.get('cm', [])[:6]):
                compras[esc][i] += v * costo
            if s.get('dq'):
                quiebre[esc]['articulos'] += 1
                quiebre[esc]['dias'] += s['dq']
                quiebre[esc]['valor'] += s.get('na', 0) * costo
        if sim.get('prop'):
            inv6 = sim['prop']['inv'][1] * costo
            inv6_act = sim.get('act', {}).get('inv', [0, 0, 0])[1] * costo
            for grupo, clave in ((cob_letra, row['letra']), (cob_abc, row['abc'])):
                grupo[clave]['inv'] += inv6
                grupo[clave]['inv_act'] += inv6_act
                grupo[clave]['cons'] += cons * costo
            por_prov[(row['proveedor_id'] or 'Sin proveedor', row['proveedor__nombre'] or '')] += sum(sim['prop'].get('cm', [])) * costo
        if row['stock_maximo'] > 0:
            sobre = row['disponible_futuro'] - (row['stock_maximo'] + 3 * cons)
            if sobre > 0 and costo > 0:
                exceso.append((row['product_id'], row['product__description'], sobre, sobre * costo))
        if (row['letra'] == 'O' or row['es_inmovilizado']) and row['stock_fisico'] > 0 and costo > 0:
            obsoleto.append((row['product_id'], row['product__description'], row['stock_fisico'],
                             row['stock_fisico'] * costo, row['es_inmovilizado']))

    exceso.sort(key=lambda x: -x[3])
    obsoleto.sort(key=lambda x: -x[3])
    import datetime
    from django.utils import timezone
    hoy = timezone.localdate()
    etiquetas_mes = []
    for i in range(6):
        total = hoy.year * 12 + hoy.month - 1 + i
        etiquetas_mes.append(_mes(datetime.date(total // 12, total % 12 + 1, 1)))
    familias = (ProductSKU.objects.filter(category__is_active=True, resultado_calc__isnull=False)
                .exclude(sap_group_code='').values_list('sap_group_code', 'sap_group_name').distinct().order_by('sap_group_name'))
    return render(request, 'calculadora/indicadores.html', {
        'f': f, 'letras': LETRAS, 'familias': familias,
        'inv': [(c, inv['act'][i], inv['prop'][i], inv['prop'][i] - inv['act'][i]) for i, c in enumerate(('3 meses', '6 meses', '12 meses'))],
        'quiebre': quiebre,
        'compras_total': (sum(compras['act']), sum(compras['prop'])),
        'grafico_compras': json.dumps({'labels': etiquetas_mes, 'act': [round(v, 2) for v in compras['act']],
                                       'prop': [round(v, 2) for v in compras['prop']]}),
        'top_proveedores': sorted(((k[0], k[1], v) for k, v in por_prov.items() if v > 0), key=lambda x: -x[2])[:12],
        'cobs': [('Letra', _cobertura(cob_letra)), ('ABC', _cobertura(cob_abc))],
        'exceso_total': sum(x[3] for x in exceso), 'exceso': exceso[:15], 'n_exceso': len(exceso),
        'obsoleto_total': sum(x[3] for x in obsoleto), 'obsoleto': obsoleto[:15], 'n_obsoleto': len(obsoleto),
        'intervencion': solicitudes.intervencion_comprador(),
        'impacto': _impacto(f['familia'], qs),
    })
