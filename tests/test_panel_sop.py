"""SPEC-28: Panel S&OP con las cifras de la Calculadora (fusion de Dashboard y Analitica)."""
import datetime

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.calculadora.models import ConsumoMensual
from apps.calculadora.servicio import ejecutar_corrida, meses_cerrados
from apps.dashboard import panel
from apps.inventory.models import Category, InventoryMetric, ProductSKU, Warehouse

HOY = timezone.localdate()


class PanelTest(TestCase):
    """Un articulo con stock y consumo en Santiago y Antofagasta, otro sin stock con consumo
    (debe comprarse) y uno sin consumo (O)."""

    @classmethod
    def setUpTestData(cls):
        cat = Category.objects.create(code='G1', name='RPTS', is_active=True, tipo='REPUESTO')
        otra = Category.objects.create(code='G2', name='OTRO', is_active=True, tipo='REPUESTO')
        for code in ('013-PP', '002-02'):
            Warehouse.objects.create(code=code, name=code)
        creado = datetime.date(2020, 1, 1)
        a = ProductSKU.objects.create(code='A', description='Con stock', category=cat, unit_cost_usd=5,
                                      lead_time_days=20, fec_creacion_sap=creado)
        b = ProductSKU.objects.create(code='B', description='Sin stock', category=cat, unit_cost_usd=40,
                                      lead_time_days=20, fec_creacion_sap=creado)
        ProductSKU.objects.create(code='C', description='Sin consumo', category=otra, unit_cost_usd=3,
                                  lead_time_days=20, fec_creacion_sap=creado)
        for mes in meses_cerrados(HOY, 12):
            ConsumoMensual.objects.create(product=a, bodega='013-PP', mes=mes, cantidad=6)
            ConsumoMensual.objects.create(product=a, bodega='002-02', mes=mes, cantidad=2)
            ConsumoMensual.objects.create(product=b, bodega='013-PP', mes=mes, cantidad=10)
        InventoryMetric.objects.create(product=a, warehouse=Warehouse.objects.get(code='013-PP'), stock_physical=200)
        InventoryMetric.objects.create(product=a, warehouse=Warehouse.objects.get(code='002-02'), stock_physical=3)
        cls.corrida = ejecutar_corrida(hoy=HOY)
        cls.admin = User.objects.create_superuser('admin', 'a@a.cl', 'x')

    def test_sin_filtros_coincide_con_el_resumen_de_la_corrida(self):
        k, r = panel.indicadores(self.corrida)['kpi'], self.corrida.resumen
        for propio, de_corrida in (('articulos', 'articulos'), ('comprar', 'comprar'),
                                   ('necesita_compra', 'necesita_compra'), ('excepciones', 'excepciones'),
                                   ('urgentes', 'urgentes'), ('compra_hoy_usd', 'valor_sugerido'),
                                   ('quiebre_usd', 'quiebre_real_usd'), ('brecha_usd', 'brecha_objetivo_usd')):
            self.assertAlmostEqual(k[propio], r[de_corrida], places=2, msg=propio)

    def test_stock_valorizado_y_por_nodo(self):
        d = panel.indicadores(self.corrida)
        self.assertAlmostEqual(d['kpi']['stock_usd'], 203 * 5)
        nodos = {n['nodo']: n for n in d['nodos']}
        self.assertAlmostEqual(nodos['013']['stock_usd'], 200 * 5)
        self.assertAlmostEqual(nodos['002-02']['stock_usd'], 3 * 5)

    def test_filtros_por_grupo_y_politica(self):
        self.assertEqual(panel.indicadores(self.corrida, {'grupo': 'G2'})['kpi']['articulos'], 1)
        solo_r = panel.indicadores(self.corrida, {'letra': 'R'})
        por_letra = {l['letra']: l['articulos'] for l in solo_r['letras']}
        self.assertEqual(por_letra['R'], solo_r['kpi']['articulos'])
        self.assertEqual(por_letra['O'] + por_letra['P'] + por_letra['E'], 0)
        vacio = panel.indicadores(self.corrida, {'grupo': 'NO-EXISTE'})['kpi']
        self.assertEqual((vacio['articulos'], vacio['compra_hoy_usd']), (0, 0))

    def test_cobertura_solo_cuenta_los_que_se_reponen(self):
        d = panel.indicadores(self.corrida)
        repone = sum(l['articulos'] for l in d['letras'] if l['letra'] in ('R', 'E'))
        self.assertEqual(sum(c['articulos'] for c in d['cobertura']), repone)

    def test_pantalla_y_redireccion_de_analitica(self):
        self.client.force_login(self.admin)
        html = self.client.get(reverse('dashboard:home')).content.decode()
        self.assertIn(f'corrida <b>#{self.corrida.pk}</b>', html)
        self.assertIn('Compra sugerida hoy', html)
        r = self.client.get(reverse('dashboard:analytics') + '?letra=R')
        self.assertRedirects(r, reverse('dashboard:home') + '?letra=R')

    def test_sin_corrida_muestra_aviso(self):
        from apps.calculadora.models import Corrida
        Corrida.objects.all().delete()
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(reverse('dashboard:home')), 'Todavía no hay una corrida')
