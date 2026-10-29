"""SPEC-30: cliente del Service Layer solo lectura, sin sobrecargar el servidor.
Ningun test sale a la red: la sesion HTTP y el socket se reemplazan."""
from unittest import mock

import pytest
import requests

from apps.data_ingestion import service_layer as sl
from apps.data_ingestion.service_layer import (ClienteServiceLayer, Config, CorteDeSeguridad, ErrorServiceLayer,
                                               EscrituraProhibida, SinConexion)


COMPROBAR_RED = ClienteServiceLayer.comprobar_red      # la real; el fixture la reemplaza en los demas tests


def _cfg(**kw):
    base = dict(url='https://sap.example:50000/b1s/v1', usuario='lector', clave='x', base='X_CHILE_PRUEBAS', pausa=0)
    base.update(kw)
    return Config(**base)


class Respuesta:
    def __init__(self, estado=200, datos=None, texto=''):
        self.status_code, self._datos, self.text = estado, datos, texto

    def json(self):
        if self._datos is None:
            raise ValueError
        return self._datos


class SesionFalsa:
    """Registra cada peticion y responde en orden."""

    def __init__(self, respuestas=()):
        self.respuestas, self.enviadas, self.verify = list(respuestas), [], True

    def request(self, metodo, url, **kw):
        self.enviadas.append((metodo, url, kw.get('params'), kw.get('headers')))
        r = self.respuestas.pop(0) if self.respuestas else Respuesta(datos={'value': []})
        if isinstance(r, Exception):
            raise r
        return r

    def close(self):
        pass


@pytest.fixture(autouse=True)
def sin_red():
    with mock.patch.object(ClienteServiceLayer, 'comprobar_red', return_value=True):
        yield


class TestSoloLectura:
    @pytest.mark.parametrize('metodo, ruta', [('PATCH', 'Items(\'A\')'), ('PUT', 'Items(\'A\')'),
                                              ('DELETE', 'PurchaseOrders(1)'), ('POST', 'PurchaseOrders'),
                                              ('POST', 'PurchaseRequests'), ('POST', 'SQLQueries')])
    def test_nada_que_no_sea_lectura_sale_a_la_red(self, metodo, ruta):
        sesion = SesionFalsa()
        cliente = ClienteServiceLayer(_cfg(), sesion=sesion)
        with pytest.raises(EscrituraProhibida):
            cliente._enviar(metodo, ruta)
        assert sesion.enviadas == []

    def test_login_y_logout_son_los_unicos_post(self):
        sesion = SesionFalsa([Respuesta(texto='{}'), Respuesta(datos={'value': [{'ItemCode': 'A'}]}), Respuesta()])
        with ClienteServiceLayer(_cfg(), sesion=sesion) as cliente:
            assert [f['ItemCode'] for f in cliente.leer('Items', select='ItemCode')] == ['A']
        assert [(m, u.rsplit('/', 1)[-1]) for m, u, _, _ in sesion.enviadas] == [
            ('POST', 'Login'), ('GET', 'Items'), ('POST', 'Logout')]

    def test_logout_aunque_falle_la_lectura(self):
        sesion = SesionFalsa([Respuesta(texto='{}'), Respuesta(500, {'error': {'message': {'value': 'x'}}}), Respuesta()])
        with pytest.raises(ErrorServiceLayer):
            with ClienteServiceLayer(_cfg(), sesion=sesion) as cliente:
                list(cliente.leer('Items', select='ItemCode'))
        assert sesion.enviadas[-1][1].endswith('/Logout')


class TestCarga:
    def test_select_obligatorio_y_pagina_chica(self):
        sesion = SesionFalsa([Respuesta(datos={'value': []})])
        cliente = ClienteServiceLayer(_cfg(pagina=50), sesion=sesion)
        with pytest.raises(ErrorServiceLayer):
            list(cliente.leer('Items', select=''))
        list(cliente.leer('Items', select='ItemCode', filtro="Valid eq 'tYES'"))
        _, _, params, headers = sesion.enviadas[0]
        assert params == {'$select': 'ItemCode', '$filter': "Valid eq 'tYES'"}
        assert headers['Prefer'] == 'odata.maxpagesize=50'

    def test_sigue_las_paginas_con_next_link(self):
        sesion = SesionFalsa([Respuesta(datos={'value': [{'a': 1}], 'odata.nextLink': 'Items?$skip=1'}),
                              Respuesta(datos={'value': [{'a': 2}]})])
        cliente = ClienteServiceLayer(_cfg(), sesion=sesion)
        assert [f['a'] for f in cliente.leer('Items', select='a')] == [1, 2]
        assert sesion.enviadas[1][1].endswith('/Items?$skip=1') and sesion.enviadas[1][2] is None

    def test_maximo_corta_sin_pedir_mas_paginas(self):
        sesion = SesionFalsa([Respuesta(datos={'value': [{'a': 1}, {'a': 2}], 'odata.nextLink': 'Items?$skip=2'})])
        cliente = ClienteServiceLayer(_cfg(), sesion=sesion)
        assert len(list(cliente.leer('Items', select='a', maximo=1))) == 1
        assert len(sesion.enviadas) == 1

    def test_presupuesto_de_peticiones(self):
        cliente = ClienteServiceLayer(_cfg(max_peticiones=2), sesion=SesionFalsa())
        cliente._enviar('GET', 'Items')
        cliente._enviar('GET', 'Items')
        with pytest.raises(CorteDeSeguridad):
            cliente._enviar('GET', 'Items')

    def test_corta_si_el_servidor_responde_lento(self):
        cliente = ClienteServiceLayer(_cfg(lento=1, max_lentas=2), sesion=SesionFalsa())
        tiempos = iter([0, 5, 10, 15])
        with mock.patch.object(sl.time, 'monotonic', side_effect=lambda: next(tiempos)):
            cliente._enviar('GET', 'Items')
            with pytest.raises(CorteDeSeguridad):
                cliente._enviar('GET', 'Items')

    def test_corta_con_errores_seguidos(self):
        sesion = SesionFalsa([requests.exceptions.ConnectTimeout()] * 3)
        cliente = ClienteServiceLayer(_cfg(max_errores=3), sesion=sesion)
        for _ in range(2):
            with pytest.raises(SinConexion):
                cliente._enviar('GET', 'Items')
        with pytest.raises(CorteDeSeguridad):
            cliente._enviar('GET', 'Items')

    def test_pausa_entre_peticiones(self):
        cliente = ClienteServiceLayer(_cfg(pausa=0.5), sesion=SesionFalsa())
        with mock.patch.object(sl.time, 'sleep') as dormir:
            cliente._enviar('GET', 'Items')
            cliente._enviar('GET', 'Items')
        dormir.assert_called_once_with(0.5)


class TestConfiguracion:
    def test_por_defecto_solo_base_de_pruebas(self):
        with pytest.raises(ErrorServiceLayer, match='no es de pruebas'):
            _cfg(base='SBO_PESCO').validar()
        _cfg(base='SBO_PESCO', permitir_produccion=True).validar()

    def test_exige_https_y_clave(self):
        with pytest.raises(ErrorServiceLayer, match='https'):
            _cfg(url='http://sap.example:50001/b1s/v1').validar()
        with pytest.raises(ErrorServiceLayer, match='SAP_SL_PASSWORD'):
            _cfg(clave='').validar()

    def test_sin_red_de_pesco_falla_rapido(self):
        cliente = ClienteServiceLayer(_cfg(), sesion=SesionFalsa())
        with mock.patch.object(sl.socket, 'create_connection', side_effect=OSError('timed out')):
            with pytest.raises(SinConexion, match='red de Pesco'):
                COMPROBAR_RED(cliente)
