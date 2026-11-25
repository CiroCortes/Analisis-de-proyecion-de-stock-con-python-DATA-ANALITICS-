"""Módulo S&OP Equipos / HIAB: Análisis y Mesa de Negociación Comercial (1 a 1).

Alimentado 100% desde nuestra base de datos local (cargada desde el Datalake / Athena):
- Maestro y agrupación por Modelo SAP: ProductSKU (sin tablas paralelas; los modelos vienen directo de SAP)
- Stock Físico por Bodega: StockActual (incluyendo bodegas de equipos como 013-06, 858, 980, 010)
- Tránsito Real (FR), Tránsito Proyectado (OC) y Taller/Montaje (OF): OCAbierta
- Backlog Clientes (PC abiertos con cliente y ejecutivo): CompromisoDetalle
- Ventas / Entregas L12M y YTD: ConsumoMensual y VentaMensual
- Presupuesto anual y Decisiones 1 a 1: PresupuestoSOP y PropuestaCompraSOP
"""
import datetime
from collections import defaultdict
from django.db.models import Q, Sum
from django.utils import timezone

from apps.inventory.models import ProductSKU
from apps.inventory.stock_actual_models import StockActual
from .models import (
    CargaDatos,
    CompromisoDetalle,
    ConsumoMensual,
    OCAbierta,
    PresupuestoSOP,
    PropuestaCompraSOP,
    VentaMensual,
)

# Bodegas que NO se suman como stock físico disponible para venta de equipos
BODEGAS_EXCLUIDAS_STOCK_EQUIPOS = {'013-NC', '000', '013'}

# Familias/subfamilias HIAB en SAP (u_rhclse='1', u_rhfamilia='113', u_rhsubfam='71')
FAMILIA_HIAB = '113'
SUBFAMILIA_HIAB = '71'


def _es_bodega_stock_equipo(wh_code: str) -> bool:
    """Indica si una bodega suma a Stock Físico de Equipos (excluye NC, pre-bodega 000 y tránsitos T*)."""
    code = (wh_code or '').strip().upper()
    if not code or code in BODEGAS_EXCLUIDAS_STOCK_EQUIPOS:
        return False
    if code.startswith('T') or code.startswith('000'):
        return False
    return True


def _es_sku_venta(sku: ProductSKU) -> tuple[str, str]:
    """Infiere si el SKU es de Venta (sobre camión / armado) o Compra (equipo base) desde SAP."""
    desc_up = (sku.description or '').upper()
    code = (sku.code or '').strip()
    if code.startswith('70') or 'S/CAMION' in desc_up or 'SOBRE CAMION' in desc_up or 'MONTAD' in desc_up:
        return 'Venta', 'Sí'
    return 'Compra', 'No'


def _get_skus_hiab_queryset():
    """Devuelve el QuerySet de Equipos HIAB directamente desde el maestro SAP (ProductSKU)."""
    return ProductSKU.objects.filter(is_active=True).filter(
        Q(clase='1', familia=FAMILIA_HIAB, subfamilia=SUBFAMILIA_HIAB)
        | Q(sap_group_code='158', familia=FAMILIA_HIAB, subfamilia=SUBFAMILIA_HIAB)
    ).order_by('modelo', 'code')


def _restar_meses(fecha: datetime.date, meses: int) -> datetime.date:
    y = fecha.year
    m = fecha.month - meses
    while m <= 0:
        m += 12
        y -= 1
    return datetime.date(y, m, 1)


def get_sop_hiab_data(force_refresh=False, solo_con_actividad=True):
    """Construye la radiografía S&OP HIAB 100% desde la base de datos local (Datalake).

    Agrupa estrictamente por ProductSKU.modelo tal cual viene de SAP.
    Los SKUs que vengan sin modelo en SAP se reportan en `skus_sin_modelo` para gestión de Master Data.
    """
    hoy = timezone.localdate()
    anio_actual = hoy.year

    skus_qs = list(_get_skus_hiab_queryset())
    if not skus_qs:
        return {
            'hay_datos': False,
            'error': 'No se encontraron equipos HIAB (clase=1, familia=113, subfamilia=71) en el maestro ProductSKU. Ejecute primero la sincronización del Datalake.',
        }

    sku_codes = [p.code for p in skus_qs]
    sku_map = {p.code: p for p in skus_qs}

    # Fecha de última carga desde Datalake
    ultima_carga = CargaDatos.objects.order_by('-cargado_en').first()
    fecha_sync = ultima_carga.cargado_en if ultima_carga else None

    # 1. Stock Físico desde StockActual (todas las bodegas de equipos)
    stock_by_sku = defaultdict(int)
    stock_bodegas_by_sku = defaultdict(lambda: defaultdict(int))
    for cod, bod, qty in StockActual.objects.filter(
        codigo__in=sku_codes, stock_disponible__gt=0
    ).values_list('codigo', 'bodega', 'stock_disponible'):
        if _es_bodega_stock_equipo(bod):
            q_int = int(round(qty or 0))
            stock_by_sku[cod] += q_int
            stock_bodegas_by_sku[cod][bod] += q_int

    # 2. Tránsito Real (FR), Tránsito Proyectado (OC) y Taller/Montaje (OF) desde OCAbierta
    tr_real_by_sku = defaultdict(int)
    tr_proj_by_sku = defaultdict(int)
    prod_by_sku = defaultdict(int)
    for cod, tipo, qty in OCAbierta.objects.filter(
        product_id__in=sku_codes, cuenta=True, cantidad_pendiente__gt=0
    ).values_list('product_id', 'tipo_documento', 'cantidad_pendiente'):
        q_int = int(round(qty or 0))
        if tipo == OCAbierta.FR:
            tr_real_by_sku[cod] += q_int
        elif tipo == OCAbierta.OC:
            tr_proj_by_sku[cod] += q_int
        elif tipo == OCAbierta.OF:
            prod_by_sku[cod] += q_int

    # 3. Backlog Clientes (PC abiertos recientes <= 12 meses) desde CompromisoDetalle
    corte_backlog = _restar_meses(hoy, 12)
    backlog_by_sku = defaultdict(int)
    backlog_usd_by_sku = defaultdict(float)
    backlog_items_by_sku = defaultdict(list)
    backlog_antiguos_count = 0

    for cd in CompromisoDetalle.objects.filter(codigo_sku__in=sku_codes, tipo='PC', cantidad__gt=0).order_by('-fecha_emision'):
        if cd.fecha_emision and cd.fecha_emision < corte_backlog:
            backlog_antiguos_count += 1
            continue
        q_int = int(round(cd.cantidad or 0))
        costo_u = float(cd.costo_unitario or (sku_map[cd.codigo_sku].unit_cost_usd if cd.codigo_sku in sku_map else 0) or 0)
        tot_usd = q_int * costo_u
        backlog_by_sku[cd.codigo_sku] += q_int
        backlog_usd_by_sku[cd.codigo_sku] += tot_usd
        backlog_items_by_sku[cd.codigo_sku].append({
            'codigo': cd.codigo_sku,
            'descripcion': sku_map[cd.codigo_sku].description if cd.codigo_sku in sku_map else '',
            'cantidad': q_int,
            'costo_unitario': costo_u,
            'total_usd': tot_usd,
            'ejecutivo': cd.responsable or 'Sin asignar',
            'linea': 'HIAB',
            'pc': cd.numero,
            'cliente': cd.nombre_cliente or cd.codigo_cliente or 'Cliente Directo',
            'fecha_emision': cd.fecha_emision.strftime('%d-%m-%Y') if cd.fecha_emision else '',
            'monto_venta': tot_usd,
        })

    # 4. Ventas / Entregas L12M y YTD desde ConsumoMensual (origen='VENTA') + VentaMensual (USD)
    ult_mes = ConsumoMensual.objects.order_by('-mes').values_list('mes', flat=True).first()
    ent_12m_by_sku = defaultdict(int)
    ent_ytd_by_sku = defaultdict(int)
    ent_12m_usd_by_sku = defaultdict(float)
    ent_ytd_usd_by_sku = defaultdict(float)

    if ult_mes:
        desde_12m = _restar_meses(ult_mes, 12)  # últimos 12 meses cerrados (mes > desde_12m)
        inicio_anio = datetime.date(ult_mes.year, 1, 1)
        anio_ref = ult_mes.year

        for row in ConsumoMensual.objects.filter(
            product_id__in=sku_codes, origen=ConsumoMensual.VENTA, mes__gt=desde_12m
        ).values('product_id').annotate(q=Sum('cantidad')):
            ent_12m_by_sku[row['product_id']] = int(round(row['q'] or 0))

        for row in ConsumoMensual.objects.filter(
            product_id__in=sku_codes, origen=ConsumoMensual.VENTA, mes__gte=inicio_anio
        ).values('product_id').annotate(q=Sum('cantidad')):
            ent_ytd_by_sku[row['product_id']] = int(round(row['q'] or 0))

        for row in VentaMensual.objects.filter(
            product_id__in=sku_codes, mes__gt=desde_12m
        ).values('product_id').annotate(m=Sum('monto_usd')):
            ent_12m_usd_by_sku[row['product_id']] = float(row['m'] or 0)

        for row in VentaMensual.objects.filter(
            product_id__in=sku_codes, mes__gte=inicio_anio
        ).values('product_id').annotate(m=Sum('monto_usd')):
            ent_ytd_usd_by_sku[row['product_id']] = float(row['m'] or 0)
    else:
        anio_ref = anio_actual

    # 5. Presupuesto anual por Modelo SAP (PresupuestoSOP)
    presup_by_modelo = {
        p.modelo: {'cantidad': int(round(p.cantidad)), 'monto_usd': float(p.monto_usd)}
        for p in PresupuestoSOP.objects.filter(anio=anio_ref, familia=FAMILIA_HIAB, subfamilia=SUBFAMILIA_HIAB)
    }

    # 6. Propuestas / Decisiones 1 a 1 registradas en la plataforma (PropuestaCompraSOP)
    propuestas_qs = list(PropuestaCompraSOP.objects.filter(
        familia=FAMILIA_HIAB, subfamilia=SUBFAMILIA_HIAB
    ).select_related('creado_por')[:100])

    solic_by_modelo = defaultdict(list)
    for pr in propuestas_qs:
        solic_by_modelo[pr.modelo].append({
            'id': pr.id,
            'modelo': pr.modelo,
            'vendedor': pr.vendedor,
            'negocio': pr.negocio or 'Propuesta comercial',
            'descripcion': pr.comentario or pr.get_decision_display(),
            'cantidad': pr.cantidad_aprobada if pr.decision in (PropuestaCompraSOP.APROBADA, PropuestaCompraSOP.PARCIAL) else pr.cantidad_solicitada,
            'cantidad_solicitada': pr.cantidad_solicitada,
            'cantidad_aprobada': pr.cantidad_aprobada,
            'total_usd': pr.inversion_usd,
            'decision': pr.decision,
            'decision_label': pr.get_decision_display(),
            'fecha': pr.creado_en.strftime('%d-%m-%Y %H:%M'),
        })

    # 7. Armar detalle por SKU y agrupar estrictamente por ProductSKU.modelo (SAP)
    skus_detalle = []
    subfamilias_map = {}
    skus_sin_modelo = []

    for idx, p in enumerate(skus_qs, start=1):
        modelo_sap = (p.modelo or '').strip()
        if not modelo_sap:
            skus_sin_modelo.append({'codigo': p.code, 'descripcion': p.description})
            modelo_key = 'SIN_MODELO'
        else:
            modelo_key = modelo_sap

        origen, sobre_camion = _es_sku_venta(p)
        costo_u = float(p.unit_cost_usd or 0)
        stk_c = stock_by_sku.get(p.code, 0)
        tr_r = tr_real_by_sku.get(p.code, 0)
        tr_p = tr_proj_by_sku.get(p.code, 0)
        prod_c = prod_by_sku.get(p.code, 0)
        bklg_c = backlog_by_sku.get(p.code, 0)
        e12_c = ent_12m_by_sku.get(p.code, 0)
        eytd_c = ent_ytd_by_sku.get(p.code, 0)

        tiene_actividad = any([stk_c, tr_r, tr_p, prod_c, bklg_c, e12_c, eytd_c])
        if solo_con_actividad and not tiene_actividad and modelo_key not in presup_by_modelo and modelo_key not in solic_by_modelo:
            continue

        stk_usd = stk_c * costo_u
        tr_r_usd = tr_r * costo_u
        tr_p_usd = tr_p * costo_u
        prod_usd = prod_c * costo_u
        bklg_usd = backlog_usd_by_sku.get(p.code, bklg_c * costo_u)
        e12_usd = ent_12m_usd_by_sku.get(p.code) or (e12_c * costo_u)
        eytd_usd = ent_ytd_usd_by_sku.get(p.code) or (eytd_c * costo_u)

        sku_obj = {
            'fila': idx,
            'codigo': p.code,
            'origen': origen,
            'familia': 'HIAB',
            'subfamilia': modelo_key,
            'descripcion': p.description,
            'sobre_camion': sobre_camion,
            'costo_unitario': costo_u,
            'stock_cant': stk_c,
            'stock_usd': stk_usd,
            'stock_bodegas': dict(stock_bodegas_by_sku.get(p.code, {})),
            'tr_real_cant': tr_r,
            'tr_real_usd': tr_r_usd,
            'tr_proj_cant': tr_p,
            'tr_proj_usd': tr_p_usd,
            'prod_cant': prod_c,
            'prod_usd': prod_usd,
            'solic_cant': 0,
            'solic_usd': 0.0,
            'backlog_cant': bklg_c,
            'backlog_usd': bklg_usd,
            'ent_2026_cant': eytd_c,
            'ent_2026_usd': eytd_usd,
            'presup_cant': 0,
            'presup_usd': 0.0,
            'ent_12m_cant': e12_c,
            'ent_12m_usd': e12_usd,
        }
        skus_detalle.append(sku_obj)

        if modelo_key not in subfamilias_map:
            ppto = presup_by_modelo.get(modelo_key, {'cantidad': 0, 'monto_usd': 0.0})
            subfamilias_map[modelo_key] = {
                'clave': modelo_key,
                'nombre': 'Sin Modelo asignado en SAP (revisar Master Data)' if modelo_key == 'SIN_MODELO' else p.description,
                'familia': 'HIAB',
                'skus': [],
                'stock_cant': 0,
                'stock_usd': 0.0,
                'tr_real_cant': 0,
                'tr_real_usd': 0.0,
                'tr_proj_cant': 0,
                'tr_proj_usd': 0.0,
                'en_proceso_cant': 0,
                'en_proceso_usd': 0.0,
                'solic_cant': 0,
                'solic_usd': 0.0,
                'backlog_cant': 0,
                'backlog_usd': 0.0,
                'ent_2026_cant': 0,
                'ent_2026_usd': 0.0,
                'presup_cant': ppto['cantidad'],
                'presup_usd': ppto['monto_usd'],
                'ent_12m_cant': 0,
                'ent_12m_usd': 0.0,
                'backlog_items': [],
                'solicitudes_items': list(solic_by_modelo.get(modelo_key, [])),
                'costo_unitario_compra': 0.0,
            }

        sf = subfamilias_map[modelo_key]
        sf['skus'].append(sku_obj)

        # Preferir la descripción del SKU de Compra como nombre representativo del modelo
        if modelo_key != 'SIN_MODELO' and origen == 'Compra':
            if sf['costo_unitario_compra'] == 0 or costo_u > sf['costo_unitario_compra']:
                sf['nombre'] = p.description
                sf['costo_unitario_compra'] = costo_u

        sf['stock_cant'] += stk_c
        sf['stock_usd'] += stk_usd
        sf['tr_real_cant'] += tr_r
        sf['tr_real_usd'] += tr_r_usd
        sf['tr_proj_cant'] += tr_p
        sf['tr_proj_usd'] += tr_p_usd
        sf['en_proceso_cant'] += prod_c
        sf['en_proceso_usd'] += prod_usd
        sf['backlog_cant'] += bklg_c
        sf['backlog_usd'] += bklg_usd
        sf['ent_2026_cant'] += eytd_c
        sf['ent_2026_usd'] += eytd_usd
        sf['ent_12m_cant'] += e12_c
        sf['ent_12m_usd'] += e12_usd
        sf['backlog_items'].extend(backlog_items_by_sku.get(p.code, []))

    # 8. Calcular métricas S&OP derivadas por modelo y KPIs macro consolidados
    subfamilias_list = []
    tot_stk_c = tot_tr_r_c = tot_tr_p_c = tot_prod_c = tot_bklg_c = 0
    tot_stk_u = tot_tr_r_u = tot_tr_p_u = tot_prod_u = tot_bklg_u = 0.0
    tot_e12_c = tot_eytd_c = tot_ppto_c = tot_solic_c = 0
    tot_e12_u = tot_eytd_u = tot_ppto_u = tot_solic_u = 0.0

    for clave, sf in subfamilias_map.items():
        # Costo respaldo si ningún SKU fue clasificado como Compra
        if sf['costo_unitario_compra'] <= 0:
            costos_validos = [s['costo_unitario'] for s in sf['skus'] if s['costo_unitario'] > 0]
            sf['costo_unitario_compra'] = round(sum(costos_validos) / len(costos_validos), 2) if costos_validos else 0.0

        # Sumar solicitudes vigentes (en evaluación o aprobadas)
        for sol in sf['solicitudes_items']:
            if sol['decision'] in (PropuestaCompraSOP.PENDIENTE, PropuestaCompraSOP.APROBADA, PropuestaCompraSOP.PARCIAL):
                sf['solic_cant'] += sol['cantidad']
                sf['solic_usd'] += sol['total_usd']

        sf['inv_inicial_cant'] = sf['stock_cant'] + sf['tr_real_cant'] + sf['tr_proj_cant'] + sf['en_proceso_cant']
        sf['inv_inicial_usd'] = sf['stock_usd'] + sf['tr_real_usd'] + sf['tr_proj_usd'] + sf['en_proceso_usd']
        sf['inv_libre_cant'] = sf['inv_inicial_cant'] - sf['backlog_cant']
        sf['inv_libre_usd'] = sf['inv_inicial_usd'] - sf['backlog_usd']

        # Ritmo mensual de venta (mayor entre L12M/12 y Presupuesto/12)
        ritmo_l12m = sf['ent_12m_cant'] / 12.0 if sf['ent_12m_cant'] > 0 else 0.0
        ritmo_ppto = sf['presup_cant'] / 12.0 if sf['presup_cant'] > 0 else 0.0
        ritmo_mensual = max(ritmo_l12m, ritmo_ppto)
        sf['ritmo_mensual'] = round(ritmo_mensual, 2)

        if ritmo_mensual > 0:
            sf['cobertura_meses'] = round(sf['inv_libre_cant'] / ritmo_mensual, 1)
        elif sf['inv_libre_cant'] > 0:
            sf['cobertura_meses'] = 999.0
        else:
            sf['cobertura_meses'] = 0.0

        if sf['cobertura_meses'] > 12.0:
            sf['semaforo'] = 'SOBRESTOCK'
            sf['semaforo_label'] = 'Sobrestock (> 12 m)'
            sf['semaforo_color'] = 'red'
        elif sf['cobertura_meses'] >= 6.0:
            sf['semaforo'] = 'PRECAUCION'
            sf['semaforo_label'] = 'Precaución (6 a 12 m)'
            sf['semaforo_color'] = 'amber'
        elif sf['cobertura_meses'] >= 3.0:
            sf['semaforo'] = 'OPTIMO'
            sf['semaforo_label'] = 'Óptimo (3 a 6 m)'
            sf['semaforo_color'] = 'emerald'
        else:
            sf['semaforo'] = 'QUIEBRE'
            sf['semaforo_label'] = 'Baja Cobertura (< 3 m)'
            sf['semaforo_color'] = 'cyan'

        subfamilias_list.append(sf)

        tot_stk_c += sf['stock_cant']
        tot_stk_u += sf['stock_usd']
        tot_tr_r_c += sf['tr_real_cant']
        tot_tr_r_u += sf['tr_real_usd']
        tot_tr_p_c += sf['tr_proj_cant']
        tot_tr_p_u += sf['tr_proj_usd']
        tot_prod_c += sf['en_proceso_cant']
        tot_prod_u += sf['en_proceso_usd']
        tot_bklg_c += sf['backlog_cant']
        tot_bklg_u += sf['backlog_usd']
        tot_e12_c += sf['ent_12m_cant']
        tot_e12_u += sf['ent_12m_usd']
        tot_eytd_c += sf['ent_2026_cant']
        tot_eytd_u += sf['ent_2026_usd']
        tot_ppto_c += sf['presup_cant']
        tot_ppto_u += sf['presup_usd']
        tot_solic_c += sf['solic_cant']
        tot_solic_u += sf['solic_usd']

    subfamilias_list.sort(key=lambda x: (-x['ent_12m_cant'], -x['inv_libre_cant'], x['clave']))

    inv_ini_c = tot_stk_c + tot_tr_r_c + tot_tr_p_c + tot_prod_c
    inv_ini_u = tot_stk_u + tot_tr_r_u + tot_tr_p_u + tot_prod_u
    inv_fin_c = inv_ini_c - tot_bklg_c
    inv_fin_u = inv_ini_u - tot_bklg_u
    inv_proj_c = inv_fin_c + tot_solic_c
    inv_proj_u = inv_fin_u + tot_solic_u

    ritmo_macro = (tot_e12_c / 12.0) if tot_e12_c > 0 else 0.0
    rot_actual = round(inv_fin_c / ritmo_macro, 1) if ritmo_macro > 0 else 0.0
    rot_proj = round(inv_proj_c / ritmo_macro, 1) if ritmo_macro > 0 else 0.0

    cump_cant_pct = round(((tot_eytd_c + tot_bklg_c) / tot_ppto_c) * 100.0, 1) if tot_ppto_c > 0 else 0.0
    cump_usd_pct = round(((tot_eytd_u + tot_bklg_u) / tot_ppto_u) * 100.0, 1) if tot_ppto_u > 0 else 0.0

    kpis = {
        'entregado_12m_usd': tot_e12_u,
        'entregado_12m_cant': tot_e12_c,
        'entregado_2026_usd': tot_eytd_u,
        'entregado_2026_cant': tot_eytd_c,
        'backlog_usd': tot_bklg_u,
        'backlog_cant': tot_bklg_c,
        'presupuesto_usd': tot_ppto_u,
        'presupuesto_cant': tot_ppto_c,
        'cumplimiento_cant_pct': cump_cant_pct,
        'cumplimiento_usd_pct': cump_usd_pct,
        'stock_usd': tot_stk_u,
        'stock_cant': tot_stk_c,
        'transito_real_usd': tot_tr_r_u,
        'transito_real_cant': tot_tr_r_c,
        'transito_proj_usd': tot_tr_p_u,
        'transito_proj_cant': tot_tr_p_c,
        'en_proceso_usd': tot_prod_u,
        'en_proceso_cant': tot_prod_c,
        'inventario_inicial_usd': inv_ini_u,
        'inventario_inicial_cant': inv_ini_c,
        'inventario_final_usd': inv_fin_u,
        'inventario_final_cant': inv_fin_c,
        'rotacion_actual_meses': rot_actual,
        'solicitud_usd': tot_solic_u,
        'solicitud_cant': tot_solic_c,
        'inv_final_proj_usd': inv_proj_u,
        'inv_final_proj_cant': inv_proj_c,
        'rotacion_proj_meses': rot_proj,
    }

    return {
        'hay_datos': True,
        'fuente': 'BD Datalake (SAP)',
        'fecha_sync': fecha_sync,
        'anio_ref': anio_ref,
        'ultimo_mes_consumo': ult_mes,
        'backlog_antiguos_excluidos': backlog_antiguos_count,
        'skus_sin_modelo': skus_sin_modelo,
        'kpis': kpis,
        'subfamilias': subfamilias_list,
        'subfamilias_dict': {sf['clave']: sf for sf in subfamilias_list},
        'skus_detalle': skus_detalle,
        'propuestas_recientes': propuestas_qs,
        'total_skus': len(skus_detalle),
        'total_subfamilias': len(subfamilias_list),
    }


def simular_propuesta_compra(subfamilia_clave: str, cantidad_solicitada: int):
    """Simula la propuesta de un vendedor para un Modelo SAP y genera el argumento de negociación."""
    data = get_sop_hiab_data()
    if not data.get('hay_datos'):
        return {'error': 'No hay datos cargados desde el Datalake'}

    sf = data['subfamilias_dict'].get(str(subfamilia_clave))
    if not sf:
        return {'error': f'Modelo SAP {subfamilia_clave} no encontrado'}

    cant = max(0, int(cantidad_solicitada or 0))
    costo_u = sf['costo_unitario_compra'] or 100000.0
    inversion_usd = cant * costo_u

    inv_libre_actual = sf['inv_libre_cant']
    inv_libre_proj = inv_libre_actual + cant
    ritmo = sf['ritmo_mensual']

    cob_actual = sf['cobertura_meses']
    if ritmo > 0:
        cob_proj = round(inv_libre_proj / ritmo, 1)
    elif inv_libre_proj > 0:
        cob_proj = 999.0
    else:
        cob_proj = 0.0

    if cant == 0:
        decision = 'NEUTRO'
        veredicto = 'Sin solicitud adicional'
        color = 'slate'
        argumento = (
            f"El modelo {sf['nombre']} (Modelo SAP {sf['clave']}) cuenta actualmente con {inv_libre_actual} unidades libres "
            f"({sf['stock_cant']} en stock, {sf['tr_real_cant'] + sf['tr_proj_cant']} en tránsito y {sf['en_proceso_cant']} en taller, "
            f"descontando {sf['backlog_cant']} comprometidas en backlog). Cobertura actual: {cob_actual} meses."
        )
    elif cob_actual > 12.0:
        decision = 'REFUTAR'
        veredicto = '⛔ REFUTAR COMPRA (Sobrestock Severo)'
        color = 'red'
        argumento = (
            f"Rechazar solicitud. El modelo ya cuenta con {inv_libre_actual} unidades disponibles no comprometidas "
            f"({cob_actual} meses de cobertura al ritmo anual de {sf['ent_12m_cant']} unidades). "
            f"Comprar {cant} unidades adicionales inmovilizaría ${inversion_usd:,.0f} USD en capital de trabajo "
            f"y dispararía la cobertura a {cob_proj} meses ({round(cob_proj / 12.0, 1)} años). "
            f"Recomendación: Priorizar la venta de las unidades en stock ({sf['stock_cant']}) y en tránsito ({sf['tr_real_cant'] + sf['tr_proj_cant']})."
        )
    elif cob_actual >= 6.0:
        decision = 'NEGOCIAR'
        veredicto = '⚠️ NEGOCIAR REDUCCIÓN O POSTERGAR'
        color = 'amber'
        argumento = (
            f"Ajustar o diferir compra. El inventario libre actual ({inv_libre_actual} unidades) cubre {cob_actual} meses de demanda, "
            f"suficiente para cubrir el lead time de fábrica. Comprar {cant} unidades (${inversion_usd:,.0f} USD) elevaría la cobertura a {cob_proj} meses. "
            f"Recomendación: Si el cliente no tiene una orden en firme firmada, aplazar la compra a la próxima ventana S&OP o comprar máximo 1 unidad."
        )
    elif cob_proj <= 6.0:
        decision = 'APROBAR'
        veredicto = '✅ APROBAR COMPRA (Completamente Justificada)'
        color = 'emerald'
        argumento = (
            f"Aprobar compra de {cant} unidades (${inversion_usd:,.0f} USD). "
            f"El inventario libre actual es de solo {inv_libre_actual} unidades con cobertura baja ({cob_actual} meses) "
            f"frente a una demanda de {ritmo} un/mes. La compra asegura suministro para los próximos {cob_proj} meses "
            f"manteniendo un nivel de inventario saludable."
        )
    else:
        decision = 'APROBAR_PARCIAL'
        veredicto = '⚠️ APROBACIÓN PARCIAL (Reducir volumen)'
        color = 'amber'
        cant_optima = max(1, int(round((6.0 * ritmo) - inv_libre_actual)))
        argumento = (
            f"La compra solicitada de {cant} unidades sobrepasa la cobertura óptima (alcanza {cob_proj} meses). "
            f"Se recomienda contra-ofertar la compra de {cant_optima} unidades (${cant_optima * costo_u:,.0f} USD) "
            f"para dejar la cobertura en un rango de ~6 meses."
        )

    return {
        'subfamilia': sf['clave'],
        'nombre': sf['nombre'],
        'cantidad_solicitada': cant,
        'costo_unitario_usd': costo_u,
        'inversion_usd': inversion_usd,
        'inv_libre_actual': inv_libre_actual,
        'inv_libre_proyectado': inv_libre_proj,
        'cobertura_actual_meses': cob_actual,
        'cobertura_proyectada_meses': cob_proj,
        'decision': decision,
        'veredicto': veredicto,
        'color': color,
        'argumento': argumento,
    }
