"""SPEC-22 (notas de credito en el consumo, pre-bodegas como transito) y SPEC-23 (calculo hibrido de
compromisos e informe de antiguedad de compromisos abiertos)."""
import datetime
import os
import tempfile
from collections import defaultdict

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.calculadora.cargadores import aplicar_notas_credito, cargar_compromisos_detalle
from apps.calculadora.models import (CompromisoAbierto, CompromisoDetalle, ConsumoMensual, Corrida, ParametroValor,
                                     ResultadoArticulo)
from apps.calculadora.servicio import _restar_meses, ejecutar_corrida, meses_cerrados
from apps.data_ingestion.warehouses import prebodega_destino, purchase_bodega
from apps.inventory.models import Category, InventoryMetric, ProductSKU, Warehouse

HOY = timezone.localdate()
CABECERA_NC = ('|nc_numero|codigo_sku|bodega_nc|fecha_nc|cantidad|tipo_origen|bodega_origen|fecha_origen|'
               'numero_origen|sin_movimiento_stock|\n|-|-|-|-|-|-|-|-|-|-|\n')


def _txt(directorio, nombre, cabecera, filas):
    with open(os.path.join(directorio, nombre), 'w', encoding='utf-8') as f:
        f.write(cabecera)
        for fila in filas:
            f.write('|' + '|'.join(str(c) for c in fila) + '|\n')


class PreBodegasTest(TestCase):
    def test_pre_bodegas_van_a_su_sucursal(self):
        self.assertEqual(prebodega_destino('000-022'), '002-02')
        self.assertEqual(prebodega_destino('000-003'), '003')
        self.assertIsNone(prebodega_destino('013-PP'))
        self.assertEqual(purchase_bodega('000-010'), '010')
        self.assertEqual(purchase_bodega('000'), '013-PP')
        self.assertEqual(purchase_bodega('013'), '013-PP')
        self.assertEqual(purchase_bodega('100'), '100')


class NotasCreditoTest(TestCase):
    """Caso real 30202505: factura en Calama (agosto) anulada por NC registrada en 013-NC (septiembre)."""

    @classmethod
    def setUpTestData(cls):
        ProductSKU.objects.create(code='NC1', description='Con NC')

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.dic, self.ago, self.sep = datetime.date(2025, 12, 1), datetime.date(2026, 8, 1), datetime.date(2026, 9, 1)
        self.mar = datetime.date(2026, 3, 1)
        _txt(self.dir, 'Notas de Credito.txt', CABECERA_NC, [
            ['10,009,848', 'NC1', '013-NC', '2026-09-04', 145, 13, '002', '2026-08-27', '97,220', 'N'],
            # NC sobre una factura de reserva: ninguna de las dos movio stock (no esta en OINM)
            ['9,374', 'NC1', '013-IN', '2026-03-27', '360,000', 13, '013', '2025-12-31', '92,876', 'N'],
            ['1', 'NC1', '010', '2026-09-10', 3, -1, '', '', '', 'N'],
        ])

    def _aplicar(self, acumulado, nc_oinm):
        return aplicar_notas_credito(acumulado, nc_oinm, {'NC1'}, self.dir)

    def test_nc_se_resta_en_la_bodega_y_mes_de_la_factura(self):
        V = ConsumoMensual.VENTA
        acumulado = defaultdict(float, {('NC1', '002', self.ago, V): 320.0, ('NC1', '013-NC', self.sep, V): 40.0})
        movidas = self._aplicar(acumulado, {('NC1', '013-NC', self.sep): -145.0})
        self.assertEqual(movidas, 145)
        self.assertEqual(acumulado[('NC1', '002', self.ago, V)], 175)
        self.assertEqual(acumulado[('NC1', '013-NC', self.sep, V)], 40)

    def test_solo_se_reubica_lo_que_registro_oinm(self):
        V = ConsumoMensual.VENTA
        acumulado = defaultdict(float, {('NC1', '013', self.dic, V): 50.0, ('NC1', '002', self.ago, V): 320.0})
        movidas = self._aplicar(acumulado, {('NC1', '013-NC', self.sep): -100.0})
        self.assertEqual(movidas, 100)                                   # la NC dice 145; OINM, 100
        self.assertEqual(acumulado[('NC1', '002', self.ago, V)], 220)
        self.assertEqual(acumulado[('NC1', '013', self.dic, V)], 50)     # la de 360.000 no movio stock

    def test_no_deja_negativo_el_origen_si_falta_la_venta(self):
        # Mes incompleto en el Datalake: la factura de 145 no esta; Calama solo tiene 30
        V = ConsumoMensual.VENTA
        acumulado = defaultdict(float, {('NC1', '002', self.ago, V): 30.0, ('NC1', '013-NC', self.sep, V): 145.0})
        movidas = self._aplicar(acumulado, {('NC1', '013-NC', self.sep): -145.0})
        self.assertEqual(movidas, 30)
        self.assertEqual(acumulado[('NC1', '002', self.ago, V)], 0)
        self.assertEqual(acumulado[('NC1', '013-NC', self.sep, V)], 30)     # 145 - (145 - 30)

    def test_nc_sin_origen_queda_como_devolucion_donde_ocurrio(self):
        acumulado = defaultdict(float, {('NC1', '010', self.sep, ConsumoMensual.VENTA): 5.0})
        self._aplicar(acumulado, {('NC1', '010', self.sep): -3.0})
        self.assertEqual(acumulado[('NC1', '010', self.sep, ConsumoMensual.VENTA)], 2)

    def test_consulta_8_sin_marca_nc_no_cambia_nada(self):
        acumulado = defaultdict(float, {('NC1', '002', self.ago, ConsumoMensual.VENTA): 320.0})
        self.assertEqual(self._aplicar(acumulado, {}), 0)
        self.assertEqual(dict(acumulado), {('NC1', '002', self.ago, ConsumoMensual.VENTA): 320.0})


class CompromisosRecientesTest(TestCase):
    """Un articulo con un PC reciente (5 u) y uno de hace 2 anos (40 u) en Antofagasta."""

    @classmethod
    def setUpTestData(cls):
        cat = Category.objects.create(code='GRP-1', name='RPTS', is_active=True, tipo='REPUESTO')
        cls.anf = Warehouse.objects.create(code='002-02', name='Antofagasta')
        cls.sku = ProductSKU.objects.create(code='C1', description='Comprometido', category=cat, unit_cost_usd=10,
                                            lead_time_days=20, fec_creacion_sap=datetime.date(2020, 1, 1))
        for mes in meses_cerrados(HOY, 12):
            ConsumoMensual.objects.create(product=cls.sku, bodega='002-02', mes=mes, cantidad=3)
        InventoryMetric.objects.create(product=cls.sku, warehouse=cls.anf, stock_physical=10, comp_pc_qty=45)
        CompromisoAbierto.objects.create(product=cls.sku, tipo='PC', numero='1', bodega='002-02', cantidad=5,
                                         fecha_emision=HOY - datetime.timedelta(days=10), fecha=HOY)
        CompromisoAbierto.objects.create(product=cls.sku, tipo='PC', numero='2', bodega='002-02', cantidad=40,
                                         fecha_emision=HOY - datetime.timedelta(days=730), fecha=HOY)
        cls.admin = User.objects.create_superuser('admin', 'a@a.cl', 'x')

    def test_restar_meses(self):
        self.assertEqual(_restar_meses(datetime.date(2026, 5, 31), 3), datetime.date(2026, 2, 28))
        self.assertEqual(_restar_meses(datetime.date(2026, 1, 15), 3), datetime.date(2025, 10, 15))

    def test_por_defecto_cuenta_todo_y_guarda_la_otra_base(self):
        ejecutar_corrida(hoy=HOY)
        r = ResultadoArticulo.objects.get(product=self.sku)
        self.assertEqual((r.comprometido, r.comprometido_antiguo), (45, 40))
        self.assertIsNotNone(r.cantidad_otra_base)
        self.assertLess(r.cantidad_otra_base, r.cantidad_a_comprar + r.cantidad_sugerida + 1)
        resumen = Corrida.objects.first().resumen
        self.assertFalse(resumen['solo_compromisos_recientes'])
        self.assertLessEqual(resumen['valor_otra_base'], resumen['valor_sugerido'])

    def test_solo_recientes_descuenta_los_antiguos(self):
        ParametroValor.objects.create(clave='solo_compromisos_recientes', nivel='GENERAL', ambito='', valor='True')
        ejecutar_corrida(hoy=HOY)
        r = ResultadoArticulo.objects.get(product=self.sku)
        self.assertEqual(r.comprometido, 5)
        self.assertTrue(Corrida.objects.first().resumen['solo_compromisos_recientes'])

    def test_ficha_marca_compromisos_antiguos(self):
        ejecutar_corrida(hoy=HOY)
        self.client.force_login(self.admin)
        r = self.client.get(reverse('calculadora:articulo', args=['C1']))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'emitidas antes del')


class InformeCompromisosTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        activa = Category.objects.create(code='G1', name='RPTS', is_active=True, tipo='REPUESTO')
        servicio = Category.objects.create(code='G2', name='SERVICIOS', is_active=False, tipo='SERVICIO')
        ProductSKU.objects.create(code='A1', description='Valorizado', unit_cost_usd=2, category=activa)
        ProductSKU.objects.create(code='S1', description='Montaje', unit_cost_usd=7000, category=servicio)
        cls.admin = User.objects.create_superuser('admin', 'a@a.cl', 'x')

    def setUp(self):
        d = tempfile.mkdtemp()
        cab = ('|tipo|numero|codigo_sku|bodega|fecha_emision|fecha_entrega|codigo_cliente|nombre_cliente|responsable|'
               'referencia|cantidad_pendiente|\n|-|-|-|-|-|-|-|-|-|-|-|\n')
        viejo = (HOY - datetime.timedelta(days=500)).isoformat()
        nuevo = (HOY - datetime.timedelta(days=20)).isoformat()
        _txt(d, 'Compromisos Abiertos.txt', cab, [
            ['PC', '1,001', 'A1', '002', viejo, viejo, 'C1', 'Cliente uno', 'Vendedor A', 'OC-9', 10],
            ['PC', '1,001', 'A1', '002', viejo, viejo, 'C1', 'Cliente uno', 'Vendedor A', 'OC-9', 5],
            ['OF', '2,002', 'A1', '013-PP', nuevo, nuevo, '', '', 'Usuario B', 'EQ1', 7],
            ['OF', '2,002', 'S1', '013-PP', nuevo, nuevo, '', '', 'Usuario B', 'EQ1', 7700],
            ['OF', '2,004', 'ZZ', '013-PP', nuevo, nuevo, '', '', 'Usuario B', 'EQ1', 1],
            ['OF', '2,003', 'A1', '013', nuevo, nuevo, '', '', 'Usuario B', 'EQ1', 0],
        ])
        self.assertEqual(cargar_compromisos_detalle(d), 3)

    def test_carga_solo_articulos_del_alcance(self):
        self.assertFalse(CompromisoDetalle.objects.filter(codigo_sku__in=['S1', 'ZZ']).exists())

    def test_carga_valoriza_y_asigna_nodo(self):
        pc = CompromisoDetalle.objects.filter(numero='1001')
        self.assertEqual(pc.count(), 2)
        self.assertEqual({(c.nodo, c.costo_unitario) for c in pc}, {('002', 2.0)})
        self.assertEqual(CompromisoDetalle.objects.get(numero='2002').nodo, '013')

    def test_informe_y_excel(self):
        self.client.force_login(self.admin)
        r = self.client.get(reverse('calculadora:compromisos'))
        self.assertEqual(r.status_code, 200)
        tabla = {t['clave']: t for t in r.context['tabla']}
        self.assertEqual(tabla['12+']['PC']['unidades'], 15)
        self.assertEqual(tabla['12+']['valor'], 30)
        self.assertEqual(tabla['0-3']['OF']['documentos'], 1)
        self.assertEqual(r.context['responsables'][0]['responsable'], 'Vendedor A')
        r = self.client.get(reverse('calculadora:compromisos'), {'tramo': '12+'})
        self.assertEqual(r.context['page_obj'].paginator.count, 1)
        r = self.client.get(reverse('calculadora:compromisos_excel'))
        self.assertEqual(r.status_code, 200)
        self.assertIn('spreadsheetml', r['Content-Type'])
