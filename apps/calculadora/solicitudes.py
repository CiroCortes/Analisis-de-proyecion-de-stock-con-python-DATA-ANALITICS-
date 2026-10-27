"""Solicitudes de compra por proveedor (documento §6, SPEC-13).

El dia de compra de cada proveedor se arma una solicitud con todo lo que la red necesita
hasta la siguiente compra. Las excepciones (quiebre proyectado antes de la proxima compra
normal) generan una solicitud "fuera de calendario" ese mismo dia, y sugieren sumar lo
que entraria de pasada del mismo proveedor para no emitir dos OC.

Escribir en SAP (Service Layer) esta descartado por ahora (SPEC-06 §3): al aprobar, la
solicitud se exporta como planilla para DTW o carga manual.
"""
import datetime
from collections import defaultdict

from django.db import transaction
from django.utils import timezone

from .models import AcuerdoGlobal, Alerta, LineaSolicitud, Proveedor, ResultadoArticulo, SolicitudCompra

ESTADOS_ABIERTOS = (SolicitudCompra.BORRADOR, SolicitudCompra.APROBADA)


def acuerdo_vigente(product_id, proveedor_codigo, hoy, acuerdos=None):
    """Acuerdo global vigente del proveedor para el articulo; con varios, el de menor precio."""
    candidatos = acuerdos if acuerdos is not None else AcuerdoGlobal.objects.filter(product_id=product_id)
    vigentes = [a for a in candidatos
                if a.product_id == product_id and (not proveedor_codigo or a.proveedor_codigo == proveedor_codigo)
                and (a.fecha_inicio is None or a.fecha_inicio <= hoy)
                and (a.fecha_termino is None or a.fecha_termino >= hoy)
                and a.estado.upper() not in ('C', 'T', 'CANCELADO', 'TERMINADO')]
    return min(vigentes, key=lambda a: a.precio_unitario or float('inf')) if vigentes else None


def _lineas_recientes(hoy):
    """Articulos con otra solicitud abierta creada en los ultimos 15 dias (§5)."""
    desde = hoy - datetime.timedelta(days=15)
    return set(LineaSolicitud.objects.filter(
        solicitud__estado__in=ESTADOS_ABIERTOS, solicitud__fecha__gte=desde,
    ).exclude(estado=LineaSolicitud.DESCARTADA).values_list('product_id', flat=True))


@transaction.atomic
def generar(hoy=None, usuario=None, proveedor=None):
    """Arma las solicitudes del dia desde la ultima corrida. Reemplaza los borradores del
    mismo dia y proveedor (no toca los aprobados). Devuelve las solicitudes creadas."""
    hoy = hoy or timezone.localdate()
    qs = ResultadoArticulo.objects.select_related('product').filter(proveedor__isnull=False)
    if proveedor:
        qs = qs.filter(proveedor_id=proveedor)
    del_dia = [r for r in qs.filter(comprar=True)]
    excepciones = [r for r in qs.filter(excepcion=True, comprar=False, cantidad_excepcion__gt=0)]
    de_pasada = defaultdict(list)
    proveedores_exc = {r.proveedor_id for r in excepciones}
    for r in qs.filter(proveedor_id__in=proveedores_exc, necesita_compra=True, comprar=False, excepcion=False):
        de_pasada[r.proveedor_id].append(r)

    acuerdos = defaultdict(list)
    codigos = {r.product_id for r in del_dia + excepciones} | {r.product_id for v in de_pasada.values() for r in v}
    for a in AcuerdoGlobal.objects.filter(product_id__in=codigos):
        acuerdos[a.product_id].append(a)
    recientes = _lineas_recientes(hoy)

    grupos = defaultdict(list)
    for r in del_dia:
        grupos[(r.proveedor_id, SolicitudCompra.CALENDARIO)].append((r, r.cantidad_sugerida, False))
    for r in excepciones:
        grupos[(r.proveedor_id, SolicitudCompra.EXCEPCION)].append((r, r.cantidad_excepcion, True))
    for prov, filas in de_pasada.items():
        for r in filas:
            grupos[(prov, SolicitudCompra.EXCEPCION)].append((r, r.cantidad_sugerida, False))

    SolicitudCompra.objects.filter(fecha=hoy, estado=SolicitudCompra.BORRADOR,
                                   proveedor_id__in={k[0] for k in grupos}).delete()
    creadas = []
    for (prov, tipo), filas in grupos.items():
        sol = SolicitudCompra.objects.create(proveedor_id=prov, tipo=tipo, fecha=hoy, creada_por=usuario)
        lineas = []
        for r, cantidad, es_exc in filas:
            if cantidad <= 0:
                continue
            ag = acuerdo_vigente(r.product_id, prov, hoy, acuerdos.get(r.product_id, []))
            precio = ag.precio_unitario if ag and ag.precio_unitario else r.costo_unitario
            saldo = ag.saldo if ag else None
            lineas.append(LineaSolicitud(
                solicitud=sol, product_id=r.product_id, cantidad_sugerida=cantidad, cantidad_final=cantidad,
                precio_unitario=precio, nro_acuerdo=ag.nro_acuerdo if ag else '', linea_acuerdo=ag.linea if ag else None,
                sin_contrato=ag is None, saldo_insuficiente=saldo is not None and cantidad > saldo,
                excepcion=es_exc, causa_excepcion=r.causa_excepcion if es_exc else '', urgencia=r.urgencia,
                duplicada_reciente=r.product_id in recientes,
                motivo='' if es_exc or tipo == SolicitudCompra.CALENDARIO else 'Compra de pasada (mismo proveedor)',
            ))
        if not lineas:
            sol.delete()
            continue
        LineaSolicitud.objects.bulk_create(lineas)
        creadas.append(sol)
        _alertas_contrato(sol, lineas)
    return creadas


def _alertas_contrato(sol, lineas):
    for l in lineas:
        if l.sin_contrato or l.saldo_insuficiente:
            motivo = 'sin acuerdo global' if l.sin_contrato else f'cantidad sobre el saldo del acuerdo {l.nro_acuerdo}'
            Alerta.objects.update_or_create(
                clave=f'CONTRATO|{l.product_id}|{sol.proveedor_id}',
                defaults={'tipo': 'CONTRATO', 'product_id': l.product_id, 'proveedor_codigo': sol.proveedor_id or '',
                          'severidad': 'BAJA', 'mensaje': f'Linea {motivo}', 'vigente': True})


def editar_linea(linea, cantidad, motivo, usuario=None):
    """El comprador cambia la cantidad (con motivo obligatorio) o la descarta (cantidad 0)."""
    if linea.solicitud.estado != SolicitudCompra.BORRADOR:
        raise ValueError('Solo se editan solicitudes pendientes')
    cantidad = float(cantidad)
    if cantidad < 0:
        raise ValueError('La cantidad no puede ser negativa')
    if cantidad != linea.cantidad_sugerida and not (motivo or '').strip():
        raise ValueError('Indica el motivo del cambio')
    linea.cantidad_final = cantidad
    linea.motivo = (motivo or linea.motivo)[:255]
    linea.estado = LineaSolicitud.DESCARTADA if cantidad == 0 else LineaSolicitud.PENDIENTE
    if linea.nro_acuerdo:
        ag = AcuerdoGlobal.objects.filter(nro_acuerdo=linea.nro_acuerdo, linea=linea.linea_acuerdo).first()
        linea.saldo_insuficiente = bool(ag and ag.saldo is not None and cantidad > ag.saldo)
    linea.save(update_fields=['cantidad_final', 'motivo', 'estado', 'saldo_insuficiente'])
    return linea


@transaction.atomic
def aprobar(solicitud, usuario):
    if solicitud.estado != SolicitudCompra.BORRADOR:
        raise ValueError('La solicitud ya no esta pendiente')
    solicitud.lineas.exclude(estado=LineaSolicitud.DESCARTADA).update(estado=LineaSolicitud.APROBADA)
    solicitud.estado = SolicitudCompra.APROBADA
    solicitud.aprobada_por = usuario
    solicitud.aprobada_en = timezone.now()
    solicitud.save(update_fields=['estado', 'aprobada_por', 'aprobada_en'])
    return solicitud


def descartar(solicitud, usuario, motivo=''):
    if solicitud.estado not in ESTADOS_ABIERTOS:
        raise ValueError('La solicitud ya fue exportada')
    solicitud.estado = SolicitudCompra.DESCARTADA
    solicitud.comentario = motivo[:255]
    solicitud.save(update_fields=['estado', 'comentario'])
    solicitud.lineas.update(estado=LineaSolicitud.DESCARTADA)


def filas_exportacion(solicitudes):
    """Filas para la planilla de carga (DTW o manual). Una fila por linea aprobada.
    Las columnas siguen PurchaseRequests de B1; validar la plantilla DTW con IT."""
    filas = []
    for s in solicitudes:
        for l in s.lineas.select_related('product').exclude(estado=LineaSolicitud.DESCARTADA):
            filas.append({
                'Solicitud plataforma': s.pk, 'Fecha': s.fecha.isoformat(), 'Tipo': s.get_tipo_display(),
                'Proveedor': s.proveedor_id or '', 'Nombre proveedor': s.proveedor.nombre if s.proveedor else '',
                'ItemCode': l.product_id, 'Descripcion': l.product.description, 'Quantity': l.cantidad_final,
                'WarehouseCode': s.bodega_entrega, 'Price': round(l.precio_unitario, 4),
                'AgreementNo': l.nro_acuerdo, 'AgreementRowNumber': '' if l.linea_acuerdo is None else l.linea_acuerdo,
                'Motivo': l.motivo, 'Excepcion': 'Si' if l.excepcion else '', 'Causa': l.causa_excepcion,
            })
    return filas


def marcar_exportadas(solicitudes):
    ids = [s.pk for s in solicitudes if s.estado == SolicitudCompra.APROBADA]
    SolicitudCompra.objects.filter(pk__in=ids).update(estado=SolicitudCompra.EXPORTADA)


def intervencion_comprador(desde=None):
    """Indicador §8: % de lineas cambiadas o descartadas, por comprador y motivo, y % de
    compras fuera de calendario con su causa."""
    qs = LineaSolicitud.objects.select_related('solicitud', 'solicitud__aprobada_por').exclude(
        solicitud__estado=SolicitudCompra.BORRADOR)
    if desde:
        qs = qs.filter(solicitud__fecha__gte=desde)
    total = modificadas = excepciones = 0
    por_comprador, por_causa = defaultdict(lambda: [0, 0]), defaultdict(int)
    for l in qs:
        total += 1
        comprador = l.solicitud.aprobada_por.get_username() if l.solicitud.aprobada_por else 'sin aprobar'
        por_comprador[comprador][0] += 1
        if l.modificada:
            modificadas += 1
            por_comprador[comprador][1] += 1
        if l.excepcion:
            excepciones += 1
            por_causa[l.causa_excepcion or 'MANUAL'] += 1
    return {
        'lineas': total, 'modificadas': modificadas,
        'pct_modificadas': round(100 * modificadas / total, 1) if total else 0,
        'pct_excepcion': round(100 * excepciones / total, 1) if total else 0,
        'por_comprador': {k: {'lineas': v[0], 'modificadas': v[1]} for k, v in por_comprador.items()},
        'por_causa': dict(por_causa),
    }


def proveedores_del_dia(hoy=None):
    """Proveedores cuyo dia de compra es hoy segun la ultima corrida."""
    return Proveedor.objects.filter(resultadoarticulo__es_dia_compra=True).distinct()
