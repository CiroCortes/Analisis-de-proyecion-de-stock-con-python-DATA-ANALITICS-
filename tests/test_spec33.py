"""SPEC-33: plazos de entrega atipicos (OC que quedo abierta o recepcion tardia)."""
import datetime

from apps.calc.motor import EntradaArticulo, calcular_articulo
from apps.calc.params import Params
from apps.calc.plazo import calcular_plazo

# 4201130215 (pistola neumatica, Wurth): la OC 2402156 tardo 294 dias; las demas 2 a 11 (y una de 69)
PLAZOS_4201130215 = [294, 3, 6, 7, 4, 2, 7, 6, 2, 11, 69, 3]
CONSUMO_4201130215 = [3, 3, 1, 0, 0, 2, 4, 1, 2, 1, 0, 1]


def test_la_oc_de_294_dias_se_recorta_al_tope():
    pl = calcular_plazo(PLAZOS_4201130215, 23, Params())
    # mediana 6 dias: tope = max(4 x 6; 6 + 30) = 36
    assert pl.tope_plazo_dias == 36
    assert pl.n_oc_atipicas == 2                      # 294 y 69
    assert pl.dias_entrega_promedio < 11              # antes 34,5
    assert pl.variacion_entrega_dias < 14             # antes 83,8


def test_sin_multiplicador_rige_la_regla_del_documento():
    pl = calcular_plazo(PLAZOS_4201130215, 23, Params(multiplicador_plazo_mediana=0))
    assert pl.n_oc_atipicas == 0 and pl.tope_plazo_dias == 0
    assert round(pl.dias_entrega_promedio, 1) == 34.5


def test_plazos_parejos_no_se_tocan():
    pl = calcular_plazo([30, 45, 60, 40, 50], 30, Params())
    assert pl.n_oc_atipicas == 0
    assert pl.dias_entrega_promedio == 45


def test_importacion_larga_y_pareja_no_es_atipica():
    # 120 dias de mediana: el tope es 480, una OC de 200 dias es variacion normal
    pl = calcular_plazo([110, 120, 130, 200, 115], 120, Params())
    assert pl.n_oc_atipicas == 0


def test_con_menos_de_3_oc_no_se_recorta():
    pl = calcular_plazo([5, 294], 23, Params())
    assert pl.origen == 'MAESTRO' and pl.n_oc_atipicas == 0


def test_caso_4201130215_deja_de_comprar():
    hoy = datetime.date(2026, 11, 3)
    base = dict(codigo='4201130215', hoy=hoy, consumo_meses=CONSUMO_4201130215, costo=126.87,
                lead_time_maestro=23, dias_oc=PLAZOS_4201130215, abc='B', es_dia_compra=True, segmento='PANOL')
    from apps.calc import red
    bodegas = [red.Bodega('013', stock_fisico=4), red.Bodega('008', stock_fisico=5)]
    antes = calcular_articulo(EntradaArticulo(**base, bodegas=bodegas, params=Params(multiplicador_plazo_mediana=0)))
    ahora = calcular_articulo(EntradaArticulo(**base, bodegas=bodegas))
    assert antes.politica.stock_seguridad == 9 and antes.cantidad_a_comprar == 8
    assert ahora.politica.stock_seguridad < antes.politica.stock_seguridad
    assert ahora.cantidad_a_comprar == 0               # 9 disponibles cubren el punto de pedido
