"""SPEC-26: picos de consumo recortados a k veces la mediana de los meses con consumo."""
import datetime
from dataclasses import replace
from types import SimpleNamespace

import pytest

from apps.calc.consumo import calcular_consumo
from apps.calc.params import Params, validar
from apps.calculadora.alertas import _reglas_articulo

P = Params()
# Caso real 40101060 (corrida 18): un mes de 34.000 u con mediana 16. Con promedio + 3 desvest
# el tope quedaba en 33.539 (el pico casi entero seguia en la demanda).
PICO_REAL = [12, 16, 20, 14, 0, 0, 18, 34000, 15, 10, 0, 16]


class TestTopePorMediana:
    def test_recorta_el_pico_que_promedio_mas_3_desvest_deja_pasar(self):
        c = calcular_consumo(PICO_REAL, P)
        assert c.mediana_con_consumo == 16
        assert c.tope_por_mediana
        assert c.tope_mes_atipico == 64            # 4 x 16
        assert c.meses_atipicos == (7,)
        assert c.meses[7] == 64
        assert c.meses_originales[7] == 34000
        assert c.consumo_promedio_mes == pytest.approx((sum(PICO_REAL) - 34000 + 64) / 12)

    def test_con_multiplicador_cero_rige_solo_la_regla_del_documento(self):
        c = calcular_consumo(PICO_REAL, replace(P, multiplicador_pico_mediana=0))
        assert not c.tope_por_mediana
        assert c.tope_mes_atipico > 30000          # promedio + 3 desvest: el pico casi no se toca

    def test_manda_el_tope_mas_bajo(self):
        # Serie pareja con un mes alto: promedio + 3 desvest queda bajo 4 x mediana
        meses = [10] * 11 + [30]
        c = calcular_consumo(meses, P)
        assert not c.tope_por_mediana
        assert c.tope_mes_atipico < 40

    def test_consumo_estable_no_se_recorta(self):
        c = calcular_consumo([8, 12, 10, 9, 11, 10, 13, 7, 10, 12, 9, 10], P)
        assert c.meses_atipicos == ()

    def test_esporadico_no_se_recorta(self):
        # Menos de 3 meses con consumo (umbral R): ese mes es su consumo normal
        c = calcular_consumo([0] * 10 + [1, 50], P)
        assert c.meses_atipicos == ()
        assert c.consumo_total_12m == 51

    def test_mes_de_evento_no_se_recorta(self):
        c = calcular_consumo(PICO_REAL, P, meses_evento=(7,))
        assert c.meses_atipicos == ()


class TestAlzaSostenida:
    def test_dos_de_los_ultimos_tres_meses_altos_es_cambio_de_nivel(self):
        c = calcular_consumo([2] * 9 + [2, 20, 20], P)
        assert c.meses_atipicos == ()

    def test_un_solo_mes_reciente_alto_es_pico(self):
        c = calcular_consumo([2] * 11 + [20], P)
        assert c.meses_atipicos == (11,)

    def test_el_alza_reciente_no_protege_un_pico_antiguo(self):
        c = calcular_consumo([2, 2, 80, 2, 2, 2, 2, 2, 2, 2, 20, 20], P)
        assert c.meses_atipicos == (2,)


def test_parametro_en_catalogo_con_rango():
    assert validar('multiplicador_pico_mediana', '4') == 4
    assert validar('multiplicador_pico_mediana', 0) == 0
    with pytest.raises(ValueError):
        validar('multiplicador_pico_mediana', 21)


def _resultado(**kw):
    base = dict(product_id='40101060', letra='R', stock_maximo=0, disponible_futuro=1, comprometido=0,
                stock_seguridad=0, fecha_bajo_ss=None, oc_atrasada=False, costo_unitario=1,
                consumo_meses=PICO_REAL, consumo_promedio_mes=10, variacion_consumo=0,
                fecha_quiebre_proyectada=None, excepcion=False, avisos=[], necesita_compra=False,
                proveedor_id=None, meses_atipicos=[7], tope_mes_atipico=64, mediana_con_consumo=16,
                corrida=SimpleNamespace(fecha_calculo=datetime.date(2026, 10, 29)))
    base.update(kw)
    return SimpleNamespace(**base)


def test_alerta_pico_con_el_mes_y_las_cantidades():
    alertas = [a for a in _reglas_articulo(_resultado(), P, '2026-10') if a[1] == 'PICO']
    # 12 meses cerrados al 29-oct-2026: oct-25 .. sep-26; el indice 7 es may-26
    assert len(alertas) == 1
    clave, _, severidad, mensaje = alertas[0]
    assert clave == 'PICO|40101060|2026-05'
    assert severidad == 'BAJA'
    assert '34,000 u recortado a 64.0' in mensaje


def test_sin_alerta_pico_en_articulos_que_no_se_reponen():
    assert not any(a[1] == 'PICO' for a in _reglas_articulo(_resultado(letra='O'), P, '2026-10'))
