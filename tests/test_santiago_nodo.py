"""SPEC-21 con la base de datos: Santiago como nodo 013 (incluye el stock de la 013 a secas),
traslados regiones -> Santiago y la seccion "¿Comprar todo de una vez?" de la ficha."""
import datetime

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.calculadora.models import ConsumoMensual, ResultadoBodega, TrasladoSugerido
from apps.calculadora.servicio import ejecutar_corrida, meses_cerrados
from apps.data_ingestion.warehouses import nodo_red
from apps.inventory.models import Category, InventoryMetric, ProductSKU, Warehouse
from apps.inventory.stock_actual_models import StockActual

HOY = timezone.localdate()


class NodoRedTest(TestCase):
    def test_nodos(self):
        for code in ('013', '013-PP', '013-03', '', '100', '0EX'):
            self.assertEqual(nodo_red(code), '013', code)
        self.assertEqual(nodo_red('002-02'), '002-02')
        self.assertEqual(nodo_red('010'), '010')


class SantiagoNodoTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cat = Category.objects.create(code='GRP-1', name='RPTS. EQ. IZAJE', is_active=True, tipo='REPUESTO')
        cls.pp = Warehouse.objects.create(code='013-PP', name='Panol')
        cls.ps = Warehouse.objects.create(code='013-PS', name='Panol servicios')
        cls.anf = Warehouse.objects.create(code='002-02', name='Antofagasta')
        cls.sku = ProductSKU.objects.create(code='R1', description='Rotacion', category=cat, unit_cost_usd=10,
                                            lead_time_days=28, fec_creacion_sap=datetime.date(2020, 1, 1))
        for i, mes in enumerate(meses_cerrados(HOY, 12)):
            ConsumoMensual.objects.create(product=cls.sku, bodega='013-PP', mes=mes, cantidad=4)
            ConsumoMensual.objects.create(product=cls.sku, bodega='013', mes=mes, origen=ConsumoMensual.VENTA, cantidad=1)
            if i == 5:
                ConsumoMensual.objects.create(product=cls.sku, bodega='002-02', mes=mes, cantidad=30)
        # Santiago: 1 en 013-PS + 2 en la 013 a secas; OF por 10 -> quiebre real de 7
        InventoryMetric.objects.create(product=cls.sku, warehouse=cls.pp, comp_of_qty=10)
        InventoryMetric.objects.create(product=cls.sku, warehouse=cls.ps, stock_physical=1)
        StockActual.objects.create(codigo='R1', bodega='013', stock_disponible=2)
        # Antofagasta: 20 con 6 comprometidas
        InventoryMetric.objects.create(product=cls.sku, warehouse=cls.anf, stock_physical=20, comp_pc_qty=6)
        cls.admin = User.objects.create_superuser('admin', 'a@a.cl', 'x')

    def test_santiago_suma_la_013_y_pide_a_regiones_solo_lo_libre(self):
        ejecutar_corrida(hoy=HOY)
        stgo = ResultadoBodega.objects.get(resultado__product=self.sku, warehouse__code='013')
        self.assertEqual((stgo.stock_fisico, stgo.comprometido, stgo.disponible_futuro), (3, 10, -7))
        self.assertEqual(stgo.componentes, [['013', 2], ['013-PS', 1]])
        # Antofagasta protege 6 + 15 dias de su consumo (30/365 x 15 = 1,2 -> 2) = 8: libres 12
        t = TrasladoSugerido.objects.get(product=self.sku)
        self.assertEqual((t.origen.code, t.destino.code, t.cantidad), ('002-02', '013', 7))
        self.assertEqual(stgo.accion, 'TRASLADAR')
        anf = ResultadoBodega.objects.get(resultado__product=self.sku, warehouse=self.anf)
        self.assertEqual((anf.protegido, anf.excedente), (8, 12))
        self.assertFalse(ResultadoBodega.objects.filter(resultado__product=self.sku,
                                                        warehouse__code__startswith='013-').exists())

    def test_ficha_muestra_decision_de_compra_y_santiago_por_bodega(self):
        ejecutar_corrida(hoy=HOY)
        self.client.force_login(self.admin)
        r = self.client.get(reverse('calculadora:articulo', args=['R1']))
        self.assertEqual(r.status_code, 200)
        d = r.context['decision']
        self.assertEqual([f['nombre'] for f in d['filas']], ['Santiago', 'Antofagasta'])
        stgo, anf = d['filas']
        self.assertEqual(stgo['promedio'], 5)                       # 4 de OF + 1 de venta por mes
        self.assertEqual(anf['meses_con_consumo'], 1)
        self.assertTrue(any(c['pico'] for c in anf['celdas']))     # 30 en un mes: atipico
        self.assertEqual({b['bodega'] for b in d['santiago']}, {'013', '013-PS', '013-PP'})
        if d['sugerida']:
            self.assertLessEqual(d['minima'], d['sugerida'])
        self.assertContains(r, '¿Comprar todo de una vez?')
        self.assertContains(r, 'Santiago (013)')

    def test_pantallas_de_traslados_y_bodegas(self):
        ejecutar_corrida(hoy=HOY)
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(reverse('calculadora:traslados')), 'Santiago (013)')
        self.assertContains(self.client.get(reverse('calculadora:bodegas') + '?todo=1'), 'Santiago (013)')
