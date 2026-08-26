"""
Servicio de carga del Stock Actual de Bodegas.
Adaptado directamente de CiroCortes/sistemaPedidosPesco — inventario/services.py
Patrón: itertuples() + TRUNCATE + bulk_create en lotes para máxima velocidad.
"""
import time
import logging
from collections import defaultdict

import pandas as pd
from django.db import transaction, connection
from django.utils import timezone
from decimal import Decimal

from .stock_actual_models import StockActual, CargaStockActual

logger = logging.getLogger(__name__)

COLUMNAS_REQUERIDAS = ['Codigo', 'Descripcion', 'Cod.Bodega', 'Descripcion Bodega', 'Stock']


class StockActualService:
    """
    Servicio para procesar el archivo de Stock Actual de Bodegas (SAP).
    Columnas esperadas: Codigo, Descripcion, Cod.Grupo, Descripcion Grupo,
                        Cod.Bodega, Descripcion Bodega, Ubicacion, Ubicacion 2,
                        Stock, Stock Reservado, Precio $, Total $, Categoria
    """

    def procesar_archivo(self, archivo, usuario):
        inicio = time.time()
        carga = None

        try:
            carga = CargaStockActual(
                usuario=usuario if usuario.is_authenticated else None,
                nombre_archivo=archivo.name,
                estado='procesando',
            )
            carga.save()

            logger.info(f"[StockActual] Iniciando carga #{carga.id} — {archivo.name}")

            df = pd.read_excel(archivo)
            total_filas = len(df)

            self._validar_columnas(df)
            df = self._limpiar_datos(df)
            stock_objects = self._crear_objetos_stock(df)
            self._volcar_a_bd(stock_objects)

            # Actualizar precios en ProductSKU automáticamente
            skus_actualizados = self._sincronizar_precios_sku(stock_objects)

            tiempo = time.time() - inicio
            total_bodegas = df['Cod.Bodega'].nunique() if 'Cod.Bodega' in df.columns else 0

            carga.total_productos = df['Codigo'].nunique() if 'Codigo' in df.columns else total_filas
            carga.total_bodegas = total_bodegas
            carga.total_registros = len(stock_objects)
            carga.tiempo_proceso = tiempo
            carga.estado = 'completado'
            carga.save()

            return {
                'success': True,
                'registros': len(stock_objects),
                'productos': carga.total_productos,
                'bodegas': total_bodegas,
                'precios_sincronizados': skus_actualizados,
                'tiempo': tiempo,
                'mensaje': (
                    f'Se cargaron {len(stock_objects):,} registros '
                    f'({carga.total_productos:,} SKUs, {total_bodegas} bodegas) '
                    f'en {tiempo:.1f}s. '
                    f'Precios actualizados: {skus_actualizados} SKUs.'
                )
            }

        except Exception as e:
            logger.error(f"[StockActual] Error en carga: {e}", exc_info=True)
            if carga:
                carga.estado = 'error'
                carga.mensaje_error = str(e)
                carga.save()
            return {
                'success': False,
                'error': str(e),
                'mensaje': f'Error al procesar archivo: {str(e)}'
            }

    def _validar_columnas(self, df):
        faltantes = [c for c in COLUMNAS_REQUERIDAS if c not in df.columns]
        if faltantes:
            raise ValueError(f"Faltan columnas requeridas: {', '.join(faltantes)}")

    def _limpiar_datos(self, df):
        df = df.where(pd.notna(df), None)
        if 'Stock' in df.columns:
            df['Stock'] = pd.to_numeric(df['Stock'], errors='coerce').fillna(0)
        if 'Stock Reservado' in df.columns:
            df['Stock Reservado'] = pd.to_numeric(df['Stock Reservado'], errors='coerce').fillna(0)
        if 'Precio $' in df.columns:
            df['Precio $'] = pd.to_numeric(df['Precio $'], errors='coerce')
        if 'Total $' in df.columns:
            df['Total $'] = pd.to_numeric(df['Total $'], errors='coerce')
        return df

    def _crear_objetos_stock(self, df):
        """
        Agrupa por (Codigo, Cod.Bodega) usando itertuples() — patrón del repo original.
        Suma stock, concatena ubicaciones, mantiene precio del primer registro del grupo.
        """
        col_indices = {col: i for i, col in enumerate(df.columns)}
        grupos = defaultdict(lambda: {
            'stock_total': 0,
            'stock_reservado': 0,
            'ubicaciones': set(),
            'primera_fila': None
        })

        for row in df.itertuples(index=False, name=None):
            try:
                codigo = str(row[col_indices['Codigo']]).strip() if col_indices.get('Codigo') is not None else ''
                bodega = str(row[col_indices['Cod.Bodega']]).strip() if col_indices.get('Cod.Bodega') is not None else ''
                if not codigo or not bodega:
                    continue

                clave = (codigo, bodega)

                stock_val = 0
                if col_indices.get('Stock') is not None:
                    try:
                        v = row[col_indices['Stock']]
                        stock_val = float(v) if v is not None and not (isinstance(v, float) and v != v) else 0
                    except (ValueError, TypeError):
                        stock_val = 0

                reservado_val = 0
                if col_indices.get('Stock Reservado') is not None:
                    try:
                        v = row[col_indices['Stock Reservado']]
                        reservado_val = float(v) if v is not None and not (isinstance(v, float) and v != v) else 0
                    except (ValueError, TypeError):
                        reservado_val = 0

                if grupos[clave]['primera_fila'] is None:
                    grupos[clave]['primera_fila'] = row

                grupos[clave]['stock_total'] += stock_val
                grupos[clave]['stock_reservado'] += reservado_val

                if col_indices.get('Ubicacion') is not None:
                    ub = row[col_indices['Ubicacion']]
                    if ub is not None and str(ub).strip():
                        grupos[clave]['ubicaciones'].add(str(ub).strip())

            except Exception as e:
                logger.warning(f"[StockActual] Error fila: {e}")
                continue

        ahora = timezone.now()
        stock_objects = []

        for (codigo, bodega), datos in grupos.items():
            primera = datos['primera_fila']

            def get_val(col, max_len=None):
                idx = col_indices.get(col)
                if idx is None:
                    return None
                val = primera[idx]
                if val is None or (isinstance(val, float) and val != val):
                    return None
                s = str(val)
                return s[:max_len] if max_len else s

            def get_decimal(col):
                idx = col_indices.get(col)
                if idx is None:
                    return None
                val = primera[idx]
                if val is None or (isinstance(val, float) and val != val):
                    return None
                try:
                    return Decimal(str(val))
                except Exception:
                    return None

            ubicacion_str = ' / '.join(sorted(datos['ubicaciones']))[:100] if datos['ubicaciones'] else None

            obj = StockActual(
                codigo=codigo[:50],
                descripcion=get_val('Descripcion'),
                cod_grupo=int(float(primera[col_indices['Cod.Grupo']])) if col_indices.get('Cod.Grupo') is not None and primera[col_indices['Cod.Grupo']] is not None and not (isinstance(primera[col_indices['Cod.Grupo']], float) and primera[col_indices['Cod.Grupo']] != primera[col_indices['Cod.Grupo']]) else None,
                descripcion_grupo=get_val('Descripcion Grupo', 200),
                bodega=bodega[:20],
                bodega_nombre=get_val('Descripcion Bodega', 200),
                ubicacion=ubicacion_str,
                ubicacion_2=get_val('Ubicacion 2', 100),
                stock_disponible=int(datos['stock_total']),
                stock_reservado=int(datos['stock_reservado']),
                precio=get_decimal('Precio $'),
                total=get_decimal('Total $'),
                categoria=get_val('Categoria', 100),
                ultima_actualizacion=ahora,
            )
            stock_objects.append(obj)

        return stock_objects

    def _volcar_a_bd(self, stock_objects):
        """
        TRUNCATE + bulk_create en lotes — idéntico al patrón del repo original.
        Mucho más rápido que DELETE + insert uno a uno.
        """
        with transaction.atomic():
            StockActual.objects.all().delete()
            logger.info(f"[StockActual] Tabla vaciada. Insertando {len(stock_objects):,} registros...")

            batch_size = 1000
            insertados = 0
            for i in range(0, len(stock_objects), batch_size):
                batch = stock_objects[i:i + batch_size]
                StockActual.objects.bulk_create(batch, batch_size=batch_size, ignore_conflicts=False)
                insertados += len(batch)

            logger.info(f"[StockActual] {insertados:,} registros insertados.")

    def _sincronizar_precios_sku(self, stock_objects):
        """
        Después de cargar el stock actual, sincroniza los precios al módulo ProductSKU
        para que el quiebre en USD tenga valores reales.
        """
        from apps.inventory.models import ProductSKU, StockProjection

        # Construir mapa: código -> mejor precio (máximo precio no nulo)
        precio_map = {}
        for obj in stock_objects:
            if obj.precio and obj.precio > 0:
                if obj.codigo not in precio_map or obj.precio > precio_map[obj.codigo]:
                    precio_map[obj.codigo] = obj.precio

        if not precio_map:
            return 0

        # Actualizar ProductSKU con los precios del stock actual
        productos = ProductSKU.objects.filter(code__in=precio_map.keys())
        to_update = []
        for prod in productos:
            if prod.code in precio_map:
                prod.unit_cost_usd = precio_map[prod.code]
                to_update.append(prod)

        if to_update:
            with transaction.atomic():
                ProductSKU.objects.bulk_update(to_update, ['unit_cost_usd'], batch_size=2000)

                # Recalcular shortage_usd
                projs = []
                for prod in to_update:
                    for proj in StockProjection.objects.filter(product=prod):
                        proj.shortage_usd = Decimal(str(proj.shortage_units)) * prod.unit_cost_usd
                        projs.append(proj)
                if projs:
                    StockProjection.objects.bulk_update(projs, ['shortage_usd'], batch_size=5000)

        return len(to_update)
