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


class BodegasSapTest(TestCase):
    """SPEC-29: el articulo en cada bodega de SAP y como cuenta (caso real 35071069, 27-oct)."""

    @classmethod
    def setUpTestData(cls):
        from apps.calculadora.models import OCAbierta
        from apps.inventory.stock_actual_models import StockActual
        cat = Category.objects.create(code='G1', name='RPTS', is_active=True, tipo='REPUESTO')
        cls.sku = ProductSKU.objects.create(code='35071069', description='BATERIA HIDUO', category=cat, unit_cost_usd=98)
        for code, activa in (('013-03', True), ('000-022', False), ('966', False), ('013', False)):
            Warehouse.objects.create(code=code, name=f'{code} - Bodega', is_active=activa)
        for bodega, q, pedido in (('013-03', 10, 0), ('000-022', 0, 20), ('966', 14, 0), ('013', 1, 0)):
            StockActual.objects.create(codigo='35071069', bodega=bodega, stock_disponible=q, stock_pedido=pedido)
        # La OC a una pre-bodega se acredita al destino (SPEC-22) y guarda su bodega de SAP (SPEC-29)
        OCAbierta.objects.create(nro_oc='1', product=cls.sku, bodega='002-02', bodega_sap='000-022', cantidad_pendiente=5)
        ejecutar_corrida(hoy=HOY)

    def test_cada_bodega_con_su_tratamiento(self):
        d = analisis.bodegas_sap('35071069')
        filas = {f['bodega']: f for f in d['bodegas_sap']}
        self.assertEqual(filas['013-03']['cuenta'], 'Stock de Santiago')
        self.assertEqual(filas['013']['cuenta'], 'Stock de Santiago')
        self.assertEqual(filas['000-022']['cuenta'], 'En camino a Antofagasta')
        self.assertEqual(filas['966']['cuenta'], 'No cuenta')
        self.assertEqual(d['totales_sap']['STOCK'], 11)
        self.assertEqual(d['totales_sap']['NO_CUENTA'], 14)
        self.assertEqual([f['bodega'] for f in d['bodegas_sap']][-1], '966')   # los que no cuentan, al final

    def test_avisa_pedido_en_sap_sin_oc_cargada(self):
        d = analisis.bodegas_sap('35071069')
        fila = next(f for f in d['bodegas_sap'] if f['bodega'] == '000-022')
        self.assertEqual((fila['pedido_sap'], fila['oc'], fila['sin_oc']), (20, 5, 15))
        self.assertEqual(d['totales_sap']['sin_oc'], 15)

    def test_selector_ofrece_pre_bodegas_y_otras(self):
        tipos = {c: t for c, _, t in analisis.ubicaciones()}
        self.assertEqual(tipos['000-022'], analisis.EN_CAMINO)
        self.assertEqual(tipos['966'], analisis.OTRA)
        self.assertNotIn('013', [c for c, _, t in analisis.ubicaciones() if t != analisis.NODO])

    def test_detalle_muestra_cada_bodega_bajo_su_nodo(self):
        filas = analisis.detalle('35071069')['ubicaciones']
        orden = [(f['tipo'], f['ubicacion']) for f in filas]
        i_stgo, i_paso = orden.index(('NODO', '013')), orden.index(('DETALLE', '013'))
        i_antof, i_pre = orden.index(('NODO', '002-02')), orden.index(('DETALLE', '000-022'))
        self.assertLess(i_stgo, i_paso)                       # la 013 de paso, dentro de Santiago
        self.assertLess(i_antof, i_pre)                       # la pre-bodega, dentro de Antofagasta
        self.assertEqual(orden[-1], ('FUERA', '966'))         # consignacion, al final
        self.assertNotIn(('DETALLE', '002-02'), orden)        # una sucursal no se repite como detalle

    def test_listado_de_una_pre_bodega(self):
        filas = analisis.listado('000-022')
        self.assertEqual([(f['codigo'], f['stock'], f['recibir'], f['a_pedir']) for f in filas], [('35071069', 0, 5, None)])
