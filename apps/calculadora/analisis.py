"""Datos de la vista "Analizar articulos" (SPEC-24), al estilo de Slim4: un listado por ubicacion,
el mismo articulo en todas las ubicaciones y su historia + prevision mensual.

Ubicaciones: Santiago completo (nodo 013, con el que calcula la Calculadora), cada bodega 013-xx
(detalle informativo pedido por Produccion: 013-PS y 013-PP rotan distinto) y cada sucursal.
La compra y los traslados se deciden por nodo (SPEC-21); en una 013-xx no hay "a pedir".
"""
import datetime
import os
from collections import defaultdict

from django.utils import timezone

from apps.calc.prevision import prever
from apps.calc.red import NODO_SANTIAGO
from apps.data_ingestion.datalake_ingest import find_data_file
from apps.data_ingestion.warehouses import (NO_CUENTA, STOCK, TRANSITO, SUCURSAL_CITIES, nodo_red, nombre_nodo,
                                            tratamiento_por_defecto, zone_for, SANTIAGO)
from apps.inventory.models import InventoryMetric, Warehouse
from apps.inventory.stock_actual_models import StockActual

from .models import ConsumoMensual, OCAbierta, ResultadoArticulo, ResultadoBodega
from .parametros import Resolutor
from .servicio import meses_cerrados

NODO, BODEGA = 'NODO', 'BODEGA'
MESES = 12


def ubicaciones():
    """[(codigo, nombre, tipo)]: Santiago, sus bodegas 013-xx activas y las sucursales."""
    bodegas = sorted(w.code for w in Warehouse.objects.filter(is_active=True) if zone_for(w.code) == SANTIAGO)
    return ([(NODO_SANTIAGO, 'Santiago (todas)', NODO)]
            + [(b, b, BODEGA) for b in bodegas]
            + [(c, f'{c} {n}', NODO) for c, n in SUCURSAL_CITIES.items()])


def _ubicacion_de(bodega):
    """Ubicaciones a las que suma el consumo de una bodega de SAP: su nodo y, si es una 013-xx, ella."""
    nodo = nodo_red(bodega)
    if not nodo:
        return ()
    b = (bodega or '').strip().upper()
    return (nodo, b) if nodo == NODO_SANTIAGO and b.startswith('013-') else (nodo,)


def _consumo(meses, sku=None, ubicacion=None):
    """(sku, ubicacion) -> consumo de cada mes (mas antiguo primero)."""
    indice = {m: i for i, m in enumerate(meses)}
    qs = ConsumoMensual.objects.filter(mes__in=meses)
    if sku:
        qs = qs.filter(product_id=sku)
    datos = defaultdict(lambda: [0.0] * len(meses))
    for s, bodega, mes, q in qs.values_list('product_id', 'bodega', 'mes', 'cantidad'):
        for u in _ubicacion_de(bodega):
            if ubicacion is None or u == ubicacion:
                datos[(s, u)][indice[mes]] += q
    return datos


def _posicion(sku=None, ubicacion=None):
    """(sku, ubicacion) -> dict(stock, recibir, entregar, a_pedir). Nodos desde la ultima corrida
    (la misma posicion con la que calcula); bodegas 013-xx desde las metricas de inventario."""
    datos = {}
    nodos = ResultadoBodega.objects.all()
    bodegas = InventoryMetric.objects.filter(warehouse__code__startswith='013-')
    if sku:
        nodos, bodegas = nodos.filter(resultado__product_id=sku), bodegas.filter(product_id=sku)
    if ubicacion:
        if ubicacion.startswith('013-'):
            nodos = nodos.none()
            bodegas = bodegas.filter(warehouse__code=ubicacion)
        else:
            nodos, bodegas = nodos.filter(warehouse__code=ubicacion), bodegas.none()
    compra_red = {}
    for s, comprar, excepcion, sugerida, cant_exc, necesita in ResultadoArticulo.objects.filter(
            **({'product_id': sku} if sku else {})).values_list(
            'product_id', 'comprar', 'excepcion', 'cantidad_sugerida', 'cantidad_excepcion', 'necesita_compra'):
        compra_red[s] = sugerida if (comprar or necesita) else (cant_exc if excepcion else 0)
    for s, code, fis, tra, com, falt in nodos.values_list('resultado__product_id', 'warehouse__code', 'stock_fisico',
                                                            'en_transito', 'comprometido', 'faltante'):
        # Santiago recibe la compra de la red; una sucursal pide su faltante (traslado o espera compra)
        datos[(s, code)] = {'stock': fis, 'recibir': tra, 'entregar': com,
                            'a_pedir': compra_red.get(s, 0) if code == NODO_SANTIAGO else falt}
    for s, code, fis, oc, sc, ti, pc, of in bodegas.values_list(
            'product_id', 'warehouse__code', 'stock_physical', 'oc_po_qty', 'sc_qty', 'stock_transito_inter',
            'comp_pc_qty', 'comp_of_qty'):
        datos[(s, code)] = {'stock': fis, 'recibir': oc + sc + ti, 'entregar': pc + of, 'a_pedir': None}
    # Santiago sin fila de nodo (todo en cero) pero con compra de la red
    if ubicacion in (None, NODO_SANTIAGO):
        for s, q in compra_red.items():
            if q and (s, NODO_SANTIAGO) not in datos:
                datos[(s, NODO_SANTIAGO)] = {'stock': 0, 'recibir': 0, 'entregar': 0, 'a_pedir': q}
    return datos


def _fila(sku, ubicacion, historia, pos, params, costo):
    p = prever(historia, params, MESES)
    pos = pos or {'stock': 0, 'recibir': 0, 'entregar': 0, 'a_pedir': None if ubicacion.startswith('013-') else 0}
    return {
        'codigo': sku, 'ubicacion': ubicacion, 'demanda': round(p.promedio, 2), 'a_pedir': pos['a_pedir'],
        'stock': pos['stock'], 'recibir': pos['recibir'], 'entregar': pos['entregar'],
        'venta12': round(sum(p.historia), 2), 'meses': p.meses_con_demanda, 'costo': costo,
        'valor': round(pos['stock'] * costo, 2), 'prevision': p,
    }


ORDENES = {'codigo', 'demanda', 'a_pedir', 'stock', 'recibir', 'entregar', 'venta12', 'meses', 'costo', 'valor'}


def listado(ubicacion, buscar='', solo_a_pedir=False, orden='-meses', hoy=None):
    """Filas de una ubicacion: articulos del alcance con consumo en 12 meses o posicion en ella."""
    hoy = hoy or timezone.localdate()
    meses = meses_cerrados(hoy, MESES)
    params = Resolutor().general
    articulos = {s: (d, c) for s, d, c in ResultadoArticulo.objects.values_list(
        'product_id', 'product__description', 'costo_unitario')}
    consumo = _consumo(meses, ubicacion=ubicacion)
    posicion = _posicion(ubicacion=ubicacion)
    skus = {s for s, _ in consumo} | {s for s, _ in posicion}
    buscar = (buscar or '').strip().lower()
    filas = []
    for s in skus:
        if s not in articulos:
            continue
        desc, costo = articulos[s]
        if buscar and buscar not in s.lower() and buscar not in (desc or '').lower():
            continue
        f = _fila(s, ubicacion, consumo.get((s, ubicacion), [0.0] * MESES), posicion.get((s, ubicacion)), params, costo)
        if solo_a_pedir and not f['a_pedir']:
            continue
        if not (f['venta12'] or f['stock'] or f['recibir'] or f['entregar'] or f['a_pedir']):
            continue
        f['descripcion'] = desc
        filas.append(f)
    campo = orden.lstrip('-')
    campo = campo if campo in ORDENES else 'meses'
    filas.sort(key=lambda f: f['codigo'])
    # Los vacios (el "a pedir" de una 013-xx) quedan al final en ambos sentidos
    if orden.startswith('-'):
        filas.sort(key=lambda f: (f[campo] is not None, f[campo] or 0), reverse=True)
    else:
        filas.sort(key=lambda f: (f[campo] is None, f[campo] or 0))
    return filas


def detalle(sku, hoy=None):
    """El articulo en todas las ubicaciones, con historia y prevision de cada una."""
    hoy = hoy or timezone.localdate()
    meses = meses_cerrados(hoy, MESES)
    params = Resolutor().general
    r = ResultadoArticulo.objects.select_related('product').filter(product_id=sku).first()
    costo = r.costo_unitario if r else 0.0
    consumo = _consumo(meses, sku=sku)
    posicion = _posicion(sku=sku)
    filas = []
    for codigo, nombre, tipo in ubicaciones():
        historia = consumo.get((sku, codigo), [0.0] * MESES)
        f = _fila(sku, codigo, historia, posicion.get((sku, codigo)), params, costo)
        # Las 013-xx sin movimiento ni stock no aportan; Santiago y las sucursales siempre se ven
        if tipo == BODEGA and not (f['venta12'] or f['stock'] or f['recibir'] or f['entregar']):
            continue
        p = f.pop('prevision')
        f.update({'nombre': nombre, 'tipo': tipo, 'historia': [round(v, 2) for v in p.historia],
                  'valores': list(p.valores), 'tendencia': round(p.tendencia, 3),
                  'desde_ultima': p.meses_desde_ultima})
        filas.append(f)
    futuro = []
    for k in range(1, MESES + 1):
        total = hoy.year * 12 + hoy.month - 1 + k - 1
        futuro.append(f'{total % 12 + 1:02d}-{str(total // 12)[2:]}')
    return {
        'codigo': sku, 'descripcion': r.product.description if r else '', 'letra': r.letra if r else '',
        'abc': r.abc if r else '', 'xyz': r.xyz if r else '',
        'etiquetas': [f'{m.month:02d}-{str(m.year)[2:]}' for m in meses] + futuro,
        'ubicaciones': filas,
        **bodegas_sap(sku),
    }


# Consultas que forman la posicion de un articulo, con la fecha en que se exportaron (SPEC-29)
_ARCHIVOS_POSICION = [
    ('Stock', 'Stock Físico por Bodega.txt', 'oitw.txt'),
    ('OC', 'Órdenes de Compra en Tránsito (OC).txt', 'opor_por1.txt'),
    ('SC', 'Solicitudes de Compra (SC).txt', 'oprq_prq1.txt'),
    ('PC', 'Pedidos de Clientes (PC).txt', 'ordr_rdr1.txt'),
    ('OF', 'Órdenes de Fabricación (OF).txt', 'owor_wor1.txt'),
]
DESFASE_AVISO_HORAS = 4


def fechas_datos():
    """[(dato, fecha de exportacion)] y el desfase en horas entre la mas antigua y la mas nueva.
    La fecha es la del archivo: una consulta exportada otro dia ve otra foto de SAP."""
    fechas = []
    for dato, largo, alt in _ARCHIVOS_POSICION:
        ruta = find_data_file(largo, alt)
        if os.path.exists(ruta):
            fechas.append((dato, datetime.datetime.fromtimestamp(os.path.getmtime(ruta))))
    horas = ((max(f for _, f in fechas) - min(f for _, f in fechas)).total_seconds() / 3600) if fechas else 0
    return [{'dato': d, 'fecha': f'{f:%d-%m %H:%M}'} for d, f in fechas], round(horas, 1)


def bodegas_sap(sku):
    """El articulo en cada bodega de SAP (como el maestro de articulos > Datos de inventario): stock,
    lo pedido en SAP (OITW.OnOrder), las OC abiertas cargadas y como cuenta en el calculo (SPEC-27).
    Avisa cuando SAP tiene unidades pedidas sin OC abierta cargada: suele ser un desfase entre la
    exportacion del stock y la de las OC (lo recibido entre ambas no aparece en ninguna)."""
    oc = defaultdict(float)
    for bodega, q in OCAbierta.objects.filter(product_id=sku).values_list('bodega', 'cantidad_pendiente'):
        oc[bodega] += q
    stock = {b: (q, ped) for b, q, ped in StockActual.objects.filter(codigo=sku).values_list(
        'bodega', 'stock_disponible', 'stock_pedido')}
    codigos = {b for b, (q, ped) in stock.items() if q or ped} | {b for b, q in oc.items() if q}
    almacenes = {w.code: w for w in Warehouse.objects.filter(code__in=codigos)}
    filas, totales = [], {STOCK: 0.0, TRANSITO: 0.0, NO_CUENTA: 0.0, 'sin_oc': 0.0}
    for codigo in codigos:
        q, pedido = stock.get(codigo, (0, 0))
        w = almacenes.get(codigo)
        tipo, nodo, motivo, manual = w.tratamiento_efectivo if w else (*tratamiento_por_defecto(codigo, False), False)
        texto = {STOCK: f'Stock de {nombre_nodo(nodo)}', TRANSITO: f'En camino a {nombre_nodo(nodo)}'}.get(tipo, 'No cuenta')
        sin_oc = max(0.0, pedido - oc.get(codigo, 0.0))
        totales[tipo] += q
        totales['sin_oc'] += sin_oc
        filas.append({'bodega': codigo, 'nombre': w.name if w else codigo, 'stock': q, 'pedido_sap': pedido,
                      'oc': oc.get(codigo, 0.0), 'sin_oc': sin_oc, 'tipo': tipo, 'cuenta': texto, 'motivo': motivo,
                      'manual': manual})
    orden = {STOCK: 0, TRANSITO: 1, NO_CUENTA: 2}
    filas.sort(key=lambda f: (orden[f['tipo']], -f['stock'], f['bodega']))
    fechas, desfase = fechas_datos()
    return {'bodegas_sap': filas, 'totales_sap': totales, 'fechas_datos': fechas, 'desfase_horas': desfase,
            'desfase_aviso': desfase > DESFASE_AVISO_HORAS}
