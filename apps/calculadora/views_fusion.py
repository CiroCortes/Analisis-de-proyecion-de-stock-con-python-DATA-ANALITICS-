"""Vistas de la fusion del Recomendador en la Calculadora (SPEC-19): bodegas y zonas (§4),
segmentacion ABC-XYZ (§6) y guia en lenguaje simple (§7.2). Mas "Analizar articulos" (SPEC-24)."""
import statistics
from collections import defaultdict

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Case, F, IntegerField, Q, Value, When
from django.http import JsonResponse
from django.shortcuts import render

from apps.calc.red import NODO_SANTIAGO
from apps.data_ingestion.warehouses import SANTIAGO, SUCURSAL, SUCURSAL_CITIES, SUCURSAL_CODES, zona_red
from apps.inventory.models import Warehouse

from . import analisis
from .excel import respuesta_excel
from .glosario import GLOSARIO
from .models import CargaDatos, ResultadoArticulo, ResultadoBodega, TrasladoSugerido
from .parametros import Resolutor

ACCIONES = [('TRASLADAR', 'Trasladar'), ('TRASLADAR_PARCIAL', 'Trasladar parcial'),
            ('ESPERA_COMPRA', 'Espera compra'), ('NINGUNA', 'Sin acción')]
ACCION_TXT = dict(ACCIONES)
URGENCIAS = [('URGENTE', 'Urgente'), ('MEDIO', 'Medio'), ('NORMAL', 'Normal')]
SANTIAGO_Q = Q(warehouse__code='013') | Q(warehouse__code__startswith='013-')


def _num(x):
    s = f'{float(x or 0):,.2f}'.rstrip('0').rstrip('.') if x else '0'
    return s.replace(',', 'X').replace('.', ',').replace('X', '.')


# ── Bodegas y zonas (§4) ─────────────────────────────────────────────────────

def _filtros_bodegas(request):
    g = request.GET
    f = {k: g.get(k, '').strip() for k in ('zona', 'bodega', 'accion', 'urgencia', 'search')}
    f['todo'] = g.get('todo') == '1'
    return f


def _base_bodegas(f, con_accion=True):
    """Filas del alcance y la zona/bodega/busqueda. `con_accion` aplica accion, urgencia y
    el filtro por defecto (solo filas con faltante o accion)."""
    qs = ResultadoBodega.objects.filter(resultado__product__category__is_active=True)
    if f['zona'] == SANTIAGO:
        qs = qs.filter(SANTIAGO_Q)
    elif f['zona'] == SUCURSAL:
        qs = qs.filter(warehouse__code__in=SUCURSAL_CODES)
    if f['bodega']:
        qs = qs.filter(warehouse__code=f['bodega'])
    if f['search']:
        qs = qs.filter(Q(resultado__product__code__icontains=f['search'])
                       | Q(resultado__product__description__icontains=f['search']))
    if con_accion:
        if f['accion']:
            qs = qs.filter(accion=f['accion'])
        if f['urgencia']:
            qs = qs.filter(urgencia=f['urgencia'])
        if not f['todo'] and not f['accion']:
            qs = qs.filter(Q(faltante__gt=0) | ~Q(accion='NINGUNA'))
    return qs


def _ordenar(qs):
    return qs.annotate(
        zona_orden=Case(When(SANTIAGO_Q, then=Value(0)), When(warehouse__code__in=SUCURSAL_CODES, then=Value(1)),
                        default=Value(2), output_field=IntegerField()),
        urg_orden=Case(When(urgencia='URGENTE', then=Value(0)), When(urgencia='MEDIO', then=Value(1)),
                       default=Value(2), output_field=IntegerField()),
    ).order_by('zona_orden', 'warehouse__code', 'urg_orden', F('cobertura_dias').asc(nulls_last=True),
               'resultado__product__code')


def _origenes_txt(origenes):
    return ', '.join(f'{_num(q)} desde {o}' for o, q in (origenes or []))


def _tarjetas(f):
    """Resumen por bodega sobre la zona/bodega/busqueda filtrada (sin el filtro de accion)."""
    base = _base_bodegas(f, con_accion=False)
    datos = defaultdict(lambda: {'riesgo': 0, 'quiebre_usd': 0.0, 'espera': 0, 'coberturas': [],
                                 'acciones': defaultdict(int), 'nombre': ''})
    for code, nombre, faltante, disp, costo, accion, cob in base.values_list(
            'warehouse__code', 'warehouse__name', 'faltante', 'disponible_futuro', 'resultado__costo_unitario',
            'accion', 'cobertura_dias'):
        d = datos[code]
        d['nombre'] = nombre
        if faltante > 0:
            d['riesgo'] += 1
        if disp < 0:
            d['quiebre_usd'] += -disp * (costo or 0)
        if accion == 'ESPERA_COMPRA':
            d['espera'] += 1
        d['acciones'][accion] += 1
        if cob is not None:
            d['coberturas'].append(cob)

    tras = TrasladoSugerido.objects.filter(product__category__is_active=True)
    entrantes, salientes = defaultdict(lambda: [0, 0.0]), defaultdict(lambda: [0, 0.0])
    for origen, destino, q in tras.values_list('origen__code', 'destino__code', 'cantidad'):
        entrantes[destino][0] += 1
        entrantes[destino][1] += q
        salientes[origen][0] += 1
        salientes[origen][1] += q

    tarjetas = []
    for code, d in datos.items():
        zona = zona_red(code)
        tarjetas.append({
            'code': code, 'nombre': d['nombre'], 'zona': zona, 'ciudad': SUCURSAL_CITIES.get(code, ''),
            'riesgo': d['riesgo'], 'quiebre_usd': d['quiebre_usd'], 'espera': d['espera'],
            'cobertura_mediana': statistics.median(d['coberturas']) if d['coberturas'] else None,
            'entran': entrantes[code][0], 'entran_u': entrantes[code][1],
            'salen': salientes[code][0], 'salen_u': salientes[code][1],
        })
    tarjetas.sort(key=lambda t: (0 if t['zona'] == SANTIAGO else 1 if t['zona'] == SUCURSAL else 2, t['code']))

    conteo = defaultdict(int)
    for d in datos.values():
        for a, n in d['acciones'].items():
            conteo[a] += n
    totales = {
        'riesgo': sum(t['riesgo'] for t in tarjetas), 'quiebre_usd': sum(t['quiebre_usd'] for t in tarjetas),
        'espera': sum(t['espera'] for t in tarjetas),
        # cada traslado sale de un nodo y entra a otro: se cuenta una vez
        'traslados': sum(t['entran'] for t in tarjetas), 'unidades': sum(t['entran_u'] for t in tarjetas),
    }
    return tarjetas, conteo, totales


@login_required
def bodegas(request):
    f = _filtros_bodegas(request)
    qs = _ordenar(_base_bodegas(f).select_related('resultado', 'resultado__product', 'warehouse'))
    page_obj = Paginator(qs, 50).get_page(request.GET.get('page'))
    filas = list(page_obj.object_list)
    for b in filas:
        b.origenes_txt = _origenes_txt(b.origenes)
        b.cobertura_corta = b.cobertura_dias is not None and b.cobertura_dias < (b.resultado.plazo_total_dias or 0)
        b.accion_txt = ACCION_TXT.get(b.accion, b.accion)

    tarjetas, conteo, totales = _tarjetas(f)
    pills = [(a, nombre, conteo.get(a, 0)) for a, nombre in ACCIONES if a != 'NINGUNA']
    codigos = sorted({t['code'] for t in tarjetas} | set(
        ResultadoBodega.objects.values_list('warehouse__code', flat=True).distinct()),
        key=lambda c: (0 if zona_red(c) == SANTIAGO else 1, c))
    sin_pagina = request.GET.copy()
    sin_pagina.pop('page', None)
    sin_accion = request.GET.copy()
    for k in ('page', 'accion'):
        sin_accion.pop(k, None)
    return render(request, 'calculadora/bodegas.html', {
        'f': f, 'page_obj': page_obj, 'filas': filas, 'tarjetas': tarjetas, 'totales': totales, 'pills': pills,
        'acciones': ACCIONES, 'urgencias': URGENCIAS, 'bodegas_lista': codigos,
        'total': page_obj.paginator.count, 'qs_sin_pagina': sin_pagina.urlencode(),
        'qs_sin_accion': sin_accion.urlencode(),
    })


@login_required
def bodegas_excel(request):
    f = _filtros_bodegas(request)
    qs = _ordenar(_base_bodegas(f).select_related('resultado', 'resultado__product', 'warehouse'))
    filas = [{
        'Bodega': b.warehouse.code, 'Zona': {SANTIAGO: 'Santiago', SUCURSAL: 'Sucursal'}.get(zona_red(b.warehouse.code), ''),
        'Artículo': b.resultado.product_id, 'Descripción': b.resultado.product.description,
        'Letra': b.resultado.letra, 'Stock físico': b.stock_fisico, 'En tránsito': b.en_transito,
        'Comprometido': b.comprometido, 'Disponible a futuro': b.disponible_futuro, 'Objetivo': b.objetivo,
        'Faltante': b.faltante, 'Consumo diario': round(b.consumo_diario, 3),
        'Cobertura (días)': round(b.cobertura_dias, 1) if b.cobertura_dias is not None else '',
        'Acción': ACCION_TXT.get(b.accion, b.accion), 'A trasladar': b.cantidad_trasladar,
        'Espera compra': b.espera_compra, 'Origen': _origenes_txt(b.origenes), 'Urgencia': b.urgencia,
        'Quiebre real USD': round(max(0.0, -b.disponible_futuro) * (b.resultado.costo_unitario or 0), 2),
    } for b in qs]
    return respuesta_excel('bodegas_calculadora.xlsx', filas, 'Bodegas')


# ── Segmentacion ABC-XYZ (§6) ────────────────────────────────────────────────

RECOMENDACION = {
    ('A', 'X'): 'Automatizar con revisión semanal', ('A', 'Y'): 'Revisar cada compra',
    ('A', 'Z'): 'Decidir con el comercial; evitar sobrestock',
    ('B', 'X'): 'Automatizar', ('B', 'Y'): 'Automatizar con revisión mensual', ('B', 'Z'): 'Revisar antes de aprobar',
    ('C', 'X'): 'Automatizar al máximo', ('C', 'Y'): 'Automatizar', ('C', 'Z'): 'Comprar a pedido o lote mínimo',
}
ALCANCES = {'rep': ('R', 'E', 'P'), 're': ('R', 'E'), 'todo': None}
XYZ_TXT = {'X': 'Estable', 'Y': 'Variable', 'Z': 'Errático'}
ABC_TXT = {'A': 'Alto valor', 'B': 'Valor medio', 'C': 'Bajo valor'}


def _cantidad_accion(comprar, excepcion, sugerida, cant_exc):
    if comprar:
        return sugerida
    return cant_exc if excepcion else 0


@login_required
def segmentacion(request):
    alcance = request.GET.get('alcance', 'rep')
    if alcance not in ALCANCES:
        alcance = 'rep'
    qs = ResultadoArticulo.objects.filter(product__category__is_active=True)
    if ALCANCES[alcance]:
        qs = qs.filter(letra__in=ALCANCES[alcance])

    celdas = {(a, x): {'n': 0, 'stock': 0.0, 'comprar': 0.0} for a in 'ABC' for x in 'XYZ'}
    for abc, xyz, fisico, costo, comprar, exc, sug, cexc in qs.values_list(
            'abc', 'xyz', 'stock_fisico', 'costo_unitario', 'comprar', 'excepcion', 'cantidad_sugerida',
            'cantidad_excepcion'):
        c = celdas.get((abc, xyz))
        if c is None:
            continue
        costo = costo or 0
        c['n'] += 1
        c['stock'] += max(0.0, fisico) * costo
        c['comprar'] += _cantidad_accion(comprar, exc, sug, cexc) * costo

    total_stock = sum(c['stock'] for c in celdas.values()) or 0
    max_stock = max((c['stock'] for c in celdas.values()), default=0) or 1
    filas = []
    for a in 'ABC':
        fila = []
        for x in 'XYZ':
            c = celdas[(a, x)]
            intensidad = c['stock'] / max_stock
            fila.append({
                'abc': a, 'xyz': x, **c, 'pct': 100 * c['stock'] / total_stock if total_stock else 0,
                'recomendacion': RECOMENDACION[(a, x)],
                # 5 tonos de cian segun el valor relativo de la celda
                'tono': 0 if c['n'] == 0 else 1 + min(4, int(intensidad * 4.999)),
            })
        filas.append({'abc': a, 'abc_txt': ABC_TXT[a], 'celdas': fila})

    riesgosos = list(qs.filter(abc='A', xyz='Z').select_related('product').order_by('-valor_consumo_anual')[:10])
    for r in riesgosos:
        r.cv = r.variacion_consumo / r.consumo_promedio_mes if r.consumo_promedio_mes else None

    p = Resolutor().general
    return render(request, 'calculadora/segmentacion.html', {
        'filas': filas, 'xyz_cols': [(x, XYZ_TXT[x]) for x in 'XYZ'], 'alcance': alcance,
        'total_stock': total_stock, 'total_n': sum(c['n'] for c in celdas.values()),
        'total_comprar': sum(c['comprar'] for c in celdas.values()),
        'riesgosos': riesgosos,
        'corte_a': round(p.corte_abc_a * 100), 'corte_b': round(p.corte_abc_b * 100),
        'corte_c': max(0, 100 - round(p.corte_abc_a * 100) - round(p.corte_abc_b * 100)),
        'corte_x': p.corte_xyz_x, 'corte_y': p.corte_xyz_y,
    })


# ── Guia (§7.2) ──────────────────────────────────────────────────────────────

SECCIONES = [
    ('Clasificación', 'Cómo se ordenan los artículos y qué trato recibe cada uno.',
     ['letra_R', 'letra_E', 'letra_P', 'letra_O', 'abc', 'xyz', 'subclase', 'nuevo', 'inmovilizado']),
    ('Cálculo', 'Los números que decide la Calculadora para cada artículo.',
     ['consumo_promedio', 'variacion', 'plazo', 'stock_seguridad', 'punto_pedido', 'stock_maximo',
      'disponible', 'cobertura', 'cantidad_sugerida', 'urgencia']),
    ('Red y calendario', 'Cómo se compra para toda la red y cómo se reparte entre bodegas.',
     ['compra_red', 'traslado', 'traslado_parcial', 'espera_compra', 'dia_compra', 'excepcion', 'quiebre_inevitable']),
    ('Indicadores', 'Cómo leer los montos de los paneles.', ['quiebre_real', 'brecha', 'escenario_actual']),
]

PASOS = [
    ('Revisar "Hoy"', 'Qué hay que hacer hoy y el estado de los datos.', 'calculadora:panel', ''),
    ('Aprobar las solicitudes del día de compra', 'Cada proveedor tiene su día; revisar cantidades y aprobar.',
     'calculadora:solicitudes', ''),
    ('Atender las excepciones', 'Artículos que se quiebran antes de la próxima compra normal.',
     'calculadora:grilla', '?compra=excepcion'),
    ('Ejecutar los traslados', 'Mover stock libre de Santiago a las bodegas que lo necesitan.',
     'calculadora:bodegas', '?accion=TRASLADAR'),
    ('Revisar las alertas', 'Cambios de consumo, OC atrasadas, datos que faltan.', 'calculadora:alertas', ''),
]

TABLAS = {
    'consumo_mensual': 'Consumo mensual', 'plazos_oc': 'Plazos reales de OC', 'parametros_compra': 'Proveedor, mínimo y múltiplo',
    'oc_abiertas': 'OC abiertas', 'compromisos': 'Pedidos y OF abiertos', 'acuerdos': 'Acuerdos globales',
    'proveedores': 'Proveedores', 'bodegas': 'Bodegas',
}
SEMAFORO = {'TXT': ('verde', 'Dato real'), 'OINM': ('verde', 'Dato real'),
            'RESPALDO': ('amarillo', 'Provisional'), 'PC_OF': ('amarillo', 'Provisional'),
            'SIN_ARCHIVO': ('rojo', 'Falta el archivo')}


@login_required
def guia(request):
    secciones = []
    usadas = set()
    for titulo, intro, claves in SECCIONES:
        entradas = []
        for clave in claves:
            if clave in GLOSARIO:
                termino, definicion, ejemplo, que_hacer = GLOSARIO[clave]
                entradas.append({'clave': clave, 'termino': termino, 'definicion': definicion,
                                 'ejemplo': ejemplo, 'que_hacer': que_hacer})
                usadas.add(clave)
        secciones.append({'titulo': titulo, 'intro': intro, 'entradas': entradas})
    resto = [k for k in GLOSARIO if k not in usadas]
    if resto:
        secciones.append({'titulo': 'Otros términos', 'intro': '', 'entradas': [
            {'clave': k, 'termino': GLOSARIO[k][0], 'definicion': GLOSARIO[k][1], 'ejemplo': GLOSARIO[k][2],
             'que_hacer': GLOSARIO[k][3]} for k in resto]})

    ultimas = {}
    for c in CargaDatos.objects.all()[:300]:
        ultimas.setdefault(c.tabla, c)
    fuentes = []
    for tabla, nombre in TABLAS.items():
        c = ultimas.get(tabla)
        color, estado = SEMAFORO.get(c.fuente, ('amarillo', c.fuente)) if c else ('rojo', 'Nunca cargado')
        fuentes.append({'nombre': nombre, 'color': color, 'estado': estado, 'carga': c})

    return render(request, 'calculadora/guia.html', {'secciones': secciones, 'pasos': PASOS, 'fuentes': fuentes})


# ── Analizar articulos (SPEC-24): vista tipo Slim4 ───────────────────────────

def _filtros_analisis(request):
    codigos = [c for c, _, _ in analisis.ubicaciones()]
    ubicacion = request.GET.get('ubicacion', NODO_SANTIAGO)
    return {'ubicacion': ubicacion if ubicacion in codigos else NODO_SANTIAGO,
            'search': request.GET.get('search', '').strip(), 'a_pedir': request.GET.get('a_pedir') == '1',
            'orden': request.GET.get('orden', '-meses')}


@login_required
def analizar(request):
    f = _filtros_analisis(request)
    filas = analisis.listado(f['ubicacion'], f['search'], f['a_pedir'], f['orden'])
    page_obj = Paginator(filas, 100).get_page(request.GET.get('page'))
    params = request.GET.copy()
    params.pop('page', None)
    sin_orden = params.copy()
    sin_orden.pop('orden', None)
    return render(request, 'calculadora/analizar.html', {
        'f': f, 'page_obj': page_obj, 'query': params.urlencode(), 'query_sin_orden': sin_orden.urlencode(),
        'ubicaciones': analisis.ubicaciones(), 'total': len(filas),
        'es_bodega': f['ubicacion'].startswith('013-'),
        'es_otra': analisis.es_otra_bodega(f['ubicacion']),
        'trat_otra': _tratamiento_texto(f['ubicacion']) if analisis.es_otra_bodega(f['ubicacion']) else '',
        'columnas': [('codigo', 'Código'), ('demanda', 'Demanda media'), ('a_pedir', 'A pedir'),
                     ('stock', 'Stock'), ('recibir', 'Por recibir'), ('entregar', 'Por entregar'),
                     ('venta12', 'Consumo 12 m'), ('meses', 'Meses c/ consumo'), ('costo', 'Costo USD'),
                     ('valor', 'Stock USD')],
    })


def _tratamiento_texto(codigo):
    from apps.data_ingestion.warehouses import NO_CUENTA, STOCK, TRANSITO, nombre_nodo
    w = Warehouse.objects.filter(code=codigo).first()
    if not w:
        return ''
    tipo, nodo, motivo, _ = w.tratamiento_efectivo
    texto = {STOCK: f'cuenta como stock de {nombre_nodo(nodo)}', TRANSITO: f'cuenta como en camino a {nombre_nodo(nodo)}'}
    return texto.get(tipo, f'no cuenta: {motivo}')


@login_required
def analizar_detalle(request, code):
    return JsonResponse(analisis.detalle(code))


@login_required
def analizar_excel(request):
    f = _filtros_analisis(request)
    filas = [{
        'Ubicacion': r['ubicacion'], 'Articulo': r['codigo'], 'Descripcion': r['descripcion'],
        'Demanda media mes': r['demanda'], 'A pedir': r['a_pedir'] if r['a_pedir'] is not None else '',
        'Stock': r['stock'], 'Por recibir': r['recibir'], 'Por entregar': r['entregar'],
        'Consumo 12 meses': r['venta12'], 'Meses con consumo': r['meses'],
        'Tendencia u/mes': round(r['prevision'].tendencia, 3),
        'Prevision proximos 12 meses': round(sum(r['prevision'].valores), 2),
        'Costo USD': r['costo'], 'Stock USD': r['valor'],
    } for r in analisis.listado(f['ubicacion'], f['search'], f['a_pedir'], f['orden'])]
    return respuesta_excel(f'analizar_{f["ubicacion"]}.xlsx', filas, 'Analizar articulos')
