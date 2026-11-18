"""Exportacion a Excel compartida por las vistas de la Calculadora."""
import io

import xlsxwriter
from django.http import HttpResponse


def respuesta_excel_multi(nombre_archivo, hojas_dict):
    """
    `hojas_dict`: diccionario de {'Nombre Hoja': [filas_dict]}.
    Permite generar un libro Excel con multiples pestañas.
    """
    buffer = io.BytesIO()
    libro = xlsxwriter.Workbook(buffer, {'in_memory': True})
    cabecera = libro.add_format({'bold': True, 'bg_color': '#0099DE', 'font_color': '#FFFFFF', 'border': 1})

    for hoja_nombre, filas in hojas_dict.items():
        ws = libro.add_worksheet(str(hoja_nombre)[:31])
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


def respuesta_excel(nombre_archivo, filas, hoja='Datos'):
    """`filas`: lista de dicts con las mismas claves (las columnas, en orden)."""
    return respuesta_excel_multi(nombre_archivo, {hoja: filas})

