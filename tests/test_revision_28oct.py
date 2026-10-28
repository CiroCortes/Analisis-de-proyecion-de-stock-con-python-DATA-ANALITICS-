"""Defectos encontrados en la revision del 28-oct-2026 (uno por test, con el caso que los mostraba)."""
import datetime

from django.test import TestCase
from django.utils import timezone

from apps.calc import politica as pol
from apps.calc import red
from apps.calc.consumo import calcular_consumo
from apps.calc.motor import EntradaArticulo, calcular_articulo
from apps.calc.params import Params
from apps.calculadora import servicio
from apps.calculadora.alertas import _reglas_articulo
from apps.calculadora.models import ConsumoMensual, LineaSolicitud, Proveedor, SolicitudCompra
from apps.calculadora.parametros import Resolutor
from apps.calculadora.servicio import Datos, _entrada, meses_cerrados
from apps.inventory.models import Category, InventoryMetric, ProductSKU, Warehouse

HOY = datetime.date(2026, 10, 28)


def test_nuevo_sin_historia_recibe_su_minimo():
    # Creado hace 3 meses, casi sin consumo y sin PC/OF: antes quedaba O y sin compra
    e = EntradaArticulo(codigo='N', hoy=HOY, consumo_meses=[0] * 10 + [2, 0], minimo_nuevo=7,
                        fecha_creacion=datetime.date(2026, 8, 1), costo=1)
    r = calcular_articulo(e)
    assert r.es_nuevo and r.politica.metodo == pol.NUEVO
    assert r.compra.cantidad_sugerida == 7


def test_nuevo_con_pedido_sigue_siendo_p():
    e = EntradaArticulo(codigo='N', hoy=HOY, minimo_nuevo=7, fecha_creacion=datetime.date(2026, 8, 1),
                        bodegas=[red.Bodega('002', comprometido=3)])
    assert calcular_articulo(e).politica.metodo == pol.A_PEDIDO


def test_consumo_diario_con_24_meses_de_historia():
    p = Params(meses_historia_consumo=24)
    c = calcular_consumo([10] * 24, p)
    assert c.consumo_promedio_mes == 10
    assert abs(c.consumo_diario * 365 / 12 - 10) < 1e-9    # antes: el doble
    assert c.meses_con_consumo_12m == 12                    # umbrales R "de 12 meses"


def test_consumo_diario_con_12_meses_no_cambia():
    c = calcular_consumo([10] * 12, Params())
    assert abs(c.consumo_diario - 120 / 365) < 1e-12


class _Base(TestCase):
    def setUp(self):
        cat = Category.objects.create(code='GRP-1', name='RPTS', is_active=True, tipo='REPUESTO')
        self.w002 = Warehouse.objects.create(code='002', name='Calama')
        self.sku = ProductSKU.objects.create(code='R1', description='Rotacion', category=cat, unit_cost_usd=10,
                                             lead_time_days=28, fec_creacion_sap=datetime.date(2020, 1, 1))
        for mes in meses_cerrados(HOY, 12):
            ConsumoMensual.objects.create(product=self.sku, bodega='002', mes=mes, cantidad=30)


class TransitoEntreBodegasTest(_Base):
    def test_stock_en_camino_entra_en_la_proyeccion(self):
        # 0 fisico, 40 en camino a 002 (bodega T): antes la serie quebraba el dia 1
        InventoryMetric.objects.create(product=self.sku, warehouse=self.w002, stock_transito_inter=40)
        e, prov, prox = _entrada(Datos(HOY, Resolutor(), producto=self.sku), self.sku, 'A')
        assert (2, 40) in e.llegadas
        r = calcular_articulo(e)
        assert r.serie[5] > 0


class SolicitudExportadaTest(_Base):
    def test_exportada_despues_de_la_carga_de_sc_sigue_en_transito(self):
        prov = Proveedor.objects.create(codigo='P1')
        s = SolicitudCompra.objects.create(proveedor=prov, fecha=HOY, estado=SolicitudCompra.APROBADA,
                                           aprobada_en=timezone.now() - datetime.timedelta(hours=2))
        LineaSolicitud.objects.create(solicitud=s, product=self.sku, cantidad_sugerida=25, cantidad_final=25)
        # TXT de SC cargado hace 1 hora (despues de aprobar, antes de exportar)
        carga = (timezone.now() - datetime.timedelta(hours=1)).timestamp()
        original = servicio._mtime_carga_sc
        servicio._mtime_carga_sc = lambda: carga
        try:
            from apps.calculadora.solicitudes import marcar_exportadas
            marcar_exportadas([s])
            assert Datos(HOY, Resolutor(), producto=self.sku).solicitado['R1'] == 25
        finally:
            servicio._mtime_carga_sc = original


def test_alerta_urgente_p_solo_con_quiebre_real():
    class R:
        pass
    r = R()
    for k, v in dict(product_id='P1', letra='P', stock_maximo=0, disponible_futuro=0, comprometido=5,
                     stock_seguridad=0, fecha_bajo_ss=None, oc_atrasada=False, costo_unitario=1,
                     consumo_meses=[0] * 12, consumo_promedio_mes=0, fecha_quiebre_proyectada=None,
                     excepcion=False, avisos=[], xyz='Z', es_inmovilizado=False, es_nuevo=False,
                     necesita_compra=False, proveedor_id=None, es_critico=False).items():
        setattr(r, k, v)
    # P con stock 5 y compromiso 5: cubierto, no es urgente (antes salia ALTA)
    assert not any(t == 'URGENTE' for _, t, _, _ in _reglas_articulo(r, Params(), 'oct-26'))
    r.disponible_futuro = -1
    assert any(t == 'URGENTE' for _, t, _, _ in _reglas_articulo(r, Params(), 'oct-26'))


def test_nuevo_sin_minimo_y_sin_historia_no_se_compra_por_proyeccion():
    # Sin minimo manual sigue como O: no infla compras fuera de calendario
    e = EntradaArticulo(codigo='N', hoy=HOY, consumo_meses=[0] * 10 + [2, 0],
                        fecha_creacion=datetime.date(2026, 8, 1), costo=1, es_dia_compra=False)
    r = calcular_articulo(e)
    assert r.politica.metodo == pol.SIN_COMPRA and r.cantidad_a_comprar == 0
