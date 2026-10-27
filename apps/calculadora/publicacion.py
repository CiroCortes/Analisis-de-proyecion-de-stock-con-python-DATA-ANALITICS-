"""Fuente unica (SPEC-19 §2): la Calculadora publica sus resultados en las tablas que leen
el Dashboard, el Reporte Gerencial, el Asistente IA, el detalle de SKU y el Recomendador
(StockProjection y SKUClassification). El resultado del motor anterior se guarda antes en
EscenarioActual para el panel "actual vs propuesto".
"""
from decimal import Decimal

from django.db import transaction

from apps.inventory.models import SKUClassification, StockProjection, Warehouse

from .models import EscenarioActual, ResultadoArticulo, ResultadoBodega, TrasladoSugerido

CENTRAL = '013-PP'
CODIGO_PLANILLA = {'R': 'VB', 'E': 'V1', 'P': 'PD', 'O': 'ND'}
MOTIVO_SIMPLE = {
    'R': 'Se repone: tiene consumo regular',
    'E': 'Estratégico: se mantiene siempre con el mínimo declarado',
    'P': 'A pedido: solo se compra lo comprometido en PC u OF',
    'O': 'No se recompra: sin consumo ni compromisos',
}


@transaction.atomic
def capturar_escenario_actual():
    """Copia el resultado del motor anterior (recien calculado en el pipeline) antes de que la
    Calculadora lo reemplace. Solo filas con algo que comparar (ROP, compra o traslado)."""
    letras = dict(SKUClassification.objects.values_list('product_id', 'repo_category'))
    filas = [
        EscenarioActual(product_id=sku, bodega=wh, rop=rop or 0, sugerido_compra=buy or 0, accion=accion,
                        letra=letras.get(sku, ''))
        for sku, wh, rop, buy, accion, transfer in StockProjection.objects.values_list(
            'product_id', 'warehouse__code', 'rop', 'suggested_buy_units', 'action_type', 'suggested_transfer_units')
        if rop or buy or transfer
    ]
    EscenarioActual.objects.all().delete()
    EscenarioActual.objects.bulk_create(filas, batch_size=5000)
    return len(filas)


def _entero(x):
    return int(round(x or 0))


@transaction.atomic
def publicar(corrida):
    """Reescribe StockProjection y SKUClassification con la ultima corrida (SPEC-19 §2.2, §2.3)."""
    bodegas = {w.code: w for w in Warehouse.objects.all()}
    central = bodegas.get(CENTRAL)
    previas = {c.product_id: c for c in SKUClassification.objects.all()}
    resultados = list(ResultadoArticulo.objects.filter(corrida=corrida))
    por_resultado = {}
    for b in ResultadoBodega.objects.filter(resultado__corrida=corrida).select_related('warehouse'):
        por_resultado.setdefault(b.resultado_id, []).append(b)
    origen_principal = {}
    for t in TrasladoSugerido.objects.filter(resultado__corrida=corrida).order_by('-cantidad'):
        origen_principal.setdefault((t.resultado_id, t.destino_id), t.origen_id)

    proyecciones, clasificaciones = [], []
    for r in resultados:
        costo = Decimal(str(round(r.costo_unitario or 0, 4)))
        filas = por_resultado.get(r.pk, [])
        compra = r.cantidad_a_comprar
        tiene_central = any(b.warehouse.code == CENTRAL for b in filas)

        for b in filas:
            es_central = b.warehouse.code == CENTRAL
            quiebre = max(0.0, -b.disponible_futuro)
            if es_central:
                accion = 'COMPRAR' if compra > 0 else (b.accion if b.accion != 'NINGUNA' else 'NINGUNA')
            else:
                accion = b.accion
            urgencia = b.urgencia
            if es_central and compra > 0 and urgencia == 'NORMAL':
                urgencia = r.urgencia if r.urgencia != 'NORMAL' else 'MEDIO'
            proyecciones.append(StockProjection(
                product_id=r.product_id, warehouse=b.warehouse,
                rop=r.punto_pedido if es_central else _entero(b.objetivo),
                safety_stock=r.stock_seguridad if es_central else 0,
                coverage_days=_entero(b.cobertura_dias) if b.cobertura_dias and b.cobertura_dias > 0 else 0,
                shortage_units=_entero(quiebre), shortage_usd=Decimal(str(round(quiebre, 4))) * costo,
                suggested_buy_units=compra if es_central else 0,
                suggested_transfer_units=_entero(b.cantidad_trasladar),
                transfer_source_warehouse_id=origen_principal.get((r.pk, b.warehouse_id)),
                action_type=accion, urgency_level=urgencia,
            ))
        # Articulo que hay que comprar sin posicion en la central: igual se publica la compra
        if not tiene_central and central and (compra > 0 or r.stock_maximo > 0):
            proyecciones.append(StockProjection(
                product_id=r.product_id, warehouse=central, rop=r.punto_pedido, safety_stock=r.stock_seguridad,
                coverage_days=0, shortage_units=0, shortage_usd=Decimal('0'),
                suggested_buy_units=compra, action_type='COMPRAR' if compra > 0 else 'NINGUNA',
                urgency_level=r.urgencia if compra > 0 else 'NORMAL',
            ))

        previa = previas.get(r.product_id)
        clasificaciones.append(SKUClassification(
            product_id=r.product_id, segment=r.segmento if r.segmento in ('PANOL', 'REPUESTOS') else 'REPUESTOS',
            abc_class=r.abc, active_months_count=r.meses_con_consumo_12m,
            annual_transactions_count=previa.annual_transactions_count if previa else 0,
            transactions_last_6m=previa.transactions_last_6m if previa else 0,
            is_new=r.es_nuevo, is_inmovilizado=r.es_inmovilizado,
            stock_policy='SI_STOCK' if r.letra in ('R', 'E') else 'NO_STOCK',
            stock_policy_reason=(MOTIVO_SIMPLE.get(r.letra, '') + (f' ({r.motivo_clasificacion})' if r.motivo_clasificacion else ''))[:150],
            service_level=Decimal(str(round(r.nivel_servicio or 0, 2))),
            z_factor=Decimal(str(round(r.factor_servicio or 0, 2))),
            annual_demand_units=Decimal(str(round(sum(r.consumo_meses or []), 2))),
            avg_daily_demand=Decimal(str(round(r.consumo_diario or 0, 4))),
            repo_category=r.letra, repo_source_code=CODIGO_PLANILLA.get(r.letra, 'ND'),
            consumption_freq_12m=r.meses_con_consumo_12m,
            rop_statistical=r.punto_pedido, safety_stock_statistical=r.stock_seguridad,
            stock_min_statistical=max(0, r.punto_pedido - r.stock_seguridad), stock_max_statistical=r.stock_maximo,
            avg_monthly_consumption=Decimal(str(round(r.consumo_promedio_mes or 0, 2))),
            std_monthly_consumption=Decimal(str(round(r.variacion_consumo or 0, 2))),
            has_active_of_or_pc=r.comprometido > 0,
        ))

    StockProjection.objects.all().delete()
    StockProjection.objects.bulk_create(proyecciones, batch_size=5000)
    SKUClassification.objects.all().delete()
    SKUClassification.objects.bulk_create(clasificaciones, batch_size=5000)
    return {'proyecciones': len(proyecciones), 'clasificaciones': len(clasificaciones)}
