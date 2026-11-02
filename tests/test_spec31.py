"""SPEC-31: marcas de gestion (excluir del calculo, plan de gerencia), SC fuera del transito,
promedio con demanda, ABC por venta y caida de consumo por nodo."""
import datetime
import os
import tempfile
from types import SimpleNamespace

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.calc import politica as pol
from apps.calc import red
from apps.calc.clasificacion import es_candidato_gerencia
from apps.calc.consumo import calcular_consumo
from apps.calc.motor import EntradaArticulo, calcular_articulo
from apps.calc.params import Params
from apps.calculadora import servicio
from apps.calculadora.alertas import caidas_por_nodo
from apps.calculadora.cargadores import cargar_ventas
from apps.calculadora.models import Alerta, ArticuloConfig, ConsumoMensual, ResultadoArticulo, VentaMensual
from apps.inventory.models import Category, InventoryMetric, ProductSKU, Warehouse

HOY = datetime.date(2026, 11, 2)


def _entrada(**kw):
    base = dict(codigo='X', hoy=HOY, abc='A', consumo_meses=[10] * 12, lead_time_maestro=28, costo=2,
                bodegas=[red.Bodega('013-PP', es_central=True, es_santiago=True, stock_fisico=2)])
    base.update(kw)
    return EntradaArticulo(**base)


# ── Nucleo ───────────────────────────────────────────────────────────────────

def test_excluido_no_compra_aunque_tenga_demanda():
    r = calcular_articulo(_entrada(excluido=True, motivo_exclusion='Código auxiliar de entrega'))
    assert r.politica.metodo == pol.SIN_COMPRA and r.cantidad_a_comprar == 0
    assert r.consumo.consumo_promedio_mes == 10          # la demanda se sigue viendo
    assert 'Excluido del calculo: Código auxiliar de entrega' in r.avisos


def test_plan_de_gerencia_compra_plan_menos_disponible_sin_esperar_calendario():
    r = calcular_articulo(_entrada(plan_gerencia=True, plan_unidades=5, consumo_meses=[0] * 9 + [1, 0, 1],
                                   es_dia_compra=False, dias_a_proxima_compra=10))
    assert r.politica.metodo == pol.GERENCIA
    assert r.compra.cantidad_sugerida == 3 and r.compra.comprar   # 5 del plan - 2 en stock
    assert r.excepcion is None                                     # sin proyeccion de consumo


def test_plan_de_gerencia_cubierto_por_la_oc_no_compra():
    bodegas = [red.Bodega('013-PP', es_central=True, es_santiago=True, stock_fisico=2, en_transito=3)]
    r = calcular_articulo(_entrada(plan_gerencia=True, plan_unidades=5, bodegas=bodegas))
    assert r.cantidad_a_comprar == 0


def test_plan_de_gerencia_respeta_minimo_y_multiplo():
    r = calcular_articulo(_entrada(plan_gerencia=True, plan_unidades=5, min_compra=4, multiplo=4))
    assert r.compra.cantidad_sugerida == 4


def test_plan_vencido_o_sin_unidades_no_compra():
    vencido = calcular_articulo(_entrada(plan_gerencia=True, plan_unidades=5, plan_hasta=datetime.date(2026, 10, 1)))
    assert vencido.cantidad_a_comprar == 0 and 'Plan de gerencia vencido: actualizar' in vencido.avisos
    vigente = calcular_articulo(_entrada(plan_gerencia=True, plan_unidades=5, plan_hasta=datetime.date(2026, 11, 1)))
    assert vigente.cantidad_a_comprar == 3
    sin = calcular_articulo(_entrada(plan_gerencia=True, plan_unidades=0))
    assert sin.cantidad_a_comprar == 0 and 'Plan de gerencia sin unidades' in sin.avisos


def test_promedio_con_demanda_ejemplo_de_cesar():
    # 40 u en 4 meses de 12: 3,3 por mes en 12 meses y 10 en los meses con demanda
    c = calcular_consumo([10, 0, 0, 10, 0, 0, 10, 0, 0, 10, 0, 0], Params())
    assert round(c.consumo_promedio_mes, 2) == 3.33
    assert c.promedio_con_demanda == 10
    assert c.mayor_consumo_mes == 10       # la regla R-Intermitente ya usa la intensidad (§3)


def test_candidato_de_gerencia():
    p = Params(umbral_costo_equipo_usd=5000, meses_max_equipo=6)
    assert es_candidato_gerencia(26822, 4, p)
    assert not es_candidato_gerencia(26822, 9, p)       # rota todos los meses: se repone por formula
    assert not es_candidato_gerencia(4999, 1, p)
    assert not es_candidato_gerencia(26822, 4, Params(umbral_costo_equipo_usd=0))


def test_sc_fuera_del_transito_por_defecto():
    m = SimpleNamespace(oc_po_qty=5, sc_qty=7, stock_transito_inter=2)
    assert servicio.transito_metrica(m, Params()) == 7
    assert servicio.transito_metrica(m, Params(sc_cuenta_en_transito=True)) == 14


# ── Corrida, carga y pantallas ───────────────────────────────────────────────

class CorridaMarcasTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cat = Category.objects.create(code='GRP-142', name='PANOL', is_active=True, tipo='REPUESTO')
        cls.wh = Warehouse.objects.create(code='013-PP', name='Central')
        Warehouse.objects.create(code='002', name='Calama')
        antiguo = timezone.localdate() - datetime.timedelta(days=900)
        cls.aux = ProductSKU.objects.create(code='4999990001', description='ENTREGA DE INSUMOS', category=cat,
                                            unit_cost_usd=10, fec_creacion_sap=antiguo)
        cls.kit = ProductSKU.objects.create(code='KIT1', description='KIT ESTRUCTURAL', category=cat,
                                            unit_cost_usd=20000, fec_creacion_sap=antiguo)
        cls.otro = ProductSKU.objects.create(code='R1', description='Filtro', category=cat, unit_cost_usd=1,
                                             fec_creacion_sap=antiguo)
        for p in (cls.aux, cls.kit, cls.otro):
            InventoryMetric.objects.create(product=p, warehouse=cls.wh, stock_physical=1, sc_qty=50)
        meses = servicio.meses_cerrados(timezone.localdate(), 12)
        for m in meses:
            ConsumoMensual.objects.create(product=cls.aux, bodega='013-PP', mes=m, origen='SALIDA', cantidad=100)
            ConsumoMensual.objects.create(product=cls.otro, bodega='013-PP', mes=m, origen='VENTA', cantidad=5)
        for m in meses[::3]:
            ConsumoMensual.objects.create(product=cls.kit, bodega='013-PP', mes=m, origen='VENTA', cantidad=1)
        VentaMensual.objects.create(product=cls.kit, bodega='002', mes=meses[-1], monto_usd=90000, cantidad=3)
        VentaMensual.objects.create(product=cls.otro, bodega='013-PP', mes=meses[-1], monto_usd=100, cantidad=5)
        cls.admin = User.objects.create_superuser('admin', 'a@a.cl', 'x')

    def _resultado(self, p):
        return ResultadoArticulo.objects.get(product=p)

    def test_marcas_cambian_la_corrida(self):
        servicio.ejecutar_corrida()
        self.assertGreater(self._resultado(self.aux).valor_sugerido, 0)
        ArticuloConfig.objects.create(product=self.aux, excluir_calculo=True, motivo_exclusion='AUXILIAR')
        ArticuloConfig.objects.create(product=self.kit, plan_gerencia=True, plan_unidades=4)
        servicio.ejecutar_corrida()
        aux, kit = self._resultado(self.aux), self._resultado(self.kit)
        self.assertEqual((aux.marca, aux.valor_sugerido, aux.cantidad_sugerida), ('EXCLUIDO', 0, 0))
        self.assertEqual(aux.abc, 'C')                      # fuera de la poblacion del ABC
        self.assertFalse(Alerta.objects.filter(product=self.aux, vigente=True).exists())
        self.assertEqual((kit.marca, kit.metodo, kit.cantidad_sugerida), ('GERENCIA', pol.GERENCIA, 3))

    def test_sc_no_suman_y_el_transito_se_desglosa(self):
        servicio.ejecutar_corrida()
        r = self._resultado(self.otro)
        self.assertEqual((r.en_transito, r.transito_desglose, r.sc_abierta), (0, {}, 50))

    def test_abc_por_venta(self):
        servicio.ejecutar_corrida()
        self.assertEqual(self._resultado(self.kit).abc_venta, 'A')
        self.assertEqual(self._resultado(self.kit).venta_12m_usd, 90000)
        self.assertEqual(self._resultado(self.otro).abc_venta, 'C')

    def test_pantallas(self):
        servicio.ejecutar_corrida()
        self.client.force_login(self.admin)
        r = self.client.get(reverse('calculadora:marcas'))
        self.assertContains(r, 'KIT1')                       # candidato de gerencia
        self.assertNotContains(r, '>R1<')
        r = self.client.post(reverse('calculadora:marcas'), {'accion': 'excluir', 'codigos': ['4999990001', 'R1'],
                                                             'motivo_exclusion': 'AUXILIAR'})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(ArticuloConfig.objects.filter(excluir_calculo=True).count(), 2)
        self.client.post(reverse('calculadora:marcas'), {'accion': 'excluir', 'codigos': ['KIT1'],
                                                         'motivo_exclusion': 'OTRO'})
        self.assertFalse(ArticuloConfig.objects.filter(product=self.kit, excluir_calculo=True).exists())
        self.client.post(reverse('calculadora:marcas'), {'accion': 'plan', 'codigo': 'KIT1', 'plan_gerencia': 'on',
                                                         'plan_unidades': '4', 'plan_hasta': '2027-03'})
        cfg = ArticuloConfig.objects.get(product=self.kit)
        self.assertEqual((cfg.plan_gerencia, cfg.plan_unidades, cfg.plan_hasta), (True, 4, datetime.date(2027, 3, 1)))
        r = self.client.get(reverse('calculadora:marcas') + '?tab=excluir&search=4999990')
        self.assertContains(r, 'Excluido')
        r = self.client.get(reverse('calculadora:abc_venta') + '?nodo=002')
        self.assertContains(r, 'KIT1')
        self.assertNotContains(r, '>R1<')
        self.assertEqual(self.client.get(reverse('calculadora:articulo', args=['KIT1'])).status_code, 200)


class CaidaPorNodoTest(TestCase):
    def test_sucursal_que_deja_de_comprar(self):
        p = ProductSKU.objects.create(code='C1', description='x')
        hoy = timezone.localdate()
        meses = servicio.meses_cerrados(hoy, 12)
        for m in meses[:8]:                                  # Calama compra 8 meses y luego nada
            ConsumoMensual.objects.create(product=p, bodega='002', mes=m, origen='VENTA', cantidad=3)
        for m in meses:                                      # Santiago sigue
            ConsumoMensual.objects.create(product=p, bodega='013-PP', mes=m, origen='VENTA', cantidad=3)
        caidas = caidas_por_nodo({'C1'}, hoy, Params())
        self.assertEqual([(s, n) for s, n, _ in caidas], [('C1', '002')])
        self.assertIn('Calama: 4 meses sin consumo', caidas[0][2])
        self.assertEqual(caidas_por_nodo({'C1'}, hoy, Params(alerta_caida_meses_nodo=5)), [])


class CargaVentasTest(TestCase):
    def test_carga_suma_facturas_y_nc(self):
        ProductSKU.objects.create(code='V1', description='x')
        d = tempfile.mkdtemp()
        with open(os.path.join(d, 'Ventas Mensuales.txt'), 'w', encoding='utf-8') as f:
            f.write('|codigo_sku|bodega|mes|cantidad|venta_usd|\n|-|-|-|-|-|\n')
            f.write('|V1|002|2026-09|10|1,500.50|\n|V1|002|2026-09|-2|-300|\n|NO|002|2026-09|1|9|\n')
        self.assertEqual(cargar_ventas(d), 1)
        v = VentaMensual.objects.get()
        self.assertEqual((v.cantidad, round(v.monto_usd, 2)), (8, 1200.5))
        self.assertEqual(cargar_ventas(tempfile.mkdtemp()), 0)    # sin archivo no falla


class DesgloseTransitoTest(TestCase):
    """El en camino se separa por origen y suma lo mismo que usa el calculo (SPEC-31 §2)."""

    def test_importacion_nacional_traslado_y_pedido_sin_oc(self):
        from apps.calculadora.models import OCAbierta, Proveedor, ResultadoBodega
        from apps.inventory.stock_actual_models import StockActual
        cat = Category.objects.create(code='G1', name='G', is_active=True, tipo='REPUESTO')
        p = ProductSKU.objects.create(code='T1', description='x', category=cat, unit_cost_usd=1,
                                      fec_creacion_sap=timezone.localdate() - datetime.timedelta(days=900))
        stgo, calama = Warehouse.objects.create(code='013-PP', name='C'), Warehouse.objects.create(code='002', name='Calama')
        Proveedor.objects.create(codigo='EXT', pais='US')
        Proveedor.objects.create(codigo='LOC', pais='CL')
        OCAbierta.objects.create(nro_oc='1', product=p, bodega='002', bodega_sap='000-002', proveedor_codigo='LOC',
                                 cantidad_pendiente=10)                       # OC a la pre-bodega: importacion
        OCAbierta.objects.create(nro_oc='2', product=p, bodega='013-PP', bodega_sap='013', proveedor_codigo='EXT',
                                 cantidad_pendiente=4)                        # proveedor extranjero
        OCAbierta.objects.create(nro_oc='3', product=p, bodega='013-PP', bodega_sap='013', proveedor_codigo='LOC',
                                 cantidad_pendiente=6)                        # nacional
        StockActual.objects.create(codigo='T1', bodega='000-002', stock_disponible=3)    # ya embarcado
        # Calama: OC 10 + transito 3 (pre-bodega) + 5 (T013-002). Santiago: OC 10 + 7 de OnOrder sin OC
        InventoryMetric.objects.create(product=p, warehouse=calama, oc_po_qty=10, stock_transito_inter=8)
        InventoryMetric.objects.create(product=p, warehouse=stgo, oc_po_qty=17)
        servicio.ejecutar_corrida()
        r = ResultadoArticulo.objects.get(product=p)
        self.assertEqual(r.transito_desglose, {'IMPORTACION': 17, 'NACIONAL': 6, 'TRASLADO': 5, 'SIN_OC': 7})
        self.assertEqual(sum(r.transito_desglose.values()), r.en_transito)
        nodos = {b.warehouse.code: b for b in ResultadoBodega.objects.filter(resultado=r)}
        self.assertEqual(nodos['002'].transito_desglose, {'IMPORTACION': 13, 'TRASLADO': 5})
        self.assertEqual(sum(nodos['002'].transito_desglose.values()), nodos['002'].en_transito)


def test_doble_envio_ejemplo_filtros_de_manga():
    """PC de 200 en una sucursal: se compran 200 (OC a su pre-bodega, 100 dias) y mientras tanto
    jefatura traslada 200 desde Santiago. A la sucursal le llegan 400 para 200 comprometidos."""
    from apps.calculadora.alertas import doble_envio
    desglose = {'IMPORTACION': 200, 'TRASLADO': 200}
    disponible = 0 + 400 - 200
    assert doble_envio(desglose, disponible) == (200, 200, 200)
    assert doble_envio({'TRASLADO': 200}, 0) is None            # solo el traslado: cubre el PC
    assert doble_envio({'IMPORTACION': 200, 'TRASLADO': 200}, 50) is None   # la sucursal consume lo demas


def test_el_traslado_cuenta_en_la_red_para_no_comprar_dos_veces():
    # Mismo caso en la red: Santiago ya entrego sus 200 (van en camino) y viene la OC de 200. El PC
    # esta cubierto: si el traslado no contara, la red veria 0 disponible y compraria otra vez
    calama = red.Bodega('002', stock_fisico=0, en_transito=400, comprometido=200)
    r = calcular_articulo(_entrada(consumo_meses=[0] * 12, bodegas=[calama]))
    assert r.compra.disponible_futuro == 200 and r.cantidad_a_comprar == 0
