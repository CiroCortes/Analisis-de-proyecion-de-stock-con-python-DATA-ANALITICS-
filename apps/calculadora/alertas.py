"""Alertas de la Calculadora (documento §8, SPEC-15 §1).

Cada corrida evalua las reglas sobre los resultados. Una alerta se identifica por su
`clave` (tipo + articulo, + mes en las mensuales): si la condicion sigue, se mantiene con
su estado y comentario; si deja de cumplirse queda `vigente=False` (no se borra).
"""
import datetime
import statistics
from collections import defaultdict

from django.db import transaction
from django.db.models import F, Sum

from apps.data_ingestion.warehouses import nodo_red, nombre_nodo

from .models import (AcuerdoGlobal, Alerta, ConsumoMensual, EventoComercial, HistorialMensual, ResultadoArticulo,
                     ResultadoBodega)

ALTA, MEDIA, BAJA = 'ALTA', 'MEDIA', 'BAJA'


def _prom(v):
    return sum(v) / len(v) if v else 0.0


def _meses(hoy, n):
    """'AAAA-MM' de los ultimos n meses cerrados, del mas antiguo al mas reciente."""
    total = hoy.year * 12 + hoy.month - 1
    return [f'{(total - i) // 12}-{(total - i) % 12 + 1:02d}' for i in range(n, 0, -1)]


def _reglas_articulo(r, p, mes_txt):
    """Alertas de un ResultadoArticulo. Devuelve [(clave, tipo, severidad, mensaje)]."""
    out = []
    if getattr(r, 'marca', '') == ResultadoArticulo.EXCLUIDO:
        return out          # excluido del calculo (SPEC-31 §1.1): no hay nada que gestionar
    sku = r.product_id
    meses = r.consumo_meses or []
    ult3 = meses[-3:]
    prom = r.consumo_promedio_mes

    if r.excepcion:
        texto = f'Quiebre proyectado el {r.fecha_quiebre_proyectada:%d-%m}; la compra normal llega el {r.fecha_llegada_posible:%d-%m}'
        if r.dias_quiebre_inevitable > 0:
            texto += f'. Aun comprando hoy hay {r.dias_quiebre_inevitable} dias de quiebre: evaluar traslado o compra urgente'
        out.append((f'QUIEBRE_PROYECTADO|{sku}', 'QUIEBRE_PROYECTADO', ALTA, texto))
    elif r.fecha_bajo_ss and r.stock_seguridad > 0 and r.disponible_futuro >= r.stock_seguridad:
        dias = (r.fecha_bajo_ss - r.corrida.fecha_calculo).days
        if dias <= p.alerta_bajo_ss_dias:
            out.append((f'BAJO_SS_PROYECTADO|{sku}', 'BAJO_SS_PROYECTADO', MEDIA,
                        f'Queda bajo el stock de seguridad ({r.stock_seguridad}) en {dias} dias'))
    if r.oc_atrasada:
        out.append((f'OC_ATRASADA|{sku}', 'OC_ATRASADA', MEDIA,
                    'OC con fecha comprometida vencida: gestionar con el proveedor antes de comprar de nuevo'))

    activo = r.stock_maximo > 0 or r.letra == 'P'
    urgente = r.disponible_futuro < 0 if r.letra == 'P' else r.disponible_futuro <= 0
    if activo and urgente and (r.comprometido > 0 or r.stock_maximo > 0):
        out.append((f'URGENTE|{sku}', 'URGENTE', ALTA, f'Disponible a futuro {r.disponible_futuro:g}'))
    elif r.stock_seguridad > 0 and r.disponible_futuro < r.stock_seguridad:
        out.append((f'BAJO_SS|{sku}', 'BAJO_SS', MEDIA,
                    f'Disponible {r.disponible_futuro:g} bajo el stock de seguridad {r.stock_seguridad}'))

    if r.stock_maximo > 0 and r.disponible_futuro > r.stock_maximo + p.alerta_sobrestock_meses * prom:
        exceso = (r.disponible_futuro - r.stock_maximo) * r.costo_unitario
        out.append((f'SOBRESTOCK|{sku}|{mes_txt}', 'SOBRESTOCK', BAJA,
                    f'Disponible {r.disponible_futuro:g} sobre el maximo {r.stock_maximo} (USD {exceso:,.0f} de exceso)'))

    if r.letra == 'R' and len(ult3) == 3 and prom > 0:
        if sum(ult3) == 0:
            out.append((f'CAIDA_CONSUMO|{sku}|{mes_txt}', 'CAIDA_CONSUMO', MEDIA, '3 meses seguidos sin consumo'))
        elif _prom(ult3) < 0.5 * prom:
            out.append((f'CAIDA_CONSUMO|{sku}|{mes_txt}', 'CAIDA_CONSUMO', BAJA,
                        f'Promedio de 3 meses {_prom(ult3):.1f} bajo el 50% del promedio {prom:.1f}'))
    # Alza e irregularidad solo en articulos que se reponen (R / E): en P y O un mes con
    # consumo ya es "alza" y lo cubre la alerta de nuevo consumo
    repone = r.letra in ('R', 'E')
    if repone and prom > 0 and len(ult3) == 3 and _prom(ult3) > 1.5 * prom:
        out.append((f'ALZA_CONSUMO|{sku}|{mes_txt}', 'ALZA_CONSUMO', MEDIA,
                    f'Promedio de 3 meses {_prom(ult3):.1f} sobre el 150% del promedio {prom:.1f}'))
    if repone and len(meses) >= 12 and r.variacion_consumo > 0:
        var6 = statistics.stdev(meses[-6:])
        if abs(var6 - r.variacion_consumo) > 0.5 * r.variacion_consumo:
            out.append((f'CONSUMO_IRREGULAR|{sku}|{mes_txt}', 'CONSUMO_IRREGULAR', BAJA,
                        f'Variacion de 6 meses {var6:.1f} vs 12 meses {r.variacion_consumo:.1f}'))
    # Pico recortado (SPEC-26): queda fuera de la demanda; Abastecimiento revisa si fue una venta
    # puntual, un proyecto o un error de registro (PC con muchas salidas, NC y refacturas...)
    if repone and r.meses_atipicos:
        etiquetas = _meses(r.corrida.fecha_calculo, len(meses))
        for i in r.meses_atipicos:
            out.append((f'PICO|{sku}|{etiquetas[i]}', 'PICO', BAJA,
                        f'{etiquetas[i]}: {meses[i]:,.0f} u recortado a {r.tope_mes_atipico:,.1f} '
                        f'(mediana de los meses con consumo {r.mediana_con_consumo:,.1f}). '
                        'Revisar si fue venta puntual, proyecto o error de registro'))
    if r.letra in ('P', 'O') and sum(1 for v in ult3 if v > 0) >= 2:
        out.append((f'NUEVO_CONSUMO|{sku}|{mes_txt}', 'NUEVO_CONSUMO', MEDIA,
                    f'Articulo {r.letra} con consumo en 2 de los ultimos 3 meses'))

    datos = list(r.avisos or [])
    if (r.necesita_compra or r.excepcion) and not r.proveedor_id:
        datos.append('Articulo sin proveedor')
    if datos and (r.letra in ('R', 'E', 'P') or r.necesita_compra):
        out.append((f'DATOS|{sku}', 'DATOS', BAJA, '; '.join(datos)[:300]))
    return out


def generar(corrida, hoy):
    """Evalua todas las reglas y sincroniza la tabla Alerta. Devuelve conteo por tipo."""
    from .parametros import Resolutor
    p = Resolutor().general
    mes_txt = hoy.strftime('%Y-%m')
    nuevas = {}

    def agregar(clave, tipo, sev, msg, sku=None, prov='', nodo=''):
        nuevas[clave] = (tipo, sku, sev, msg[:300], prov, nodo)

    repone = set()
    for r in ResultadoArticulo.objects.filter(corrida=corrida).select_related('corrida').iterator(chunk_size=2000):
        for clave, tipo, sev, msg in _reglas_articulo(r, p, mes_txt):
            agregar(clave, tipo, sev, msg, r.product_id, r.proveedor_id or '')
        if r.letra == 'R' and r.marca != ResultadoArticulo.EXCLUIDO:
            repone.add(r.product_id)

    # Doble envio a una sucursal (SPEC-31 §2): le llega stock por traslado y ademas una OC, y con eso
    # le sobra. Caso tipico: el traslado cubrio el PC mientras llegaba la compra; al llegar la OC no
    # hay que volver a enviar (la compra repone Santiago)
    for sku, nodo, msg in dobles_envios(corrida):
        agregar(f'DOBLE_ENVIO|{sku}|{nodo}', 'DOBLE_ENVIO', MEDIA, msg, sku, nodo=nodo)

    # Caida de consumo por nodo (SPEC-31 §5): para revisar con el gerente de cada sucursal
    for sku, nodo, msg in caidas_por_nodo(repone, hoy, p):
        agregar(f'CAIDA_CONSUMO_NODO|{sku}|{nodo}|{mes_txt}', 'CAIDA_CONSUMO_NODO', MEDIA, msg, sku, nodo=nodo)

    # Cambio de letra (mensual)
    mes = hoy.replace(day=1)
    for h in HistorialMensual.objects.filter(mes=mes).exclude(letra_anterior='').exclude(letra_anterior=F('letra')):
        agregar(f'CAMBIO_LETRA|{h.product_id}|{mes_txt}', 'CAMBIO_LETRA', MEDIA,
                f'Cambio de {h.letra_anterior} a {h.letra}. {h.motivo}', h.product_id)

    # Traslado entre sucursales: Santiago no cubre y otra sucursal tiene stock libre
    for b in ResultadoBodega.objects.filter(resultado__corrida=corrida).exclude(sucursales_con_stock=[]).select_related('warehouse'):
        agregar(f'TRASLADO_SUCURSALES|{b.resultado.product_id}|{b.warehouse.code}', 'TRASLADO_SUCURSALES', MEDIA,
                f'{b.warehouse.code} espera compra ({b.espera_compra:g} u); hay stock libre en '
                f'{", ".join(b.sucursales_con_stock)}', b.resultado.product_id)

    # Eventos comerciales pendientes o vencidos con consumo real bajo lo comprometido
    for ev in EventoComercial.objects.filter(estado=EventoComercial.PROPUESTO):
        agregar(f'EVENTO_COMERCIAL|pend|{ev.pk}', 'EVENTO_COMERCIAL', MEDIA,
                f'Evento comercial pendiente de aprobacion: {ev.comentario[:120]}', ev.product_id)
    for ev in EventoComercial.objects.filter(estado=EventoComercial.APROBADO, mes_fin__lt=mes, product__isnull=False,
                                             cantidad_adicional__gt=0):
        real = _consumo_periodo(ev)
        if real < 0.5 * ev.cantidad_adicional:
            agregar(f'EVENTO_COMERCIAL|venc|{ev.pk}', 'EVENTO_COMERCIAL', BAJA,
                    f'Evento vencido: consumo real {real:g} bajo el 50% de lo anunciado ({ev.cantidad_adicional:g})',
                    ev.product_id)

    # Contratos por vencer
    limite = hoy.toordinal() + p.alerta_contrato_vence_dias
    for a in AcuerdoGlobal.objects.filter(fecha_termino__isnull=False, fecha_termino__gte=hoy):
        if a.fecha_termino.toordinal() <= limite:
            agregar(f'CONTRATO|vence|{a.nro_acuerdo}|{a.linea}', 'CONTRATO', MEDIA,
                    f'Acuerdo {a.nro_acuerdo} vence el {a.fecha_termino:%d-%m-%Y}', a.product_id, a.proveedor_codigo)

    _sincronizar(nuevas)
    conteo = {}
    for tipo, *_ in nuevas.values():
        conteo[tipo] = conteo.get(tipo, 0) + 1
    return conteo


ORIGENES_OC = ('IMPORTACION', 'NACIONAL', 'SIN_OC')


def doble_envio(desglose, disponible_futuro):
    """(oc, traslado, sobra) si a un nodo le llega stock por traslado y por OC y le sobra al menos lo
    de la parte menor; None si no. `disponible_futuro` ya descuenta los compromisos del nodo."""
    desglose = desglose or {}
    traslado = desglose.get('TRASLADO', 0.0)
    oc = sum(desglose.get(k, 0.0) for k in ORIGENES_OC)
    if traslado > 0 and oc > 0 and disponible_futuro >= min(oc, traslado):
        return oc, traslado, disponible_futuro
    return None


def dobles_envios(corrida):
    out = []
    for b in ResultadoBodega.objects.filter(resultado__corrida=corrida).exclude(warehouse__code='013').exclude(
            resultado__marca=ResultadoArticulo.EXCLUIDO).select_related('warehouse', 'resultado'):
        caso = doble_envio(b.transito_desglose, b.disponible_futuro)
        if caso:
            oc, traslado, sobra = caso
            out.append((b.resultado.product_id, b.warehouse.code,
                        f'{nombre_nodo(b.warehouse.code)}: llegan {traslado:,.0f} u por traslado y {oc:,.0f} u por OC; '
                        f'con lo comprometido ({b.comprometido:,.0f}) sobran {sobra:,.0f} u. Si el traslado ya cubrio '
                        'el pedido, al llegar la OC no reenviar: la compra repone Santiago'))
    return out


def caidas_por_nodo(skus, hoy, p):
    """[(sku, nodo, mensaje)]: articulos R con consumo regular en un nodo (>= umbral R meses de 12)
    y sin consumo en ese nodo en los ultimos `alerta_caida_meses_nodo` meses cerrados."""
    if not skus:
        return []
    total = hoy.year * 12 + hoy.month - 1
    meses = [datetime.date((total - i) // 12, (total - i) % 12 + 1, 1) for i in range(12, 0, -1)]
    indice = {m: i for i, m in enumerate(meses)}
    serie = defaultdict(lambda: [0.0] * 12)
    for sku, bodega, mes, q in ConsumoMensual.objects.filter(mes__gte=meses[0], mes__lte=meses[-1]).values_list(
            'product_id', 'bodega', 'mes', 'cantidad'):
        nodo = nodo_red(bodega)
        if sku in skus and nodo and mes in indice:
            serie[(sku, nodo)][indice[mes]] += q
    n = p.alerta_caida_meses_nodo
    out = []
    for (sku, nodo), v in serie.items():
        v = [max(0.0, x) for x in v]
        con = sum(1 for x in v if x > 0)
        if con >= p.umbral_r and not any(v[-n:]):
            out.append((sku, nodo, f'{nombre_nodo(nodo)}: {n} meses sin consumo; antes {sum(v):,.0f} u en '
                                   f'{con} de 12 meses. Revisar con la sucursal a que se debe'))
    return out


def _consumo_periodo(ev):
    return ConsumoMensual.objects.filter(product_id=ev.product_id, mes__gte=ev.mes_inicio.replace(day=1),
                                         mes__lte=ev.mes_fin.replace(day=1)).aggregate(s=Sum('cantidad'))['s'] or 0


@transaction.atomic
def _sincronizar(nuevas):
    existentes = {a.clave: a for a in Alerta.objects.filter(clave__in=list(nuevas))}
    crear, actualizar = [], []
    for clave, (tipo, sku, sev, msg, prov, nodo) in nuevas.items():
        a = existentes.get(clave)
        if a:
            a.mensaje, a.severidad, a.vigente, a.nodo = msg, sev, True, nodo
            actualizar.append(a)
        else:
            crear.append(Alerta(clave=clave, tipo=tipo, product_id=sku, severidad=sev, mensaje=msg,
                                proveedor_codigo=prov, nodo=nodo))
    Alerta.objects.bulk_create(crear, batch_size=2000)
    Alerta.objects.bulk_update(actualizar, ['mensaje', 'severidad', 'vigente', 'nodo'], batch_size=2000)
    Alerta.objects.filter(vigente=True).exclude(clave__in=list(nuevas)).update(vigente=False)
