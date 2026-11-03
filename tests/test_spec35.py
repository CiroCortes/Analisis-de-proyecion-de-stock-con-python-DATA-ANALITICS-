"""SPEC-35: importaciones en camino (factura de reserva) y proveedores extranjeros (sufijo PE)."""
import os
import re
import tempfile

from django.test import SimpleTestCase, TestCase

from apps.calculadora import analisis
from apps.calculadora.cargadores import cargar_oc_abiertas
from apps.calculadora.models import OCAbierta
from apps.data_ingestion.athena_client import load_queries
from apps.inventory.models import Category, ProductSKU, Warehouse

from .test_calculadora_servicio import _txt

CABECERA = ['nro_oc_sap', 'bodega_destino', 'codigo_sku', 'codigo_proveedor', 'nombre_proveedor', 'fecha_emision_oc',
            'fecha_llegada_estimada', 'cantidad_comprada', 'cantidad_en_transito_pendiente', 'tipo_documento',
            'nro_documento']


def _consulta(archivo):
    return next(sql for a, sql in load_queries() if a == archivo)


class ConsultasTest(SimpleTestCase):
    def test_consulta_5_incluye_importaciones(self):
        sql = _consulta('Órdenes de Compra en Tránsito (OC).txt')
        self.assertNotIn("'%PE'", sql)                   # PE = proveedor extranjero, no interno
        self.assertIn("fr.isins = 'Y'", sql)              # facturas de reserva de acreedores
        self.assertIn('gl.basetype = 18', sql)            # lo ya recibido desde la factura
        self.assertEqual(len(re.findall(r'\bAS tipo_documento\b', sql)), 2)

    def test_consulta_9_mide_el_plazo_de_las_importaciones(self):
        sql = _consulta('Plazos de Entrega OC.txt')
        self.assertIn('gl.basetype = 22', sql)
        self.assertIn('gl.basetype = 18', sql)
        self.assertIn('UNION ALL', sql)


class CargaFacturaReservaTest(TestCase):
    def setUp(self):
        cat = Category.objects.create(code='G1', name='RPTS', is_active=True, tipo='REPUESTO')
        self.sku = ProductSKU.objects.create(code='36274254', description='CILINDRO', category=cat, unit_cost_usd=3189)
        ProductSKU.objects.create(code='A2', description='Filtro', category=cat, unit_cost_usd=1)

    def _cargar(self, filas):
        with tempfile.TemporaryDirectory() as d:
            _txt(d, 'Órdenes de Compra en Tránsito (OC).txt', CABECERA, filas)
            return cargar_oc_abiertas(d)

    def test_factura_de_reserva_cuenta_como_en_camino(self):
        n = self._cargar([
            ['2,610,008', '000-022', '36274254', '0000000370PE', 'HIAB FINLAND OY', '2026-10-01', '2026-11-15', 1, 1,
             'FR', '74,500'],
            ['2,610,100', '013', 'A2', '76000000P', 'NACIONAL', '2026-10-20', '2026-10-27', 5, 5, 'OC', '2,610,100'],
        ])
        self.assertEqual(n, 2)
        fr = OCAbierta.objects.get(product_id='36274254')
        self.assertEqual((fr.nro_oc, fr.tipo_documento, fr.nro_documento), ('2610008', 'FR', '74500'))
        self.assertEqual((fr.bodega, fr.bodega_sap), ('002-02', '000-022'))   # pre-bodega -> destino
        self.assertEqual(OCAbierta.objects.get(product_id='A2').tipo_documento, 'OC')

    def test_archivo_antiguo_de_9_columnas(self):
        self._cargar([['2,610,100', '013', 'A2', '76000000P', 'NACIONAL', '2026-10-20', '2026-10-27', 5, 5]])
        oc = OCAbierta.objects.get()
        self.assertEqual((oc.tipo_documento, oc.nro_documento), ('OC', '2610100'))


class AnalizarSinAvisoTest(TestCase):
    def test_lo_pedido_en_la_pre_bodega_queda_cubierto(self):
        from apps.inventory.stock_actual_models import StockActual
        cat = Category.objects.create(code='G1', name='RPTS', is_active=True, tipo='REPUESTO')
        sku = ProductSKU.objects.create(code='36274254', description='CILINDRO', category=cat, unit_cost_usd=3189)
        Warehouse.objects.create(code='000-022', name='Pre-bodega Antofagasta', is_active=False)
        StockActual.objects.create(codigo='36274254', bodega='000-022', stock_disponible=0, stock_pedido=1)
        OCAbierta.objects.create(nro_oc='2610008', tipo_documento='FR', nro_documento='74500', product=sku,
                                 bodega='002-02', bodega_sap='000-022', cantidad_pendiente=1)
        d = analisis.bodegas_sap('36274254')
        fila = next(f for f in d['bodegas_sap'] if f['bodega'] == '000-022')
        self.assertEqual((fila['pedido_sap'], fila['oc'], fila['sin_oc']), (1, 1, 0))


class PlazoImportacionTest(TestCase):
    def test_entrada_a_pre_bodega_no_mide_plazo(self):
        """La entrada a una pre-bodega es el embarque: no sirve como plazo de entrega (SPEC-35 §3)."""
        from apps.calculadora.cargadores import cargar_plazos_oc
        from apps.calculadora.models import PlazoOC
        cat = Category.objects.create(code='G1', name='RPTS', is_active=True, tipo='REPUESTO')
        ProductSKU.objects.create(code='36274254', description='CILINDRO', category=cat, unit_cost_usd=3189)
        cab = ['nro_oc', 'codigo_sku', 'codigo_proveedor', 'bodega_oc', 'fecha_oc', 'fecha_comprometida', 'nro_entrada',
               'fecha_entrada', 'dias_entrega', 'cantidad_oc', 'cantidad_recibida']
        with tempfile.TemporaryDirectory() as d:
            _txt(d, 'Plazos de Entrega OC.txt', cab, [
                ['2,510,110', '36274254', '0000000370PE', '000-022', '2025-10-07', '2025-10-07', '1', '2025-10-22', 15, 1, 1],
                ['2,607,300', '36274254', '0000000370PE', '002-02', '2026-07-10', '2026-07-10', '2', '2026-10-09', 91, 1, 1],
            ])
            self.assertEqual(cargar_plazos_oc(d), 1)
        self.assertEqual(list(PlazoOC.objects.values_list('nro_oc', 'dias_entrega')), [('2607300', 91)])
