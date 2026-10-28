"""Vistas de planificacion de la Calculadora (SPEC-18 §4.1): panel, grilla, articulo,
indicadores."""
import datetime

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.calculadora import servicio
from apps.calculadora.models import ArticuloConfig, ConsumoMensual, Corrida, ResultadoArticulo
from apps.inventory.models import Category, InventoryMetric, ProductSKU, Warehouse

XLSX = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'


class VistasPlanificacionTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cat = Category.objects.create(code='GRP-101', name='RPTS. EQ. IZAJE', is_active=True, tipo='REPUESTO')
        wh = Warehouse.objects.create(code='013-PP', name='Central')
        hoy = timezone.localdate()
        meses = servicio.meses_cerrados(hoy, 12)
        cls.sku = ProductSKU.objects.create(code='A1', description='Filtro hidraulico', category=cat,
                                            unit_cost_usd=10, lead_time_days=20, sap_group_code='101',
                                            sap_group_name='RPTS. EQ. IZAJE',
                                            fec_creacion_sap=hoy - datetime.timedelta(days=900))
        cls.otro = ProductSKU.objects.create(code='B2', description='Perno', category=cat, unit_cost_usd=1,
                                             fec_creacion_sap=hoy - datetime.timedelta(days=900))
        InventoryMetric.objects.create(product=cls.sku, warehouse=wh, stock_physical=1, comp_pc_qty=0)
        InventoryMetric.objects.create(product=cls.otro, warehouse=wh, stock_physical=500)
        for m in meses:
            ConsumoMensual.objects.create(product=cls.sku, bodega='013-PP', mes=m, origen='VENTA', cantidad=10)
            ConsumoMensual.objects.create(product=cls.sku, bodega='013-PP', mes=m, origen='OF', cantidad=2)
        servicio.ejecutar_corrida()
        cls.admin = User.objects.create_superuser('admin', 'a@a.cl', 'x')
        cls.normal = User.objects.create_user('comprador', 'c@a.cl', 'x')

    def setUp(self):
        self.client.force_login(self.admin)

    def test_anonimo_redirige_a_login(self):
        self.client.logout()
        for nombre in ('panel', 'grilla', 'indicadores'):
            r = self.client.get(reverse(f'calculadora:{nombre}'))
            self.assertEqual(r.status_code, 302)
            self.assertIn('/auth/', r['Location'])

    def test_panel(self):
        r = self.client.get(reverse('calculadora:panel'))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Recalcular ahora')
        self.assertContains(r, 'Qué hay que hacer hoy')
        self.assertContains(r, 'Detalle de la corrida')
        self.assertContains(r, 'A1')

    def test_panel_tarjetas_y_semaforo(self):
        from apps.calculadora.models import Alerta, CargaDatos
        CargaDatos.objects.create(tabla='consumo_mensual', fuente='PC_OF')
        CargaDatos.objects.create(tabla='plazos_oc', fuente='SIN_ARCHIVO')
        previas = Alerta.objects.filter(vigente=True, estado=Alerta.NUEVA, severidad='ALTA').count()
        Alerta.objects.create(tipo='URGENTE', product=self.sku, severidad='ALTA', mensaje='x', clave='t|A1')
        Alerta.objects.create(tipo='URGENTE', product=self.otro, severidad='ALTA', mensaje='x', clave='t|B2',
                              estado=Alerta.REVISADA)        # revisada: no cuenta
        r = self.client.get(reverse('calculadora:panel'))
        hoy = r.context['hoy']
        self.assertEqual(hoy['alertas'], previas + 1)
        for texto in ('Compras del día', 'Fuera de calendario', 'Traslados urgentes', 'Alertas importantes',
                      'Revisar solicitudes', 'Ver excepciones', 'Ver bodegas'):
            self.assertContains(r, texto)
        self.assertContains(r, '?severidad=ALTA')
        self.assertContains(r, 'Al día')                    # sin traslados urgentes
        semaforo = {s['nombre']: s['color'] for s in r.context['semaforo']}
        self.assertEqual(semaforo['Consumo mensual'], 'amarillo')
        self.assertEqual(semaforo['Plazos de entrega'], 'rojo')
        self.assertContains(r, 'los plazos son los del maestro de SAP')

    def test_correr_requiere_permiso(self):
        n = Corrida.objects.count()
        self.client.force_login(self.normal)
        self.client.post(reverse('calculadora:correr'))
        self.assertEqual(Corrida.objects.count(), n)
        self.client.force_login(self.admin)
        r = self.client.post(reverse('calculadora:correr'))
        self.assertRedirects(r, reverse('calculadora:panel'))
        self.assertEqual(Corrida.objects.count(), n + 1)

    def test_grilla_y_filtros(self):
        r = self.client.get(reverse('calculadora:grilla'))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'A1')               # necesita compra: aparece por defecto
        self.assertNotContains(r, '>B2<')          # sin accion: oculto por defecto
        r = self.client.get(reverse('calculadora:grilla'), {'todo': '1'})
        self.assertContains(r, 'B2')
        r = self.client.get(reverse('calculadora:grilla'), {'letra': 'O', 'todo': '1'})
        self.assertNotContains(r, 'Filtro hidraulico')
        r = self.client.get(reverse('calculadora:grilla'), {'search': 'perno'})
        self.assertContains(r, 'B2')
        for orden in ('valor', 'urgencia', 'cobertura', 'codigo'):
            self.assertEqual(self.client.get(reverse('calculadora:grilla'), {'orden': orden, 'todo': '1'}).status_code, 200)

    def test_grilla_filtro_xyz(self):
        self.assertEqual(ResultadoArticulo.objects.get(product=self.sku).xyz, 'X')     # consumo constante
        self.assertEqual(ResultadoArticulo.objects.get(product=self.otro).xyz, 'Z')    # sin consumo
        r = self.client.get(reverse('calculadora:grilla'), {'xyz': 'Z'})
        self.assertContains(r, 'Perno')                   # la celda XYZ se ve completa (con o sin accion)
        self.assertNotContains(r, 'Filtro hidraulico')
        r = self.client.get(reverse('calculadora:grilla'), {'xyz': 'X'})
        self.assertContains(r, 'Filtro hidraulico')
        self.assertNotContains(r, 'Perno')

    def test_grilla_excel(self):
        r = self.client.get(reverse('calculadora:grilla_excel'), {'todo': '1'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], XLSX)

    def test_articulo_memoria_y_graficos(self):
        r = self.client.get(reverse('calculadora:articulo', args=['A1']))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Memoria de cálculo')
        self.assertContains(r, 'RAIZ(')
        self.assertContains(r, 'chartConsumo')
        self.assertContains(r, 'chartLinea')
        self.assertContains(r, 'Qué dice el sistema')
        self.assertContains(r, 'Es un artículo R')
        self.assertContains(r, 'XYZ X')
        import json
        linea = json.loads(r.context['grafico_linea'])
        self.assertEqual(linea['hoy'], 12)                          # 12 cierres de mes antes de hoy
        self.assertEqual(len(linea['pasado']), len(linea['labels']))
        self.assertEqual(linea['pasado'][12], linea['futuro'][12])  # la linea es continua en "hoy"
        self.assertEqual(linea['labels'][12], 'hoy')
        self.assertTrue(any(v is not None for v in linea['futuro'][13:]))

    def test_articulo_inexistente_404(self):
        self.assertEqual(self.client.get(reverse('calculadora:articulo', args=['NOEXISTE'])).status_code, 404)

    def test_articulo_fuera_de_corrida(self):
        ResultadoArticulo.objects.filter(product=self.otro).delete()
        r = self.client.get(reverse('calculadora:articulo', args=['B2']))
        self.assertContains(r, 'no está en la última corrida')

    def test_articulo_config_superusuario(self):
        r = self.client.post(reverse('calculadora:articulo_config', args=['A1']),
                             {'es_estrategico': 'on', 'minimo_declarado': '6', 'minimo_nuevo': '0', 'nota': 'pañol'})
        self.assertRedirects(r, reverse('calculadora:articulo', args=['A1']))
        cfg = ArticuloConfig.objects.get(product=self.sku)
        self.assertTrue(cfg.es_estrategico)
        self.assertEqual(cfg.minimo_declarado, 6)
        self.assertEqual(cfg.actualizado_por, self.admin)

    def test_articulo_config_proveedor_inexistente(self):
        self.client.post(reverse('calculadora:articulo_config', args=['A1']), {'proveedor': 'NOPE'})
        self.assertFalse(ArticuloConfig.objects.filter(product=self.sku).exists())

    def test_articulo_config_rechazado_usuario_normal(self):
        self.client.force_login(self.normal)
        self.client.post(reverse('calculadora:articulo_config', args=['A1']), {'es_estrategico': 'on'})
        self.assertFalse(ArticuloConfig.objects.filter(product=self.sku).exists())

    def test_indicadores(self):
        r = self.client.get(reverse('calculadora:indicadores'))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'escenario actual vs propuesto')
        r = self.client.get(reverse('calculadora:indicadores'), {'letra': 'R', 'abc': 'A', 'familia': '101'})
        self.assertEqual(r.status_code, 200)
        r = self.client.get(reverse('calculadora:indicadores'), {'xyz': 'X'})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Escenario anterior')
        self.assertContains(r, reverse('purchasing:list'))
