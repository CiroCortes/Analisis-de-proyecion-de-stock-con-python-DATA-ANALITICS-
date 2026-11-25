import datetime
import io
import openpyxl
import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.utils import timezone

from apps.calculadora import sop_hiab
from apps.calculadora.models import (
    CompromisoDetalle,
    ConsumoMensual,
    OCAbierta,
    PresupuestoSOP,
    PropuestaCompraSOP,
)
from apps.inventory.models import ProductSKU
from apps.inventory.stock_actual_models import StockActual


@pytest.fixture
def auth_client(db):
    User = get_user_model()
    user = User.objects.create_user(username='testuser', password='password123')
    client = Client()
    client.force_login(user)
    return client


@pytest.fixture
def datos_hiab_bd(db):
    """Puebla datos realistas de Equipos HIAB directamente en la BD (como llegan desde el Datalake)."""
    hoy = timezone.localdate()
    mes_cerrado = datetime.date(hoy.year, hoy.month, 1)

    # Modelo 5108 (alta venta, baja cobertura -> APROBAR)
    sku_558_c = ProductSKU.objects.create(
        code='13171058', description='GRUA ARTICULADA HIAB X-HIPRO 558 EP-6',
        unit_cost_usd=140000, clase='1', familia='113', subfamilia='71', modelo='5108',
        sap_group_code='158', is_active=True,
    )
    sku_558_v = ProductSKU.objects.create(
        code='70100558', description='GRUA HIAB 558 SOBRE CAMION',
        unit_cost_usd=160000, clase='1', familia='113', subfamilia='71', modelo='5108',
        sap_group_code='158', is_active=True,
    )
    StockActual.objects.create(codigo=sku_558_c.code, bodega='013-06', stock_disponible=2)
    StockActual.objects.create(codigo=sku_558_c.code, bodega='858', stock_disponible=1)
    # Bodega NC debe excluirse
    StockActual.objects.create(codigo=sku_558_c.code, bodega='013-NC', stock_disponible=5)
    OCAbierta.objects.create(nro_oc='OC100', tipo_documento=OCAbierta.FR, product=sku_558_c, bodega='013-06', cantidad_pendiente=2, cuenta=True)
    OCAbierta.objects.create(nro_oc='OF100', tipo_documento=OCAbierta.OF, product=sku_558_v, bodega='013-06', cantidad_pendiente=1, cuenta=True)
    CompromisoDetalle.objects.create(
        tipo='PC', numero='2609001', codigo_sku=sku_558_v.code, bodega='013',
        fecha_emision=hoy, nombre_cliente='VFS CHILE S.A.', responsable='Juan Perez',
        cantidad=2, costo_unitario=140000, en_alcance_repo=False,
    )
    # 36 unidades vendidas en L12M -> ritmo 3.0 un/mes; inv libre = 3+2+1-2 = 4 un -> cob = 1.3 m
    ConsumoMensual.objects.create(product=sku_558_v, bodega='013', mes=mes_cerrado, origen=ConsumoMensual.VENTA, cantidad=36)

    # Modelo 5077 (alto inventario, baja venta -> REFUTAR)
    sku_1188 = ProductSKU.objects.create(
        code='13171188', description='GRUA ARTICULADA HIAB X-HIPRO 1058',
        unit_cost_usd=210000, clase='1', familia='113', subfamilia='71', modelo='5077',
        sap_group_code='158', is_active=True,
    )
    StockActual.objects.create(codigo=sku_1188.code, bodega='013-06', stock_disponible=10)
    ConsumoMensual.objects.create(product=sku_1188, bodega='013', mes=mes_cerrado, origen=ConsumoMensual.VENTA, cantidad=2)

    PresupuestoSOP.objects.create(anio=hoy.year, familia='113', subfamilia='71', modelo='5108', cantidad=30, monto_usd=4200000)
    return {'mod_aprobar': '5108', 'mod_refutar': '5077'}


def test_sop_hiab_data_desde_bd(datos_hiab_bd):
    data = sop_hiab.get_sop_hiab_data()
    assert data['hay_datos'] is True
    assert data['fuente'] == 'BD Datalake (SAP)'
    assert data['total_subfamilias'] == 2
    assert data['total_skus'] == 3
    # Verifica que bodega 013-NC (5 un) fue excluida del stock físico (2+1+10 = 13)
    assert data['kpis']['stock_cant'] == 13
    assert data['kpis']['transito_real_cant'] == 2
    assert data['kpis']['en_proceso_cant'] == 1
    assert data['kpis']['backlog_cant'] == 2
    assert data['kpis']['inventario_final_cant'] == 14


def test_sop_hiab_simulation(datos_hiab_bd):
    sim_refutar = sop_hiab.simular_propuesta_compra('5077', 2)
    assert sim_refutar['decision'] == 'REFUTAR'
    assert 'REFUTAR' in sim_refutar['veredicto']

    sim_aprobar = sop_hiab.simular_propuesta_compra('5108', 4)
    assert sim_aprobar['decision'] == 'APROBAR'
    assert 'APROBAR' in sim_aprobar['veredicto']


def test_sop_hiab_views_y_decisiones(auth_client, datos_hiab_bd):
    # 1. Vista principal
    resp = auth_client.get('/calculadora/sop-hiab/')
    assert resp.status_code == 200
    html = resp.content.decode('utf-8')
    assert 'S&OP HIAB' in html
    assert '{{' not in html

    # 2. Endpoint de simulación API
    resp_sim = auth_client.get('/calculadora/sop-hiab/simular/?subfamilia=5077&cantidad=3')
    assert resp_sim.status_code == 200
    data = resp_sim.json()
    assert data['subfamilia'] == '5077'
    assert data['cantidad_solicitada'] == 3
    assert data['decision'] == 'REFUTAR'

    # 3. Guardar decisión 1 a 1
    resp_dec = auth_client.post('/calculadora/sop-hiab/decision/', {
        'modelo': '5108',
        'vendedor': 'Carlos Soto',
        'negocio': 'Minera Norte',
        'cantidad_solicitada': '4',
        'cantidad_aprobada': '2',
        'decision': PropuestaCompraSOP.PARCIAL,
        'comentario': 'Aprobadas 2 unidades para Q2',
    })
    assert resp_dec.status_code == 302
    assert PropuestaCompraSOP.objects.filter(modelo='5108', cantidad_aprobada=2).exists()

    # 4. Guardar presupuesto anual
    resp_ppto = auth_client.post('/calculadora/sop-hiab/presupuesto/', {
        'modelo': '5077',
        'anio': timezone.localdate().year,
        'cantidad': '6',
        'monto_usd': '1260000',
    })
    assert resp_ppto.status_code == 302
    assert PresupuestoSOP.objects.filter(modelo='5077', cantidad=6).exists()

    # 5. Exportación Excel
    resp_excel = auth_client.get('/calculadora/sop-hiab/excel/')
    assert resp_excel.status_code == 200
    assert resp_excel['Content-Type'] == 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    wb = openpyxl.load_workbook(io.BytesIO(resp_excel.content))
    assert 'Resumen Subfamilias' in wb.sheetnames
