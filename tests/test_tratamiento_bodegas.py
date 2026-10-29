"""SPEC-27: tratamiento del stock de cada bodega en el calculo, editable en Configuracion."""
import pytest
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from apps.calc.red import Bodega
from apps.calculadora import servicio
from apps.calculadora.cargadores import cargar_bodegas
from apps.data_ingestion.warehouses import NO_CUENTA, STOCK, TRANSITO, tratamiento_por_defecto
from apps.inventory.models import Category, ProductSKU, Warehouse
from apps.inventory.stock_actual_models import StockActual


@pytest.mark.parametrize('codigo, activa, esperado', [
    ('013', True, (STOCK, '013')),                  # el propio nodo Santiago
    ('013-PP', True, (STOCK, '013')),
    ('002', True, (STOCK, '002')),
    ('013-IN', False, (NO_CUENTA, '013')),          # de la red pero excluida
    ('000', False, (TRANSITO, '013')),              # pre-bodega central
    ('000-022', False, (TRANSITO, '002-02')),       # pre-bodega Antofagasta
    ('T002-013', False, (TRANSITO, '013')),
    ('T013-022', False, (TRANSITO, '002-02')),
    ('013-NC', False, (NO_CUENTA, '')),
    ('013-NC_E', False, (NO_CUENTA, '')),
    ('0EX', False, (NO_CUENTA, '')),
    ('960', False, (NO_CUENTA, '')),
    ('902', False, (NO_CUENTA, '')),
])
def test_tratamiento_por_defecto(codigo, activa, esperado):
    assert tratamiento_por_defecto(codigo, activa)[:2] == esperado


def test_motivos_acordados():
    assert 'Cobranzas' in tratamiento_por_defecto('013-NC')[2]
    assert 'COMEX' in tratamiento_por_defecto('0EX')[2]
    assert 'Consignación' in tratamiento_por_defecto('966')[2]
    assert 'Consignación' in tratamiento_por_defecto('957')[2]       # TRECK, KDM: 95x


class TestAplicarAjustes:
    def test_suma_stock_a_una_sucursal_existente(self):
        bodegas = [Bodega('002', stock_fisico=5, en_transito=1)]
        bodegas, stock_013, neto = servicio._aplicar_ajustes(bodegas, 0, {'002': 3}, {'002': 2})
        assert (bodegas[0].stock_fisico, bodegas[0].en_transito) == (8, 3)
        assert neto == 2

    def test_crea_la_sucursal_si_no_tenia_posicion(self):
        bodegas, _, _ = servicio._aplicar_ajustes([], 0, {'008': 4}, {})
        assert bodegas[0].codigo == '008' and bodegas[0].stock_fisico == 4

    def test_santiago_va_a_la_013_y_nunca_queda_negativo(self):
        bodegas, stock_013, neto = servicio._aplicar_ajustes([], 2, {'013': -5}, {'013': -3})
        assert bodegas == [] and stock_013 == 0 and neto == -3


class TestAjustesPorTratamiento(TestCase):
    def setUp(self):
        for code in ('0EX', 'T002-013', '013-PP'):
            Warehouse.objects.create(code=code, name=code, is_active=code == '013-PP')
        StockActual.objects.create(codigo='A', bodega='0EX', stock_disponible=7)
        StockActual.objects.create(codigo='A', bodega='T002-013', stock_disponible=4)
        StockActual.objects.create(codigo='A', bodega='013-PP', stock_disponible=9)

    def test_sin_configuracion_manual_no_hay_ajustes(self):
        stock, transito = servicio.ajustes_por_tratamiento()
        assert not stock and not transito

    def test_bodega_que_no_contaba_pasa_a_stock_de_un_nodo(self):
        Warehouse.objects.filter(code='0EX').update(tratamiento=STOCK, nodo_destino='013')
        stock, transito = servicio.ajustes_por_tratamiento()
        assert dict(stock['A']) == {'013': 7} and not transito

    def test_transito_que_deja_de_contar_se_resta_de_su_destino(self):
        Warehouse.objects.filter(code='T002-013').update(tratamiento=NO_CUENTA)
        stock, transito = servicio.ajustes_por_tratamiento()
        assert dict(transito['A']) == {'013': -4} and not stock

    def test_transito_redirigido_a_otro_nodo(self):
        Warehouse.objects.filter(code='T002-013').update(tratamiento=TRANSITO, nodo_destino='010')
        _, transito = servicio.ajustes_por_tratamiento()
        assert dict(transito['A']) == {'013': -4, '010': 4}

    def test_las_bodegas_de_la_red_no_usan_tratamiento_manual(self):
        Warehouse.objects.filter(code='013-PP').update(tratamiento=NO_CUENTA)
        stock, transito = servicio.ajustes_por_tratamiento()
        assert not stock and not transito


class TestPantallaBodegas(TestCase):
    @classmethod
    def setUpTestData(cls):
        cat = Category.objects.create(code='G1', name='Grupo', tipo='REPUESTO', is_active=True)
        ProductSKU.objects.create(code='A', description='Art', category=cat, unit_cost_usd=10)
        for code, activa in (('013-PP', True), ('013-IN', False), ('0EX', False), ('013', False)):
            Warehouse.objects.create(code=code, name=f'{code} - Bodega', is_active=activa)
        StockActual.objects.create(codigo='A', bodega='0EX', stock_disponible=3)
        cls.admin = User.objects.create_superuser('admin', 'a@a.cl', 'x')
        cls.lector = User.objects.create_user('lector', 'l@a.cl', 'x')

    def _post(self, user, code, valor, motivo=''):
        self.client.force_login(user)
        return self.client.post(reverse('inventory:configuracion'),
                                {'action': 'set_tratamiento', 'warehouse_code': code, 'valor': valor, 'motivo': motivo},
                                HTTP_X_REQUESTED_WITH='XMLHttpRequest')

    def test_pantalla_muestra_el_tratamiento_y_el_valor_en_alcance(self):
        self.client.force_login(self.admin)
        html = self.client.get(reverse('inventory:configuracion') + '?tab=bodegas').content.decode()
        assert 'Exportación: ya vendido' in html
        assert 'Es el nodo Santiago: siempre cuenta' in html
        assert '>30<' in html                         # 3 u x USD 10 en el alcance

    def test_cambia_una_bodega_fuera_de_la_red_con_registro(self):
        r = self._post(self.admin, '0EX', 'STOCK|013', 'Stock devuelto por COMEX')
        assert r.json()['texto'] == 'Stock de Santiago' and r.json()['manual']
        w = Warehouse.objects.get(code='0EX')
        assert (w.tratamiento, w.nodo_destino, w.motivo, w.modificado_por) == (STOCK, '013', 'Stock devuelto por COMEX', self.admin)
        assert w.tratamiento_efectivo[:2] == (STOCK, '013')

    def test_volver_a_automatico(self):
        self._post(self.admin, '0EX', 'TRANSITO|002')
        r = self._post(self.admin, '0EX', '')
        assert r.json()['texto'] == 'No cuenta' and not r.json()['manual']
        assert Warehouse.objects.get(code='0EX').tratamiento == ''

    def test_bodega_de_la_red_se_incluye_o_excluye(self):
        r = self._post(self.admin, '013-IN', 'STOCK')
        assert r.json()['texto'] == 'Stock de Santiago'
        assert Warehouse.objects.get(code='013-IN').is_active

    def test_valida_opciones(self):
        assert self._post(self.admin, '0EX', 'STOCK|999').status_code == 400
        assert self._post(self.admin, '013-IN', 'TRANSITO|002').status_code == 400
        assert self._post(self.admin, '013', 'NO_CUENTA|').status_code == 400

    def test_sin_permiso_no_cambia(self):
        assert self._post(self.lector, '0EX', 'STOCK|013').status_code == 403
        assert Warehouse.objects.get(code='0EX').tratamiento == ''


class TestCatalogoDeBodegas(TestCase):
    def test_crea_excluidas_las_bodegas_con_stock_que_faltan(self):
        Warehouse.objects.create(code='013-PP', name='viejo', is_active=True)
        StockActual.objects.create(codigo='A', bodega='TANF-CAL', bodega_nombre='TRANSITO ANTOFAGASTA - CALAMA',
                                   stock_disponible=5)
        cargar_bodegas(data_dir='no-existe')
        w = Warehouse.objects.get(code='TANF-CAL')
        assert not w.is_active and 'TRANSITO ANTOFAGASTA' in w.name
        assert Warehouse.objects.get(code='013-PP').is_active


class TestDePuntaAPunta(TestCase):
    """El tratamiento elegido llega a las bodegas del articulo que recibe el nucleo."""

    def test_stock_de_exportacion_pasa_a_santiago(self):
        import datetime
        from apps.calculadora.parametros import Resolutor
        cat = Category.objects.create(code='G1', name='Grupo', tipo='REPUESTO', is_active=True)
        sku = ProductSKU.objects.create(code='A', description='Art', category=cat, unit_cost_usd=10)
        Warehouse.objects.create(code='0EX', name='0EX', is_active=False)
        StockActual.objects.create(codigo='A', bodega='0EX', stock_disponible=6)
        hoy = datetime.date(2026, 10, 29)

        def stock_santiago():
            e, _, _ = servicio._entrada(servicio.Datos(hoy, Resolutor(), producto=sku), sku, 'C')
            return sum(b.stock_fisico for b in e.bodegas if b.es_santiago)

        assert stock_santiago() == 0
        Warehouse.objects.filter(code='0EX').update(tratamiento=STOCK, nodo_destino='013')
        assert stock_santiago() == 6
