"""Prueba minima del Service Layer (SPEC-30): Login, 3 lecturas chicas y Logout.

Solo lectura y solo la base de pruebas por defecto. Correr desde la red de Pesco:
    python manage.py sl_probar
"""
from django.core.management.base import BaseCommand, CommandError

from apps.data_ingestion.service_layer import ClienteServiceLayer, Config, ErrorServiceLayer


class Command(BaseCommand):
    help = 'Prueba la conexion al Service Layer con 3 lecturas chicas (solo lectura).'

    def handle(self, *args, **opts):
        try:
            cfg = Config.desde_env()
            cfg.max_peticiones = 5                     # Login + 3 lecturas + margen
            self.stdout.write(f'Service Layer: {cfg.url} · base {cfg.base} · usuario {cfg.usuario}')
            with ClienteServiceLayer(cfg) as sl:
                self.stdout.write(self.style.SUCCESS('Login correcto.'))
                bodegas = list(sl.leer('Warehouses', select='WarehouseCode,WarehouseName', maximo=5))
                self.stdout.write('Bodegas (5): ' + ', '.join(b['WarehouseCode'] for b in bodegas))
                art = list(sl.leer('Items', select='ItemCode,ItemName', maximo=3))
                self.stdout.write('Articulos (3): ' + ', '.join(a['ItemCode'] for a in art))
                abiertas = sl.contar('PurchaseOrders', filtro="DocumentStatus eq 'bost_Open'")
                self.stdout.write(f'OC abiertas en la base: {abiertas}')
            self.stdout.write(self.style.SUCCESS(f'Logout correcto. {sl.stats.resumen()}'))
            for ruta, seg, estado in sl.stats.detalle:
                self.stdout.write(f'  {ruta:<35} {seg:>6.2f} s  {estado}')
        except ErrorServiceLayer as e:
            raise CommandError(str(e))
