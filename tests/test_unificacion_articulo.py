"""Ficha unica del articulo y recalculo unico (SPEC-20): todos los enlaces llevan a la
Calculadora y ningun boton deja publicados los numeros del motor anterior."""
import datetime
import re
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.calculadora.models import ConsumoMensual, Corrida, ResultadoArticulo
from apps.calculadora.servicio import meses_cerrados
from apps.inventory.models import (Category, InventoryMetric, ProductionOrderMovement, ProductSKU,
                                   SalesOrderMovement, StockProjection, Warehouse)

TEMPLATES = Path(settings.BASE_DIR) / 'templates'
# Unicas pantallas que pueden enlazar al Recomendador antiguo (escenario anterior, SPEC-19 §7.4)
RECOMENDADOR_PERMITIDO = {'calculadora/indicadores.html', 'purchasing/list.html'}


class EnlacesTest(TestCase):
    def _plantillas_con(self, patron):
        return {p.relative_to(TEMPLATES).as_posix() for p in TEMPLATES.rglob('*.html')
                if re.search(patron, p.read_text(encoding='utf-8'))}

    def test_ninguna_plantilla_enlaza_la_ficha_antigua(self):
        self.assertEqual(self._plantillas_con(r"url 'inventory:sku_detail'"), set())

    def test_recomendador_solo_como_escenario_anterior(self):
        self.assertLessEqual(self._plantillas_con(r"url 'purchasing:list'"), RECOMENDADOR_PERMITIDO)


class FichaUnicaTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cat = Category.objects.create(code='GRP-1', name='RPTS. EQ. IZAJE', is_active=True, tipo='REPUESTO')
        cls.pp = Warehouse.objects.create(code='013-PP', name='Central')
        cls.sku = ProductSKU.objects.create(code='R1', description='Rotacion', category=cat, unit_cost_usd=10,
                                            lead_time_days=28, fec_creacion_sap=datetime.date(2020, 1, 1))
        for mes in meses_cerrados(timezone.localdate(), 12):
            ConsumoMensual.objects.create(product=cls.sku, bodega='013-PP', mes=mes, cantidad=9)
        InventoryMetric.objects.create(product=cls.sku, warehouse=cls.pp, stock_physical=5)
        SalesOrderMovement.objects.create(order_number='PC-777', product=cls.sku, quantity=3, warehouse='013-PP',
                                          delivery_date=datetime.date(2026, 9, 1), client_name='Minera Uno')
        SalesOrderMovement.objects.create(order_number='PC-ABIERTO', product=cls.sku, quantity=1, status='Abierto')
        ProductionOrderMovement.objects.create(of_number='OF-555', product=cls.sku, quantity_delivered=4,
                                               end_date=datetime.date(2026, 8, 1))
        cls.admin = User.objects.create_superuser('admin', 'a@a.cl', 'x')

    def setUp(self):
        self.client.force_login(self.admin)

    def test_url_antigua_redirige_a_la_calculadora(self):
        r = self.client.get(reverse('inventory:sku_detail', args=['R1']))
        self.assertRedirects(r, reverse('calculadora:articulo', args=['R1']))

    def test_url_antigua_exige_sesion(self):
        self.client.logout()
        r = self.client.get(reverse('inventory:sku_detail', args=['R1']))
        self.assertIn('/auth/', r['Location'])

    def test_ficha_muestra_movimientos_cerrados(self):
        r = self.client.get(reverse('calculadora:articulo', args=['R1']))
        self.assertContains(r, 'PC-777')
        self.assertContains(r, 'Minera Uno')
        self.assertContains(r, 'OF-555')
        self.assertNotContains(r, 'PC-ABIERTO')   # los abiertos ya salen en Compromisos

    def test_recalcular_en_configuracion_publica_la_calculadora(self):
        """El boton Recalcular S&OP corria solo el motor anterior y pisaba lo publicado."""
        r = self.client.post(reverse('inventory:configuracion'), {'action': 'recalculate_sop'})
        self.assertEqual(r.status_code, 302)
        corrida = Corrida.objects.latest('pk')
        self.assertEqual(corrida.estado, Corrida.OK)
        self.assertTrue(corrida.resumen['publicado'])
        res = ResultadoArticulo.objects.get(product=self.sku)
        self.assertEqual(StockProjection.objects.get(product=self.sku, warehouse__code='013').rop, res.punto_pedido)
