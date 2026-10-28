"""Cargadores de los TXT de la Calculadora (SPEC-08).

Cada cargador reemplaza su tabla completa (la carga es una foto del Datalake) y deja un
registro en CargaDatos. Si un archivo no existe se informa y se usa el respaldo indicado
en SPEC-08 §3, nunca un cero silencioso.
"""
import datetime
import os
from collections import defaultdict

from django.db import transaction

from apps.data_ingestion.datalake_ingest import _clean_num, find_data_file, iter_txt_rows, parse_date
from apps.data_ingestion.warehouses import commitment_bodega, nodo_red, purchase_bodega
from apps.inventory.models import ProductionOrderMovement, ProductSKU, SalesOrderMovement, Warehouse

from .models import (AcuerdoGlobal, CargaDatos, CompromisoAbierto, CompromisoDetalle, ConsumoMensual, OCAbierta, ParametroCompra,
                     PlazoOC, Proveedor)

# tabla -> (nombre largo del archivo, prefijo alternativo del task de DBeaver)
ARCHIVOS = {
    'consumo_mensual': ('Consumo Mensual.txt', 'consumo_mensual.txt'),
    'consumo_of_mensual': ('Consumo OF Mensual.txt', 'consumo_of_mensual.txt'),
    'plazos_oc': ('Plazos de Entrega OC.txt', 'plazos_oc.txt'),
    'parametros_compra': ('Parametros de Compra.txt', 'parametros_compra.txt'),
    'proveedores': ('Proveedores.txt', 'ocrd.txt'),
    'bodegas': ('Bodegas.txt', 'owhs.txt'),
    'acuerdos': ('Acuerdos Globales.txt', 'ooat_oat1.txt'),
    'oc_abiertas': ('Órdenes de Compra en Tránsito (OC).txt', 'opor_por1.txt'),
    'pedidos': ('Pedidos de Clientes (PC).txt', 'ordr_rdr1.txt'),
    'ofs': ('Órdenes de Fabricación (OF).txt', 'owor_wor1.txt'),
    'entradas': ('Entradas de Mercancias (EM).txt', 'opdn_pdn1.txt'),
    'notas_credito': ('Notas de Credito.txt', 'orin_rin1.txt'),
    'compromisos_detalle': ('Compromisos Abiertos.txt', 'ordr_owor_abiertos.txt'),
}

# Recepciones internas (produccion propia): no son un proveedor al que se le compre
PROVEEDORES_INTERNOS = {'96877150P'}


def archivo(tabla, data_dir=None):
    largo, alt = ARCHIVOS[tabla]
    return find_data_file(largo, alt, data_dir)


def _registrar(tabla, ruta, filas, fuente='TXT', nota=''):
    CargaDatos.objects.create(tabla=tabla, archivo=os.path.basename(ruta or ''), filas=filas, fuente=fuente, nota=nota)


def _primer_dia(fecha):
    return fecha.replace(day=1)


def _mes(texto):
    """'2026-09' o '2026-09-15' -> date(2026, 9, 1)."""
    texto = (texto or '').strip()
    try:
        return datetime.date(int(texto[:4]), int(texto[5:7]), 1)
    except (ValueError, IndexError):
        return None


def _skus():
    return set(ProductSKU.objects.values_list('code', flat=True))


# ── Consumo mensual ───────────────────────────────────────────────────────────

def cargar_consumo_mensual(data_dir=None):
    """Consulta 8 (OINM agregado por mes). Sin archivo: se reconstruye desde los PC y OF
    cerrados ya cargados (fuente provisional, SPEC-08 §3). Devuelve la fuente usada."""
    ruta = archivo('consumo_mensual', data_dir)
    if not os.path.exists(ruta):
        n = reconstruir_consumo_desde_movimientos()
        _registrar('consumo_mensual', '', n, fuente='PC_OF',
                   nota='Sin consulta 8: consumo reconstruido desde PC y OF cerrados')
        return 'PC_OF'

    skus = _skus()
    acumulado = defaultdict(float)
    nc_oinm = defaultdict(float)       # (sku, bodega, mes) -> NC registradas por OINM (negativo)
    for cols in iter_txt_rows(ruta, 5):
        sku, bodega, mes, origen = cols[0], cols[1], _mes(cols[2]), (cols[3] or 'VENTA').upper()
        if sku not in skus or mes is None:
            continue
        if origen == 'NC':
            nc_oinm[(sku, bodega, mes)] += _clean_num(cols[4])
            continue
        origen = origen if origen in (ConsumoMensual.VENTA, ConsumoMensual.OF) else ConsumoMensual.SALIDA
        acumulado[(sku, bodega, mes, origen)] += _clean_num(cols[4])

    # 8b opcional: separa las emisiones a OF de las demas salidas de mercancia
    ruta_of = archivo('consumo_of_mensual', data_dir)
    if os.path.exists(ruta_of):
        for cols in iter_txt_rows(ruta_of, 4):
            sku, bodega, mes = cols[0], cols[1], _mes(cols[2])
            q = _clean_num(cols[3])
            if sku in skus and mes and q:
                clave = (sku, bodega, mes, ConsumoMensual.SALIDA)
                mover = min(q, acumulado.get(clave, 0.0))
                if mover > 0:
                    acumulado[clave] -= mover
                    acumulado[(sku, bodega, mes, ConsumoMensual.OF)] += mover

    aplicar_notas_credito(acumulado, nc_oinm, skus, data_dir)

    filas = [ConsumoMensual(product_id=s, bodega=b, mes=m, origen=o, cantidad=q)
             for (s, b, m, o), q in acumulado.items() if q]
    with transaction.atomic():
        ConsumoMensual.objects.all().delete()
        ConsumoMensual.objects.bulk_create(filas, batch_size=5000)
    _registrar('consumo_mensual', ruta, len(filas), fuente='OINM')
    return 'OINM'


def aplicar_notas_credito(acumulado, nc_oinm, skus, data_dir=None):
    """SPEC-22 §1. `nc_oinm`: lo que OINM registro como nota de credito (TransType 14, origen 'NC'
    de la consulta 8) por (sku, bodega, mes). Esa cantidad se resta en la bodega y el mes de la
    factura o entrega de origen (consulta 15) en vez de donde se registro la NC (casi siempre la
    013-NC, que cae en Santiago). Solo se reubica lo que OINM registro: una NC que no movio stock
    (por ejemplo, sobre una factura de reserva) no tiene venta que anular. Lo que no se puede
    ligar a un origen queda donde estaba. Nunca se resta mas de lo que el origen tiene: si la venta
    original no esta en la consulta 8 (mes incompleto en el Datalake), la NC queda donde se
    registro. `acumulado` se modifica en el lugar."""
    if not nc_oinm:
        _registrar('notas_credito', '', 0, fuente='SIN_MARCA',
                   nota='La consulta 8 no separa las NC (origen NC): re-exportarla; las NC quedan donde se registraron')
        return 0
    ruta = archivo('notas_credito', data_dir)
    lineas = defaultdict(list)          # (sku, bodega_nc, mes_nc) -> [(cantidad, bodega_origen, mes_origen)]
    if os.path.exists(ruta):
        for cols in iter_txt_rows(ruta, 10):
            sku, q, mes_nc, mes_origen = cols[1], _clean_num(cols[4]), _mes(cols[3]), _mes(cols[7])
            if sku in skus and q > 0 and cols[5] in ('13', '15') and cols[6] and mes_nc and mes_origen:
                lineas[(sku, cols[2], mes_nc)].append((q, cols[6], mes_origen))
    reubicadas = 0.0
    for (sku, bodega, mes), cantidad in nc_oinm.items():
        pendiente = -cantidad
        for q, bodega_origen, mes_origen in lineas.get((sku, bodega, mes), ()):
            if pendiente <= 0:
                break
            origen = (sku, bodega_origen, mes_origen, ConsumoMensual.VENTA)
            mover = min(q, pendiente, max(0.0, acumulado.get(origen, 0.0)))
            if mover <= 0:
                continue
            acumulado[origen] -= mover
            pendiente -= mover
            reubicadas += mover
        # Lo no ligado a un origen (o una NC sin consulta 15) queda como devolucion donde ocurrio
        acumulado[(sku, bodega, mes, ConsumoMensual.VENTA)] -= pendiente
    nota = (f'{reubicadas:,.0f} u restadas en la bodega y el mes de su factura' if os.path.exists(ruta)
            else 'Sin consulta 15: las NC quedan en la bodega y el mes en que se registraron')
    _registrar('notas_credito', ruta if os.path.exists(ruta) else '', len(nc_oinm), nota=nota)
    return reubicadas


def reconstruir_consumo_desde_movimientos():
    """Respaldo: PC cerrados (venta, por fecha de entrega) y OF cerradas (por fecha de cierre)."""
    acumulado = defaultdict(float)
    for sku, bodega, fecha, q in SalesOrderMovement.objects.values_list('product_id', 'warehouse', 'delivery_date', 'quantity'):
        if fecha:
            acumulado[(sku, bodega or '013-PP', _primer_dia(fecha), ConsumoMensual.VENTA)] += float(q or 0)
    for sku, bodega, fecha, q in ProductionOrderMovement.objects.values_list('product_id', 'warehouse', 'end_date', 'quantity_delivered'):
        if fecha:
            acumulado[(sku, bodega or '013-PP', _primer_dia(fecha), ConsumoMensual.OF)] += float(q or 0)
    filas = [ConsumoMensual(product_id=s, bodega=b, mes=m, origen=o, cantidad=q)
             for (s, b, m, o), q in acumulado.items() if q]
    with transaction.atomic():
        ConsumoMensual.objects.all().delete()
        ConsumoMensual.objects.bulk_create(filas, batch_size=5000)
    return len(filas)


# ── Plazos, OC, compromisos ──────────────────────────────────────────────────

def cargar_plazos_oc(data_dir=None):
    """Consulta 9: una fila por recepcion. Con recepciones parciales se usa la PRIMERA
    entrada de cada linea de OC (decision abierta #4, SPEC-08 §4)."""
    ruta = archivo('plazos_oc', data_dir)
    if not os.path.exists(ruta):
        _registrar('plazos_oc', '', 0, fuente='SIN_ARCHIVO', nota='Sin consulta 9: se usa OITM.LeadTime')
        return 0
    skus = _skus()
    primera = {}
    for cols in iter_txt_rows(ruta, 9):
        nro_oc, sku, prov = cols[0].replace(',', ''), cols[1], cols[2]
        f_oc, f_in = parse_date(cols[4]), parse_date(cols[7])
        if sku not in skus or not f_oc or not f_in:
            continue
        clave = (nro_oc, sku)
        if clave not in primera or f_in < primera[clave][2]:
            primera[clave] = (prov, f_oc, f_in)
    filas = [PlazoOC(nro_oc=oc, product_id=sku, proveedor_codigo=prov, fecha_oc=f_oc, fecha_entrada=f_in,
                     dias_entrega=(f_in - f_oc).days)
             for (oc, sku), (prov, f_oc, f_in) in primera.items()]
    with transaction.atomic():
        PlazoOC.objects.all().delete()
        PlazoOC.objects.bulk_create(filas, batch_size=5000)
    _registrar('plazos_oc', ruta, len(filas))
    return len(filas)


def cargar_oc_abiertas(data_dir=None):
    """Lineas de OC con pendiente (consulta 5 actual), con fecha para la proyeccion.
    Tambien registra los proveedores que aparecen."""
    ruta = archivo('oc_abiertas', data_dir)
    if not os.path.exists(ruta):
        _registrar('oc_abiertas', '', 0, fuente='SIN_ARCHIVO')
        return 0
    skus = _skus()
    filas, proveedores = [], {}
    for cols in iter_txt_rows(ruta, 9):
        sku = cols[2]
        pendiente = _clean_num(cols[8])
        if cols[3]:
            proveedores[cols[3]] = cols[4][:200]
        if sku not in skus or pendiente <= 0:
            continue
        filas.append(OCAbierta(
            nro_oc=cols[0].replace(',', ''), product_id=sku, bodega=purchase_bodega(cols[1]),
            proveedor_codigo=cols[3], fecha_oc=parse_date(cols[5]), fecha_comprometida=parse_date(cols[6]),
            cantidad_pendiente=pendiente,
        ))
    with transaction.atomic():
        OCAbierta.objects.all().delete()
        OCAbierta.objects.bulk_create(filas, batch_size=5000)
        _upsert_proveedores(proveedores)
    _registrar('oc_abiertas', ruta, len(filas))
    return len(filas)


def cargar_compromisos(data_dir=None):
    """Lineas abiertas de PC (estado O) y OF (estado P o R) con su fecha."""
    skus = _skus()
    filas = []
    ruta_pc = archivo('pedidos', data_dir)
    if os.path.exists(ruta_pc):
        for cols in iter_txt_rows(ruta_pc, 10):
            sku, estado, pend = cols[1], cols[5], _clean_num(cols[9])
            if sku in skus and estado == 'O' and pend > 0:
                filas.append(CompromisoAbierto(
                    product_id=sku, tipo=CompromisoAbierto.PC, numero=cols[0].replace(',', ''),
                    bodega=commitment_bodega(cols[2] or '013'), fecha=parse_date(cols[7]) or parse_date(cols[6]),
                    fecha_emision=parse_date(cols[6]), cantidad=pend))
    ruta_of = archivo('ofs', data_dir)
    if os.path.exists(ruta_of):
        for cols in iter_txt_rows(ruta_of, 9):
            sku, estado, pend = cols[1], cols[3], _clean_num(cols[8])
            if sku in skus and estado in ('P', 'R') and pend > 0:
                filas.append(CompromisoAbierto(
                    product_id=sku, tipo=CompromisoAbierto.OF, numero=cols[0].replace(',', ''),
                    bodega=commitment_bodega(cols[2] or '013-PP'), fecha=parse_date(cols[5]) or parse_date(cols[4]),
                    fecha_emision=parse_date(cols[4]), cantidad=pend))
    with transaction.atomic():
        CompromisoAbierto.objects.all().delete()
        CompromisoAbierto.objects.bulk_create(filas, batch_size=5000)
    _registrar('compromisos', ruta_pc, len(filas))
    return len(filas)


def cargar_compromisos_detalle(data_dir=None):
    """Consulta 16: PC y OF abiertos con responsable, para el informe de antiguedad (SPEC-23 §3).
    Solo articulos del alcance de la Calculadora: los servicios y grupos excluidos (montajes de OF,
    por ejemplo) no afectan la planificacion y su "costo" distorsiona el valor."""
    ruta = archivo('compromisos_detalle', data_dir)
    if not os.path.exists(ruta):
        _registrar('compromisos_detalle', '', 0, fuente='SIN_ARCHIVO', nota='Sin consulta 16: informe de antiguedad vacio')
        return 0
    costos = {c: float(v or 0) for c, v in ProductSKU.objects.filter(is_active=True, category__is_active=True)
              .values_list('code', 'unit_cost_usd')}
    filas = []
    for cols in iter_txt_rows(ruta, 11):
        q = _clean_num(cols[10])
        if q <= 0 or cols[2] not in costos:
            continue
        filas.append(CompromisoDetalle(
            tipo=cols[0][:2], numero=cols[1].replace(',', ''), codigo_sku=cols[2], bodega=cols[3][:20],
            nodo=nodo_red(cols[3] or '013'), fecha_emision=parse_date(cols[4]), fecha_entrega=parse_date(cols[5]),
            codigo_cliente=cols[6][:30], nombre_cliente=cols[7][:200], responsable=cols[8][:120],
            referencia=cols[9][:100], cantidad=q, costo_unitario=costos[cols[2]]))
    with transaction.atomic():
        CompromisoDetalle.objects.all().delete()
        CompromisoDetalle.objects.bulk_create(filas, batch_size=5000)
    _registrar('compromisos_detalle', ruta, len(filas))
    return len(filas)


# ── Parametros de compra y proveedores ───────────────────────────────────────

def cargar_parametros_compra(data_dir=None):
    """Consulta 10. Sin archivo: proveedor preferido = ultimo proveedor que entrego el
    articulo (Entradas de Mercancias) o el de su OC abierta mas reciente (SPEC-08 §3)."""
    ruta = archivo('parametros_compra', data_dir)
    skus = _skus()
    datos = {}
    if os.path.exists(ruta):
        for cols in iter_txt_rows(ruta, 9):
            sku = cols[0]
            if sku not in skus:
                continue
            datos[sku] = ParametroCompra(
                product_id=sku, proveedor_preferido=cols[1], lead_time_maestro=int(_clean_num(cols[2])),
                min_compra=_clean_num(cols[3]), multiplo_compra=_clean_num(cols[4]), unidad_medida=cols[6][:20],
                bloqueado=(cols[7] or '').upper() == 'Y',
            )
        fuente = 'TXT'
    else:
        fuente = 'RESPALDO'

    sin_proveedor = [s for s in skus if s not in datos or not datos[s].proveedor_preferido]
    respaldo = _proveedor_por_historia(data_dir)
    for sku in sin_proveedor:
        prov = respaldo.get(sku, '')
        if sku in datos:
            datos[sku].proveedor_preferido = prov
        elif prov:
            datos[sku] = ParametroCompra(product_id=sku, proveedor_preferido=prov)

    with transaction.atomic():
        ParametroCompra.objects.all().delete()
        ParametroCompra.objects.bulk_create(list(datos.values()), batch_size=5000)
    _registrar('parametros_compra', ruta if fuente == 'TXT' else '', len(datos), fuente=fuente,
               nota='' if fuente == 'TXT' else 'Sin consulta 10: proveedor desde entradas y OC; sin minimo ni multiplo')
    return len(datos)


def _proveedor_por_historia(data_dir=None):
    """sku -> proveedor de la entrada de mercancia mas reciente (o de la OC abierta)."""
    resultado, fechas = {}, {}
    ruta = archivo('entradas', data_dir)
    if os.path.exists(ruta):
        nombres = {}
        for cols in iter_txt_rows(ruta, 7):
            sku, fecha, prov = cols[1], parse_date(cols[2]), cols[3]
            if not prov or prov in PROVEEDORES_INTERNOS or not fecha:
                continue
            nombres[prov] = cols[4][:200]
            if sku not in fechas or fecha > fechas[sku]:
                fechas[sku], resultado[sku] = fecha, prov
        _upsert_proveedores(nombres)
    for sku, prov, fecha in OCAbierta.objects.exclude(proveedor_codigo='').values_list(
            'product_id', 'proveedor_codigo', 'fecha_oc'):
        if prov in PROVEEDORES_INTERNOS:
            continue
        if sku not in fechas or (fecha and fecha > fechas[sku]):
            fechas[sku], resultado[sku] = fecha or datetime.date.min, prov
    return resultado


def _upsert_proveedores(nombres):
    existentes = set(Proveedor.objects.filter(codigo__in=list(nombres)).values_list('codigo', flat=True))
    nuevos = [Proveedor(codigo=c, nombre=n) for c, n in nombres.items() if c and c not in existentes]
    Proveedor.objects.bulk_create(nuevos, batch_size=2000, ignore_conflicts=True)
    for c in existentes:
        if nombres.get(c):
            Proveedor.objects.filter(codigo=c, nombre='').update(nombre=nombres[c])


def cargar_proveedores(data_dir=None):
    """Consulta 11: nombre, pais (nacional / importado) y congelado. No toca el calendario."""
    ruta = archivo('proveedores', data_dir)
    if not os.path.exists(ruta):
        return 0
    n = 0
    with transaction.atomic():
        for cols in iter_txt_rows(ruta, 4):
            Proveedor.objects.update_or_create(codigo=cols[0], defaults={
                'nombre': cols[1][:200], 'pais': cols[2][:5], 'congelado': (cols[3] or '').upper() == 'Y'})
            n += 1
    _registrar('proveedores', ruta, n)
    return n


def cargar_bodegas(data_dir=None):
    """Consulta 14: nombres reales de bodega (el tipo y la zona se definen en la plataforma)."""
    ruta = archivo('bodegas', data_dir)
    if not os.path.exists(ruta):
        return 0
    n = 0
    for cols in iter_txt_rows(ruta, 3):
        n += Warehouse.objects.filter(code=cols[0]).update(name=f'{cols[0]} - {cols[1]}'[:100])
    _registrar('bodegas', ruta, n)
    return n


def cargar_acuerdos(data_dir=None):
    """Consulta 12: lineas de acuerdos globales. El precio debe venir en USD (columna 10, con la
    moneda original en la 11). Un archivo sin columna de moneda trae el precio en la moneda del
    acuerdo (CLP): el precio se descarta y la linea se valoriza al costo del maestro."""
    ruta = archivo('acuerdos', data_dir)
    if not os.path.exists(ruta):
        _registrar('acuerdos', '', 0, fuente='SIN_ARCHIVO', nota='Sin consulta 12: todas las lineas quedan sin contrato')
        return 0
    skus = _skus()
    filas, sin_moneda = [], False
    for cols in iter_txt_rows(ruta, 10):
        sku = cols[6]
        if sku not in skus:
            continue
        sin_moneda = sin_moneda or len(cols) < 11
        filas.append(AcuerdoGlobal(
            nro_acuerdo=cols[0].replace(',', ''), proveedor_codigo=cols[1], fecha_inicio=parse_date(cols[2]),
            fecha_termino=parse_date(cols[3]), estado=cols[4][:5], linea=int(_clean_num(cols[5])),
            product_id=sku, cantidad_plan=_clean_num(cols[7]), cantidad_acumulada=_clean_num(cols[8]),
            precio_unitario=_clean_num(cols[9]) if len(cols) >= 11 else 0,
        ))
    with transaction.atomic():
        AcuerdoGlobal.objects.all().delete()
        AcuerdoGlobal.objects.bulk_create(filas, batch_size=5000)
    _registrar('acuerdos', ruta, len(filas), fuente='SIN_MONEDA' if sin_moneda else 'TXT',
               nota='Archivo sin columna de moneda: precio del acuerdo descartado, se valoriza al costo'
               if sin_moneda else '')
    return len(filas)


def cargar_todo(data_dir=None):
    """Carga todos los datos de la Calculadora. Se llama despues del pipeline actual
    (maestro, stock, OF, PC, OC, SC) porque necesita los SKUs y los movimientos."""
    resumen = {
        'oc_abiertas': cargar_oc_abiertas(data_dir),
        'compromisos': cargar_compromisos(data_dir),
        'compromisos_detalle': cargar_compromisos_detalle(data_dir),
        'proveedores': cargar_proveedores(data_dir),
        'bodegas': cargar_bodegas(data_dir),
        'parametros_compra': cargar_parametros_compra(data_dir),
        'plazos_oc': cargar_plazos_oc(data_dir),
        'acuerdos': cargar_acuerdos(data_dir),
    }
    resumen['fuente_consumo'] = cargar_consumo_mensual(data_dir)
    return resumen
