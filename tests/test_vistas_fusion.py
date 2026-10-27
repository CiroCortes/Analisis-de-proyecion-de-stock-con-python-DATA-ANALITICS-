"""Pantallas de la fusion del Recomendador (SPEC-19 §4, §6, §7.2): Bodegas, Segmentacion y Guia."""
import datetime

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.calculadora import servicio
from apps.calculadora.glosario import GLOSARIO
from apps.calculadora.models import ConsumoMensual, ResultadoArticulo
from apps.inventory.models import Category, InventoryMetric, ProductSKU, Warehouse

XLSX = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'


class VistasFusionTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cat = Category.objects.create(code='GRP-101', name='RPTS. EQ. IZAJE', is_active=True, tipo='REPUESTO')
        pp = Warehouse.objects.create(code='013-PP', name='Central')
        w03 = Warehouse.objects.create(code='013-03', name='Emergencias')
        w002 = Warehouse.objects.create(code='002', name='Calama')
        # Articulo estable de alto valor (AX): consumo parejo 10/mes
        cls.estable = ProductSKU.objects.create(code='EST1', description='Estable', category=cat, unit_cost_usd=100,
                                                lead_time_days=20, fec_creacion_sap=datetime.date(2020, 1, 1))
        # Articulo erratico de bajo valor: consumo solo en 3 meses
        cls.erratico = ProductSKU.objects.create(code='ERR1', description='Erratico', category=cat, unit_cost_usd=1,
                                                 lead_time_days=20, fec_creacion_sap=datetime.date(2020, 1, 1))
        meses = servicio.meses_cerrados(timezone.localdate(), 12)
        for i, mes in enumerate(meses):
            ConsumoMensual.objects.create(product=cls.estable, bodega='013-PP', mes=mes, cantidad=10)
            if i in (2, 6, 10):
                ConsumoMensual.objects.create(product=cls.erratico, bodega='002', mes=mes, cantidad=12)
        InventoryMetric.objects.create(product=cls.estable, warehouse=pp, stock_physical=8, comp_of_qty=1)
        InventoryMetric.objects.create(product=cls.estable, warehouse=w03, stock_physical=4)
        InventoryMetric.objects.create(product=cls.estable, warehouse=w002, comp_pc_qty=2)
        InventoryMetric.objects.create(product=cls.erratico, warehouse=w002, stock_physical=1)
        servicio.ejecutar_corrida()
        cls.user = User.objects.create_user('comprador', password='x')

    def setUp(self):
        self.client.force_login(self.user)

    def test_anonimo_redirige(self):
        self.client.logout()
        for nombre in ('bodegas', 'segmentacion', 'guia', 'bodegas_excel'):
            r = self.client.get(reverse(f'calculadora:{nombre}'))
            self.assertEqual(r.status_code, 302, nombre)
            self.assertIn('/auth/', r['Location'])

    def test_bodegas_por_defecto_muestra_solo_acciones(self):
        r = self.client.get(reverse('calculadora:bodegas'))
        self.assertEqual(r.status_code, 200)
        codigos = {(b.warehouse.code, b.resultado.product_id) for b in r.context['filas']}
        # Calama tiene faltante (comprometido 2, disponible -2) y se cubre por traslado
        self.assertIn(('002', 'EST1'), codigos)
        fila = next(b for b in r.context['filas'] if b.warehouse.code == '002' and b.resultado.product_id == 'EST1')
        self.assertIn(fila.accion, ('TRASLADAR', 'TRASLADAR_PARCIAL'))
        self.assertIn('desde', fila.origenes_txt)
        # 013-03 no tiene faltante ni accion: no aparece sin "ver todo"
        self.assertNotIn(('013-03', 'EST1'), codigos)
        tarjetas = {t['code']: t for t in r.context['tarjetas']}
        self.assertEqual(tarjetas['002']['riesgo'], 1)
        self.assertGreater(tarjetas['002']['quiebre_usd'], 0)
        self.assertGreaterEqual(tarjetas['002']['entran'], 1)
        # Santiago antes que sucursales
        zonas = [t['zona'] for t in r.context['tarjetas']]
        self.assertEqual(zonas, sorted(zonas, key=lambda z: 0 if z == 'SANTIAGO' else 1))

    def test_bodegas_filtros_zona_accion_y_todo(self):
        r = self.client.get(reverse('calculadora:bodegas'), {'zona': 'SANTIAGO', 'todo': '1'})
        self.assertTrue(r.context['filas'])
        self.assertTrue(all(b.warehouse.code.startswith('013') for b in r.context['filas']))
        r = self.client.get(reverse('calculadora:bodegas'), {'zona': 'SUCURSAL'})
        self.assertTrue(all(b.warehouse.code == '002' for b in r.context['filas']))
        r = self.client.get(reverse('calculadora:bodegas'), {'accion': 'ESPERA_COMPRA'})
        self.assertTrue(all(b.accion == 'ESPERA_COMPRA' for b in r.context['filas']))
        r = self.client.get(reverse('calculadora:bodegas'), {'search': 'NOEXISTE'})
        self.assertEqual(r.context['total'], 0)

    def test_bodegas_excel(self):
        r = self.client.get(reverse('calculadora:bodegas_excel'), {'zona': 'SUCURSAL'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], XLSX)

    def test_segmentacion_ubica_cada_articulo_en_su_celda(self):
        est = ResultadoArticulo.objects.get(product=self.estable)
        err = ResultadoArticulo.objects.get(product=self.erratico)
        r = self.client.get(reverse('calculadora:segmentacion'), {'alcance': 'todo'})
        self.assertEqual(r.status_code, 200)
        celdas = {(c['abc'], c['xyz']): c for fila in r.context['filas'] for c in fila['celdas']}
        self.assertEqual(est.xyz, 'X')
        self.assertEqual(celdas[(est.abc, est.xyz)]['n'], 1 + (1 if (err.abc, err.xyz) == (est.abc, est.xyz) else 0))
        self.assertGreaterEqual(celdas[(err.abc, err.xyz)]['n'], 1)
        self.assertEqual(sum(c['n'] for c in celdas.values()), 2)
        self.assertContains(r, f'grilla/?abc={est.abc}&xyz={est.xyz}&todo=1')
        self.assertEqual(celdas[(est.abc, est.xyz)]['stock'], 1200.0)   # 12 u fisicas x USD 100

    def test_segmentacion_alcance_re_excluye_otras_letras(self):
        letras = set(ResultadoArticulo.objects.values_list('letra', flat=True))
        r = self.client.get(reverse('calculadora:segmentacion'), {'alcance': 're'})
        total = sum(c['n'] for fila in r.context['filas'] for c in fila['celdas'])
        self.assertEqual(total, ResultadoArticulo.objects.filter(letra__in=('R', 'E')).count())
        self.assertTrue(letras)

    def test_guia_tiene_cada_termino_con_su_ancla(self):
        r = self.client.get(reverse('calculadora:guia'))
        self.assertEqual(r.status_code, 200)
        html = r.content.decode()
        for clave in GLOSARIO:
            self.assertIn(f'id="{clave}"', html, clave)
        self.assertContains(r, 'Cómo usar la Calculadora en 5 pasos')
        self.assertContains(r, 'De dónde salen los datos')
