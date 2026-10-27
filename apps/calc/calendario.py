"""Calendario de compra por proveedor (documento §4.6.1, SPEC-12 §1).

Cada proveedor se compra en dias fijos: una fecha ancla y una frecuencia (15 dias por
defecto). Un dia de compra que cae en fin de semana pasa al lunes. Si el proveedor no
tiene ancla definida, se reparte de forma estable segun su codigo, para que no caigan
todos los proveedores el mismo dia.
"""
import datetime
import zlib

ANCLA_BASE = datetime.date(2026, 1, 5)   # lunes


def _habil(fecha):
    while fecha.weekday() >= 5:
        fecha += datetime.timedelta(days=1)
    return fecha


def ancla_por_defecto(codigo_proveedor, frecuencia):
    offset = zlib.crc32((codigo_proveedor or '').encode('utf-8')) % max(1, int(frecuencia))
    return _habil(ANCLA_BASE + datetime.timedelta(days=offset))


def proxima_fecha_compra(hoy, frecuencia, ancla):
    """Primer dia de compra >= hoy."""
    frecuencia = max(1, int(frecuencia))
    n = max(0, (hoy - ancla).days // frecuencia - 1)
    while True:
        fecha = _habil(ancla + datetime.timedelta(days=n * frecuencia))
        if fecha >= hoy:
            return fecha
        n += 1


def fechas_compra(desde, hasta, frecuencia, ancla):
    """Dias de compra entre dos fechas (para proyectar compras por mes)."""
    fechas = []
    fecha = proxima_fecha_compra(desde, frecuencia, ancla)
    while fecha <= hasta:
        fechas.append(fecha)
        fecha = proxima_fecha_compra(fecha + datetime.timedelta(days=1), frecuencia, ancla)
    return fechas
