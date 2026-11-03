"""SPEC-36: lo que producen las OF abiertas cuenta como en camino; las OF antiguas se informan."""
import datetime
import tempfile

from django.test import SimpleTestCase, TestCase

from apps.calculadora import alertas
from apps.calculadora.cargadores import cargar_oc_abiertas
from apps.calculadora.models import Corrida, OCAbierta, ResultadoArticulo
from apps.calculadora.parametros import Resolutor
from apps.data_ingestion.athena_client import load_queries
from apps.data_ingestion.datalake_ingest import ingest_datalake_ocs, linea_cuenta
from apps.inventory.models import Category, ProductSKU

from .test_calculadora_servicio import _txt
from .test_spec35 import CABECERA

HOY = datetime.date.today()
RECIENTE = (HOY - datetime.timedelta(days=40)).isoformat()
ANTIGUA = '2023-08-17'


def _fila_of(numero, sku, emision, pendiente):
    return [numero, '013', sku, '', 'FABRICACION PROPIA', emision, emision, pendiente, pendiente, 'OF', numero]


class ConsultaTest(SimpleTestCase):
    def test_consulta_5_trae_el_producto_de_las_of(self):
        sql = next(s for a, s in load_queries() if a == 'Órdenes de Compra en Tránsito (OC).txt')
        self.assertIn('pesco_sbo_pescousd.owor w', sql)
        self.assertIn("'OF'", sql)
        self.assertEqual(sql.count('UNION ALL'), 2)

    def test_regla_de_vigencia(self):
        corte = datetime.date(2026, 5, 3)
        self.assertTrue(linea_cuenta(_fila_of('1', 'A', '2026-09-01', 1), corte))
        self.assertFalse(linea_cuenta(_fila_of('1', 'A', ANTIGUA, 1), corte))
        oc = ['2', '013', 'A', 'P1', 'PROV', ANTIGUA, ANTIGUA, 1, 1, 'OC', '2']
        self.assertTrue(linea_cuenta(oc, corte))          # una OC antigua sigue contando (SPEC-33 la informa)


class CargaOFTest(TestCase):
    def setUp(self):
        cat = Category.objects.create(code='G1', name='RPTS', is_active=True, tipo='REPUESTO')
        for code, costo in (('36274821', 31217), ('32010492', 866)):
            ProductSKU.objects.create(code=code, description=code, category=cat, unit_cost_usd=costo)
        self.dir = tempfile.TemporaryDirectory()
        _txt(self.dir.name, 'Órdenes de Compra en Tránsito (OC).txt', CABECERA, [
            _fila_of('2,308,271', '36274821', ANTIGUA, 1),       # kit HIAB: OF de ago-2023 sin cerrar
            _fila_of('2,308,272', '36274821', ANTIGUA, 1),
            _fila_of('2,609,227', '32010492', RECIENTE, 70),     # butacas: fabricacion vigente
        ])

    def tearDown(self):
        self.dir.cleanup()

    def test_la_calculadora_guarda_todas_y_marca_las_antiguas(self):
        self.assertEqual(cargar_oc_abiertas(self.dir.name), 3)
        vigentes = OCAbierta.objects.filter(tipo_documento='OF', cuenta=True)
        self.assertEqual(list(vigentes.values_list('product_id', 'cantidad_pendiente')), [('32010492', 70)])
        self.assertEqual(OCAbierta.objects.filter(cuenta=False).count(), 2)
        self.assertEqual(OCAbierta.objects.get(nro_oc='2609227').bodega, '013-PP')

    def test_el_transito_por_bodega_no_suma_las_antiguas(self):
        import os
        mapa = ingest_datalake_ocs(os.path.join(self.dir.name, 'Órdenes de Compra en Tránsito (OC).txt'))
        self.assertEqual(dict(mapa), {('32010492', '013-PP'): 70})

    def test_alerta_of_antigua(self):
        cargar_oc_abiertas(self.dir.name)
        corrida = Corrida.objects.create(fecha_calculo=HOY)
        ResultadoArticulo.objects.create(corrida=corrida, product_id='36274821', letra='R', costo_unitario=31217,
                                         necesita_compra=True)
        ResultadoArticulo.objects.create(corrida=corrida, product_id='32010492', letra='R', costo_unitario=866)
        out = {sku: (sev, msg) for sku, sev, msg in alertas.ofs_antiguas(corrida, HOY, Resolutor().general)}
        self.assertEqual(list(out), ['36274821'])
        sev, msg = out['36274821']
        self.assertEqual(sev, alertas.MEDIA)
        self.assertIn('2 u en 2 OF', msg)
        self.assertIn('OF 2308271', msg)
