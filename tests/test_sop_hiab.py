import datetime
import io
import openpyxl
import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.utils import timezone

from apps.calculadora import sop_equipos, sop_equipos_io, sop_hiab
from apps.calculadora.models import (
    CompromisoDetalle,
    ConsumoMensual,
    LineaSolicitud,
    OCAbierta,
    ParametroCompra,
    PresupuestoSOP,
    PropuestaCompraSOP,
    Proveedor,
    SolicitudCompra,
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
def datos_equipos_multimarca(db):
    """Puebla equipos multi-marca incluyendo Superproducts (sub=05), reemplazo 455+456 y colisión."""
    hoy = timezone.localdate()
    mes_cerrado = datetime.date(hoy.year, hoy.month, 1)

    prov_hiab = Proveedor.objects.create(codigo='P-HIAB', nombre='HIAB FINLAND OY', pais='FI')
    prov_sp = Proveedor.objects.create(codigo='P-SP', nombre='SUPER PRODUCTS LLC', pais='US')

    # 1) HIAB modelo 455 (anterior) y 456 (reemplazo)
    hiab_455 = ProductSKU.objects.create(
        code='13171455', description='GRUA ARTICULADA HIAB X-HIPRO 455',
        unit_cost_usd=130000, clase='1', familia='113', subfamilia='71', modelo='455',
        sap_group_code='158', sap_group_name='EQUIPOS IZAJE', is_active=True,
    )
    hiab_456 = ProductSKU.objects.create(
        code='13171456', description='GRUA ARTICULADA HIAB X-HIPRO 456 EVO',
        unit_cost_usd=140000, clase='1', familia='113', subfamilia='71', modelo='456',
        sap_group_code='158', sap_group_name='EQUIPOS IZAJE', is_active=True,
    )
    ParametroCompra.objects.create(product=hiab_456, proveedor_preferido=prov_hiab.codigo)
    StockActual.objects.create(codigo=hiab_455.code, bodega='013-06', stock_disponible=2)
    StockActual.objects.create(codigo=hiab_456.code, bodega='013-06', stock_disponible=1)
    StockActual.objects.create(codigo=hiab_456.code, bodega='013-NC', stock_disponible=5)  # debe excluirse
    OCAbierta.objects.create(nro_oc='OC100', tipo_documento=OCAbierta.FR, product=hiab_456, bodega='013-06', cantidad_pendiente=2, cuenta=True)
    CompromisoDetalle.objects.create(
        tipo='PC', numero='2609001', codigo_sku=hiab_456.code, bodega='013',
        fecha_emision=hoy, nombre_cliente='VFS CHILE S.A.', responsable='Juan Perez',
        cantidad=1, costo_unitario=140000, en_alcance_repo=False,
    )
    # 455 vendió 24 un en L12M; 456 es nuevo y vendió 12 un -> juntos 36 un (3.0/mes), disponible = 2+1+2-1 = 4 un
    ConsumoMensual.objects.create(product=hiab_455, bodega='013', mes=mes_cerrado, origen=ConsumoMensual.VENTA, cantidad=24)
    ConsumoMensual.objects.create(product=hiab_456, bodega='013', mes=mes_cerrado, origen=ConsumoMensual.VENTA, cantidad=12)

    # 2) SUPER PRODUCTS (sub=05, descripción dice CAMEL pero proveedor es SUPER PRODUCTS LLC)
    sp_sku = ProductSKU.objects.create(
        code='10601004', description='CAMION DESOBSTRUCTOR CAMEL 900',
        unit_cost_usd=210000, clase='1', familia='06', subfamilia='05', modelo='0035',
        sap_group_code='109', sap_group_name='EQUIPOS ESPECIALES', is_active=True,
    )
    ParametroCompra.objects.create(product=sp_sku, proveedor_preferido=prov_sp.codigo)
    StockActual.objects.create(codigo=sp_sku.code, bodega='013-06', stock_disponible=8)
    ConsumoMensual.objects.create(product=sp_sku, bodega='013', mes=mes_cerrado, origen=ConsumoMensual.VENTA, cantidad=2)

    # 3) USIMECA (sub=02, para probar orden alfabético H < S < U)
    usi_sku = ProductSKU.objects.create(
        code='14100201', description='RECOLECTOR USIMECA IPANEMA 15M3',
        unit_cost_usd=95000, clase='1', familia='11', subfamilia='02', modelo='455',  # misma clave '455' que HIAB -> cero colisión
        sap_group_code='109', sap_group_name='EQUIPOS ESPECIALES', is_active=True,
    )
    StockActual.objects.create(codigo=usi_sku.code, bodega='013-06', stock_disponible=10)
    ConsumoMensual.objects.create(product=usi_sku, bodega='013', mes=mes_cerrado, origen=ConsumoMensual.VENTA, cantidad=2)

    PresupuestoSOP.objects.create(anio=hoy.year, familia='113', subfamilia='71', modelo='456', cantidad=20, monto_usd=2800000)

    return {
        'key_455': '113|71|455',
        'key_456': '113|71|456',
        'key_sp': '06|05|0035',
        'key_usi': '11|02|455',
    }


def test_marcas_alfabeticas_superproducts_y_multimodelo(datos_equipos_multimarca):
    data = sop_equipos.get_sop_equipos_data()
    assert data['hay_datos'] is True
    assert data['total_subfamilias'] == 4  # 455 HIAB, 456 HIAB, 0035 SUPER PRODUCTS, 455 USIMECA

    # Orden alfabético estricto de marcas + SUPER PRODUCTS reconocido correctamente
    nombres_marcas = [m['name'] for m in data['catalogo']['marcas']]
    assert nombres_marcas == sorted(nombres_marcas)
    assert 'SUPER PRODUCTS' in nombres_marcas
    assert data['subfamilias_dict'][datos_equipos_multimarca['key_sp']]['marca_label'] == 'SUPER PRODUCTS'

    # Consolidación multimodelo (456 principal + 455 anterior)
    csv_keys = f"{datos_equipos_multimarca['key_456']},{datos_equipos_multimarca['key_455']}"
    sim_multi = sop_hiab.simular_propuesta_compra(csv_keys, 4)
    assert sim_multi['es_multimodelo'] is True
    assert sim_multi['consolidado']['stock_cant'] == 3        # 1 + 2
    assert sim_multi['consolidado']['ent_12m_cant'] == 36     # 12 + 24
    assert sim_multi['consolidado']['inv_libre_cant'] == 4    # (3 + 2 FR) - 1 PC
    assert sim_multi['decision'] == 'APROBAR'                 # (4+4)/3.0 = 2.7 meses <= 6m

    # Sobrestock Superproducts -> REFUTAR
    sim_sp = sop_hiab.simular_propuesta_compra(datos_equipos_multimarca['key_sp'], 2)
    assert sim_sp['decision'] == 'REFUTAR'


def test_vistas_gerencial_generar_sc_y_excel(auth_client, datos_equipos_multimarca):
    # 1. Vista principal: tarjeta gerencial, Grupo SAP, Inventario Disponible y SIN NEC
    resp = auth_client.get('/calculadora/sop-hiab/')
    assert resp.status_code == 200
    html = resp.content.decode('utf-8')
    assert 'Grupo SAP:' in html
    assert 'Inventario Disponible' in html
    assert 'SUPER PRODUCTS' in html
    assert 'panel-nec' not in html
    assert 'Consolidado Total' in html
    assert 'Expandir SKUs' in html
    assert '/calculadora/articulo/' in html
    assert '{{' not in html

    # 2. API Simulación multimodelo con SKUs incluidos
    csv_keys = f"{datos_equipos_multimarca['key_456']},{datos_equipos_multimarca['key_455']}"
    resp_sim = auth_client.get(f'/calculadora/sop-hiab/simular/?subfamilia={csv_keys}&cantidad=3')
    assert resp_sim.status_code == 200
    payload = resp_sim.json()
    assert payload['es_multimodelo'] is True
    assert payload['consolidado']['stock_cant'] == 3
    sku_codes = [s['codigo'] for s in payload['consolidado']['skus']]
    assert '13171456' in sku_codes
    assert '13171455' in sku_codes

    # 3. Guardar decisión 1 a 1 consolidada y generar SC oficial
    resp_dec = auth_client.post('/calculadora/sop-hiab/decision/', {
        'grupo': '158',
        'marca': '71',
        'clave_modelo': csv_keys,
        'vendedor': 'Carlos Soto',
        'negocio': 'Minera Norte',
        'cantidad_solicitada': '4',
        'cantidad_aprobada': '2',
        'decision': PropuestaCompraSOP.PARCIAL,
        'comentario': 'Reemplazo 455 por 456',
    })
    assert resp_dec.status_code == 302
    pr = PropuestaCompraSOP.objects.get(familia='113', subfamilia='71', modelo='456')
    assert '[Consolidado multimodelo: 456 + 455]' in pr.comentario

    # Generar Solicitud de Compra (SC) oficial desde la bitácora
    resp_sc = auth_client.post(f'/calculadora/sop-hiab/decision/{pr.pk}/generar-sc/')
    assert resp_sc.status_code == 302
    pr.refresh_from_db()
    assert pr.solicitud_compra_id is not None
    sc = SolicitudCompra.objects.get(pk=pr.solicitud_compra_id)
    assert sc.proveedor_id == 'P-HIAB'
    linea = LineaSolicitud.objects.get(solicitud=sc)
    assert linea.product_id == '13171456'
    assert linea.cantidad_final == 2.0

    # Probar botón Rechazar sobre otra decisión pendiente en la bitácora
    pr_pend = PropuestaCompraSOP.objects.create(
        familia='06', subfamilia='05', modelo='0035', cantidad_solicitada=2,
        cantidad_aprobada=0, decision=PropuestaCompraSOP.PENDIENTE,
    )
    resp_rej = auth_client.post(f'/calculadora/sop-hiab/decision/{pr_pend.pk}/rechazar/')
    assert resp_rej.status_code == 302
    pr_pend.refresh_from_db()
    assert pr_pend.decision == PropuestaCompraSOP.REFUTADA
    assert pr_pend.cantidad_aprobada == 0

    # 4. Importar Presupuesto desde Excel
    anio = timezone.localdate().year
    wb_in = openpyxl.Workbook()
    ws = wb_in.active
    ws.title = 'Presupuesto (2026)'
    ws.append(['Código', 'Equipo terminado', 'Cantidad', 'Precio unitario', 'Valor total'])
    ws.append(['10601004', 'CAMION DESOBSTRUCTOR CAMEL 900', 5, 220000, 1100000])
    buf = io.BytesIO()
    wb_in.save(buf)
    buf.seek(0)
    res_imp = sop_equipos_io.importar_presupuesto_excel(buf, anio=anio)
    assert res_imp['ok'] is True
    assert PresupuestoSOP.objects.filter(anio=anio, familia='06', subfamilia='05', modelo='0035', cantidad=5).exists()

    # 5. Exportación Excel de 5 hojas (sin NEC)
    resp_excel = auth_client.get('/calculadora/sop-hiab/excel/')
    assert resp_excel.status_code == 200
    wb = openpyxl.load_workbook(io.BytesIO(resp_excel.content))
    assert set(wb.sheetnames) == {'Resumen Modelos', 'Detalle SKUs', 'Backlog Clientes', 'Decisiones 1 a 1', 'Master Data Pendiente'}
