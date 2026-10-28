"""Alertas de la Calculadora (documento §8, SPEC-15 §1).

Cada corrida evalua las reglas sobre los resultados. Una alerta se identifica por su
`clave` (tipo + articulo, + mes en las mensuales): si la condicion sigue, se mantiene con
su estado y comentario; si deja de cumplirse queda `vigente=False` (no se borra).
"""
import statistics

from django.db import transaction
from django.db.models import F, Sum

from .models import (AcuerdoGlobal, Alerta, ConsumoMensual, EventoComercial, HistorialMensual, ResultadoArticulo,
                     ResultadoBodega)

ALTA, MEDIA, BAJA = 'ALTA', 'MEDIA', 'BAJA'


def _prom(v):
    return sum(v) / len(v) if v else 0.0


def _reglas_articulo(r, p, mes_txt):
    """Alertas de un ResultadoArticulo. Devuelve [(clave, tipo, severidad, mensaje)]."""
    out = []
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

    def agregar(clave, tipo, sev, msg, sku=None, prov=''):
        nuevas[clave] = (tipo, sku, sev, msg[:300], prov)

    for r in ResultadoArticulo.objects.filter(corrida=corrida).select_related('corrida').iterator(chunk_size=2000):
        for clave, tipo, sev, msg in _reglas_articulo(r, p, mes_txt):
            agregar(clave, tipo, sev, msg, r.product_id, r.proveedor_id or '')

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


def _consumo_periodo(ev):
    return ConsumoMensual.objects.filter(product_id=ev.product_id, mes__gte=ev.mes_inicio.replace(day=1),
                                         mes__lte=ev.mes_fin.replace(day=1)).aggregate(s=Sum('cantidad'))['s'] or 0


@transaction.atomic
def _sincronizar(nuevas):
    existentes = {a.clave: a for a in Alerta.objects.filter(clave__in=list(nuevas))}
    crear, actualizar = [], []
    for clave, (tipo, sku, sev, msg, prov) in nuevas.items():
        a = existentes.get(clave)
        if a:
            a.mensaje, a.severidad, a.vigente = msg, sev, True
            actualizar.append(a)
        else:
            crear.append(Alerta(clave=clave, tipo=tipo, product_id=sku, severidad=sev, mensaje=msg,
                                proveedor_codigo=prov))
    Alerta.objects.bulk_create(crear, batch_size=2000)
    Alerta.objects.bulk_update(actualizar, ['mensaje', 'severidad', 'vigente'], batch_size=2000)
    Alerta.objects.filter(vigente=True).exclude(clave__in=list(nuevas)).update(vigente=False)
