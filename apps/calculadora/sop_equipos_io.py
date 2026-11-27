"""Importadores DRY desde Excel hacia nuestra BD S&OP (PresupuestoSOP y NegocioEnCursoSOP).

Pensado para poblar la base inicial desde los Excel existentes y permitir migraciones rápidas
de nuevas marcas hacia la gestión 100% nativa en plataforma.
"""
import unicodedata
from collections import defaultdict
from typing import Any

import openpyxl
from django.db import transaction

from apps.inventory.models import ProductSKU
from .models import NegocioEnCursoSOP, PresupuestoSOP


def _norm(texto: Any) -> str:
    s = unicodedata.normalize('NFKD', str(texto or ''))
    return ''.join(c for c in s if not unicodedata.combining(c)).strip().lower()


def _num(val: Any, default: float = 0.0) -> float:
    if val is None or val == '':
        return default
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).replace('$', '').replace('€', '').replace('USD', '').strip()
    if ',' in s and '.' in s:
        s = s.replace('.', '').replace(',', '.')
    elif ',' in s:
        s = s.replace(',', '.')
    try:
        return float(s)
    except ValueError:
        return default


def _elegir_hoja(wb: openpyxl.Workbook, keywords: tuple[str, ...]):
    """Selecciona la primera hoja que coincida con las palabras clave o la hoja activa si hay 1."""
    for name in wb.sheetnames:
        n = _norm(name)
        if any(k in n for k in keywords):
            return wb[name]
    return wb.active


def _mapear_columnas(ws) -> dict[str, int]:
    """Detecta índices (1-based) de columnas estándar en la fila de cabecera (1 a 5).
    Limita la búsqueda al primer bloque de columnas contiguas para no leer tablas auxiliares a la derecha.
    """
    for header_row in range(1, min(6, ws.max_row + 1)):
        cols: dict[str, int] = {}
        vistos_inicio = False
        for c in range(1, min(15, ws.max_column + 1)):
            h = _norm(ws.cell(header_row, c).value)
            if not h:
                if vistos_inicio and 'codigo' in cols:
                    break  # corta antes de tablas resumen a la derecha (ej. col H en Presupuesto 2026)
                continue
            vistos_inicio = True
            if 'codigo' in h and 'codigo' not in cols:
                cols['codigo'] = c
            elif ('cant' in h) and 'cantidad' not in cols:
                cols['cantidad'] = c
            elif ('precio' in h or 'unitario' in h) and 'precio' not in cols:
                cols['precio'] = c
            elif ('total' in h) and 'total' not in cols:
                cols['total'] = c
            elif ('cliente' in h or 'negocio' in h) and 'cliente' not in cols:
                cols['cliente'] = c
            elif ('comercial' in h or 'vendedor' in h or 'ejecutivo' in h) and 'comercial' not in cols:
                cols['comercial'] = c
            elif ('descrip' in h or 'equipo' in h) and 'descripcion' not in cols:
                cols['descripcion'] = c
            elif ('etapa' in h) and 'etapa' not in cols:
                cols['etapa'] = c
        if 'codigo' in cols and 'cantidad' in cols:
            cols['_header_row'] = header_row
            return cols
    return {}


def _parsear_excel_por_sku(archivo_o_ruta, keywords_hoja: tuple[str, ...]) -> dict[str, Any]:
    """Parser DRY común: lee Excel, resuelve códigos contra ProductSKU en 1 sola consulta."""
    wb = openpyxl.load_workbook(archivo_o_ruta, data_only=True)
    ws = _elegir_hoja(wb, keywords_hoja)
    cols = _mapear_columnas(ws)
    if not cols:
        return {'error': f"No se encontraron columnas 'Código' y 'Cantidad' en la hoja '{ws.title}'."}

    filas_raw = []
    codigos = set()
    for r in range(cols['_header_row'] + 1, ws.max_row + 1):
        cod_val = ws.cell(r, cols['codigo']).value
        if cod_val is None or str(cod_val).strip() == '':
            continue
        cod = str(int(cod_val)) if isinstance(cod_val, float) and cod_val.is_integer() else str(cod_val).strip()
        cant = _num(ws.cell(r, cols['cantidad']).value)
        if cant <= 0:
            continue
        precio = _num(ws.cell(r, cols['precio']).value) if 'precio' in cols else 0.0
        total = _num(ws.cell(r, cols['total']).value) if 'total' in cols else 0.0
        if total <= 0 and precio > 0:
            total = cant * precio
        elif precio <= 0 and total > 0:
            precio = total / cant

        filas_raw.append({
            'codigo': cod,
            'cantidad': cant,
            'precio': precio,
            'total': total,
            'cliente': str(ws.cell(r, cols['cliente']).value or '').strip() if 'cliente' in cols else '',
            'comercial': str(ws.cell(r, cols['comercial']).value or '').strip() if 'comercial' in cols else '',
            'descripcion': str(ws.cell(r, cols['descripcion']).value or '').strip() if 'descripcion' in cols else '',
            'etapa': str(ws.cell(r, cols['etapa']).value or '').strip() if 'etapa' in cols else '',
        })
        codigos.add(cod)

    sku_map = {
        p.code: p
        for p in ProductSKU.objects.filter(code__in=codigos)
    }

    resueltas = []
    no_encontrados = []
    sin_modelo = []
    for f in filas_raw:
        sku = sku_map.get(f['codigo'])
        if not sku:
            no_encontrados.append(f['codigo'])
            continue
        mod = (sku.modelo or '').strip()
        if not mod:
            sin_modelo.append(f['codigo'])
            continue
        resueltas.append({
            **f,
            'familia': (sku.familia or '').strip(),
            'subfamilia': (sku.subfamilia or '').strip(),
            'modelo': mod,
            'sku_desc': sku.description,
        })

    return {
        'hoja': ws.title,
        'resueltas': resueltas,
        'no_encontrados': sorted(set(no_encontrados)),
        'sin_modelo': sorted(set(sin_modelo)),
    }


def importar_presupuesto_excel(archivo_o_ruta, anio: int, user=None) -> dict[str, Any]:
    """Importa presupuesto anual por Código SKU, agrupa por (familia, subfamilia, modelo) SAP y guarda en PresupuestoSOP."""
    parsed = _parsear_excel_por_sku(archivo_o_ruta, ('presupuesto', 'ppto'))
    if parsed.get('error'):
        return parsed

    agrupado = defaultdict(lambda: {'cantidad': 0.0, 'monto_usd': 0.0})
    for f in parsed['resueltas']:
        key = (f['familia'], f['subfamilia'], f['modelo'])
        agrupado[key]['cantidad'] += f['cantidad']
        agrupado[key]['monto_usd'] += f['total']

    with transaction.atomic():
        for (fam, sub, mod), vals in agrupado.items():
            PresupuestoSOP.objects.update_or_create(
                anio=anio,
                familia=fam,
                subfamilia=sub,
                modelo=mod,
                defaults={
                    'cantidad': round(vals['cantidad'], 2),
                    'monto_usd': round(vals['monto_usd'], 2),
                    'actualizado_por': user,
                },
            )

    return {
        'ok': True,
        'hoja': parsed['hoja'],
        'modelos_importados': len(agrupado),
        'filas_leidas': len(parsed['resueltas']),
        'total_unidades': int(round(sum(v['cantidad'] for v in agrupado.values()))),
        'total_usd': round(sum(v['monto_usd'] for v in agrupado.values()), 2),
        'no_encontrados': parsed['no_encontrados'],
        'sin_modelo': parsed['sin_modelo'],
    }


def importar_nec_excel(archivo_o_ruta, anio: int, user=None, reemplazar_anio: bool = False) -> dict[str, Any]:
    """Importa Negocios en Curso (NEC) desde Excel por Código SKU hacia NegocioEnCursoSOP."""
    parsed = _parsear_excel_por_sku(archivo_o_ruta, ('nec', 'negocio'))
    if parsed.get('error'):
        return parsed

    etapas_validas = set(dict(NegocioEnCursoSOP.ETAPAS).keys())
    creados = []
    with transaction.atomic():
        if reemplazar_anio and parsed['resueltas']:
            subs = {(f['familia'], f['subfamilia']) for f in parsed['resueltas']}
            for fam, sub in subs:
                NegocioEnCursoSOP.objects.filter(anio=anio, familia=fam, subfamilia=sub).delete()

        for f in parsed['resueltas']:
            etapa = f['etapa'].upper() if f['etapa'].upper() in etapas_validas else NegocioEnCursoSOP.NEC_4
            creados.append(NegocioEnCursoSOP(
                anio=anio,
                familia=f['familia'],
                subfamilia=f['subfamilia'],
                modelo=f['modelo'],
                modelo_nombre=f['sku_desc'],
                cliente=f['cliente'] or f['descripcion'] or 'Oportunidad comercial',
                comercial=f['comercial'],
                etapa=etapa,
                cantidad=max(1, int(round(f['cantidad']))),
                precio_unitario_usd=round(f['precio'], 2),
                comentario=f"Importado desde hoja '{parsed['hoja']}' (SKU {f['codigo']})",
                creado_por=user,
            ))
        if creados:
            NegocioEnCursoSOP.objects.bulk_create(creados)

    return {
        'ok': True,
        'hoja': parsed['hoja'],
        'registros_creados': len(creados),
        'total_unidades': sum(c.cantidad for c in creados),
        'total_usd': round(sum(c.total_usd for c in creados), 2),
        'no_encontrados': parsed['no_encontrados'],
        'sin_modelo': parsed['sin_modelo'],
    }
