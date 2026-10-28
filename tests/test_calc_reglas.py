"""Reglas y casos borde del nucleo de calculo (documento §3, §5, §9; SPEC-09 a SPEC-12)."""
import datetime

import pytest

from apps.calc import calendario, red
from apps.calc import politica as pol
from apps.calc.clasificacion import (PANOL, REPUESTOS, clases_abc, clasificar, es_inmovilizado, es_nuevo,
                                     factor_servicio, nivel_servicio)
from apps.calc.consumo import calcular_consumo
from apps.calc.motor import OC_ATRASADA, PEDIDO, EntradaArticulo, calcular_articulo
from apps.calc.params import Params, validar
from apps.calc.plazo import MAESTRO, REAL, calcular_plazo
from apps.calc.redondeo import al_multiplo, redondear_mas

P = Params()
HOY = datetime.date(2026, 10, 27)


class TestRedondeo:
    def test_redondear_mas_tolera_flotante(self):
        assert redondear_mas(7.000000000001) == 7
        assert redondear_mas(7.2) == 8
        assert redondear_mas(0) == 0
        assert redondear_mas(-3) == 0

    def test_multiplo(self):
        assert al_multiplo(10, 5) == 10
        assert al_multiplo(11, 5) == 15
        assert al_multiplo(1.2, 0) == 2


class TestClasificacion:
    @pytest.mark.parametrize('meses, compromiso, estrategico, letra, subclase', [
        (12, False, False, 'R', 'REGULAR'),
        (9, False, False, 'R', 'REGULAR'),
        (8, False, False, 'R', 'INTERMITENTE'),
        (3, False, False, 'R', 'INTERMITENTE'),
        (2, True, False, 'P', ''),
        (0, True, False, 'P', ''),
        (2, False, False, 'O', ''),       # regla acordada 26-oct: P exige compromiso
        (0, False, False, 'O', ''),
        (0, False, True, 'E', 'INTERMITENTE'),
        (12, True, True, 'E', 'REGULAR'),   # E manda sobre R
    ])
    def test_orden_de_reglas(self, meses, compromiso, estrategico, letra, subclase):
        c = clasificar(meses, compromiso, estrategico, P)
        assert (c.letra, c.subclase) == (letra, subclase)

    def test_regla_literal_del_documento(self):
        p = Params(p_solo_con_compromiso=False)
        assert clasificar(2, False, False, p).letra == 'P'

    def test_abc_por_valor(self):
        valores = {'a': 800, 'b': 100, 'c': 60, 'd': 40, 'z': 0}
        assert clases_abc(valores, P) == {'a': 'A', 'b': 'B', 'c': 'B', 'd': 'C', 'z': 'C'}

    def test_nivel_servicio(self):
        assert nivel_servicio('A', False, REPUESTOS, P) == 0.97
        assert nivel_servicio('C', False, REPUESTOS, P) == 0.90
        assert nivel_servicio('C', True, REPUESTOS, P) == 0.97
        assert nivel_servicio('C', False, PANOL, P) == 0.97
        assert factor_servicio(0.95) == 1.65
        assert factor_servicio(0.99) == 2.33

    def test_nuevo_e_inmovilizado(self):
        assert es_nuevo(datetime.date(2026, 3, 1), HOY, REPUESTOS, P)
        assert not es_nuevo(datetime.date(2026, 1, 1), HOY, REPUESTOS, P)
        assert not es_nuevo(datetime.date(2026, 5, 1), HOY, PANOL, P)
        assert es_inmovilizado(datetime.date(2024, 9, 1), None, HOY, REPUESTOS, P)
        assert not es_inmovilizado(datetime.date(2025, 1, 1), None, HOY, REPUESTOS, P)
        assert es_inmovilizado(datetime.date(2025, 9, 1), None, HOY, PANOL, P)


class TestConsumo:
    def test_completa_con_ceros_y_no_usa_negativos(self):
        c = calcular_consumo([5, -2], P)
        assert len(c.meses) == 12
        assert c.consumo_total_12m == 5          # un esporadico no se recorta
        assert c.meses_con_consumo_12m == 1
        assert c.mayor_consumo_mes == 5

    def test_recorta_mes_atipico(self):
        meses = [1] * 11 + [100]
        c = calcular_consumo(meses, P)
        assert c.meses_atipicos == (11,)
        assert c.meses[11] == pytest.approx(c.tope_mes_atipico)
        assert c.mayor_consumo_mes == 1   # el atipico no cuenta para intermitentes

    def test_mes_de_evento_no_es_atipico(self):
        c = calcular_consumo([1] * 11 + [100], P, meses_evento=(11,))
        assert c.meses_atipicos == ()
        assert c.consumo_total_12m == 111


class TestPlazo:
    def test_menos_de_3_oc_usa_maestro(self):
        pl = calcular_plazo([10, 20], 30, P)
        assert pl.origen == MAESTRO
        assert pl.dias_entrega_promedio == 30
        assert pl.variacion_entrega_dias == 7.5

    def test_excluye_plazos_invalidos(self):
        pl = calcular_plazo([10, 20, 30, -5, 400], 99, P)
        assert pl.origen == REAL
        assert pl.n_oc == 3 and pl.n_oc_invalidas == 2
        assert pl.dias_entrega_promedio == 20

    def test_piso_largo_sobre_60_dias(self):
        pl = calcular_plazo([], 90, P)
        p = pol.politica_general(10, 0, pl, 1.88, P)
        assert p.meses_piso_ss == 4
        assert p.stock_seguridad == 40


class TestCompra:
    def test_no_compra_si_disponible_sobre_umbral(self):
        pl = calcular_plazo([], 28, P)
        p = pol.politica_general(10, 2, pl, 1.88, P)
        c = pol.evaluar_compra(p, 1000, 10, 0.33, 1, P)
        assert not c.necesita_compra and c.cantidad_sugerida == 0

    def test_fuera_del_dia_de_compra_necesita_pero_no_compra(self):
        pl = calcular_plazo([], 28, P)
        p = pol.politica_general(10, 2, pl, 1.88, P)
        c = pol.evaluar_compra(p, 0, 10, 0.33, 1, P, es_dia_compra=False)
        assert c.necesita_compra and not c.comprar and c.cantidad_sugerida > 0

    def test_a_pedido_compra_lo_comprometido_no_cubierto(self):
        p = pol.politica_minimo(pol.A_PEDIDO, 0, P)
        c = pol.evaluar_compra(p, -7, 0, 0, 2, P, min_compra=0, multiplo=5)
        assert c.cantidad_sugerida == 10 and c.urgencia == pol.URGENTE

    def test_consumo_cero_no_compra(self):
        pl = calcular_plazo([], 28, P)
        p = pol.politica_general(0, 0, pl, 1.88, P)
        assert pol.evaluar_compra(p, -5, 0, 0, 1, P).cantidad_sugerida == 0

    def test_estrategico_con_minimo_compra_sin_consumo(self):
        pl = calcular_plazo([], 28, P)
        p = pol.politica_general(0, 0, pl, 1.88, P, minimo_declarado=6)
        assert p.stock_seguridad == 6
        assert pol.evaluar_compra(p, 0, 0, 0, 1, P).cantidad_sugerida == 6

    def test_urgencia(self):
        assert pol.urgencia(0, 5) == pol.URGENTE
        assert pol.urgencia(3, 5) == pol.MEDIO
        assert pol.urgencia(5, 5) == pol.NORMAL


class TestRed:
    def _bodegas(self):
        return red.agrupar_santiago([
            red.Bodega('013-PP', es_santiago=True, stock_fisico=5, comprometido=2),
            red.Bodega('013-03', es_santiago=True, stock_fisico=1),
            red.Bodega('002', comprometido=3, fecha_compromiso=datetime.date(2026, 11, 20)),
            red.Bodega('003', comprometido=2, stock_fisico=1, fecha_compromiso=datetime.date(2026, 11, 1)),
        ])

    def test_santiago_un_nodo_y_urgentes_primero(self):
        acciones, traslados = red.distribuir('R', self._bodegas())
        a = {x.codigo: x for x in acciones}
        # Santiago = 013-PP + 013-03: stock 6, comprometido 2 -> libre 4
        # Ambas son urgentes (disponible <= 0): manda la fecha comprometida mas cercana (003).
        # 003: objetivo 2, disponible -1 -> faltante 3 (regla del caso 4 del documento)
        assert a['003'].accion == red.TRASLADAR
        assert a['003'].origenes == [(red.NODO_SANTIAGO, 3)]
        # queda 1 libre en Santiago de los 6 que pide 002
        assert a['002'].faltante == 6
        assert a['002'].accion == red.TRASLADAR_PARCIAL
        assert a['002'].cantidad_trasladar == 1 and a['002'].espera_compra == 5
        assert all(t.origen == red.NODO_SANTIAGO for t in traslados)
        # Se saca de la bodega con mas stock primero (013-PP tiene 5)
        assert [t.desde for t in traslados] == [(('013-PP', 3),), (('013-PP', 1),)]

    def test_comprometido_de_santiago_nunca_se_traslada(self):
        bodegas = red.agrupar_santiago([
            red.Bodega('013-PP', es_santiago=True, stock_fisico=4, comprometido=4),
            red.Bodega('008', comprometido=1),
        ])
        acciones, traslados = red.distribuir('R', bodegas)
        assert traslados == []
        assert {x.codigo: x for x in acciones}['008'].accion == red.ESPERA_COMPRA

    def test_obsoleto_sin_objetivo(self):
        acciones, _ = red.distribuir('O', [red.Bodega('002', stock_fisico=-1)])
        assert acciones[0].objetivo == 0


class TestCalendario:
    def test_proxima_fecha_y_fin_de_semana(self):
        ancla = datetime.date(2026, 10, 1)   # jueves
        assert calendario.proxima_fecha_compra(datetime.date(2026, 10, 1), 15, ancla) == ancla
        # 1-oct + 15 = 16-oct (viernes)
        assert calendario.proxima_fecha_compra(datetime.date(2026, 10, 2), 15, ancla) == datetime.date(2026, 10, 16)
        # 16-oct + 15 = 31-oct (sabado) -> lunes 2-nov
        assert calendario.proxima_fecha_compra(datetime.date(2026, 10, 17), 15, ancla) == datetime.date(2026, 11, 2)

    def test_ancla_por_defecto_estable_y_habil(self):
        a = calendario.ancla_por_defecto('P001', 15)
        assert a == calendario.ancla_por_defecto('P001', 15)
        assert a.weekday() < 5


class TestMotor:
    def _entrada(self, **kw):
        base = dict(codigo='X', hoy=HOY, abc='A', consumo_meses=[10] * 12, lead_time_maestro=28, costo=2,
                    bodegas=[red.Bodega('013-PP', es_central=True, es_santiago=True, stock_fisico=50)])
        base.update(kw)
        return EntradaArticulo(**base)

    def test_bloqueado_no_compra(self):
        r = calcular_articulo(self._entrada(bloqueado=True, bodegas=[]))
        assert r.cantidad_a_comprar == 0 and 'bloqueado' in r.avisos[0]

    def test_nuevo_usa_minimo_manual(self):
        r = calcular_articulo(self._entrada(fecha_creacion=datetime.date(2026, 8, 1), minimo_nuevo=7, bodegas=[]))
        assert r.politica.metodo == pol.NUEVO and r.politica.stock_maximo == 7
        assert r.compra.cantidad_sugerida == 7

    def test_excepcion_con_causa_oc_atrasada(self):
        r = calcular_articulo(self._entrada(
            bodegas=[red.Bodega('013-PP', es_central=True, es_santiago=True, stock_fisico=3)],
            oc_atrasada=True, dias_a_proxima_compra=10, es_dia_compra=False))
        assert r.excepcion.excepcion
        assert r.causa_excepcion == OC_ATRASADA
        assert r.cantidad_a_comprar > 0

    def test_excepcion_por_pedido_grande(self):
        r = calcular_articulo(self._entrada(compromisos=[(3, 60)], dias_a_proxima_compra=10, es_dia_compra=False))
        assert r.excepcion.excepcion and r.causa_excepcion == PEDIDO

    def test_ajuste_comercial_sube_punto_de_pedido(self):
        sin = calcular_articulo(self._entrada())
        con = calcular_articulo(self._entrada(ajuste_comercial=20))
        assert con.politica.punto_pedido > sin.politica.punto_pedido
        assert con.politica.stock_seguridad == sin.politica.stock_seguridad


class TestParametros:
    def test_validacion_de_rango(self):
        assert validar('nivel_servicio_a', '0,98') == 0.98
        with pytest.raises(ValueError):
            validar('nivel_servicio_a', 1.2)
        with pytest.raises(ValueError):
            validar('meses_cobertura', 'abc')
        assert validar('p_solo_con_compromiso', 'false') is False
