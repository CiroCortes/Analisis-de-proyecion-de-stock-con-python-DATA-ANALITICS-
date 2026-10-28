"""SPEC-24: prevision de demanda y vista "Analizar articulos" (tipo Slim4)."""
import datetime

from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone

from apps.calc.params import Params
from apps.calc.prevision import prever
from apps.calculadora import analisis
from apps.calculadora.models import ConsumoMensual
from apps.calculadora.servicio import ejecutar_corrida, meses_cerrados
from apps.inventory.models import Category, InventoryMetric, ProductSKU, Warehouse

HOY = timezone.localdate()


class PrevisionTest(SimpleTestCase):
    def test_demanda_pareja_sin_tendencia(self):
        p = prever([10] * 12, Params())
        self.assertEqual((p.promedio, p.tendencia, p.meses_con_demanda, p.meses_desde_ultima), (10, 0, 12, 0))
        self.assertEqual(p.valores, (10.0,) * 12)

    def test_tendencia_creciente_acotada(self):
        p = prever(list(range(1, 13)), Params())       # pendiente real 1 u/mes
        self.assertAlmostEqual(p.tendencia, 0.5 * 6.5 / 17.5)
        self.assertGreater(p.valores[-1], p.valores[0])
        self.assertLessEqual(p.valores[-1], 6.5 * 1.5 + 0.01)

    def test_sin_demanda(self):
        p = prever([0] * 12, Params())
        self.assertEqual((p.promedio, p.valores[0], p.meses_desde_ultima), (0, 0, None))

    def test_ultima_demanda_y_nunca_negativa(self):
        p = prever([30, 20, 10, 5, 0, 0, 0, 0, 0, 0, 0, 0], Params())
        self.assertEqual(p.meses_desde_ultima, 8)
        self.assertTrue(all(v >= 0 for v in p.valores))


class AnalizarTest(TestCase):
    """Un articulo que rota en 013-PS y 013-PP, con stock en Antofagasta y sin demanda en Copiapo."""

    @classmethod
    def setUpTestData(cls):
        cat = Category.objects.create(code='G1', name='RPTS', is_active=True, tipo='REPUESTO')
        for code in ('013-PP', '013-PS', '002-02', '003'):
            Warehouse.objects.create(code=code, name=code)
        cls.sku = ProductSKU.objects.create(code='L1', description='LIMPIA CONTACTOS', category=cat, unit_cost_usd=5,
                                            lead_time_days=20, fec_creacion_sap=datetime.date(2020, 1, 1))
        for mes in meses_cerrados(HOY, 12):
            ConsumoMensual.objects.create(product=cls.sku, bodega='013-PS', mes=mes, cantidad=6)
            ConsumoMensual.objects.create(product=cls.sku, bodega='013-PP', mes=mes, cantidad=4)
            ConsumoMensual.objects.create(product=cls.sku, bodega='002-02', mes=mes, cantidad=5)
        InventoryMetric.objects.create(product=cls.sku, warehouse=Warehouse.objects.get(code='013-PS'), stock_physical=24)
        InventoryMetric.objects.create(product=cls.sku, warehouse=Warehouse.objects.get(code='013-PP'), stock_physical=18)
        InventoryMetric.objects.create(product=cls.sku, warehouse=Warehouse.objects.get(code='002-02'), stock_physical=21)
        InventoryMetric.objects.create(product=cls.sku, warehouse=Warehouse.objects.get(code='003'), stock_physical=15)
        ejecutar_corrida(hoy=HOY)
        cls.admin = User.objects.create_superuser('admin', 'a@a.cl', 'x')

    def test_listado_santiago_suma_sus_bodegas(self):
        fila = analisis.listado('013')[0]
        self.assertEqual((fila['codigo'], fila['demanda'], fila['stock'], fila['venta12'], fila['meses']),
                         ('L1', 10, 42, 120, 12))
        self.assertIsNotNone(fila['a_pedir'])

    def test_listado_de_una_bodega_013_no_tiene_a_pedir(self):
        fila = analisis.listado('013-PS')[0]
        self.assertEqual((fila['demanda'], fila['stock'], fila['a_pedir']), (6, 24, None))

    def test_detalle_en_todas_las_ubicaciones(self):
        d = analisis.detalle('L1')
        por_ubic = {u['ubicacion']: u for u in d['ubicaciones']}
        self.assertEqual(set(por_ubic) >= {'013', '013-PS', '013-PP', '002', '002-02', '003', '008', '010'}, True)
        self.assertEqual((por_ubic['003']['stock'], por_ubic['003']['meses']), (15, 0))
        self.assertEqual(por_ubic['002-02']['valores'], [5.0] * 12)
        self.assertEqual(len(d['etiquetas']), 24)
        self.assertEqual(len(por_ubic['013']['historia']), 12)

    def test_pantalla_json_y_excel(self):
        self.client.force_login(self.admin)
        r = self.client.get(reverse('calculadora:analizar'), {'ubicacion': '002-02', 'orden': 'stock'})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'data-codigo="L1"')
        r = self.client.get(reverse('calculadora:analizar'), {'ubicacion': 'XX'})
        self.assertEqual(r.context['f']['ubicacion'], '013')
        r = self.client.get(reverse('calculadora:analizar_detalle', args=['L1']))
        self.assertEqual(r.json()['descripcion'], 'LIMPIA CONTACTOS')
        r = self.client.get(reverse('calculadora:analizar_excel'), {'ubicacion': '013'})
        self.assertIn('spreadsheetml', r['Content-Type'])
