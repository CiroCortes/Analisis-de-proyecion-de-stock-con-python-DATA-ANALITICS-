"""SPEC-21: Santiago como un solo stock, proteccion simetrica y compra minima (nucleo puro)."""
import datetime

from apps.calc import politica as pol
from apps.calc import red
from apps.calc.params import Params
from apps.calc.plazo import calcular_plazo

P = Params()


class TestAgruparSantiago:
    def test_suma_santiago_y_deja_sucursales(self):
        nodos = red.agrupar_santiago([
            red.Bodega('013-PP', es_santiago=True, stock_fisico=1, en_transito=4, comprometido=2,
                       fecha_compromiso=datetime.date(2026, 12, 1)),
            red.Bodega('013-03', es_santiago=True, stock_fisico=7, fecha_compromiso=datetime.date(2026, 11, 5)),
            red.Bodega(red.NODO_SANTIAGO, es_santiago=True, stock_fisico=3, consumo_diario=0.5),
            red.Bodega('002', stock_fisico=9),
        ])
        stgo, suc = nodos
        assert stgo.codigo == red.NODO_SANTIAGO and stgo.es_central
        assert (stgo.stock_fisico, stgo.en_transito, stgo.comprometido) == (11, 4, 2)
        assert stgo.fecha_compromiso == datetime.date(2026, 11, 5)
        assert stgo.consumo_diario == 0.5
        assert stgo.componentes == (('013-03', 7), (red.NODO_SANTIAGO, 3), ('013-PP', 1))
        assert suc.codigo == '002' and not suc.es_central

    def test_totales_de_la_red_no_cambian(self):
        bodegas = [red.Bodega('013-PP', es_santiago=True, stock_fisico=5, comprometido=1),
                   red.Bodega('013-09', es_santiago=True, stock_fisico=2), red.Bodega('008', stock_fisico=3)]
        assert red.totales_red(red.agrupar_santiago(bodegas)) == red.totales_red(bodegas)

    def test_sin_traslados_entre_bodegas_de_santiago(self):
        # Antes: 013-09 -> 013-PP por 5. Ahora no hay nada que mover: es el mismo stock.
        nodos = red.agrupar_santiago([
            red.Bodega('013-PP', es_santiago=True, comprometido=5),
            red.Bodega('013-09', es_santiago=True, stock_fisico=20),
        ])
        acciones, traslados = red.distribuir('R', nodos)
        assert traslados == []
        assert acciones[0].accion == red.NINGUNA


class TestProteccionSimetrica:
    def test_santiago_protege_compromisos_y_reserva(self):
        nodos = [red.Bodega(red.NODO_SANTIAGO, es_central=True, es_santiago=True, stock_fisico=20,
                            comprometido=5, consumo_diario=0.5),
                 red.Bodega('002', comprometido=15)]
        acciones, traslados = red.distribuir('R', nodos, dias_reserva=10)
        a = {x.codigo: x for x in acciones}
        assert a[red.NODO_SANTIAGO].protegido == 10       # 5 comprometidos + 0,5 x 10 dias
        assert a[red.NODO_SANTIAGO].excedente == 10       # libre
        assert traslados == [red.Traslado(red.NODO_SANTIAGO, '002', 10)]
        # 002 necesita 15: recibe 10, espera 5 y ve lo retenido en Santiago
        assert a['002'].accion == red.TRASLADAR_PARCIAL and a['002'].espera_compra == 5
        assert a['002'].retenido_en == [(red.NODO_SANTIAGO, 10)]

    def test_sucursal_entrega_a_santiago_solo_lo_libre(self):
        # Santiago con quiebre real de 6; Antofagasta tiene 12 con 8 comprometidas (caso relatado
        # por el usuario: la sucursal lo tiene para compromisos)
        nodos = [red.Bodega(red.NODO_SANTIAGO, es_central=True, es_santiago=True, stock_fisico=0, comprometido=6),
                 red.Bodega('002-02', stock_fisico=12, comprometido=8),
                 red.Bodega('008', stock_fisico=1)]
        acciones, traslados = red.distribuir('R', nodos)
        a = {x.codigo: x for x in acciones}[red.NODO_SANTIAGO]
        assert a.origenes == [('002-02', 4), ('008', 1)]   # mayor libre primero
        assert a.accion == red.TRASLADAR_PARCIAL and a.espera_compra == 1
        assert a.retenido_en == [('002-02', 8)]            # moverlo es decision de jefatura
        assert all(t.desde == () for t in traslados)

    def test_santiago_pide_solo_su_quiebre_real(self):
        # Stock = comprometido: el pedido esta cubierto, no pide nada a regiones
        nodos = [red.Bodega(red.NODO_SANTIAGO, es_central=True, es_santiago=True, stock_fisico=5, comprometido=5),
                 red.Bodega('010', stock_fisico=30)]
        acciones, traslados = red.distribuir('R', nodos)
        a = {x.codigo: x for x in acciones}[red.NODO_SANTIAGO]
        assert a.faltante == 0
        assert traslados == [] and a.accion == red.NINGUNA

    def test_sin_traslados_entre_sucursales(self):
        nodos = [red.Bodega('002', comprometido=2), red.Bodega('003', stock_fisico=9)]
        acciones, traslados = red.distribuir('R', nodos)
        a = {x.codigo: x for x in acciones}['002']
        assert traslados == [] and a.accion == red.ESPERA_COMPRA
        assert a.sucursales_con_stock == ['003']


class TestCompraMinima:
    def _politica(self):
        plazo = calcular_plazo([], 30, P)
        return pol.politica_general(10, 3, plazo, 1.65, P)

    def test_llega_al_punto_de_pedido_y_es_menor_que_la_sugerida(self):
        po = self._politica()
        compra = pol.evaluar_compra(po, 5, 10, 10 / 30, 2, P)
        minima = pol.compra_hasta_punto_pedido(po, 5, P)
        assert minima == po.punto_pedido - 5
        assert 0 < minima < compra.cantidad_sugerida

    def test_respeta_minimo_de_meses_y_multiplo(self):
        po = self._politica()
        # falta 1 para el punto de pedido, pero se compra al menos 1 mes (10) al multiplo de 6
        assert pol.compra_hasta_punto_pedido(po, po.punto_pedido - 1, P, multiplo=6) == 12

    def test_sobre_el_punto_de_pedido_o_a_pedido_es_cero(self):
        po = self._politica()
        assert pol.compra_hasta_punto_pedido(po, po.punto_pedido + 1, P) == 0
        assert pol.compra_hasta_punto_pedido(pol.politica_minimo(pol.A_PEDIDO, 0, P), -5, P) == 0
