"""Fusion del Recomendador en la Calculadora (SPEC-19): XYZ, historico, cobertura por bodega,
escenario actual y publicacion en StockProjection / SKUClassification."""
import datetime

from django.test import TestCase

from apps.calc.clasificacion import clase_xyz
from apps.calc.historico import reconstruir
from apps.calc.params import Params
from apps.calculadora.models import ConsumoMensual, EscenarioActual, ParametroCompra, Proveedor, ResultadoArticulo, ResultadoBodega
from apps.calculadora.publicacion import capturar_escenario_actual
from apps.calculadora.servicio import ejecutar_corrida, historico_articulo, meses_cerrados
from apps.inventory.models import (Category, GoodsReceipt, InventoryMetric, ProductSKU, SKUClassification,
                                   StockProjection, Warehouse)

P = Params()
HOY = datetime.date(2026, 10, 27)


class XYZTest(TestCase):
    def test_cortes(self):
        assert clase_xyz(10, 2, P) == 'X'      # cv 0,2
        assert clase_xyz(10, 10, P) == 'X'     # cv 1,0 (incluido)
        assert clase_xyz(10, 15, P) == 'Y'     # cv 1,5
        assert clase_xyz(10, 20, P) == 'Z'     # cv 2,0
        assert clase_xyz(0, 0, P) == 'Z'


class HistoricoTest(TestCase):
    def test_reconstruye_hacia_atras(self):
        # hoy 10; mes en curso: entro 0, salio 2 -> cierre del ultimo mes = 12
        puntos = reconstruir(10, [5, 0, 0], [1, 3, 4], entradas_mes_en_curso=0, consumo_mes_en_curso=2)
        # cierre m3 = 12; cierre m2 = 12 - 0 + 4 = 16; cierre m1 = 16 - 0 + 3 = 19
        assert [p.stock for p in puntos] == [19, 16, 12]
        assert not any(p.inconsistente for p in puntos)

    def test_marca_inconsistencia_sin_negativos(self):
        # Hoy 0 y entraron 10 el ultimo mes sin consumo: el mes anterior habria quedado en -10
        puntos = reconstruir(0, [0, 10], [0, 0])
        assert puntos[0].stock == 0 and puntos[0].inconsistente
        assert puntos[1].stock == 0 and not puntos[1].inconsistente


class FusionCorridaTest(TestCase):
    def setUp(self):
        cat = Category.objects.create(code='GRP-1', name='RPTS. EQ. IZAJE', is_active=True, tipo='REPUESTO')
        self.pp = Warehouse.objects.create(code='013-PP', name='Central')
        self.w002 = Warehouse.objects.create(code='002', name='Calama')
        self.sku = ProductSKU.objects.create(code='R1', description='Rotacion', category=cat, unit_cost_usd=10,
                                             lead_time_days=28, fec_creacion_sap=datetime.date(2020, 1, 1))
        for mes in meses_cerrados(HOY, 12):
            ConsumoMensual.objects.create(product=self.sku, bodega='013-PP', mes=mes, cantidad=9)
            ConsumoMensual.objects.create(product=self.sku, bodega='002', mes=mes, cantidad=1)
        InventoryMetric.objects.create(product=self.sku, warehouse=self.pp, stock_physical=5)
        InventoryMetric.objects.create(product=self.sku, warehouse=self.w002, stock_physical=0, comp_pc_qty=2)
        Proveedor.objects.create(codigo='P1', fecha_ancla=HOY)
        ParametroCompra.objects.create(product=self.sku, proveedor_preferido='P1')
        # Resultado del motor anterior
        StockProjection.objects.create(product=self.sku, warehouse=self.pp, rop=40, suggested_buy_units=35,
                                       action_type='COMPRAR')

    def test_captura_escenario_y_publica_resultados_de_la_calculadora(self):
        self.assertEqual(capturar_escenario_actual(), 1)
        corrida = ejecutar_corrida(hoy=HOY)
        res = ResultadoArticulo.objects.get(product=self.sku)
        # El escenario actual sale de EscenarioActual (motor anterior), no de lo publicado
        self.assertEqual(res.cantidad_actual, 35)
        self.assertTrue(corrida.resumen['publicado'])
        self.assertEqual(res.xyz, 'X')

        central = StockProjection.objects.get(product=self.sku, warehouse=self.pp)
        self.assertEqual(central.action_type, 'COMPRAR')
        self.assertEqual(central.suggested_buy_units, res.cantidad_a_comprar)
        self.assertEqual(central.rop, res.punto_pedido)
        sucursal = StockProjection.objects.get(product=self.sku, warehouse=self.w002)
        self.assertEqual(sucursal.suggested_buy_units, 0)       # las bodegas no compran
        self.assertEqual(sucursal.shortage_units, 2)             # quiebre real: disponible -2
        self.assertEqual(sucursal.action_type, 'TRASLADAR')      # la central tiene 5 libres

        clasif = SKUClassification.objects.get(product=self.sku)
        self.assertEqual(clasif.repo_category, 'R')
        self.assertEqual(clasif.stock_policy, 'SI_STOCK')
        self.assertEqual(clasif.rop_statistical, res.punto_pedido)

        # Una segunda corrida sin nueva captura sigue comparando contra el motor anterior
        ejecutar_corrida(hoy=HOY)
        self.assertEqual(ResultadoArticulo.objects.get(product=self.sku).cantidad_actual, 35)
        self.assertEqual(EscenarioActual.objects.count(), 1)

    def test_cobertura_por_bodega(self):
        ejecutar_corrida(hoy=HOY)
        b = ResultadoBodega.objects.get(resultado__product=self.sku, warehouse=self.pp)
        self.assertAlmostEqual(b.consumo_diario, 108 / 365)
        self.assertAlmostEqual(b.cobertura_dias, 5 / (108 / 365))

    def test_historico_articulo(self):
        mes = meses_cerrados(HOY, 12)[-1]
        GoodsReceipt.objects.create(document_number='1', product=self.sku, quantity=4,
                                    posting_date=mes + datetime.timedelta(days=3))
        serie = historico_articulo('R1', hoy=HOY)
        self.assertEqual(len(serie), 12)
        # cierre del ultimo mes = stock de la red hoy (5) sin movimientos en el mes en curso
        self.assertEqual(serie[-1][1], 5)
        # cierre del penultimo = 5 - 4 (entradas) + 10 (consumo) = 11
        self.assertEqual(serie[-2][1], 11)
