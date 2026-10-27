"""Parametros editables por nivel, con registro de cambios (documento §7, SPEC-14).

Niveles: GENERAL < FAMILIA (grupo SAP) / BODEGA < PROVEEDOR < ARTICULO. Manda el mas
especifico. "Familia" = grupo de articulos SAP (decision abierta #6, SPEC-14 §2).
"""
from collections import defaultdict

from django.db import transaction

from apps.calc.params import ARTICULO, BODEGA, CATALOGO, DEFAULTS, FAMILIA, GENERAL, PROVEEDOR, con_valores, convertir, validar

from .models import ParametroCambio, ParametroValor

ROLES_EDICION = ('Administrador Abastecimiento',)
ROLES_APROBACION = ('Jefe Abastecimiento', 'Administrador Abastecimiento')


def puede_editar(user):
    return user.is_superuser or user.groups.filter(name__in=ROLES_EDICION).exists()


def puede_aprobar(user):
    return user.is_superuser or user.groups.filter(name__in=ROLES_APROBACION).exists()


class Resolutor:
    """Entrega el Params de un articulo combinando los niveles. Cachea por combinacion."""

    def __init__(self, valores=None, extra_general=None):
        self.por_nivel = defaultdict(dict)   # (nivel, ambito) -> {clave: valor}
        filas = valores if valores is not None else ParametroValor.objects.all()
        for v in filas:
            if v.clave in CATALOGO:
                try:
                    self.por_nivel[(v.nivel, v.ambito)][v.clave] = convertir(v.clave, v.valor)
                except (TypeError, ValueError):
                    continue
        general = dict(self.por_nivel.get((GENERAL, ''), {}))
        general.update(extra_general or {})
        self.general = con_valores(DEFAULTS, general)
        self._cache = {}

    def para(self, familia='', proveedor='', articulo='', bodega='013-PP'):
        claves = [(FAMILIA, familia), (BODEGA, bodega), (PROVEEDOR, proveedor), (ARTICULO, articulo)]
        presentes = tuple((n, a) for n, a in claves if a and (n, a) in self.por_nivel)
        if not presentes:
            return self.general
        if presentes not in self._cache:
            valores = {}
            for nivel_ambito in presentes:      # en orden de prioridad creciente
                valores.update(self.por_nivel[nivel_ambito])
            self._cache[presentes] = con_valores(self.general, valores)
        return self._cache[presentes]


def valor_actual(clave, nivel=GENERAL, ambito=''):
    fila = ParametroValor.objects.filter(clave=clave, nivel=nivel, ambito=ambito).first()
    if fila:
        return convertir(clave, fila.valor)
    return getattr(DEFAULTS, clave) if nivel == GENERAL else None


@transaction.atomic
def guardar(clave, valor, usuario, nivel=GENERAL, ambito='', motivo=''):
    """Valida, guarda y registra el cambio. `valor=None` borra la excepcion de un nivel."""
    _, niveles, _, _ = CATALOGO[clave]
    if nivel not in niveles:
        raise ValueError(f'El parametro no se puede ajustar a nivel {nivel.lower()}')
    if nivel != GENERAL and not ambito:
        raise ValueError('Falta indicar a que familia, proveedor, articulo o bodega aplica')
    fila = ParametroValor.objects.filter(clave=clave, nivel=nivel, ambito=ambito).first()
    anterior = fila.valor if fila else (str(getattr(DEFAULTS, clave)) if nivel == GENERAL else '')

    if valor is None or valor == '':
        if fila:
            fila.delete()
        nuevo = ''
    else:
        v = validar(clave, valor)
        nuevo = str(v)
        ParametroValor.objects.update_or_create(clave=clave, nivel=nivel, ambito=ambito, defaults={'valor': nuevo})

    if nuevo != anterior:
        ParametroCambio.objects.create(clave=clave, nivel=nivel, ambito=ambito, valor_anterior=anterior,
                                       valor_nuevo=nuevo, usuario=usuario, motivo=motivo[:255])
    return nuevo
