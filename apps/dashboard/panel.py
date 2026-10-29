"""Panel S&OP (SPEC-28): un solo tablero gerencial con las cifras de la ultima corrida de la
Calculadora. Reemplaza al Dashboard S&OP y a Analitica, que volvian a sumar las proyecciones
publicadas con otras definiciones (urgentes por nodo, unidades de articulos distintos).

Regla: sin filtros, cada KPI es identico al resumen de la corrida (`servicio._resumen`).
Todo se expresa en USD; nunca se suman unidades de articulos distintos.
"""

from django.db.models import Count, Max

from apps.calculadora.models import Alerta, CargaDatos, Corrida, ResultadoArticulo, ResultadoBodega
from apps.calculadora.parametros import Resolutor
from apps.data_ingestion.warehouses import nodos_red

# Tramos de cobertura (dias) de los articulos que se reponen (R/E)
TRAMOS_COBERTURA = [(0, 'Sin stock'), (15, '1-15 d'), (30, '16-30 d'), (60, '31-60 d'), (90, '61-90 d'),
                    (180, '91-180 d'), (None, 'Más de 180 d')]
LETRAS = [('R', 'Se repone'), ('E', 'Estratégico'), ('P', 'A pedido'), ('O', 'No se recompra')]


def ultima_corrida():
    return Corrida.objects.filter(estado=Corrida.OK).order_by('-inicio').first()


def _filtrar(qs, filtros, prefijo=''):
    if filtros.get('grupo'):
        qs = qs.filter(**{f'{prefijo}product__category__code': filtros['grupo']})
    if filtros.get('letra'):
        qs = qs.filter(**{f'{prefijo}letra': filtros['letra']})
    if filtros.get('abc'):
        qs = qs.filter(**{f'{prefijo}abc': filtros['abc']})
    return qs


def indicadores(corrida, filtros=None):
    """KPIs, nodos, letras, cobertura, top de compras y alertas de la corrida, con filtros
    opcionales (grupo, letra, abc). Mismas formulas que el resumen de la corrida."""
    filtros = filtros or {}
    qs = _filtrar(ResultadoArticulo.objects.filter(corrida=corrida), filtros)
    sobre_meses = Resolutor().general.alerta_sobrestock_meses

    k = dict.fromkeys(('articulos', 'comprar', 'necesita_compra', 'excepciones', 'urgentes', 'compra_hoy_usd',
                       'necesita_usd', 'quiebre_usd', 'brecha_usd', 'stock_usd', 'sobrestock_usd',
                       'sobrestock_articulos'), 0.0)
    por_letra = {l: {'letra': l, 'nombre': n, 'articulos': 0, 'compra_hoy': 0.0, 'necesita': 0.0, 'stock': 0.0}
                 for l, n in LETRAS}
    cobertura = [0] * len(TRAMOS_COBERTURA)
    compras = []
    campos = ('product_id', 'product__description', 'letra', 'abc', 'costo_unitario', 'comprar', 'cantidad_sugerida',
              'excepcion', 'cantidad_excepcion', 'necesita_compra', 'valor_sugerido', 'urgencia', 'stock_maximo',
              'disponible_futuro', 'faltante', 'stock_fisico', 'cobertura_dias', 'consumo_promedio_mes')
    for fila in qs.values_list(*campos):
        r = dict(zip(campos, fila))
        costo = r['costo_unitario'] or 0
        compra_q = r['cantidad_sugerida'] if r['comprar'] else (r['cantidad_excepcion'] if r['excepcion'] else 0)
        compra_usd = compra_q * costo
        k['articulos'] += 1
        k['comprar'] += int(r['comprar'])
        k['necesita_compra'] += int(r['necesita_compra'])
        k['excepciones'] += int(r['excepcion'])
        k['urgentes'] += int(r['urgencia'] == 'URGENTE' and r['stock_maximo'] > 0)
        k['compra_hoy_usd'] += compra_usd
        if r['necesita_compra']:
            k['necesita_usd'] += r['valor_sugerido'] or 0
        if r['disponible_futuro'] < 0:
            k['quiebre_usd'] += -r['disponible_futuro'] * costo
        k['brecha_usd'] += r['faltante'] * costo
        k['stock_usd'] += r['stock_fisico'] * costo
        if r['stock_maximo'] > 0 and r['disponible_futuro'] > r['stock_maximo'] + sobre_meses * r['consumo_promedio_mes']:
            k['sobrestock_usd'] += (r['disponible_futuro'] - r['stock_maximo']) * costo
            k['sobrestock_articulos'] += 1
        letra = por_letra.get(r['letra'])
        if letra:
            letra['articulos'] += 1
            letra['compra_hoy'] += compra_usd
            letra['necesita'] += (r['valor_sugerido'] or 0) if r['necesita_compra'] else 0
            letra['stock'] += r['stock_fisico'] * costo
        if r['letra'] in ('R', 'E'):
            cobertura[_tramo(r['cobertura_dias'], r['stock_fisico'])] += 1
        if compra_usd > 0:
            compras.append({'codigo': r['product_id'], 'descripcion': r['product__description'] or '',
                            'letra': r['letra'], 'abc': r['abc'], 'cantidad': compra_q, 'usd': compra_usd,
                            'urgencia': r['urgencia'], 'excepcion': r['excepcion']})
    compras.sort(key=lambda c: -c['usd'])

    return {
        'kpi': k, 'nodos': _por_nodo(corrida, filtros), 'letras': list(por_letra.values()),
        'cobertura': [{'tramo': t[1], 'articulos': n} for t, n in zip(TRAMOS_COBERTURA, cobertura)],
        'top_compras': compras[:15], 'alertas': _alertas(corrida, filtros),
    }


def _tramo(dias, stock):
    if not stock or stock <= 0:
        return 0
    if dias is None:
        return len(TRAMOS_COBERTURA) - 1      # con stock y sin consumo: cobertura indefinida
    for i, (tope, _) in enumerate(TRAMOS_COBERTURA[1:-1], start=1):
        if dias <= tope:
            return i
    return len(TRAMOS_COBERTURA) - 1


def _por_nodo(corrida, filtros):
    """Stock, faltante y excedente valorizados por nodo, y traslados sugeridos hacia el nodo."""
    nombres = dict(nodos_red())
    filas = {n: {'nodo': n, 'nombre': nombres[n], 'stock_usd': 0.0, 'faltante_usd': 0.0, 'excedente_usd': 0.0,
                 'urgentes': 0, 'recibe_traslado': 0, 'espera_compra': 0} for n in nombres}
    qs = _filtrar(ResultadoBodega.objects.filter(resultado__corrida=corrida), filtros, 'resultado__')
    for nodo, costo, stock, faltante, excedente, urgencia, trasladar, espera in qs.values_list(
            'warehouse__code', 'resultado__costo_unitario', 'stock_fisico', 'faltante', 'excedente', 'urgencia',
            'cantidad_trasladar', 'espera_compra'):
        f = filas.get(nodo)
        if not f:
            continue
        costo = costo or 0
        f['stock_usd'] += stock * costo
        f['faltante_usd'] += faltante * costo
        f['excedente_usd'] += excedente * costo
        f['urgentes'] += int(urgencia == 'URGENTE')
        f['recibe_traslado'] += int(trasladar > 0)
        f['espera_compra'] += int(espera > 0)
    return list(filas.values())


def _alertas(corrida, filtros):
    qs = Alerta.objects.filter(vigente=True)
    if any(filtros.get(c) for c in ('grupo', 'letra', 'abc')):
        articulos = _filtrar(ResultadoArticulo.objects.filter(corrida=corrida), filtros).values('product_id')
        qs = qs.filter(product_id__in=articulos)
    nombres = dict(Alerta.TIPOS)
    return [{'tipo': t, 'nombre': nombres.get(t, t), 'n': n}
            for t, n in qs.values_list('tipo').annotate(n=Count('id')).order_by('-n')]


def evolucion(n=20):
    """Ultimas n corridas OK: fecha y cifras del resumen, de la mas antigua a la mas reciente."""
    filas = []
    for c in Corrida.objects.filter(estado=Corrida.OK).order_by('-inicio')[:n]:
        r = c.resumen or {}
        filas.append({'id': c.pk, 'fecha': c.inicio, 'compra_hoy_usd': r.get('valor_sugerido', 0),
                      'necesita_compra': r.get('necesita_compra', 0), 'quiebre_usd': r.get('quiebre_real_usd', 0)})
    return filas[::-1]


def cargas_recientes():
    """Ultima carga de cada tabla: de donde vienen los datos y cuando (calidad de datos)."""
    ultimas = CargaDatos.objects.values('tabla').annotate(ultima=Max('id')).values_list('ultima', flat=True)
    return list(CargaDatos.objects.filter(id__in=list(ultimas)).order_by('tabla'))
