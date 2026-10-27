"""Casos de prueba dorados del documento (§10, SPEC-17). Deben dar exactamente los
resultados del documento: es el criterio de aceptacion de la fase de calculo."""
import datetime

import pytest

from apps.calc import politica as pol
from apps.calc import red
from apps.calc.clasificacion import factor_servicio
from apps.calc.consumo import calcular_consumo
from apps.calc.motor import EntradaArticulo, calcular_articulo
from apps.calc.params import Params
from apps.calc.plazo import calcular_plazo
from apps.calc.proyeccion import evaluar_excepcion, proyectar

P = Params()
HOY = datetime.date(2026, 10, 27)


class TestCaso1RRegular:
    """R-Regular, clase A, no critico."""
    meses = [2, 0, 3, 1, 0, 2, 4, 1, 0, 3, 2, 2]
    oc = [40, 52, 48, 38, 47]

    def test_consumo(self):
        c = calcular_consumo(self.meses, P)
        assert c.consumo_promedio_mes == pytest.approx(1.67, abs=0.005)
        assert c.variacion_consumo == pytest.approx(1.30, abs=0.005)
        assert c.meses_con_consumo_12m == 9

    def test_plazo(self):
        pl = calcular_plazo(self.oc, 30, P)
        assert pl.dias_entrega_promedio == 45
        assert pl.variacion_entrega_dias == pytest.approx(5.83, abs=0.005)
        assert pl.plazo_total_meses == pytest.approx(1.57, abs=0.005)

    def test_politica_y_compra(self):
        c = calcular_consumo(self.meses, P)
        pl = calcular_plazo(self.oc, 30, P)
        p = pol.politica_general(c.consumo_promedio_mes, c.variacion_consumo, pl, factor_servicio(0.97), P)
        assert p.ss_calculado == pytest.approx(3.13, abs=0.01)
        assert p.piso_ss == pytest.approx(3.33, abs=0.01)
        assert p.stock_seguridad == 4
        assert p.punto_pedido == 8
        assert p.stock_maximo == 13
        compra = pol.evaluar_compra(p, pol.disponible_futuro(4, 0, 1), c.consumo_promedio_mes,
                                    c.consumo_diario, 1.0, P, min_compra=5, multiplo=5)
        assert compra.disponible_futuro == 3
        assert compra.comprar
        assert compra.cantidad_sugerida == 10

    def test_motor_completo(self):
        e = EntradaArticulo(
            codigo='CASO1', hoy=HOY, abc='A', consumo_meses=self.meses, dias_oc=self.oc,
            lead_time_maestro=30, costo=1.0, min_compra=5, multiplo=5,
            bodegas=[red.Bodega('013-PP', es_central=True, es_santiago=True, stock_fisico=4, comprometido=1)],
        )
        r = calcular_articulo(e)
        assert r.letra == 'R' and r.clasificacion.subclase == 'REGULAR'
        assert (r.politica.stock_seguridad, r.politica.punto_pedido, r.politica.stock_maximo) == (4, 8, 13)
        assert r.compra.cantidad_sugerida == 10


class TestCaso2RIntermitente:
    @pytest.mark.parametrize('plazo_meses, salidas, rop, maximo', [
        (2, 1, 12, 24),
        (6, 2, 24, 36),
        (9, 3, 36, 48),
    ])
    def test_salidas_segun_plazo(self, plazo_meses, salidas, rop, maximo):
        pl = calcular_plazo([], plazo_meses * 30 - P.dias_recepcion, P)
        assert pl.plazo_total_meses == pytest.approx(plazo_meses)
        p = pol.politica_intermitente(3, 12, 3, pl, P)
        assert (p.salidas_en_plazo, p.punto_pedido, p.stock_maximo) == (salidas, rop, maximo)


class TestCaso3KitElectricoHiab:
    """81310204 KIT ELECTRICO GRUAS HIAB @ 013-PP: R, clase A, plazo SAP 7 dias sin OC."""

    def test_esta_version(self):
        pl = calcular_plazo([], 7, P)
        assert pl.plazo_total_meses == pytest.approx(0.3)
        assert pl.variacion_entrega_meses == pytest.approx(0.058, abs=0.001)
        p = pol.politica_general(11.5, 8.42, pl, factor_servicio(0.97), P)
        assert p.ss_calculado == pytest.approx(8.76, abs=0.01)
        assert p.stock_seguridad == 23
        assert p.punto_pedido == 33
        assert p.stock_maximo == 68
        compra = pol.evaluar_compra(p, pol.disponible_futuro(12, 0, 9), 11.5, 146 / 365, 166.78, P)
        assert compra.disponible_futuro == 3
        assert compra.cantidad_sugerida == 65
        assert round(compra.valor_sugerido) == 10841


class TestCaso4Traslado:
    """31302313 FILTRO RETORNO @ 002: comprometido 1, disponible -1; 013-03 tiene 2 libres."""

    def test_traslada_desde_013_03_sin_comprar(self):
        bodegas = [
            red.Bodega('013-PP', es_central=True, es_santiago=True),
            red.Bodega('013-03', es_santiago=True, stock_fisico=2),
            red.Bodega('002', stock_fisico=0, comprometido=1),
        ]
        acciones, traslados = red.distribuir('R', bodegas)
        a = {x.codigo: x for x in acciones}['002']
        assert a.objetivo == 1
        assert a.disponible_futuro == -1
        assert a.faltante == 2
        assert a.accion == red.TRASLADAR
        assert traslados == [red.Traslado('013-03', '002', 2)]


class TestCaso5FueraDeCalendario:
    """Proxima compra en 12 dias, plazo 10, recepcion 2, stock 6, consumo diario 0,5,
    pedido de 4 unidades en 2 dias."""

    def test_proyeccion(self):
        serie = proyectar(6, 0.5, compromisos=[(2, 4)], horizonte=10)
        assert serie[:5] == [5.5, 1, 0.5, 0, -0.5]

    def test_excepcion(self):
        serie = proyectar(6, 0.5, compromisos=[(2, 4)], horizonte=120)
        ex = evaluar_excepcion(serie, 0, dias_a_proxima_compra=12, dias_entrega=10, dias_recepcion=2)
        assert ex.dia_quiebre == 5
        assert ex.dia_llegada_posible == 24
        assert ex.excepcion
        assert ex.dias_quiebre_inevitable == 7
