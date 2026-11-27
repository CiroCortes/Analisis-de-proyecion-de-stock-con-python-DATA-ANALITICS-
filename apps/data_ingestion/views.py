import datetime
import os
import time

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_POST

from apps.data_ingestion.athena_client import athena_permitido, sync_datalake
from apps.data_ingestion.datalake_ingest import run_full_datalake_pipeline
from apps.data_ingestion.sync_runner import sync_manager
from apps.inventory.models import (
    ProductSKU,
    ProductionOrderMovement,
    SKUClassification,
    SalesOrderMovement,
    StockProjection,
)
from apps.inventory.stock_actual_models import StockActual

# Caché local en carpeta data/ (refrescado automáticamente por Athena; carga manual por TXT OBSOLETA)
DATALAKE_FILES = [
    {
        'id': 'dl_maestro',
        'name': 'Maestro de Artículos & Costos (Datalake)',
        'filename': 'Maestro de Artículos & Costos.txt',
        'description': '20.500+ SKUs con costo unitario en USD, lead times y taxonomía viva SAP B1.',
        'target_model': 'ProductSKU',
    },
    {
        'id': 'dl_stock',
        'name': 'Stock Físico por Bodega (Datalake)',
        'filename': 'Stock Físico por Bodega.txt',
        'description': 'Stock físico, reservas y tránsitos en las 63 bodegas y ubicaciones SAP B1.',
        'target_model': 'StockActual & InventoryMetric',
    },
    {
        'id': 'dl_ofs',
        'name': 'Órdenes de Fabricación OF (Datalake)',
        'filename': 'Órdenes de Fabricación (OF).txt',
        'description': 'Consumos de taller en OFs cerradas + compromisos de fabricación abiertos.',
        'target_model': 'ProductionOrderMovement & Comp. OF',
    },
    {
        'id': 'dl_pedidos',
        'name': 'Pedidos de Clientes PC (Datalake)',
        'filename': 'Pedidos de Clientes (PC).txt',
        'description': 'Despachos históricos a clientes + compromisos comerciales abiertos.',
        'target_model': 'SalesOrderMovement & Comp. PC',
    },
    {
        'id': 'dl_ocs',
        'name': 'Órdenes de Compra en Tránsito OC (Datalake)',
        'filename': 'Órdenes de Compra en Tránsito (OC).txt',
        'description': 'Compras a proveedores en viaje (OC/FR) y fabricación en taller (OF).',
        'target_model': 'OCAbierta & InventoryMetric',
    },
    {
        'id': 'dl_scs',
        'name': 'Solicitudes de Compra SC (Datalake)',
        'filename': 'Solicitudes de Compra (SC).txt',
        'description': 'SC abiertas aún sin OC. Suman al Disponible Futuro.',
        'target_model': 'SC (InventoryMetric)',
        'optional': True,
    },
]


def _get_db_stats():
    """Única fuente de métricas de BD para la vista y el reporte de cierre del streaming."""
    return {
        'total_skus': ProductSKU.objects.count(),
        'total_ofs': ProductionOrderMovement.objects.count(),
        'total_pedidos': SalesOrderMovement.objects.count(),
        'total_clasificaciones': SKUClassification.objects.count(),
        'total_proyecciones': StockProjection.objects.count(),
        'total_stock_actual': StockActual.objects.count(),
    }


def _get_files_status(file_list, base_folder):
    """Escanea carpeta data/ y reporta estado del caché local TXT generado por Athena."""
    alt_mapping = {
        'Maestro de Artículos & Costos.txt': 'oitm.txt',
        'Stock Físico por Bodega.txt': 'oitw.txt',
        'Órdenes de Fabricación (OF).txt': 'owor_wor1.txt',
        'Pedidos de Clientes (PC).txt': 'ordr_rdr1.txt',
        'Órdenes de Compra en Tránsito (OC).txt': 'opor_por1.txt',
        'Solicitudes de Compra (SC).txt': 'oprq_prq1.txt',
    }
    files_info = []
    for f in file_list:
        full_path = os.path.join(base_folder, f['filename'])
        exists = os.path.exists(full_path)
        if f['filename'] in alt_mapping:
            alt_path = os.path.join(base_folder, alt_mapping[f['filename']])
            if os.path.exists(alt_path):
                if not exists or os.path.getmtime(alt_path) > os.path.getmtime(full_path):
                    full_path = alt_path
                    exists = True
        size_mb = 0.0
        mod_time_str = 'No disponible'

        if exists:
            stat = os.stat(full_path)
            size_mb = round(stat.st_size / (1024 * 1024), 2)
            mod_time_str = datetime.datetime.fromtimestamp(stat.st_mtime).strftime('%d/%m/%Y %H:%M:%S')

        files_info.append({
            **f,
            'exists': exists,
            'size_mb': size_mb,
            'mod_time': mod_time_str,
            'full_path': full_path,
        })
    return files_info


@login_required
def upload_view(request):
    """Centro de Control y Sincronización Oficial desde AWS Athena (Datalake Pesco).

    NOTA: La sincronización manual por TXT (action='sync_datalake') quedó OBSOLETA y se
    eliminó de la interfaz. Los archivos en data/ actúan únicamente como caché intermedio
    que Athena regenera automáticamente en cada corrida.
    """
    data_dir = os.path.join(settings.BASE_DIR, 'data')

    if request.method == 'POST':
        action = request.POST.get('action', 'sync_athena')
        t0 = time.time()

        try:
            if action == 'sync_athena':
                if not athena_permitido(request.user):
                    messages.error(request, 'La conexión directa a Athena solo está disponible en modo DEBUG para administradores.')
                    return redirect('data_ingestion:upload')
                sync_datalake(log=lambda *_: None)
                run_full_datalake_pipeline()
                dt = round(time.time() - t0, 1)
                messages.success(request, f'Sincronización desde AWS Athena completada en {dt} segundos. Base de datos, Calculadora y S&OP Equipos actualizados.')

            elif action == 'sync_datalake':
                # OBSOLETO (legacy TXT): mantenido solo como respaldo técnico; botón eliminado de la UI.
                run_full_datalake_pipeline()
                dt = round(time.time() - t0, 1)
                messages.info(request, f'[Legacy TXT] Ingesta local completada en {dt} segundos.')

            elif action == 'sync_engine':
                from apps.calculadora.servicio import recalcular_red
                recalcular_red(usuario=request.user)
                dt = round(time.time() - t0, 1)
                messages.success(request, f'Motor S&OP y Calculadora recalculados en {dt} segundos.')

            else:
                messages.error(request, f'Acción desconocida: {action}')

        except Exception as e:
            messages.error(request, f'Error durante la sincronización: {str(e)}')

        return redirect('data_ingestion:upload')

    datalake_status = _get_files_status(DATALAKE_FILES, data_dir)
    context = {
        'datalake_status': datalake_status,
        'all_datalake_exist': all(f['exists'] for f in datalake_status if not f.get('optional')),
        'db_stats': _get_db_stats(),
        'puede_athena': athena_permitido(request.user),
        'sync_en_curso': sync_manager.snapshot().get('status') == 'running',
    }
    return render(request, 'data_ingestion/upload.html', context)


@login_required
@require_POST
def sync_athena_start(request):
    """Inicia la sincronización en vivo (Athena -> data/ -> BD -> S&OP) en segundo plano."""
    if not athena_permitido(request.user):
        return JsonResponse(
            {'error': 'La conexión directa a Athena solo está disponible en modo DEBUG para administradores.'},
            status=403,
        )
    payload = sync_manager.start(
        sync_fn=sync_datalake,
        ingest_fn=run_full_datalake_pipeline,
        stats_fn=_get_db_stats,
    )
    return JsonResponse(payload)


@login_required
@require_GET
def sync_athena_status(request):
    """Devuelve el progreso, fase actual y líneas nuevas de la terminal en vivo."""
    if not athena_permitido(request.user):
        return JsonResponse({'error': 'No autorizado.'}, status=403)
    try:
        since = max(0, int(request.GET.get('since', 0)))
    except (ValueError, TypeError):
        since = 0
    return JsonResponse(sync_manager.snapshot(since=since))
