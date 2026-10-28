"""Corrida de la Calculadora: lee la BD, arma las entradas del nucleo puro (apps.calc),
calcula todos los articulos y guarda los resultados (SPEC-18 §3).

Cada corrida recalcula todo desde cero (documento §1) y reemplaza los resultados de la
anterior. La historia mensual (clasificacion, valor del stock maximo) se conserva.
"""
import datetime
import math
import os
import time
from collections import defaultdict
from dataclasses import replace

from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from apps.calc import calendario
from apps.calc.clasificacion import PANOL, REPUESTOS, clases_abc
from apps.calc.motor import EntradaArticulo, calcular_articulo
from apps.calc.plazo import calcular_plazo
from apps.calc.proyeccion import dia_llegada_oc
from apps.calc.red import Bodega
from apps.calc.simulacion import Escenario, simular
from apps.data_ingestion.datalake_ingest import find_data_file
from apps.data_ingestion.warehouses import SANTIAGO, commitment_bodega
from apps.inventory.group_types import PANOL as TIPO_PANOL
from apps.inventory.models import InventoryMetric, ProductSKU, StockProjection, Warehouse

from . import alertas, publicacion
from .models import (ArticuloConfig, CargaDatos, CompromisoAbierto, ConsumoMensual, Corrida, Equivalencia,
                     EscenarioActual, EventoComercial, HistorialMensual, LineaSolicitud, OCAbierta, ParametroCompra,
                     PlazoOC, Proveedor, ResultadoArticulo, ResultadoBodega, SolicitudCompra, TrasladoSugerido)
from .parametros import Resolutor

CENTRAL = '013-PP'


def meses_cerrados(hoy, n):
    """Primer dia de los ultimos n meses cerrados, del mas antiguo al mas reciente."""
    total = hoy.year * 12 + hoy.month - 1
    return [datetime.date((total - i) // 12, (total - i) % 12 + 1, 1) for i in range(n, 0, -1)]


def _en_rango(mes, inicio, fin):
    return inicio.replace(day=1) <= mes <= fin.replace(day=1)


def _mtime_carga_sc():
    ruta = find_data_file('Solicitudes de Compra (SC).txt', 'oprq_prq1.txt')
    return os.path.getmtime(ruta) if os.path.exists(ruta) else 0


class Datos:
    """Todo lo que la corrida necesita, cargado una sola vez en memoria.
    Con `producto` carga solo ese articulo (detalle y memoria de calculo)."""

    def __init__(self, hoy, resolutor, producto=None):
        self.hoy = hoy
        self.resolutor = resolutor
        general = resolutor.general
        self.meses = meses_cerrados(hoy, general.meses_historia_consumo)
        self.indice_mes = {m: i for i, m in enumerate(self.meses)}

        def filtro(qs):
            return qs.filter(product_id=producto.code) if producto else qs.all()

        if producto:
            self.productos = [producto]
        else:
            self.productos = list(ProductSKU.objects.filter(is_active=True, category__is_active=True)
                                  .select_related('category'))
        self.bodegas = {w.code: w for w in Warehouse.objects.filter(is_active=True) if w.zone}

        # Consumo de la red por articulo y mes (todas las bodegas: las salidas de la 013 y
        # de consignacion son demanda de Santiago, SPEC-07 §5). Equivalencias suman al nuevo.
        equiv = dict(Equivalencia.objects.values_list('codigo_antiguo', 'codigo_nuevo'))
        consumo_qs = ConsumoMensual.objects.all()
        if producto:
            antiguos = [a for a, n in equiv.items() if n == producto.code]
            consumo_qs = consumo_qs.filter(product_id__in=[producto.code] + antiguos)
        self.consumo = defaultdict(lambda: [0.0] * len(self.meses))
        self.consumo_bodega = defaultdict(float)     # (sku, bodega) -> consumo de 12 meses (SPEC-19 §3.2)
        self.ultimo_mov = {}
        for sku, bodega, mes, q in consumo_qs.values_list('product_id', 'bodega', 'mes', 'cantidad'):
            sku = equiv.get(sku, sku)
            if q > 0 and (sku not in self.ultimo_mov or mes > self.ultimo_mov[sku]):
                self.ultimo_mov[sku] = mes
            i = self.indice_mes.get(mes)
            if i is not None:
                self.consumo[sku][i] += q
                self.consumo_bodega[(sku, commitment_bodega(bodega))] += q

        self.metricas = defaultdict(list)
        for m in filtro(InventoryMetric.objects.select_related('warehouse')):
            if m.warehouse.code in self.bodegas:
                self.metricas[m.product_id].append(m)

        # Compromisos con fecha (proyeccion) y fecha mas cercana por bodega (reparto)
        self.compromisos = defaultdict(list)
        self.fecha_compromiso = {}
        for sku, bodega, fecha, q in filtro(CompromisoAbierto.objects).values_list('product_id', 'bodega', 'fecha', 'cantidad'):
            self.compromisos[sku].append(((fecha - hoy).days if fecha else 1, q))
            if fecha and ((sku, bodega) not in self.fecha_compromiso or fecha < self.fecha_compromiso[(sku, bodega)]):
                self.fecha_compromiso[(sku, bodega)] = fecha

        self.oc = defaultdict(list)
        for o in filtro(OCAbierta.objects):
            self.oc[o.product_id].append(o)

        # Solicitudes de la plataforma aprobadas que SAP todavia no refleja: se suman al
        # transito al crearlas (§5). Las exportadas cuentan hasta la siguiente carga de SC.
        self.solicitado = defaultdict(float)
        carga_sc = _mtime_carga_sc()
        for l in filtro(LineaSolicitud.objects.select_related('solicitud')).exclude(estado=LineaSolicitud.DESCARTADA):
            s = l.solicitud
            if s.estado == SolicitudCompra.APROBADA or (
                    s.estado == SolicitudCompra.EXPORTADA and s.aprobada_en and s.aprobada_en.timestamp() > carga_sc):
                self.solicitado[l.product_id] += l.cantidad_final

        desde = hoy - datetime.timedelta(days=30 * general.meses_historia_oc)
        self.plazos = defaultdict(list)
        for sku, dias in filtro(PlazoOC.objects.filter(fecha_entrada__gte=desde)).values_list('product_id', 'dias_entrega'):
            self.plazos[sku].append(dias)

        self.param_compra = {p.product_id: p for p in filtro(ParametroCompra.objects)}
        self.config = {c.product_id: c for c in filtro(ArticuloConfig.objects)}
        self.proveedores = {p.codigo: p for p in Proveedor.objects.all()}

        self.eventos_sku = defaultdict(list)
        self.eventos_familia = defaultdict(list)
        for ev in EventoComercial.objects.filter(estado=EventoComercial.APROBADO):
            if ev.product_id:
                self.eventos_sku[ev.product_id].append(ev)
            elif ev.familia:
                self.eventos_familia[ev.familia].append(ev)

        # Escenario actual (motor anterior) para comparar. Desde SPEC-19 StockProjection lo
        # publica la Calculadora: el motor anterior queda en EscenarioActual. Solo si nunca se
        # publico se lee StockProjection (primera corrida tras instalar SPEC-19).
        self.rop_actual = {}
        self.sugerido_actual = defaultdict(int)
        escenario = filtro(EscenarioActual.objects)
        if escenario.exists():
            filas = escenario.values_list('product_id', 'bodega', 'rop', 'sugerido_compra')
        elif not Corrida.objects.filter(resumen__publicado=True).exists():
            filas = filtro(StockProjection.objects).values_list('product_id', 'warehouse__code', 'rop', 'suggested_buy_units')
        else:
            filas = []
        for sku, bodega, rop, q in filas:
            self.sugerido_actual[sku] += q or 0
            if bodega == CENTRAL:
                self.rop_actual[sku] = rop or 0


def _segmento(p):
    tipo = p.category.tipo if p.category else ''
    return PANOL if tipo == TIPO_PANOL else REPUESTOS


def _familia(p):
    return p.sap_group_code or (p.category.code if p.category else '')


def _eventos(datos, p):
    return (datos.eventos_sku.get(p.code, []) + datos.eventos_familia.get(p.sap_group_code, [])
            + (datos.eventos_familia.get(p.category.name, []) if p.category else []))


def _ajuste_y_meses_evento(datos, p, consumo_meses):
    """Ajuste mensual de los eventos aprobados vigentes este mes y meses de historia
    cubiertos por algun evento (no se marcan atipicos, §4.7)."""
    eventos = _eventos(datos, p)
    if not eventos:
        return 0.0, ()
    mes = datos.hoy.replace(day=1)
    promedio = sum(consumo_meses) / max(1, len(consumo_meses))
    ajuste = 0.0
    for ev in eventos:
        if _en_rango(mes, ev.mes_inicio, ev.mes_fin):
            delta = ev.cantidad_adicional / max(1, ev.meses_vigencia) if ev.cantidad_adicional \
                else promedio * ev.porcentaje / 100.0
            ajuste += -abs(delta) if ev.tipo == EventoComercial.BAJA else delta
    meses_evento = tuple(i for i, m in enumerate(datos.meses)
                         if any(_en_rango(m, ev.mes_inicio, ev.mes_fin) for ev in eventos))
    return ajuste, meses_evento


def _entrada(datos, p, abc):
    """EntradaArticulo del nucleo + proveedor y proxima fecha de compra."""
    hoy = datos.hoy
    cfg = datos.config.get(p.code)
    pc = datos.param_compra.get(p.code)
    prov_codigo = (cfg.proveedor_id if cfg and cfg.proveedor_id else '') or (pc.proveedor_preferido if pc else '')
    prov = datos.proveedores.get(prov_codigo)
    params = datos.resolutor.para(familia=_familia(p), proveedor=prov_codigo, articulo=p.code)

    # Calendario del proveedor (§4.6.1)
    if prov and prov.frecuencia_compra_dias:
        params = replace(params, frecuencia_compra_dias=prov.frecuencia_compra_dias)
    frecuencia = params.frecuencia_compra_dias
    ancla = prov.fecha_ancla if prov and prov.fecha_ancla else calendario.ancla_por_defecto(prov_codigo or p.code, frecuencia)
    proxima = calendario.proxima_fecha_compra(hoy, frecuencia, ancla)

    solicitado = datos.solicitado.get(p.code, 0)
    bodegas = []
    for m in datos.metricas.get(p.code, []):
        code = m.warehouse.code
        transito = m.oc_po_qty + m.sc_qty + m.stock_transito_inter + (solicitado if code == CENTRAL else 0)
        bodegas.append(Bodega(
            codigo=code, es_central=code == CENTRAL, es_santiago=m.warehouse.zone == SANTIAGO,
            stock_fisico=m.stock_physical, en_transito=transito, comprometido=m.comp_pc_qty + m.comp_of_qty,
            fecha_compromiso=datos.fecha_compromiso.get((p.code, code)),
        ))
    if solicitado and not any(b.es_central for b in bodegas):
        bodegas.append(Bodega(CENTRAL, es_central=True, es_santiago=True, en_transito=solicitado))

    lead_maestro = pc.lead_time_maestro if pc and pc.lead_time_maestro else p.lead_time_days
    llegadas, atrasada = [], False
    for o in datos.oc.get(p.code, []):
        dias = (o.fecha_comprometida - hoy).days if o.fecha_comprometida else 0
        atrasada = atrasada or (o.fecha_comprometida is not None and o.fecha_comprometida < hoy)
        llegadas.append((dia_llegada_oc(dias, params.dias_recepcion), o.cantidad_pendiente))
    if solicitado:
        plazo = calcular_plazo(datos.plazos.get(p.code), lead_maestro, params)
        llegadas.append((int(math.ceil(plazo.plazo_total_dias)), solicitado))

    consumo_meses = datos.consumo.get(p.code) or [0.0] * len(datos.meses)
    ajuste, meses_evento = _ajuste_y_meses_evento(datos, p, consumo_meses)

    entrada = EntradaArticulo(
        codigo=p.code, hoy=hoy, params=params, segmento=_segmento(p), abc=abc,
        es_estrategico=bool(cfg and cfg.es_estrategico), minimo_declarado=cfg.minimo_declarado if cfg else 0,
        es_critico=bool(cfg and cfg.es_critico), minimo_nuevo=cfg.minimo_nuevo if cfg else 0,
        bloqueado=bool(pc and pc.bloqueado),
        fecha_creacion=p.fec_creacion_sap, fecha_ultimo_movimiento=datos.ultimo_mov.get(p.code),
        consumo_meses=consumo_meses, meses_evento=meses_evento, ajuste_comercial=ajuste,
        dias_oc=datos.plazos.get(p.code, []), lead_time_maestro=lead_maestro,
        costo=float(p.unit_cost_usd or 0), min_compra=pc.min_compra if pc else 0,
        multiplo=pc.multiplo_compra if pc else 0, bodegas=bodegas,
        compromisos=datos.compromisos.get(p.code, []), llegadas=llegadas, oc_atrasada=atrasada,
        dias_a_proxima_compra=(proxima - hoy).days, es_dia_compra=proxima == hoy,
    )
    return entrada, (prov_codigo if prov else ''), proxima


def _simulaciones(e, r, datos):
    """Escenario propuesto vs actual a 12 meses (SPEC-15 §3)."""
    if r.consumo.consumo_diario <= 0 or r.politica.stock_maximo <= 0:
        return {}
    inicial = r.stock_fisico - r.comprometido
    prop = simular(inicial, r.consumo.consumo_diario, Escenario(
        umbral=r.compra.umbral_compra, hasta=r.politica.stock_maximo,
        plazo_dias=int(math.ceil(r.plazo.plazo_total_dias)),
        revision_dias=e.params.frecuencia_compra_dias, primera_revision=e.dias_a_proxima_compra,
        minimo_compra=max(e.min_compra, e.params.meses_minimo_compra * r.politica.consumo_usado),
        multiplo=e.multiplo), e.llegadas)
    rop_act = datos.rop_actual.get(e.codigo, 0) or 0
    act = simular(inicial, r.consumo.consumo_diario, Escenario(
        umbral=rop_act, hasta=rop_act, plazo_dias=int(math.ceil((e.lead_time_maestro or 0) + 2))), e.llegadas)

    def _d(s):
        return {'inv': [round(v, 2) for v in s.inventario], 'dq': s.dias_quiebre,
                'na': round(s.unidades_no_atendidas, 2), 'cm': [round(v, 2) for v in s.compras_mes]}
    return {'prop': _d(prop), 'act': _d(act)}


def _fecha(hoy, dia):
    return hoy + datetime.timedelta(days=int(dia)) if dia is not None else None


def ejecutar_corrida(usuario=None, hoy=None, guardar=True, extra_general=None):
    """Corrida completa. Con guardar=False no toca la BD y devuelve el resumen (simulacion
    de un cambio de parametros, SPEC-14 §4)."""
    hoy = hoy or timezone.localdate()
    t0 = time.time()
    corrida = None
    if guardar:
        ultima = CargaDatos.objects.filter(tabla='consumo_mensual').first()
        corrida = Corrida.objects.create(fecha_calculo=hoy, usuario=usuario,
                                         fuente_consumo=ultima.fuente if ultima else 'SIN_CARGA')
    try:
        resolutor = Resolutor(extra_general=extra_general)
        datos = Datos(hoy, resolutor)

        # ABC sobre toda la poblacion: valor de consumo anual = cantidad x costo
        valor_anual = {p.code: sum(datos.consumo.get(p.code, ())) * float(p.unit_cost_usd or 0) for p in datos.productos}
        abc = clases_abc(valor_anual, resolutor.general)

        calculados = []
        for p in datos.productos:
            e, prov, proxima = _entrada(datos, p, abc.get(p.code, 'C'))
            calculados.append((p, e, calcular_articulo(e), prov, proxima))

        resumen = _resumen(calculados)
        if not guardar:
            return resumen
        _guardar(corrida, datos, calculados, valor_anual)
        resumen['alertas'] = alertas.generar(corrida, hoy)
        resumen['publicacion'] = publicacion.publicar(corrida)
        resumen['publicado'] = True
        resumen['segundos'] = round(time.time() - t0, 1)
        corrida.estado = Corrida.OK
        corrida.resumen = resumen
        corrida.fin = timezone.now()
        corrida.save()
        return corrida
    except Exception as exc:
        if corrida:
            corrida.estado = Corrida.ERROR
            corrida.error = repr(exc)[:2000]
            corrida.fin = timezone.now()
            corrida.save()
        raise


def recalcular_red(usuario=None, recargar=False):
    """Recalculo completo en el orden de SPEC-19 §2: motor anterior (escenario actual),
    captura del escenario y corrida de la Calculadora, que publica encima. Es el unico punto
    de entrada para recalcular fuera de Sincronizar: correr solo el motor anterior deja el
    Dashboard con numeros distintos a los de la Calculadora."""
    from apps.inventory.classification_engine import run_classification_engine
    from .cargadores import cargar_todo
    run_classification_engine()
    publicacion.capturar_escenario_actual()
    if recargar:
        cargar_todo()
    return ejecutar_corrida(usuario=usuario)


def calcular_detalle(codigo, hoy=None):
    """Recalcula un articulo en memoria para la memoria de calculo y la serie diaria del
    detalle. Usa el ABC de la ultima corrida (depende de toda la poblacion)."""
    hoy = hoy or timezone.localdate()
    p = ProductSKU.objects.select_related('category').get(code=codigo)
    datos = Datos(hoy, Resolutor(), producto=p)
    previo = ResultadoArticulo.objects.filter(product=p).values_list('abc', flat=True).first()
    e, prov, proxima = _entrada(datos, p, previo or 'C')
    return e, calcular_articulo(e), prov, proxima


def historico_articulo(codigo, hoy=None, meses=12):
    """Stock al cierre de los ultimos meses cerrados, reconstruido hacia atras desde el stock
    fisico de hoy de la red (SPEC-19 §3.3). Devuelve [(mes, stock, inconsistente)]."""
    from django.db.models import Sum

    from apps.calc.historico import reconstruir
    from apps.inventory.models import GoodsReceipt
    hoy = hoy or timezone.localdate()
    lista = meses_cerrados(hoy, meses)
    inicio = lista[0]
    bodegas = {w.code for w in Warehouse.objects.filter(is_active=True) if w.zone}
    stock_hoy = InventoryMetric.objects.filter(product_id=codigo, warehouse__code__in=bodegas).aggregate(
        s=Sum('stock_physical'))['s'] or 0

    def por_mes(pares):
        acumulado = defaultdict(float)
        for fecha, q in pares:
            if fecha:
                acumulado[fecha.replace(day=1)] += float(q or 0)
        return acumulado

    entradas = por_mes(GoodsReceipt.objects.filter(product_id=codigo, posting_date__gte=inicio)
                       .values_list('posting_date', 'quantity'))
    consumo = por_mes(ConsumoMensual.objects.filter(product_id=codigo, mes__gte=inicio).values_list('mes', 'cantidad'))
    actual = hoy.replace(day=1)
    puntos = reconstruir(stock_hoy, [entradas.get(m, 0) for m in lista], [consumo.get(m, 0) for m in lista],
                         entradas.get(actual, 0), consumo.get(actual, 0))
    return [(m, pt.stock, pt.inconsistente) for m, pt in zip(lista, puntos)]


def _resumen(calculados):
    letras = defaultdict(int)
    res = {'articulos': len(calculados), 'comprar': 0, 'necesita_compra': 0, 'excepciones': 0, 'urgentes': 0,
           'valor_sugerido': 0.0, 'valor_stock_maximo': 0.0, 'traslados': 0, 'unidades_trasladar': 0.0,
           'quiebre_real_usd': 0.0, 'brecha_objetivo_usd': 0.0}
    for p, e, r, prov, proxima in calculados:
        letras[r.letra] += 1
        res['comprar'] += int(r.compra.comprar)
        res['necesita_compra'] += int(r.compra.necesita_compra)
        res['excepciones'] += int(bool(r.excepcion and r.excepcion.excepcion))
        res['urgentes'] += int(r.compra.urgencia == 'URGENTE' and r.politica.stock_maximo > 0)
        res['valor_sugerido'] += r.cantidad_a_comprar * e.costo
        res['valor_stock_maximo'] += r.compra.valor_stock_maximo
        res['traslados'] += len(r.traslados)
        res['unidades_trasladar'] += sum(t.cantidad for t in r.traslados)
        # Quiebre real (disponible < 0) separado de la brecha contra el objetivo (§5, §12)
        if r.compra.disponible_futuro < 0:
            res['quiebre_real_usd'] += -r.compra.disponible_futuro * e.costo
        res['brecha_objetivo_usd'] += r.compra.faltante * e.costo
    res['letras'] = dict(letras)
    for k in ('valor_sugerido', 'valor_stock_maximo', 'quiebre_real_usd', 'brecha_objetivo_usd'):
        res[k] = round(res[k], 2)
    return res


@transaction.atomic
def _guardar(corrida, datos, calculados, valor_anual):
    hoy = datos.hoy
    ResultadoArticulo.objects.all().delete()   # cascada: bodegas y traslados
    objetos = []
    for p, e, r, prov, proxima in calculados:
        c, pl, po, co, ex = r.consumo, r.plazo, r.politica, r.compra, r.excepcion
        objetos.append(ResultadoArticulo(
            corrida=corrida, product=p, proveedor_id=prov or None,
            letra=r.letra, subclase=r.clasificacion.subclase, motivo_clasificacion=r.clasificacion.motivo[:150],
            abc=e.abc, xyz=r.xyz, segmento=e.segmento, es_nuevo=r.es_nuevo, es_inmovilizado=r.es_inmovilizado,
            es_critico=e.es_critico, nivel_servicio=r.nivel_servicio, factor_servicio=po.factor_servicio,
            consumo_meses=[round(v, 2) for v in c.meses_originales], meses_con_consumo_12m=c.meses_con_consumo_12m,
            consumo_promedio_mes=c.consumo_promedio_mes,
            consumo_ajustado_mes=po.consumo_usado if e.ajuste_comercial else None,
            consumo_diario=c.consumo_diario, variacion_consumo=c.variacion_consumo,
            tope_mes_atipico=c.tope_mes_atipico, mayor_consumo_mes=c.mayor_consumo_mes,
            valor_consumo_anual=valor_anual.get(p.code, 0),
            dias_entrega_promedio=pl.dias_entrega_promedio, variacion_entrega_dias=pl.variacion_entrega_dias,
            plazo_total_dias=pl.plazo_total_dias, origen_plazo=pl.origen, n_oc=pl.n_oc,
            metodo=po.metodo, ss_calculado=po.ss_calculado, piso_ss=po.piso_ss, stock_seguridad=po.stock_seguridad,
            punto_pedido=po.punto_pedido, stock_maximo=po.stock_maximo, salidas_en_plazo=po.salidas_en_plazo,
            stock_fisico=r.stock_fisico, en_transito=r.en_transito, comprometido=r.comprometido,
            disponible_futuro=co.disponible_futuro, cobertura_dias=co.cobertura_dias,
            necesita_compra=co.necesita_compra, comprar=co.comprar, faltante=co.faltante,
            cantidad_sugerida=co.cantidad_sugerida, costo_unitario=e.costo, valor_sugerido=co.valor_sugerido,
            urgencia=co.urgencia, fecha_llegada_estimada=_fecha(hoy, math.ceil(pl.plazo_total_dias)),
            valor_stock_maximo=co.valor_stock_maximo,
            proxima_fecha_compra=proxima, es_dia_compra=e.es_dia_compra,
            fecha_quiebre_proyectada=_fecha(hoy, ex.dia_quiebre) if ex else None,
            fecha_bajo_ss=_fecha(hoy, ex.dia_bajo_ss) if ex else None,
            fecha_llegada_posible=_fecha(hoy, ex.dia_llegada_posible) if ex else None,
            excepcion=bool(ex and ex.excepcion), causa_excepcion=r.causa_excepcion,
            cantidad_excepcion=r.cantidad_excepcion, dias_quiebre_inevitable=ex.dias_quiebre_inevitable if ex else 0,
            oc_atrasada=e.oc_atrasada,
            cantidad_actual=datos.sugerido_actual.get(p.code, 0),
            valor_actual=datos.sugerido_actual.get(p.code, 0) * e.costo,
            simulacion=_simulaciones(e, r, datos),
            avisos=r.avisos,
        ))
    creados = {o.product_id: o for o in ResultadoArticulo.objects.bulk_create(objetos, batch_size=2000)}

    bodegas_obj, traslados_obj = [], []
    for p, e, r, prov, proxima in calculados:
        res = creados[p.code]
        posicion = {b.codigo: b for b in e.bodegas}
        for a in r.acciones:
            b, wh = posicion.get(a.codigo), datos.bodegas.get(a.codigo)
            if not wh or not b or not (b.stock_fisico or b.en_transito or b.comprometido or a.faltante):
                continue
            consumo_dia = datos.consumo_bodega.get((p.code, a.codigo), 0.0) / 365.0
            bodegas_obj.append(ResultadoBodega(
                consumo_diario=consumo_dia,
                cobertura_dias=a.disponible_futuro / consumo_dia if consumo_dia > 0 else None,
                resultado=res, warehouse=wh, stock_fisico=b.stock_fisico, en_transito=b.en_transito,
                comprometido=b.comprometido, disponible_futuro=a.disponible_futuro, objetivo=a.objetivo,
                faltante=a.faltante, excedente=a.excedente, accion=a.accion, cantidad_trasladar=a.cantidad_trasladar,
                espera_compra=a.espera_compra, origenes=[[o, q] for o, q in a.origenes],
                sucursales_con_stock=a.sucursales_con_stock,
                urgencia='URGENTE' if a.faltante > 0 and a.disponible_futuro <= 0 else ('MEDIO' if a.faltante > 0 else 'NORMAL'),
            ))
        for t in r.traslados:
            if t.origen in datos.bodegas and t.destino in datos.bodegas:
                destino = posicion.get(t.destino)
                traslados_obj.append(TrasladoSugerido(
                    resultado=res, product=p, origen=datos.bodegas[t.origen], destino=datos.bodegas[t.destino],
                    cantidad=t.cantidad,
                    urgencia='URGENTE' if destino is None or destino.disponible_futuro <= 0 else 'MEDIO'))
    ResultadoBodega.objects.bulk_create(bodegas_obj, batch_size=5000)
    TrasladoSugerido.objects.bulk_create(traslados_obj, batch_size=5000)
    _historial(datos, calculados)


def _historial(datos, calculados):
    """Foto del mes en curso: se reescribe en cada corrida del mes; la letra anterior es la
    del ultimo mes registrado antes de este (SPEC-09 §5)."""
    mes = datos.hoy.replace(day=1)
    anteriores = {}
    ultimo_mes = HistorialMensual.objects.filter(mes__lt=mes).aggregate(m=Max('mes'))['m']
    if ultimo_mes:
        anteriores = dict(HistorialMensual.objects.filter(mes=ultimo_mes).values_list('product_id', 'letra'))
    HistorialMensual.objects.filter(mes=mes).delete()
    filas = []
    for p, e, r, prov, proxima in calculados:
        anterior = anteriores.get(p.code, '')
        filas.append(HistorialMensual(
            product=p, mes=mes, letra=r.letra, subclase=r.clasificacion.subclase, abc=e.abc, xyz=r.xyz,
            letra_anterior=anterior, motivo=r.clasificacion.motivo[:150] if anterior and anterior != r.letra else '',
            valor_stock_maximo=r.compra.valor_stock_maximo, stock_maximo=r.politica.stock_maximo,
            consumo_promedio_mes=r.consumo.consumo_promedio_mes, variacion_consumo=r.consumo.variacion_consumo,
        ))
    HistorialMensual.objects.bulk_create(filas, batch_size=5000)
