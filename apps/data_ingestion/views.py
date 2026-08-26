import os
import time
import datetime
from django.shortcuts import render, redirect
from django.contrib import messages
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.conf import settings

from apps.inventory.models import (
    ProductSKU, Warehouse, InventoryMetric,
    StockProjection, ProductionOrderMovement,
    SalesOrderMovement, SKUClassification
)
from apps.data_ingestion.excel_parser import parse_and_ingest_excel
from apps.data_ingestion.historical_ingest import (
    ingest_maestro_articulos,
    ingest_detalle_ofs,
    ingest_detalle_pedidos
)
from apps.inventory.classification_engine import run_classification_engine

PIPELINE_FILES = [
    {
        'id': 'maestro',
        'name': 'Maestro de Artículos v7',
        'filename': '00.- Maestro Articulos v7.xlsx',
        'description': 'Catálogo maestro con 20.400+ SKUs, costos unitarios, taxonomía y fechas de creación SAP.',
        'target_model': 'ProductSKU (Catálogo)',
    },
    {
        'id': 'ofs',
        'name': 'Detalle OFs Cerradas (Producción)',
        'filename': 'Detalle OFs_v4.xlsx',
        'description': 'Historial de consumo real de componentes e insumos en taller/planta (solo OFs Cerradas).',
        'target_model': 'ProductionOrderMovement',
    },
    {
        'id': 'pedidos',
        'name': 'Detalle Pedidos Clientes (Ventas)',
        'filename': 'Detalle Pedidos Clientes 2023.xlsx',
        'description': 'Historial de despachos y salidas comerciales a clientes por sucursal (solo Cerrados).',
        'target_model': 'SalesOrderMovement',
    },
    {
        'id': 'stock_proyectado',
        'name': 'Stock Proyectado & Bodegas SAP',
        'filename': '0. Stock Proyectado.xlsx',
        'description': 'Disponibilidad física, compromisos abiertos y ROP por las 9 bodegas operativas.',
        'target_model': 'StockProjection & InventoryMetric',
    },
    {
        'id': 'stock_actual',
        'name': 'Stock Físico & Tránsitos Inter-Sucursal',
        'filename': '00.- Stock.xlsx',
        'description': 'Inventario físico actualizado en las 56 ubicaciones SAP y bodegas en tránsito (T*).',
        'target_model': 'StockActual (Tránsitos T*)',
    },
]


def _get_files_status():
    """Escanea el directorio raíz y obtiene el estado de cada archivo del pipeline."""
    base_dir = settings.BASE_DIR
    files_info = []

    for f in PIPELINE_FILES:
        full_path = os.path.join(base_dir, f['filename'])
        exists = os.path.exists(full_path)
        size_mb = 0.0
        mod_time_str = 'No disponible'

        if exists:
            stat = os.stat(full_path)
            size_mb = round(stat.st_size / (1024 * 1024), 2)
            mod_time = datetime.datetime.fromtimestamp(stat.st_mtime)
            mod_time_str = mod_time.strftime('%d/%m/%Y %H:%M:%S')

        files_info.append({
            **f,
            'exists': exists,
            'size_mb': size_mb,
            'mod_time': mod_time_str,
            'full_path': full_path,
        })

    return files_info


@login_required
def upload_excel_view(request):
    """
    Centro de Control y Sincronización Directa de Datos S&OP.
    Consume los archivos directamente desde el directorio raíz sin necesidad de subida web.
    Preparado para conexión directa a SAP en el futuro.
    """
    if request.method == 'POST':
        action = request.POST.get('action', 'sync_all')
        base_dir = settings.BASE_DIR
        t0 = time.time()

        try:
            if action == 'sync_all' or action == 'sync_maestro':
                path = os.path.join(base_dir, '00.- Maestro Articulos v7.xlsx')
                if os.path.exists(path):
                    ingest_maestro_articulos(path)

            if action == 'sync_all' or action == 'sync_ofs':
                path = os.path.join(base_dir, 'Detalle OFs_v4.xlsx')
                if os.path.exists(path):
                    ingest_detalle_ofs(path)

            if action == 'sync_all' or action == 'sync_pedidos':
                path = os.path.join(base_dir, 'Detalle Pedidos Clientes 2023.xlsx')
                if os.path.exists(path):
                    ingest_detalle_pedidos(path)

            if action == 'sync_all' or action == 'sync_stock':
                path = os.path.join(base_dir, '0. Stock Proyectado.xlsx')
                if os.path.exists(path):
                    parse_and_ingest_excel(path)

            if action == 'sync_all' or action == 'sync_engine':
                run_classification_engine()

            dt = round(time.time() - t0, 1)
            messages.success(request, f"¡Sincronización completada exitosamente en {dt} segundos! La base de datos y el motor S&OP han sido actualizados.")
        except Exception as e:
            messages.error(request, f"Error durante la sincronización: {str(e)}")

        return redirect('data_ingestion:upload')

    files_status = _get_files_status()

    # Métricas actuales en BD
    db_stats = {
        'total_skus': ProductSKU.objects.count(),
        'total_ofs': ProductionOrderMovement.objects.count(),
        'total_pedidos': SalesOrderMovement.objects.count(),
        'total_clasificaciones': SKUClassification.objects.count(),
        'total_proyecciones': StockProjection.objects.count(),
    }

    context = {
        'files_status': files_status,
        'db_stats': db_stats,
        'all_files_exist': all(f['exists'] for f in files_status),
    }
    return render(request, 'data_ingestion/upload.html', context)


@login_required
def progress_api_view(request):
    """Retorna el estado de sincronización."""
    return JsonResponse({"current": 100, "total": 100, "percent": 100, "status": "idle"})
