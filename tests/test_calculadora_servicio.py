"""Capa Django de la Calculadora: cargadores, corrida, historial y alertas (SPEC-08, SPEC-18)."""
import datetime
import os
import tempfile

from django.test import TestCase

from apps.calc.simulacion import Escenario, simular
from apps.calculadora import cargadores
from apps.calculadora.models import (Alerta, ArticuloConfig, CompromisoAbierto, ConsumoMensual, HistorialMensual,
                                     OCAbierta, ParametroCompra, PlazoOC, Proveedor, ResultadoArticulo,
                                     ResultadoBodega, TrasladoSugerido)
from apps.calculadora.servicio import ejecutar_corrida, meses_cerrados
from apps.data_ingestion.warehouses import purchase_bodega
from apps.inventory.models import Category, InventoryMetric, ProductSKU, Warehouse

HOY = datetime.date(2026, 10, 27)


def _txt(directorio, nombre, cabecera, filas):
    lineas = ['|' + '|'.join(cabecera) + '|', '|' + '|'.join('---' for _ in cabecera) + '|']
    lineas += ['|' + '|'.join(str(c) for c in f) + '|' for f in filas]
    with open(os.path.join(directorio, nombre), 'w', encoding='utf-8') as fp:
        fp.write('\n'.join(lineas) + '\n')


class PurchaseBodegaTest(TestCase):
    def test_013_y_vacio_van_a_la_central(self):
        self.assertEqual(purchase_bodega('013'), '013-PP')
        self.assertEqual(purchase_bodega(''), '013-PP')
        self.assertEqual(purchase_bodega('002-02'), '002-02')
        self.assertEqual(purchase_bodega('100'), '100')


class MesesCerradosTest(TestCase):
    def test_excluye_mes_en_curso(self):
        meses = meses_cerrados(HOY, 12)
        self.assertEqual(meses[0], datetime.date(2025, 10, 1))
        self.assertEqual(meses[-1], datetime.date(2026, 9, 1))


class CargadoresTest(TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        ProductSKU.objects.create(code='A1', description='Articulo 1')

    def test_consumo_mensual_desde_txt_y_8b_separa_of(self):
        _txt(self.dir, 'Consumo Mensual.txt', ['codigo_sku', 'bodega', 'mes', 'origen', 'cantidad_neta'], [
            ['A1', '013-PP', '2026-09', 'VENTA', '5'],
            ['A1', '013-PP', '2026-09', 'SALIDA', '7'],
            ['NOEXISTE', '013-PP', '2026-09', 'VENTA', '9'],
        ])
        _txt(self.dir, 'Consumo OF Mensual.txt', ['codigo_sku', 'bodega', 'mes', 'cantidad_of'], [
            ['A1', '013-PP', '2026-09', '4'],
        ])
        self.assertEqual(cargadores.cargar_consumo_mensual(self.dir), 'OINM')
        filas = dict(ConsumoMensual.objects.values_list('origen', 'cantidad'))
        self.assertEqual(filas, {'VENTA': 5, 'SALIDA': 3, 'OF': 4})

    def test_sin_consulta_8_reconstruye_desde_pc_y_of(self):
        from apps.inventory.models import SalesOrderMovement
        SalesOrderMovement.objects.create(order_number='1', product_id='A1', quantity=3, warehouse='002',
                                          delivery_date=datetime.date(2026, 8, 10))
        self.assertEqual(cargadores.cargar_consumo_mensual(self.dir), 'PC_OF')
        self.assertEqual(ConsumoMensual.objects.get().cantidad, 3)

    def test_plazos_usa_primera_recepcion_de_cada_linea(self):
        _txt(self.dir, 'Plazos de Entrega OC.txt',
             ['nro_oc', 'codigo_sku', 'codigo_proveedor', 'bodega_oc', 'fecha_oc', 'fecha_comprometida',
              'nro_entrada', 'fecha_entrada', 'dias_entrega', 'cantidad_oc', 'cantidad_recibida'], [
                 ['1,001', 'A1', 'P1', '013-PP', '2026-01-01', '2026-01-20', '9', '2026-02-10', '40', '10', '4'],
                 ['1,001', 'A1', 'P1', '013-PP', '2026-01-01', '2026-01-20', '8', '2026-01-21', '20', '10', '6'],
             ])
        self.assertEqual(cargadores.cargar_plazos_oc(self.dir), 1)
        self.assertEqual(PlazoOC.objects.get().dias_entrega, 20)

    def test_oc_abiertas_acredita_013_a_la_central_y_crea_proveedor(self):
        _txt(self.dir, 'Órdenes de Compra en Tránsito (OC).txt',
             ['nro_oc_sap', 'bodega_destino', 'codigo_sku', 'codigo_proveedor', 'nombre_proveedor',
              'fecha_emision_oc', 'fecha_llegada_estimada', 'cantidad_comprada', 'cantidad_en_transito_pendiente'], [
                 ['2,604,645', '013', 'A1', 'P9', 'PROVEEDOR NUEVE', '2026-10-01', '2026-11-05', '5', '5'],
             ])
        self.assertEqual(cargadores.cargar_oc_abiertas(self.dir), 1)
        oc = OCAbierta.objects.get()
        self.assertEqual((oc.bodega, oc.nro_oc, oc.cantidad_pendiente), ('013-PP', '2604645', 5))
        self.assertEqual(Proveedor.objects.get(codigo='P9').nombre, 'PROVEEDOR NUEVE')

    def test_parametros_respaldo_toma_proveedor_de_la_ultima_entrada_sin_internos(self):
        _txt(self.dir, 'Entradas de Mercancias (EM).txt',
             ['nro_documento', 'codigo_sku', 'fecha_contabilizacion', 'codigo_proveedor', 'nombre_proveedor',
              'cantidad', 'total_linea'], [
                 ['1', 'A1', '2026-01-01', 'P1', 'UNO', '1', '10'],
                 ['2', 'A1', '2026-05-01', 'P2', 'DOS', '1', '10'],
                 ['3', 'A1', '2026-09-01', '96877150P', 'PESCO', '1', '10'],
             ])
        cargadores.cargar_parametros_compra(self.dir)
        self.assertEqual(ParametroCompra.objects.get(product_id='A1').proveedor_preferido, 'P2')

    def test_entradas_de_mercancias_se_cargan_en_goods_receipt(self):
        from apps.data_ingestion.datalake_ingest import ingest_datalake_entradas
        from apps.inventory.models import GoodsReceipt
        _txt(self.dir, 'Entradas de Mercancias (EM).txt',
                    ['nro_documento', 'codigo_sku', 'fecha_contabilizacion', 'codigo_proveedor', 'nombre_proveedor',
                     'cantidad', 'total_linea'], [
                        ['1,204', 'A1', '2026-05-01', 'P2', 'DOS', '3', '30'],
                        ['1,205', 'NOEXISTE', '2026-05-01', 'P2', 'DOS', '3', '30'],
                    ])
        self.assertEqual(ingest_datalake_entradas(os.path.join(self.dir, 'Entradas de Mercancias (EM).txt')), 1)
        gr = GoodsReceipt.objects.get()
        self.assertEqual((gr.document_number, gr.quantity, str(gr.posting_date)), ('1204', 3, '2026-05-01'))

    def test_compromisos_con_fecha_y_atribucion(self):
        _txt(self.dir, 'Pedidos de Clientes (PC).txt',
             ['pedido_numero', 'codigo_sku', 'bodega_despacho', 'codigo_cliente', 'nombre_cliente', 'estado_pedido',
              'fecha_emision', 'fecha_entrega', 'cantidad_solicitada', 'cantidad_pendiente_despacho'], [
                 ['1', 'A1', '013', 'C1', 'Cliente', 'O', '2026-10-01', '2026-11-01', '3', '2'],
                 ['2', 'A1', '002', 'C1', 'Cliente', 'C', '2026-10-01', '2026-11-01', '3', '0'],
             ])
        cargadores.cargar_compromisos(self.dir)
        c = CompromisoAbierto.objects.get()
        self.assertEqual((c.tipo, c.bodega, c.cantidad, c.fecha), ('PC', '013-PP', 2, datetime.date(2026, 11, 1)))


class CorridaTest(TestCase):
    """Red minima: central 013-PP, satelite 013-03 y sucursal 002."""

    def setUp(self):
        cat = Category.objects.create(code='GRP-1', name='RPTS. EQ. IZAJE', is_active=True, tipo='REPUESTO')
        self.pp = Warehouse.objects.create(code='013-PP', name='Central')
        self.w03 = Warehouse.objects.create(code='013-03', name='Satelite')
        self.w002 = Warehouse.objects.create(code='002', name='Calama')
        self.r = ProductSKU.objects.create(code='R1', description='Rotacion', category=cat, unit_cost_usd=10,
                                           lead_time_days=28, fec_creacion_sap=datetime.date(2020, 1, 1))
        self.o = ProductSKU.objects.create(code='O1', description='Obsoleto', category=cat, unit_cost_usd=5,
                                           fec_creacion_sap=datetime.date(2020, 1, 1))
        for mes in meses_cerrados(HOY, 12):
            ConsumoMensual.objects.create(product=self.r, bodega='013-PP', mes=mes, cantidad=10)
        InventoryMetric.objects.create(product=self.r, warehouse=self.pp, stock_physical=12, comp_of_qty=2)
        InventoryMetric.objects.create(product=self.r, warehouse=self.w03, stock_physical=3)
        InventoryMetric.objects.create(product=self.r, warehouse=self.w002, comp_pc_qty=1)
        InventoryMetric.objects.create(product=self.o, warehouse=self.pp, stock_physical=4)
        Proveedor.objects.create(codigo='P1', nombre='Proveedor', fecha_ancla=HOY)
        ParametroCompra.objects.create(product=self.r, proveedor_preferido='P1', min_compra=0, multiplo_compra=5)

    def test_compra_de_la_red_traslados_e_historial(self):
        corrida = ejecutar_corrida(hoy=HOY)
        res = ResultadoArticulo.objects.get(product=self.r)
        self.assertEqual(res.letra, 'R')
        self.assertEqual(res.subclase, 'REGULAR')
        self.assertTrue(res.es_dia_compra)
        # Disponible de la red = 12 + 3 - 2 - 1 = 12; consumo 10/mes -> debe comprar hasta el maximo
        self.assertEqual(res.disponible_futuro, 12)
        self.assertTrue(res.comprar)
        self.assertEqual(res.cantidad_sugerida % 5, 0)
        self.assertGreaterEqual(res.cantidad_sugerida, res.stock_maximo - 12)
        # Sucursal 002: objetivo 1, disponible -1 -> faltante 2 cubierto por 013-03 (excedente 3)
        b002 = ResultadoBodega.objects.get(resultado=res, warehouse=self.w002)
        self.assertEqual(b002.accion, 'TRASLADAR')
        t = TrasladoSugerido.objects.get(product=self.r)
        self.assertEqual((t.origen.code, t.destino.code, t.cantidad), ('013-03', '002', 2))
        # Obsoleto: no compra
        self.assertEqual(ResultadoArticulo.objects.get(product=self.o).cantidad_a_comprar, 0)
        # Historial mensual y resumen
        self.assertEqual(HistorialMensual.objects.filter(mes=HOY.replace(day=1)).count(), 2)
        self.assertEqual(corrida.resumen['letras'], {'R': 1, 'O': 1})
        self.assertIn('prop', res.simulacion)

    def test_recalcula_desde_cero_y_mantiene_estado_de_alertas(self):
        InventoryMetric.objects.filter(product=self.r).update(stock_physical=0)
        ejecutar_corrida(hoy=HOY)
        alerta = Alerta.objects.get(tipo='URGENTE', product=self.r)
        alerta.estado = Alerta.REVISADA
        alerta.save()
        ejecutar_corrida(hoy=HOY)
        self.assertEqual(ResultadoArticulo.objects.count(), 2)
        alerta.refresh_from_db()
        self.assertEqual(alerta.estado, Alerta.REVISADA)
        self.assertTrue(alerta.vigente)
        # Si la condicion desaparece la alerta queda no vigente
        InventoryMetric.objects.filter(product=self.r, warehouse=self.pp).update(stock_physical=500)
        ejecutar_corrida(hoy=HOY)
        alerta.refresh_from_db()
        self.assertFalse(alerta.vigente)

    def test_estrategico_declarado_y_cambio_de_letra(self):
        ejecutar_corrida(hoy=datetime.date(2026, 9, 15))
        ArticuloConfig.objects.create(product=self.o, es_estrategico=True, minimo_declarado=6)
        ejecutar_corrida(hoy=HOY)
        res = ResultadoArticulo.objects.get(product=self.o)
        self.assertEqual(res.letra, 'E')
        self.assertEqual(res.stock_seguridad, 6)
        h = HistorialMensual.objects.get(product=self.o, mes=HOY.replace(day=1))
        self.assertEqual((h.letra_anterior, h.letra), ('O', 'E'))
        self.assertTrue(Alerta.objects.filter(tipo='CAMBIO_LETRA', product=self.o).exists())

    def test_simulacion_sin_guardar_no_toca_resultados(self):
        resumen = ejecutar_corrida(hoy=HOY, guardar=False, extra_general={'meses_cobertura': 6})
        self.assertEqual(resumen['articulos'], 2)
        self.assertFalse(ResultadoArticulo.objects.exists())


class SimulacionTest(TestCase):
    def test_hasta_el_maximo_compra_menos_veces_y_guarda_mas_stock(self):
        # Revision cada 15 dias: el umbral debe cubrir plazo + revision (10 + 15 dias de consumo)
        actual = simular(20, 1, Escenario(umbral=20, hasta=20, plazo_dias=10))
        propuesto = simular(20, 1, Escenario(umbral=30, hasta=110, plazo_dias=10, revision_dias=15))
        self.assertEqual(actual.dias_quiebre, 0)
        self.assertEqual(propuesto.dias_quiebre, 0)
        self.assertGreater(propuesto.inventario[0], actual.inventario[0])
        compras = lambda s: sum(1 for q in s.compras_mes if q)
        self.assertLessEqual(compras(propuesto), compras(actual))

    def test_quiebre_sin_reposicion(self):
        r = simular(5, 1, Escenario(umbral=0, hasta=0, plazo_dias=10), horizonte=30)
        self.assertEqual(r.dias_quiebre, 25)
