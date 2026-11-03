"""SPEC-34: Santiago por bodega en el menu Bodegas."""
import datetime

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.calculadora import analisis, servicio
from apps.calculadora.models import ConsumoMensual, ResultadoArticulo, ResultadoBodega
from apps.inventory.models import Category, InventoryMetric, ProductSKU, Warehouse

HOY = datetime.date(2026, 11, 3)


class SantiagoPorBodegaTest(TestCase):
    def setUp(self):
        cat = Category.objects.create(code='G1', name='RPTS', is_active=True, tipo='REPUESTO')
        self.sku = ProductSKU.objects.create(code='A1', description='Filtro', category=cat, unit_cost_usd=10)
        self.ps = Warehouse.objects.create(code='013-PS', name='Postventa', is_active=True)
        self.pp = Warehouse.objects.create(code='013-PP', name='Produccion', is_active=True)
        self.stgo = Warehouse.objects.create(code='013', name='Santiago')
        corrida = servicio.Corrida.objects.create(fecha_calculo=HOY)
        r = ResultadoArticulo.objects.create(corrida=corrida, product=self.sku, letra='R', costo_unitario=10,
                                             plazo_total_dias=30)
        ResultadoBodega.objects.create(resultado=r, warehouse=self.stgo, stock_fisico=12, comprometido=5,
                                       componentes=[['013-PS', 12]], accion='NINGUNA')
        # 013-PS tiene el stock; 013-PP tiene las OF: faltante local, Santiago cubre
        InventoryMetric.objects.create(product=self.sku, warehouse=self.ps, stock_physical=12)
        InventoryMetric.objects.create(product=self.sku, warehouse=self.pp, comp_of_qty=5)
        ConsumoMensual.objects.create(product=self.sku, bodega='013-PP', mes=datetime.date(2026, 9, 1), cantidad=36.5)

    def test_cada_bodega_con_su_posicion(self):
        d = analisis.santiago_por_bodega(hoy=HOY)
        pp, ps = d['013-PP'][0], d['013-PS'][0]
        assert ps['stock'] == 12 and ps['faltante'] == 0
        assert pp['disponible'] == -5 and pp['faltante'] == 5 and pp['faltante_usd'] == 50
        assert abs(pp['consumo_diario'] - 0.1) < 1e-9

    def test_resumen_por_bodega(self):
        res = {x['code']: x for x in analisis.resumen_santiago_por_bodega(analisis.santiago_por_bodega(hoy=HOY))}
        assert res['013-PP']['faltantes'] == 1 and res['013-PS']['faltantes'] == 0

    def test_pantalla_bodega_013(self):
        u = get_user_model().objects.create_superuser('admin', 'a@a.cl', 'x')
        self.client.force_login(u)
        r = self.client.get('/calculadora/bodegas/?bodega=013-PP')
        assert r.status_code == 200
        texto = r.content.decode()
        assert 'es parte de Santiago' in texto and 'A1' in texto
        r = self.client.get('/calculadora/bodegas/')
        assert '013-PS' in r.content.decode()
        assert self.client.get('/calculadora/bodegas/excel/?bodega=013-PP').status_code == 200
