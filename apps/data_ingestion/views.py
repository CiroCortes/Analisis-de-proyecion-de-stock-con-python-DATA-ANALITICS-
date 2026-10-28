import os
import time
import datetime
from django.shortcuts import render, redirect
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.conf import settings

from apps.inventory.models import (
    ProductSKU, StockProjection, ProductionOrderMovement,
    SalesOrderMovement, SKUClassification
)
from apps.inventory.stock_actual_models import StockActual
from apps.data_ingestion.datalake_ingest import run_full_datalake_pipeline

DATALAKE_FILES = [
    {
        'id': 'dl_maestro',
        'name': 'Maestro de Artículos & Costos (Datalake)',
        'filename': 'Maestro de Artículos & Costos.txt',
        'description': '20.500+ SKUs con costo unitario promedio en USD, lead times y taxonomía viva SAP B1.',
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
        'description': 'Compras a proveedores en viaje con fecha de entrega para evitar duplicados.',
        'target_model': 'OC Tránsito (InventoryMetric)',
    },
    {
        'id': 'dl_scs',
        'name': 'Solicitudes de Compra SC (Datalake)',
        'filename': 'Solicitudes de Compra (SC).txt',
        'description': 'SC abiertas aún sin OC. Suman al Disponible Futuro (consulta 6 de data/consultas_datalake.sql). Si falta, SC = 0.',
        'target_model': 'SC (InventoryMetric)',
        'optional': True,
    },
]


def _get_files_status(file_list, base_folder):
    """Escanea un directorio y obtiene el estado de cada archivo."""
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
def upload_view(request):
    """
    Centro de Control y Sincronización de Datos S&OP.
    La única fuente de datos es el Datalake (archivos TXT exportados de Athena/SAP B1 en /data).
    """
    data_dir = os.path.join(settings.BASE_DIR, 'data')

    if request.method == 'POST':
        action = request.POST.get('action', 'sync_datalake')
        t0 = time.time()

        try:
            if action == 'sync_datalake':
                run_full_datalake_pipeline()
                dt = round(time.time() - t0, 1)
                messages.success(request, f"¡Sincronización oficial desde Datalake (TXT) completada con éxito en {dt} segundos! Base de datos y motor S&OP actualizados.")

            elif action == 'sync_engine':
                from apps.calculadora.servicio import recalcular_red
                recalcular_red(usuario=request.user)
                dt = round(time.time() - t0, 1)
                messages.success(request, f"Motor S&OP y Calculadora recalculados en {dt} segundos.")

            else:
                messages.error(request, f"Acción desconocida: {action}")

        except Exception as e:
            messages.error(request, f"Error durante la sincronización: {str(e)}")

        return redirect('data_ingestion:upload')

    datalake_status = _get_files_status(DATALAKE_FILES, data_dir)

    # Métricas actuales en BD
    db_stats = {
        'total_skus': ProductSKU.objects.count(),
        'total_ofs': ProductionOrderMovement.objects.count(),
        'total_pedidos': SalesOrderMovement.objects.count(),
        'total_clasificaciones': SKUClassification.objects.count(),
        'total_proyecciones': StockProjection.objects.count(),
        'total_stock_actual': StockActual.objects.count(),
    }

    context = {
        'datalake_status': datalake_status,
        'all_datalake_exist': all(f['exists'] for f in datalake_status if not f.get('optional')),
        'db_stats': db_stats,
    }
    return render(request, 'data_ingestion/upload.html', context)
