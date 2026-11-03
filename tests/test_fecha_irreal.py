"""Pendiente #42: fecha comprometida irreal heredada de la SC (caso 35471214)."""
import datetime

from django.test import SimpleTestCase, TestCase

from apps.calc.proyeccion import fecha_llegada_oc
from apps.calculadora import alertas
from apps.calculadora.models import Corrida, OCAbierta, ResultadoArticulo
from apps.calculadora.parametros import Resolutor
from apps.inventory.models import Category, ProductSKU

D = datetime.date
HOY = D(2026, 11, 3)


class FechaLlegadaTest(SimpleTestCase):
    def test_importacion_que_promete_dos_dias(self):
        # OC 2610879 del 28-10 a HIAB, comprometida el 30-10, plazo de 70 dias -> se estima 06-01-2027
        self.assertEqual(fecha_llegada_oc(D(2026, 10, 28), D(2026, 10, 30), 70, 0.5), (D(2027, 1, 6), True))

    def test_fecha_razonable_se_respeta(self):
        self.assertEqual(fecha_llegada_oc(D(2026, 10, 1), D(2026, 11, 20), 70, 0.5), (D(2026, 11, 20), False))

    def test_fecha_anterior_a_la_oc(self):
        self.assertTrue(fecha_llegada_oc(D(2026, 8, 10), D(2026, 8, 4), 32, 0.5)[1])

    def test_desactivada_y_sin_datos(self):
        self.assertEqual(fecha_llegada_oc(D(2026, 10, 28), D(2026, 10, 30), 70, 0), (D(2026, 10, 30), False))
        self.assertEqual(fecha_llegada_oc(None, D(2026, 10, 30), 70, 0.5), (D(2026, 10, 30), False))
        self.assertEqual(fecha_llegada_oc(D(2026, 10, 28), None, 70, 0.5), (None, False))


class AlertaFechaIrrealTest(TestCase):
    def setUp(self):
        cat = Category.objects.create(code='G1', name='RPTS', is_active=True, tipo='REPUESTO')
        for code in ('35471214', 'NAC1'):
            ProductSKU.objects.create(code=code, description=code, category=cat, unit_cost_usd=1)
        self.corrida = Corrida.objects.create(fecha_calculo=HOY)
        ResultadoArticulo.objects.create(corrida=self.corrida, product_id='35471214', letra='P', dias_entrega_promedio=70)
        ResultadoArticulo.objects.create(corrida=self.corrida, product_id='NAC1', letra='R', dias_entrega_promedio=7)
        OCAbierta.objects.create(nro_oc='2610879', tipo_documento='FR', nro_documento='75825', product_id='35471214',
                                 bodega='013-PP', bodega_sap='000', proveedor_codigo='0000000370PE',
                                 fecha_oc=D(2026, 10, 28), fecha_comprometida=D(2026, 10, 30), cantidad_pendiente=6)
        # Nacional de 7 dias comprometida el mismo dia: se estima +7, pero no amerita alerta (< 15 dias)
        OCAbierta.objects.create(nro_oc='2610900', product_id='NAC1', bodega='013-PP', fecha_oc=D(2026, 10, 20),
                                 fecha_comprometida=D(2026, 10, 20), cantidad_pendiente=1)

    def test_avisa_a_compras(self):
        out = alertas.fechas_irreales(self.corrida, HOY, Resolutor().general)
        self.assertEqual([x[0] for x in out], ['35471214'])
        sku, sev, msg, prov = out[0]
        self.assertEqual((sev, prov), (alertas.BAJA, '0000000370PE'))
        self.assertIn('FR 75825 (OC 2610879)', msg)
        self.assertIn('06-01-2027', msg)
