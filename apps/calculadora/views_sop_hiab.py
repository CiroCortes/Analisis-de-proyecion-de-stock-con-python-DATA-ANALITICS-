"""Vistas para el Panel S&OP Equipos (Todas las Marcas) y Mesa de Negociación 1 a 1."""
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from . import sop_equipos, sop_equipos_io
from .excel import respuesta_excel_multi
from .models import PresupuestoSOP, PropuestaCompraSOP


def _leer_filtros(request):
    """Lee y normaliza los filtros de alcance y búsqueda desde GET o POST."""
    src = request.GET if request.method == 'GET' else request.POST
    return {
        'grupo': src.get('grupo', '').strip(),
        'marca': src.get('marca', '').strip(),
        'semaforo': src.get('semaforo', '').strip(),
        'q': src.get('q', '').strip(),
    }


def _url_retorno(filtros, extra=None, anchor=''):
    """Construye la URL de retorno preservando filtros activos de Grupo/Marca/Semáforo."""
    params = {k: v for k, v in filtros.items() if v}
    if extra:
        params.update({k: v for k, v in extra.items() if v not in ('', None)})
    base = reverse('calculadora:sop_hiab')
    qs = f'?{urlencode(params)}' if params else ''
    frag = f'#{anchor}' if anchor else ''
    return f'{base}{qs}{frag}'


def _parse_int(val, default=0, minimo=0):
    try:
        return max(minimo, int(val or 0))
    except (ValueError, TypeError):
        return default


def _parse_float(val, default=0.0, minimo=0.0):
    try:
        return max(minimo, float(val or 0))
    except (ValueError, TypeError):
        return default


def _filtrar_modelos(subfamilias, f_semaforo, f_search):
    q = f_search.lower()
    out = []
    for sf in subfamilias:
        if f_semaforo and sf['semaforo'] != f_semaforo:
            continue
        if q:
            match_txt = (
                q in sf['modelo'].lower()
                or q in sf['nombre'].lower()
                or q in sf['marca_label'].lower()
                or q in sf['grupo_sap'].lower()
                or any(q in s['codigo'].lower() or q in s['descripcion'].lower() for s in sf['skus'])
            )
            if not match_txt:
                continue
        out.append(sf)
    return out


def _serializar_modelo_js(sf):
    """Payload compacto por modelo para el selector multimodelo en cliente."""
    return {
        'clave': sf['clave'],
        'modelo': sf['modelo'],
        'familia': sf['familia'],
        'subfamilia_code': sf['subfamilia_code'],
        'marca_label': sf['marca_label'],
        'grupo_sap': sf['grupo_sap'],
        'nombre': sf['nombre'],
        'inv_libre_cant': sf['inv_libre_cant'],
        'semaforo': sf['semaforo'],
        'semaforo_label': sf['semaforo_label'],
    }


@login_required
def sop_hiab_view(request):
    """Vista principal S&OP Equipos (Todas las Marcas) y Mesa de Negociación 1 a 1."""
    filtros = _leer_filtros(request)
    data = sop_equipos.get_sop_equipos_data(grupo=filtros['grupo'], marca=filtros['marca'])
    if not data.get('hay_datos'):
        return render(request, 'calculadora/sop_hiab.html', {
            'hay_datos': False,
            'error': data.get('error'),
        })

    todas = data['subfamilias']
    filtradas = _filtrar_modelos(todas, filtros['semaforo'], filtros['q'])

    # Modelo(s) activo(s) para el Simulador 1 a 1 (por defecto: Consolidado Total de todas las marcas)
    selected_raw = request.GET.get('sim_subfam', '').strip()
    if not selected_raw or selected_raw.upper() in ('TODOS', 'ALL', 'CONSOLIDADO'):
        modelos_sel = filtradas or todas
        is_consolidado_total = True
    else:
        modelos_sel = sop_equipos.resolver_modelos_multi(data, selected_raw)
        if not modelos_sel:
            modelos_sel = filtradas or todas
            is_consolidado_total = True
        else:
            is_consolidado_total = False

    active_sf = sop_equipos.consolidar_modelos(modelos_sel, alcance_label=data['alcance_label']) if modelos_sel else None
    sim_cant = _parse_int(request.GET.get('sim_cant'), default=0 if is_consolidado_total else 2)
    simulacion = sop_equipos.evaluar_simulacion(active_sf, sim_cant) if active_sf else None

    subfamilias_map = {sf['clave']: _serializar_modelo_js(sf) for sf in todas}
    selected_keys = [] if is_consolidado_total else [m['clave'] for m in modelos_sel]

    alcance_params = {k: v for k, v in (('grupo', filtros['grupo']), ('marca', filtros['marca'])) if v}
    alcance_qs = f'?{urlencode(alcance_params)}' if alcance_params else ''

    context = {
        'hay_datos': True,
        'fuente': data['fuente'],
        'fecha_sync': data['fecha_sync'],
        'anio_ref': data['anio_ref'],
        'ultimo_mes_consumo': data.get('ultimo_mes_consumo'),
        'catalogo': data['catalogo'],
        'alcance_label': data['alcance_label'],
        'alcance_qs': alcance_qs,
        'skus_sin_modelo': data['skus_sin_modelo'],
        'backlog_antiguos_excluidos': data['backlog_antiguos_excluidos'],
        'kpis': data['kpis'],
        'subfamilias': filtradas,
        'todas_subfamilias': todas,
        'total_filtradas': len(filtradas),
        'subfamilias_map': subfamilias_map,
        'selected_keys': selected_keys,
        'is_consolidado_total': is_consolidado_total,
        'active_sf': active_sf,
        'simulacion': simulacion,
        'propuestas_recientes': data['propuestas_recientes'],
        'decision_choices': PropuestaCompraSOP.DECISIONES,
        'f_grupo': filtros['grupo'],
        'f_marca': filtros['marca'],
        'f_semaforo': filtros['semaforo'],
        'f_search': filtros['q'],
        'total_subfamilias': len(todas),
        'total_filtradas': len(filtradas),
        'total_skus': data['total_skus'],
    }
    return render(request, 'calculadora/sop_hiab.html', context)


@login_required
def sop_hiab_simular_api(request):
    """Endpoint JSON — fuente única de verdad para el Simulador 1 a 1 (single y multimodelo)."""
    clave = request.GET.get('subfamilia', '').strip()
    cant = _parse_int(request.GET.get('cantidad'), default=0)
    grupo = request.GET.get('grupo', '').strip()
    marca = request.GET.get('marca', '').strip()
    res = sop_equipos.simular_propuesta_compra(clave, cant, grupo=grupo, marca=marca)
    status = 404 if res.get('error') else 200
    return JsonResponse(res, status=status)


def _resolver_triplet_modelo(request):
    """Extrae (familia, subfamilia, modelo, clave_principal, claves_csv) desde POST."""
    claves_csv = request.POST.get('clave_modelo', '').strip()
    primera = claves_csv.split(',')[0].strip() if claves_csv else ''
    parsed = sop_equipos.ClaveModelo.parse(primera)
    if parsed:
        return parsed.familia, parsed.subfamilia, parsed.modelo, parsed.to_key(), claves_csv
    familia = request.POST.get('familia', '').strip()
    subfamilia = request.POST.get('subfamilia', '').strip()
    modelo = request.POST.get('modelo', '').strip()
    clave = sop_equipos.ClaveModelo(familia, subfamilia, modelo).to_key() if (familia or subfamilia) else modelo
    return familia, subfamilia, modelo, clave, (claves_csv or clave)


@login_required
@require_POST
def sop_hiab_guardar_decision(request):
    """Registra una decisión de la reunión 1 a 1 en BD (soporta trazabilidad multimodelo)."""
    filtros = _leer_filtros(request)
    familia, subfamilia, modelo, clave_principal, claves_csv = _resolver_triplet_modelo(request)
    vendedor = request.POST.get('vendedor', '').strip()
    negocio = request.POST.get('negocio', '').strip()
    decision = request.POST.get('decision', PropuestaCompraSOP.PENDIENTE).strip()
    comentario = request.POST.get('comentario', '').strip()
    cant_sol = _parse_int(request.POST.get('cantidad_solicitada'), default=0)
    cant_apr = _parse_int(request.POST.get('cantidad_aprobada'), default=0)

    if not modelo or modelo.upper() in ('TODOS', 'ALL', 'CONSOLIDADO') or modelo.startswith('Consolidado'):
        messages.warning(request, 'Para registrar una decisión en la bitácora comercial, selecciona un modelo específico en el evaluador.')
        return redirect(_url_retorno(filtros))

    if decision == PropuestaCompraSOP.APROBADA and cant_apr == 0:
        cant_apr = cant_sol
    elif decision in (PropuestaCompraSOP.REFUTADA, PropuestaCompraSOP.POSTERGADA):
        cant_apr = 0

    cant_eval = cant_apr if decision in (PropuestaCompraSOP.APROBADA, PropuestaCompraSOP.PARCIAL) else cant_sol
    sim = sop_equipos.simular_propuesta_compra(claves_csv, cant_eval)

    if not sim.get('error'):
        familia = familia or sim.get('familia', '')
        subfamilia = subfamilia or sim.get('marca_code', '')
        if sim.get('es_multimodelo'):
            traza = f"[Consolidado multimodelo: {sim['modelo_display']}]"
            comentario = f'{traza} {comentario}'.strip() if comentario else traza

    PropuestaCompraSOP.objects.create(
        familia=familia,
        subfamilia=subfamilia,
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
    return redirect(_url_retorno(filtros, extra={'sim_subfam': claves_csv, 'sim_cant': cant_sol}, anchor='historial-decisiones'))


@login_required
@require_POST
def sop_hiab_eliminar_decision(request, pk):
    """Elimina una decisión 1 a 1 registrada por error."""
    filtros = _leer_filtros(request)
    obj = get_object_or_404(PropuestaCompraSOP, pk=pk)
    obj.delete()
    messages.info(request, 'Registro de decisión eliminado.')
    return redirect(_url_retorno(filtros, anchor='historial-decisiones'))


@login_required
@require_POST
def sop_hiab_rechazar_decision(request, pk):
    """Marca una propuesta/decisión como Rechazada (Refutada) conservando su trazabilidad histórica."""
    filtros = _leer_filtros(request)
    propuesta = get_object_or_404(PropuestaCompraSOP, pk=pk)
    if propuesta.solicitud_compra_id:
        messages.error(request, f'Esta decisión ya tiene la SC #{propuesta.solicitud_compra_id} generada; descártala desde Solicitudes.')
        return redirect(_url_retorno(filtros, anchor='historial-decisiones'))
    propuesta.decision = PropuestaCompraSOP.REFUTADA
    propuesta.cantidad_aprobada = 0
    propuesta.save(update_fields=['decision', 'cantidad_aprobada', 'actualizado_en'])
    messages.info(request, f'Propuesta del Modelo SAP {propuesta.modelo} marcada como Refutada / Rechazada.')
    return redirect(_url_retorno(filtros, anchor='historial-decisiones'))


@login_required
@require_POST
def sop_hiab_generar_sc(request, pk):
    """Genera una Solicitud de Compra oficial (SolicitudCompra + LineaSolicitud) desde la Bitácora 1 a 1."""
    filtros = _leer_filtros(request)
    propuesta = get_object_or_404(PropuestaCompraSOP, pk=pk)
    try:
        sc = sop_equipos.generar_solicitud_compra_desde_propuesta(propuesta, usuario=request.user)
        messages.success(request, f'Solicitud de Compra SC #{sc.pk} creada en borrador. Puedes revisarla, aprobarla y exportarla a SAP.')
        return redirect('calculadora:solicitud_detalle', pk=sc.pk)
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect(_url_retorno(filtros, anchor='historial-decisiones'))


@login_required
@require_POST
def sop_hiab_guardar_presupuesto(request):
    """Guarda o actualiza el presupuesto anual de un Modelo SAP."""
    filtros = _leer_filtros(request)
    familia, subfamilia, modelo, _, _ = _resolver_triplet_modelo(request)
    anio = _parse_int(request.POST.get('anio'), default=timezone.localdate().year, minimo=2020)
    cantidad = _parse_float(request.POST.get('cantidad'), default=0.0)
    monto_usd = _parse_float(request.POST.get('monto_usd'), default=0.0)

    if not modelo:
        messages.error(request, 'Modelo SAP inválido para presupuesto.')
        return redirect(_url_retorno(filtros, anchor='matriz-consolidada'))

    PresupuestoSOP.objects.update_or_create(
        anio=anio,
        familia=familia,
        subfamilia=subfamilia,
        modelo=modelo,
        defaults={
            'cantidad': cantidad,
            'monto_usd': monto_usd,
            'actualizado_por': request.user,
        },
    )
    messages.success(request, f'Presupuesto {anio} guardado para Modelo SAP {modelo}.')
    return redirect(_url_retorno(filtros, anchor='matriz-consolidada'))


@login_required
@require_POST
def sop_hiab_importar_excel(request):
    """Importación opcional desde Excel hacia PresupuestoSOP (puente inicial de migración)."""
    filtros = _leer_filtros(request)
    anio = _parse_int(request.POST.get('anio'), default=timezone.localdate().year, minimo=2020)
    archivo = request.FILES.get('archivo_excel')
    if not archivo:
        messages.error(request, 'Seleccione un archivo .xlsx para importar.')
        return redirect(_url_retorno(filtros))

    res = sop_equipos_io.importar_presupuesto_excel(archivo, anio=anio, user=request.user)
    if res.get('error'):
        messages.error(request, res['error'])
    else:
        aviso_extra = ''
        if res.get('no_encontrados'):
            aviso_extra += f" ({len(res['no_encontrados'])} códigos no existen en SAP)"
        if res.get('sin_modelo'):
            aviso_extra += f" ({len(res['sin_modelo'])} códigos sin u_rhmodelo en SAP)"
        messages.success(
            request,
            f"Presupuesto importado desde '{res['hoja']}': {res['modelos_importados']} modelos · {res['total_unidades']} un · ${res['total_usd']:,.0f} USD.{aviso_extra}",
        )
    return redirect(_url_retorno(filtros, anchor='matriz-consolidada'))


@login_required
def sop_hiab_excel(request):
    """Exporta el acta S&OP Equipos a Excel multi-pestaña respetando el filtro Grupo/Marca activo."""
    filtros = _leer_filtros(request)
    data = sop_equipos.get_sop_equipos_data(grupo=filtros['grupo'], marca=filtros['marca'])
    if not data.get('hay_datos'):
        return HttpResponse('No hay datos para exportar', status=400)

    hoy = timezone.localdate()

    filas_modelos = [{
        'Grupo SAP': sf['grupo_sap'],
        'Marca (Subfam SAP)': f"{sf['marca_label']} ({sf['subfamilia_code']})",
        'Modelo SAP': sf['modelo'],
        'Descripción Representativa': sf['nombre'],
        'Stock Físico (u)': sf['stock_cant'],
        'Stock Físico (USD)': round(sf['stock_usd'], 2),
        'Tránsito Real FR (u)': sf['tr_real_cant'],
        'Tránsito Proy OC (u)': sf['tr_proj_cant'],
        'En Taller OF (u)': sf['en_proceso_cant'],
        'Inventario Inicial (u)': sf['inv_inicial_cant'],
        'Backlog Comprometido (u)': sf['backlog_cant'],
        'Backlog (USD)': round(sf['backlog_usd'], 2),
        'Inventario Disponible (u)': sf['inv_libre_cant'],
        'Ventas L12M (u)': sf['ent_12m_cant'],
        f"Ventas {data['anio_ref']} YTD (u)": sf['ent_2026_cant'],
        f"Presupuesto {data['anio_ref']} (u)": sf['presup_cant'],
        'Ritmo Mensual (u/m)': sf['ritmo_mensual'],
        'Cobertura (meses)': sf['cobertura_meses'] if sf['cobertura_meses'] < sop_equipos.COBERTURA_SIN_VENTA else 'Sin ventas',
        'Estado Semáforo': sf['semaforo_label'],
        'Propuesta Compra (u)': sf['solic_cant'],
        'Costo Unitario Compra (USD)': sf['costo_unitario_compra'],
    } for sf in data['subfamilias']]

    filas_skus = [{
        'Código SKU': s['codigo'],
        'Origen': s['origen'],
        'Grupo SAP': s['grupo_sap'],
        'Marca (Subfam SAP)': f"{s['marca_label']} ({s['marca_code']})",
        'Modelo SAP': s['subfamilia'],
        'Descripción': s['descripcion'],
        'Sobre Camión': s['sobre_camion'],
        'Costo Unitario USD': round(s['costo_unitario'], 2),
        'Stock (u)': s['stock_cant'],
        'Stock (USD)': round(s['stock_usd'], 2),
        'Tránsito Real FR (u)': s['tr_real_cant'],
        'Tránsito Proy OC (u)': s['tr_proj_cant'],
        'Taller OF (u)': s['prod_cant'],
        'Backlog PC (u)': s['backlog_cant'],
        'Ventas L12M (u)': s['ent_12m_cant'],
        f"Ventas {data['anio_ref']} YTD (u)": s['ent_2026_cant'],
    } for s in data['skus_detalle']]

    filas_backlog = [{
        'Marca': sf['marca_label'],
        'Modelo SAP': sf['modelo'],
        'Código SKU': b['codigo'],
        'Descripción': b['descripcion'],
        'Cantidad (u)': b['cantidad'],
        'Total USD': round(b['total_usd'], 2),
        'Ejecutivo Responsable': b['ejecutivo'],
        'Fecha Emisión': b.get('fecha_emision', ''),
        'N° Pedido (PC)': b['pc'],
        'Cliente': b['cliente'],
    } for sf in data['subfamilias'] for b in sf['backlog_items']]

    filas_decisiones = [{
        'Fecha': pr.creado_en.strftime('%d-%m-%Y %H:%M'),
        'Familia SAP': pr.familia,
        'Subfam/Marca SAP': pr.subfamilia,
        'Modelo SAP': pr.modelo,
        'Equipo': pr.modelo_nombre,
        'Vendedor': pr.vendedor,
        'Negocio / Cliente': pr.negocio,
        'Decisión': pr.get_decision_display(),
        'Cant. Solicitada': pr.cantidad_solicitada,
        'Cant. Aprobada': pr.cantidad_aprobada,
        'Inversión USD': round(pr.inversion_usd, 2),
        'SC Generada': f'SC #{pr.solicitud_compra_id}' if pr.solicitud_compra_id else '—',
        'Comentario': pr.comentario,
    } for pr in data['propuestas_recientes']]

    filas_master_data = [{
        'Código SKU': m['codigo'],
        'Descripción': m['descripcion'],
        'Grupo SAP': m['grupo'],
        'Familia SAP': m['familia'],
        'Subfamilia SAP': m['subfamilia'],
        'Marca': m['marca'],
        'Acción Requerida': 'Asignar campo u_rhmodelo en Maestro SAP',
    } for m in data['skus_sin_modelo']]

    hojas = {
        'Resumen Modelos': filas_modelos if filas_modelos else [{'Nota': 'Sin modelos con actividad'}],
        'Detalle SKUs': filas_skus if filas_skus else [{'Nota': 'Sin SKUs'}],
        'Backlog Clientes': filas_backlog if filas_backlog else [{'Nota': 'Sin backlog abierto'}],
        'Decisiones 1 a 1': filas_decisiones if filas_decisiones else [{'Nota': 'Sin decisiones registradas'}],
        'Master Data Pendiente': filas_master_data if filas_master_data else [{'Nota': 'Todos los SKUs tienen modelo asignado en SAP'}],
    }

    sufijo = f"_{filtros['marca'] or filtros['grupo'] or 'Todas'}"
    return respuesta_excel_multi(f'SOP_Equipos{sufijo}_{hoy:%Y%m%d}.xlsx', hojas)
