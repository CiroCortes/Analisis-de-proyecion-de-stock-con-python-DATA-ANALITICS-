"""Marcas de gestion por articulo (SPEC-31 §1): excluir del calculo y plan de gerencia.

Las usan la ficha del articulo y la pantalla Marcas. Validan y guardan en ArticuloConfig; el
calculo las aplica en la siguiente corrida.
"""
import datetime

from .models import ArticuloConfig

MOTIVOS = dict(ArticuloConfig.MOTIVOS_EXCLUSION)


def mes_desde_texto(texto):
    """'2026-12' (input type=month) -> date(2026, 12, 1); vacio -> None."""
    texto = (texto or '').strip()
    if not texto:
        return None
    try:
        return datetime.date(int(texto[:4]), int(texto[5:7]), 1)
    except (ValueError, IndexError):
        raise ValueError(f'"{texto}" no es un mes válido (AAAA-MM)')


def unidades_desde_texto(texto):
    try:
        valor = float(str(texto or '0').replace(',', '.'))
    except ValueError:
        raise ValueError(f'"{texto}" no es un número válido')
    if valor < 0:
        raise ValueError('Las unidades del plan no pueden ser negativas')
    return valor


def aplicar_exclusion(cfg, excluir, motivo='', nota=None):
    """Marca o desmarca 'Excluir del calculo' en `cfg` (sin guardar). Lanza ValueError si falta el
    motivo, o la nota cuando el motivo es OTRO."""
    if excluir:
        if motivo not in MOTIVOS:
            raise ValueError('Indica el motivo de la exclusión')
        texto_nota = cfg.nota if nota is None else nota
        if motivo == ArticuloConfig.OTRO and not (texto_nota or '').strip():
            raise ValueError('Con el motivo "Otro" la nota es obligatoria')
    cfg.excluir_calculo = bool(excluir)
    cfg.motivo_exclusion = motivo if excluir else ''
    if nota is not None:
        cfg.nota = nota.strip()[:255]
    return cfg


def aplicar_plan(cfg, activo, unidades=0, hasta=None):
    """Marca o desmarca 'Planificado por gerencia' en `cfg` (sin guardar)."""
    cfg.plan_gerencia = bool(activo)
    cfg.plan_unidades = unidades if activo else 0
    cfg.plan_hasta = hasta if activo else None
    return cfg


def config_de(producto):
    return ArticuloConfig.objects.get_or_create(product=producto)[0]
