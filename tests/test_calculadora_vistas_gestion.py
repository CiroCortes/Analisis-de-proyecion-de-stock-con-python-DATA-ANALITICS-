"""Pantallas de gestion de la Calculadora (SPEC-18 §4.2): solicitudes, traslados, alertas,
eventos comerciales, parametros y proveedores."""
import datetime

from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.calc.params import ARTICULO, FAMILIA, GENERAL, PROVEEDOR
from apps.calculadora import servicio
from apps.calculadora.models import (AcuerdoGlobal, Alerta, ConsumoMensual, EventoComercial, LineaSolicitud,
                                     ParametroCambio, ParametroCompra, ParametroValor, Proveedor, SolicitudCompra)
from apps.calculadora.parametros import Resolutor
from apps.calculadora.solicitudes import acuerdo_vigente
from apps.inventory.models import Category, InventoryMetric, ProductSKU, Warehouse


def _dia_habil():
    hoy = timezone.localdate()
    while hoy.weekday() >= 5:
        hoy -= datetime.timedelta(days=1)
    return hoy


HOY = _dia_habil()

GET_URLS = [
    ('calculadora:solicitudes', {}), ('calculadora:traslados', {}), ('calculadora:traslados_excel', {}),
    ('calculadora:alertas', {}), ('calculadora:eventos', {}), ('calculadora:parametros', {}),
    ('calculadora:parametros_historial_excel', {}), ('calculadora:proveedores', {}),
]


class Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        cat = Category.objects.create(code='GRP-101', name='RPTS. EQ. IZAJE', tipo='REPUESTO', is_active=True)
        cls.wh = Warehouse.objects.create(code='013-PP', name='Central')
        cls.sku = ProductSKU.objects.create(code='SKU1', description='Filtro de prueba', category=cat,
                                            unit_cost_usd=10, lead_time_days=28, sap_group_code='101')
        InventoryMetric.objects.create(product=cls.sku, warehouse=cls.wh, stock_physical=0, disp_future=0)
        for mes in servicio.meses_cerrados(HOY, 12):
            ConsumoMensual.objects.create(product=cls.sku, bodega='013-PP', mes=mes, cantidad=10)
        cls.prov = Proveedor.objects.create(codigo='P001', nombre='Proveedor Uno', fecha_ancla=HOY)
        ParametroCompra.objects.create(product=cls.sku, proveedor_preferido='P001')
        servicio.ejecutar_corrida(hoy=HOY)

        cls.comprador = User.objects.create_user('comprador', password='x')
        cls.jefe = User.objects.create_user('jefe', password='x')
        cls.jefe.groups.add(Group.objects.create(name='Jefe Abastecimiento'))
        cls.admin = User.objects.create_user('admin_abast', password='x')
        cls.admin.groups.add(Group.objects.create(name='Administrador Abastecimiento'))

    def setUp(self):
        self.client.force_login(self.comprador)

    def _generar(self):
        self.client.post(reverse('calculadora:solicitudes_generar'))
        return SolicitudCompra.objects.get(proveedor=self.prov)


class AccesoTest(Base):
    def test_anonimo_redirige_al_login(self):
        self.client.logout()
        for nombre, kw in GET_URLS:
            r = self.client.get(reverse(nombre, kwargs=kw))
            self.assertEqual(r.status_code, 302, nombre)
            self.assertIn('/auth/', r['Location'])

    def test_paginas_responden(self):
        sol = self._generar()
        Alerta.objects.create(tipo='URGENTE', product=self.sku, mensaje='x', clave='URGENTE|SKU1|t')
        for nombre, kw in GET_URLS + [('calculadora:solicitud_detalle', {'pk': sol.pk})]:
            r = self.client.get(reverse(nombre, kwargs=kw))
            self.assertEqual(r.status_code, 200, nombre)

    def test_mutaciones_solo_post(self):
        self.assertEqual(self.client.get(reverse('calculadora:solicitudes_generar')).status_code, 405)


class SolicitudesTest(Base):
    def test_generar_crea_solicitud_del_dia_de_compra(self):
        sol = self._generar()
        self.assertEqual(sol.tipo, SolicitudCompra.CALENDARIO)
        linea = sol.lineas.get()
        self.assertEqual(linea.product_id, 'SKU1')
        self.assertGreater(linea.cantidad_final, 0)
        self.assertTrue(linea.sin_contrato)

    def test_editar_linea_exige_motivo(self):
        sol = self._generar()
        linea = sol.lineas.get()
        url = reverse('calculadora:solicitud_linea', args=[sol.pk, linea.pk])
        self.client.post(url, {'cantidad': linea.cantidad_sugerida + 5, 'motivo': ''})
        linea.refresh_from_db()
        self.assertEqual(linea.cantidad_final, linea.cantidad_sugerida)
        self.client.post(url, {'cantidad': linea.cantidad_sugerida + 5, 'motivo': 'Pedido del cliente X'})
        linea.refresh_from_db()
        self.assertEqual(linea.cantidad_final, linea.cantidad_sugerida + 5)
        self.client.post(url, {'cantidad': 0, 'motivo': 'No se compra'})
        linea.refresh_from_db()
        self.assertEqual(linea.estado, LineaSolicitud.DESCARTADA)

    def test_aprobar_requiere_rol(self):
        sol = self._generar()
        url = reverse('calculadora:solicitud_aprobar', args=[sol.pk])
        self.client.post(url)
        sol.refresh_from_db()
        self.assertEqual(sol.estado, SolicitudCompra.BORRADOR)
        self.client.force_login(self.jefe)
        self.client.post(url)
        sol.refresh_from_db()
        self.assertEqual(sol.estado, SolicitudCompra.APROBADA)
        self.assertEqual(sol.aprobada_por, self.jefe)

    def test_aprobar_con_duplicada_pide_confirmacion(self):
        sol = self._generar()
        sol.lineas.update(duplicada_reciente=True)
        self.client.force_login(self.jefe)
        url = reverse('calculadora:solicitud_aprobar', args=[sol.pk])
        self.client.post(url)
        sol.refresh_from_db()
        self.assertEqual(sol.estado, SolicitudCompra.BORRADOR)
        self.client.post(url, {'confirmar_duplicadas': '1'})
        sol.refresh_from_db()
        self.assertEqual(sol.estado, SolicitudCompra.APROBADA)

    def test_exportar_devuelve_excel_y_marca_exportada(self):
        sol = self._generar()
        self.client.force_login(self.jefe)
        self.client.post(reverse('calculadora:solicitud_aprobar', args=[sol.pk]))
        r = self.client.get(reverse('calculadora:solicitudes_exportar') + f'?ids={sol.pk}')
        self.assertEqual(r.status_code, 200)
        self.assertIn('spreadsheetml', r['Content-Type'])
        sol.refresh_from_db()
        self.assertEqual(sol.estado, SolicitudCompra.EXPORTADA)

    def test_exportar_borrador_no_lo_marca(self):
        sol = self._generar()
        self.client.get(reverse('calculadora:solicitudes_exportar') + f'?ids={sol.pk}')
        sol.refresh_from_db()
        self.assertEqual(sol.estado, SolicitudCompra.BORRADOR)

    def test_descartar_exige_motivo(self):
        sol = self._generar()
        url = reverse('calculadora:solicitud_descartar', args=[sol.pk])
        self.client.post(url, {'motivo': ''})
        sol.refresh_from_db()
        self.assertEqual(sol.estado, SolicitudCompra.BORRADOR)
        self.client.post(url, {'motivo': 'Proveedor sin stock'})
        sol.refresh_from_db()
        self.assertEqual(sol.estado, SolicitudCompra.DESCARTADA)


class ParametrosTest(Base):
    def test_comprador_no_edita(self):
        self.client.post(reverse('calculadora:parametros'), {'clave': 'meses_cobertura', 'nivel': GENERAL, 'valor': '4'})
        self.assertFalse(ParametroValor.objects.exists())

    def test_fuera_de_rango_se_rechaza_y_valido_se_registra(self):
        self.client.force_login(self.admin)
        url = reverse('calculadora:parametros')
        self.client.post(url, {'clave': 'nivel_servicio_a', 'nivel': GENERAL, 'valor': '1,5'})
        self.assertFalse(ParametroValor.objects.exists())
        self.assertFalse(ParametroCambio.objects.exists())
        self.client.post(url, {'clave': 'nivel_servicio_a', 'nivel': GENERAL, 'valor': '0,98', 'motivo': 'Prueba'})
        self.assertEqual(ParametroValor.objects.get(clave='nivel_servicio_a').valor, '0.98')
        cambio = ParametroCambio.objects.get()
        self.assertEqual((cambio.valor_anterior, cambio.valor_nuevo, cambio.usuario), ('0.97', '0.98', self.admin))

    def test_ajuste_por_familia_y_borrado(self):
        self.client.force_login(self.admin)
        url = reverse('calculadora:parametros')
        self.client.post(url, {'clave': 'meses_cobertura', 'nivel': FAMILIA, 'ambito': '101', 'valor': '5'})
        self.assertTrue(ParametroValor.objects.filter(nivel=FAMILIA, ambito='101').exists())
        self.client.post(url, {'clave': 'meses_cobertura', 'nivel': FAMILIA, 'ambito': '101', 'accion': 'borrar'})
        self.assertFalse(ParametroValor.objects.exists())
        self.assertEqual(ParametroCambio.objects.count(), 2)

    def test_simular_no_guarda(self):
        r = self.client.post(reverse('calculadora:parametros_simular'), {'clave': 'meses_cobertura', 'valor': '6'})
        self.assertEqual(r.status_code, 200)
        sim = r.context['simulacion']
        valor = {m['etiqueta']: m for m in sim['metricas']}['Valor del stock maximo']
        self.assertGreater(valor['despues'], valor['antes'])
        self.assertFalse(ParametroValor.objects.exists())


class EventosAlertasProveedoresTest(Base):
    def test_crear_y_aprobar_evento(self):
        self.client.post(reverse('calculadora:eventos'), {
            'product': 'SKU1', 'tipo': 'ALZA', 'cantidad_adicional': '30', 'mes_inicio': '2026-11',
            'mes_fin': '2027-01', 'comentario': 'Negocio minera'})
        ev = EventoComercial.objects.get()
        self.assertEqual((ev.mes_inicio, ev.mes_fin), (datetime.date(2026, 11, 1), datetime.date(2027, 1, 1)))
        self.assertEqual(ev.estado, EventoComercial.PROPUESTO)
        url = reverse('calculadora:evento_estado', args=[ev.pk])
        self.client.post(url, {'accion': 'aprobar'})
        ev.refresh_from_db()
        self.assertEqual(ev.estado, EventoComercial.PROPUESTO)
        self.client.force_login(self.jefe)
        self.client.post(url, {'accion': 'aprobar'})
        ev.refresh_from_db()
        self.assertEqual((ev.estado, ev.aprobado_por), (EventoComercial.APROBADO, self.jefe))

    def test_evento_invalido_no_se_crea(self):
        self.client.post(reverse('calculadora:eventos'), {
            'product': 'NOEXISTE', 'tipo': 'ALZA', 'cantidad_adicional': '30', 'mes_inicio': '2026-11',
            'mes_fin': '2026-10', 'comentario': 'x'})
        self.assertFalse(EventoComercial.objects.exists())

    def test_actualizar_alerta(self):
        a = Alerta.objects.create(tipo='URGENTE', product=self.sku, mensaje='x', clave='URGENTE|SKU1|t2')
        self.client.post(reverse('calculadora:alerta_actualizar', args=[a.pk]),
                         {'estado': 'REVISADA', 'responsable': 'Ana', 'comentario': 'Gestionado'})
        a.refresh_from_db()
        self.assertEqual((a.estado, a.responsable, a.comentario), ('REVISADA', 'Ana', 'Gestionado'))
        r = self.client.get(reverse('calculadora:alertas') + '?estado=REVISADA')
        self.assertContains(r, 'Gestionado')

    def test_calendario_proveedor_solo_admin(self):
        url = reverse('calculadora:proveedores')
        datos = {'codigo': 'P001', 'frecuencia_compra_dias': '30', 'fecha_ancla': '2026-11-02', 'comprador': 'Ana'}
        self.client.post(url, datos)
        self.prov.refresh_from_db()
        self.assertIsNone(self.prov.frecuencia_compra_dias)
        self.client.force_login(self.admin)
        self.client.post(url, datos)
        self.prov.refresh_from_db()
        self.assertEqual((self.prov.frecuencia_compra_dias, self.prov.fecha_ancla, self.prov.comprador),
                         (30, datetime.date(2026, 11, 2), 'Ana'))
        self.client.post(url, dict(datos, frecuencia_compra_dias='500'))
        self.prov.refresh_from_db()
        self.assertEqual(self.prov.frecuencia_compra_dias, 30)

    def test_proveedor_listado_muestra_dia_de_compra(self):
        r = self.client.get(reverse('calculadora:proveedores'))
        fila = next(f for f in r.context['filas'] if f['p'].codigo == 'P001')
        self.assertTrue(fila['es_hoy'] or HOY != timezone.localdate())


class AcuerdoVigenteTest(TestCase):
    def test_menor_precio_entre_vigentes(self):
        cat = Category.objects.create(code='G', name='G')
        ProductSKU.objects.create(code='A1', description='x', category=cat)
        hoy = datetime.date(2026, 10, 27)
        comun = dict(proveedor_codigo='P1', product_id='A1', fecha_inicio=datetime.date(2026, 1, 1))
        AcuerdoGlobal.objects.create(nro_acuerdo='1', precio_unitario=12, fecha_termino=datetime.date(2026, 12, 31), **comun)
        AcuerdoGlobal.objects.create(nro_acuerdo='2', precio_unitario=9, fecha_termino=datetime.date(2026, 12, 31), **comun)
        AcuerdoGlobal.objects.create(nro_acuerdo='3', precio_unitario=5, fecha_termino=datetime.date(2026, 9, 30), **comun)
        AcuerdoGlobal.objects.create(nro_acuerdo='4', precio_unitario=1, proveedor_codigo='OTRO', product_id='A1')
        self.assertEqual(acuerdo_vigente('A1', 'P1', hoy).nro_acuerdo, '2')
        self.assertIsNone(acuerdo_vigente('A1', 'P1', datetime.date(2027, 2, 1)))


class ResolutorTest(TestCase):
    def test_prioridad_de_niveles(self):
        valores = [
            ParametroValor(clave='meses_cobertura', nivel=GENERAL, ambito='', valor='4'),
            ParametroValor(clave='meses_cobertura', nivel=FAMILIA, ambito='101', valor='5'),
            ParametroValor(clave='meses_cobertura', nivel=PROVEEDOR, ambito='P1', valor='6'),
            ParametroValor(clave='meses_cobertura', nivel=ARTICULO, ambito='A1', valor='7'),
        ]
        r = Resolutor(valores=valores)
        self.assertEqual(r.para().meses_cobertura, 4)
        self.assertEqual(r.para(familia='101').meses_cobertura, 5)
        self.assertEqual(r.para(familia='101', proveedor='P1').meses_cobertura, 6)
        self.assertEqual(r.para(familia='101', proveedor='P1', articulo='A1').meses_cobertura, 7)
        self.assertEqual(r.para(familia='999', proveedor='P9', articulo='A9').meses_cobertura, 4)
