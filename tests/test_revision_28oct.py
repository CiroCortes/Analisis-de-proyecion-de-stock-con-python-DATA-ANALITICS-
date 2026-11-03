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


class RevisionNov3Test(_Base):
    """Revision del 3-nov (SPEC-32): duplicados al regenerar y exportadas sin OC."""

    def _exportada(self, hace_dias=0):
        from apps.calculadora.solicitudes import marcar_exportadas
        prov, _ = Proveedor.objects.get_or_create(codigo='P1')
        s = SolicitudCompra.objects.create(proveedor=prov, fecha=HOY, estado=SolicitudCompra.APROBADA,
                                           aprobada_en=timezone.now())
        LineaSolicitud.objects.create(solicitud=s, product=self.sku, cantidad_sugerida=25, cantidad_final=25)
        marcar_exportadas([s])
        if hace_dias:
            SolicitudCompra.objects.filter(pk=s.pk).update(
                exportada_en=timezone.now() - datetime.timedelta(days=hace_dias))
        return s

    def _solicitado(self):
        hoy = timezone.localdate()
        return Datos(hoy, Resolutor(), producto=self.sku).solicitado['R1']

    def test_exportada_sigue_contando_tras_la_carga_de_sc_hasta_que_hay_oc(self):
        from apps.calculadora.models import OCAbierta
        self._exportada()
        original = servicio._mtime_carga_sc
        servicio._mtime_carga_sc = lambda: timezone.now().timestamp() + 60   # SC cargada despues
        try:
            assert self._solicitado() == 25          # antes: 0 y se volvia a sugerir
            OCAbierta.objects.create(product=self.sku, nro_oc='9001', bodega='013-PP', proveedor_codigo='P1',
                                     fecha_oc=timezone.localdate(), cantidad_pendiente=25)
            assert self._solicitado() == 0           # la OC ya esta en camino: no se cuenta dos veces
        finally:
            servicio._mtime_carga_sc = original

    def test_oc_anterior_o_de_otro_proveedor_no_la_reemplaza(self):
        from apps.calculadora.models import OCAbierta
        self._exportada()
        OCAbierta.objects.create(product=self.sku, nro_oc='8001', bodega='013-PP', proveedor_codigo='P1',
                                 fecha_oc=timezone.localdate() - datetime.timedelta(days=20), cantidad_pendiente=5)
        OCAbierta.objects.create(product=self.sku, nro_oc='8002', bodega='013-PP', proveedor_codigo='OTRO',
                                 fecha_oc=timezone.localdate(), cantidad_pendiente=5)
        assert self._solicitado() == 25

    def test_exportada_vencida_deja_de_contar(self):
        self._exportada(hace_dias=46)
        assert self._solicitado() == 0

    def test_regenerar_el_mismo_dia_no_marca_duplicados_contra_su_borrador(self):
        from apps.calculadora.models import ResultadoArticulo
        from apps.calculadora.solicitudes import generar
        prov = Proveedor.objects.create(codigo='P2')
        corrida = servicio.Corrida.objects.create(fecha_calculo=HOY)
        ResultadoArticulo.objects.create(corrida=corrida, product=self.sku, proveedor=prov, comprar=True,
                                         cantidad_sugerida=10)
        generar(hoy=HOY)
        generar(hoy=HOY)
        lineas = LineaSolicitud.objects.filter(solicitud__fecha=HOY, product=self.sku)
        assert lineas.count() == 1 and not lineas.first().duplicada_reciente
