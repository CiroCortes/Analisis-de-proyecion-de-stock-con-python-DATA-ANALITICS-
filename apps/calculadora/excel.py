"""Exportacion a Excel compartida por las vistas de la Calculadora."""
import io

import xlsxwriter
from django.http import HttpResponse


def respuesta_excel(nombre_archivo, filas, hoja='Datos'):
    """`filas`: lista de dicts con las mismas claves (las columnas, en orden)."""
    buffer = io.BytesIO()
    libro = xlsxwriter.Workbook(buffer, {'in_memory': True})
    ws = libro.add_worksheet(hoja[:31])
    cabecera = libro.add_format({'bold': True, 'bg_color': '#0099DE', 'font_color': '#FFFFFF', 'border': 1})
    columnas = list(filas[0].keys()) if filas else ['Sin datos']
    for c, col in enumerate(columnas):
        ws.write(0, c, col, cabecera)
        ancho = max([len(str(col))] + [len(str(f.get(col, ''))) for f in filas[:500]])
        ws.set_column(c, c, min(60, max(10, ancho + 2)))
    for r, fila in enumerate(filas, start=1):
        for c, col in enumerate(columnas):
            v = fila.get(col, '')
            ws.write(r, c, v if isinstance(v, (int, float)) or v is None else str(v))
    ws.freeze_panes(1, 0)
    if filas:
        ws.autofilter(0, 0, len(filas), len(columnas) - 1)
    libro.close()
    resp = HttpResponse(buffer.getvalue(),
                        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    resp['Content-Disposition'] = f'attachment; filename="{nombre_archivo}"'
    return resp
