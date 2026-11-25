"""Vistas para el Panel S&OP HIAB: Análisis y Mesa de Negociación Comercial (1 a 1)."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from . import sop_hiab
from .excel import respuesta_excel_multi
from .models import PresupuestoSOP, PropuestaCompraSOP


@login_required
def sop_hiab_view(request):
    """Vista principal de la mesa S&OP HIAB de Ignacio."""
    data = sop_hiab.get_sop_hiab_data()
    if not data.get('hay_datos'):
        return render(request, 'calculadora/sop_hiab.html', {'hay_datos': False, 'error': data.get('error')})

    subfamilias = data['subfamilias']
    kpis = data['kpis']

    # Filtros
    f_subfam = request.GET.get('subfamilia', '').strip()
    f_semaforo = request.GET.get('semaforo', '').strip()
    f_search = request.GET.get('q', '').strip().lower()

    subfamilias_filtradas = []
    for sf in subfamilias:
        if f_subfam and sf['clave'] != f_subfam:
            continue
        if f_semaforo and sf['semaforo'] != f_semaforo:
            continue
        if f_search:
            match_txt = (
                f_search in sf['clave'].lower() or
                f_search in sf['nombre'].lower() or
                any(f_search in s['codigo'].lower() or f_search in s['descripcion'].lower() for s in sf['skus'])
            )
            if not match_txt:
                continue
        subfamilias_filtradas.append(sf)

    # Subfamilia activa para el simulador 1 a 1
    selected_clave = request.GET.get('sim_subfam') or (subfamilias_filtradas[0]['clave'] if subfamilias_filtradas else '1188')
    active_sf = data['subfamilias_dict'].get(selected_clave) or (subfamilias_filtradas[0] if subfamilias_filtradas else None)

    # Simulación inicial
    sim_cant = int(request.GET.get('sim_cant') or 0)
    simulacion = None
    if active_sf:
        simulacion = sop_hiab.simular_propuesta_compra(active_sf['clave'], sim_cant)

    # Mapa serializable para el simulador interactivo en cliente (evita problemas de localización)
    subfamilias_map = {}
    for sf in subfamilias:
        subfamilias_map[sf['clave']] = {
            'clave': sf['clave'],
            'nombre': sf['nombre'],
            'familia': sf['familia'],
            'stock_cant': sf['stock_cant'],
            'tr_real_cant': sf['tr_real_cant'],
            'tr_proj_cant': sf['tr_proj_cant'],
            'en_proceso_cant': sf['en_proceso_cant'],
            'inv_inicial_cant': sf['inv_inicial_cant'],
            'backlog_cant': sf['backlog_cant'],
            'inv_libre_cant': sf['inv_libre_cant'],
            'ent_12m_cant': sf['ent_12m_cant'],
            'ritmo_mensual': float(sf['ritmo_mensual']),
            'cobertura_meses': float(sf['cobertura_meses']),
            'semaforo': sf['semaforo'],
            'semaforo_label': sf['semaforo_label'],
            'costo_unitario_compra': float(sf['costo_unitario_compra']),
        }

    context = {
        'hay_datos': True,
        'fuente': data.get('fuente', 'BD Datalake (SAP)'),
        'fecha_sync': data.get('fecha_sync'),
        'anio_ref': data.get('anio_ref', timezone.localdate().year),
        'ultimo_mes_consumo': data.get('ultimo_mes_consumo'),
        'skus_sin_modelo': data.get('skus_sin_modelo', []),
        'backlog_antiguos_excluidos': data.get('backlog_antiguos_excluidos', 0),
        'kpis': kpis,
        'subfamilias': subfamilias_filtradas,
        'todas_subfamilias': subfamilias,
        'subfamilias_map': subfamilias_map,
        'active_sf': active_sf,
        'simulacion': simulacion,
        'propuestas_recientes': data.get('propuestas_recientes', []),
        'decision_choices': PropuestaCompraSOP.DECISIONES,
        'f_subfam': f_subfam,
        'f_semaforo': f_semaforo,
        'f_search': f_search,
        'total_subfamilias': len(subfamilias),
        'total_skus': data['total_skus'],
    }
    return render(request, 'calculadora/sop_hiab.html', context)


@login_required
@require_POST
def sop_hiab_guardar_decision(request):
    """Registra una decisión de la reunión 1 a 1 en BD (reemplaza la hoja Solicitud del Excel)."""
    modelo = request.POST.get('modelo', '').strip()
    vendedor = request.POST.get('vendedor', '').strip()
    negocio = request.POST.get('negocio', '').strip()
    decision = request.POST.get('decision', PropuestaCompraSOP.PENDIENTE).strip()
    comentario = request.POST.get('comentario', '').strip()

    try:
        cant_sol = max(0, int(request.POST.get('cantidad_solicitada', 0) or 0))
    except (ValueError, TypeError):
        cant_sol = 0
    try:
        cant_apr = max(0, int(request.POST.get('cantidad_aprobada', 0) or 0))
    except (ValueError, TypeError):
        cant_apr = 0

    if not modelo:
        messages.error(request, 'Debe seleccionar un modelo SAP válido.')
        return redirect('calculadora:sop_hiab')

    if decision == PropuestaCompraSOP.APROBADA and cant_apr == 0:
        cant_apr = cant_sol
    elif decision in (PropuestaCompraSOP.REFUTADA, PropuestaCompraSOP.POSTERGADA):
        cant_apr = 0

    cant_eval = cant_apr if decision in (PropuestaCompraSOP.APROBADA, PropuestaCompraSOP.PARCIAL) else cant_sol
    sim = sop_hiab.simular_propuesta_compra(modelo, cant_eval)

    PropuestaCompraSOP.objects.create(
        familia=sop_hiab.FAMILIA_HIAB,
        subfamilia=sop_hiab.SUBFAMILIA_HIAB,
        modelo=modelo,
        modelo_nombre=sim.get('nombre', '') if not sim.get('error') else '',
        vendedor=vendedor,
        negocio=negocio,
        cantidad_solicitada=cant_sol,
        cantidad_aprobada=cant_apr,
        costo_unitario_usd=sim.get('costo_unitario_usd', 0) if not sim.get('error') else 0,
        inversion_usd=sim.get('inversion_usd', 0) if not sim.get('error') else 0,
        cobertura_actual_meses=sim.get('cobertura_actual_meses', 0) if not sim.get('error') else 0,
        cobertura_proyectada_meses=sim.get('cobertura_proyectada_meses', 0) if not sim.get('error') else 0,
        decision=decision if decision in dict(PropuestaCompraSOP.DECISIONES) else PropuestaCompraSOP.PENDIENTE,
        comentario=comentario,
        creado_por=request.user,
    )
    messages.success(request, f'Decisión registrada para Modelo SAP {modelo}.')
    return redirect(f"/calculadora/sop-hiab/?sim_subfam={modelo}&sim_cant={cant_sol}#historial-decisiones")


@login_required
@require_POST
def sop_hiab_eliminar_decision(request, pk):
    """Elimina una decisión 1 a 1 registrada por error."""
    obj = get_object_or_404(PropuestaCompraSOP, pk=pk)
    obj.delete()
    messages.info(request, 'Registro de decisión eliminado.')
    return redirect('/calculadora/sop-hiab/#historial-decisiones')


@login_required
@require_POST
def sop_hiab_guardar_presupuesto(request):
    """Guarda o actualiza el presupuesto anual de un Modelo SAP."""
    modelo = request.POST.get('modelo', '').strip()
    try:
        anio = int(request.POST.get('anio', timezone.localdate().year))
    except (ValueError, TypeError):
        anio = timezone.localdate().year
    try:
        cantidad = max(0.0, float(request.POST.get('cantidad', 0) or 0))
    except (ValueError, TypeError):
        cantidad = 0.0
    try:
        monto_usd = max(0.0, float(request.POST.get('monto_usd', 0) or 0))
    except (ValueError, TypeError):
        monto_usd = 0.0

    if not modelo:
        messages.error(request, 'Modelo SAP inválido para presupuesto.')
        return redirect('/calculadora/sop-hiab/#matriz-consolidada')

    PresupuestoSOP.objects.update_or_create(
        anio=anio,
        familia=sop_hiab.FAMILIA_HIAB,
        subfamilia=sop_hiab.SUBFAMILIA_HIAB,
        modelo=modelo,
        defaults={
            'cantidad': cantidad,
            'monto_usd': monto_usd,
            'actualizado_por': request.user,
        },
    )
    messages.success(request, f'Presupuesto {anio} guardado para Modelo SAP {modelo}.')
    return redirect('/calculadora/sop-hiab/#matriz-consolidada')


@login_required
def sop_hiab_simular_api(request):
    """Endpoint AJAX para la simulación interactiva en tiempo real."""
    sf_clave = request.GET.get('subfamilia', '').strip()
    cant = request.GET.get('cantidad', 0)
    try:
        cant_num = int(cant)
    except (ValueError, TypeError):
        cant_num = 0

    res = sop_hiab.simular_propuesta_compra(sf_clave, cant_num)
    return JsonResponse(res)


@login_required
def sop_hiab_excel(request):
    """Exporta el análisis S&OP HIAB a un libro Excel multi-pestaña."""
    data = sop_hiab.get_sop_hiab_data()
    if not data.get('hay_datos'):
        return HttpResponse('No hay datos para exportar', status=400)

    hoy = timezone.localdate()

    # Hoja 1: Resumen por Subfamilia
    filas_subfam = []
    for sf in data['subfamilias']:
        filas_subfam.append({
            'Subfamilia': sf['clave'],
            'Modelo Representativo': sf['nombre'],
            'Familia': sf['familia'],
            'Stock Físico (u)': sf['stock_cant'],
            'Stock Físico (USD)': round(sf['stock_usd'], 2),
            'Tránsito Real (u)': sf['tr_real_cant'],
            'Tránsito Proyectado (u)': sf['tr_proj_cant'],
            'En Taller/Proceso (u)': sf['en_proceso_cant'],
            'Inventario Inicial Total (u)': sf['inv_inicial_cant'],
            'Backlog Comprometido (u)': sf['backlog_cant'],
            'Backlog (USD)': round(sf['backlog_usd'], 2),
            'Inventario Libre No Comprometido (u)': sf['inv_libre_cant'],
            'Ventas L12M (u)': sf['ent_12m_cant'],
            'Ventas 2026 YTD (u)': sf['ent_2026_cant'],
            'Presupuesto 2026 (u)': sf['presup_cant'],
            'Ritmo Mensual Demanda (u/m)': sf['ritmo_mensual'],
            'Meses de Cobertura': sf['cobertura_meses'] if sf['cobertura_meses'] < 999 else 'Sin ventas',
            'Estado Semáforo': sf['semaforo_label'],
            'Solicitud Compra Propuesta (u)': sf['solic_cant'],
            'Costo Unitario Compra (USD)': sf['costo_unitario_compra'],
        })

    # Hoja 2: Detalle por SKU (90 ítems)
    filas_skus = []
    for s in data['skus_detalle']:
        filas_skus.append({
            'Fila': s['fila'],
            'Código': s['codigo'],
            'Origen': s['origen'],
            'Familia': s['familia'],
            'Subfamilia': s['subfamilia'],
            'Descripción': s['descripcion'],
            'Sobre Camión': s['sobre_camion'],
            'Costo Unitario USD': round(s['costo_unitario'], 2),
            'Stock Cant': s['stock_cant'],
            'Stock Total USD': round(s['stock_usd'], 2),
            'Tránsito Real Cant': s['tr_real_cant'],
            'Tránsito Proy Cant': s['tr_proj_cant'],
            'En Taller/Producción': s['prod_cant'],
            'Solicitud Cant': s['solic_cant'],
            'Backlog Cant': s['backlog_cant'],
            'Entregado 2026 Cant': s['ent_2026_cant'],
            'Presupuesto 2026 Cant': s['presup_cant'],
            'Entregado L12M Cant': s['ent_12m_cant'],
        })

    # Hoja 3: Backlog detallado por Cliente
    filas_backlog = []
    for sf in data['subfamilias']:
        for b in sf['backlog_items']:
            filas_backlog.append({
                'Subfamilia': sf['clave'],
                'Código SKU': b['codigo'],
                'Descripción': b['descripcion'],
                'Cantidad (u)': b['cantidad'],
                'Total USD': round(b['total_usd'], 2),
                'Ejecutivo Responsable': b['ejecutivo'],
                'N° Pedido (PC)': b['pc'],
                'Cliente': b['cliente'],
            })

    # Hoja 4: Decisiones y Solicitudes 1 a 1
    filas_solicitudes = []
    for sf in data['subfamilias']:
        for sol in sf['solicitudes_items']:
            filas_solicitudes.append({
                'Modelo SAP': sf['clave'],
                'Fecha': sol.get('fecha', ''),
                'Vendedor': sol.get('vendedor', ''),
                'Negocio / Cliente': sol.get('negocio', ''),
                'Decisión': sol.get('decision_label', ''),
                'Cant. Solicitada': sol.get('cantidad_solicitada', sol.get('cantidad', 0)),
                'Cant. Aprobada': sol.get('cantidad_aprobada', 0),
                'Inversión USD': round(sol.get('total_usd', 0), 2),
                'Comentario': sol.get('descripcion', ''),
            })

    hojas = {
        'Resumen Subfamilias': filas_subfam,
        'Detalle SKUs': filas_skus,
        'Backlog Clientes': filas_backlog if filas_backlog else [{'Nota': 'Sin backlog'}],
        'Decisiones 1 a 1': filas_solicitudes if filas_solicitudes else [{'Nota': 'Sin decisiones registradas'}],
    }

    return respuesta_excel_multi(f'SOP_HIAB_Analisis_{hoy:%Y%m%d}.xlsx', hojas)
