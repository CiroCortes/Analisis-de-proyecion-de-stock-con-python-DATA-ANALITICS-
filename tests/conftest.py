"""Configuracion comun de pytest.

Django 5.1 + Python 3.14: BaseContext.__copy__ usa copy(super()), que ya no funciona en
3.14, y el test client copia el contexto de cada plantilla renderizada. Solo afecta a los
tests (el servidor no copia contextos). Se puede quitar al subir a Django >= 5.2.
"""
from django.template.context import BaseContext


def _copiar_contexto(self):
    duplicado = object.__new__(self.__class__)
    duplicado.__dict__ = self.__dict__.copy()
    duplicado.dicts = self.dicts[:]
    return duplicado


BaseContext.__copy__ = _copiar_contexto
