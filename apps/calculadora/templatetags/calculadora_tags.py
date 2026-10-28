"""Ayuda en contexto (SPEC-19 §7.3). Uso: {% load calculadora_tags %} ... {% ayuda 'stock_seguridad' %}"""
from django import template
from django.urls import reverse
from django.utils.html import format_html

from apps.calc.red import NODO_SANTIAGO
from apps.calculadora.glosario import termino

register = template.Library()


@register.filter
def nodo(codigo):
    """Nombre de un nodo de la red: la 013 representa a todo Santiago (SPEC-21)."""
    return 'Santiago (013)' if codigo == NODO_SANTIAGO else codigo


@register.simple_tag
def ayuda(clave):
    """Icono (?) con la definicion corta del glosario; enlaza a la Guia."""
    nombre, definicion, _, _ = termino(clave)
    return format_html(
        '<a href="{}#{}" class="inline-flex items-center text-slate-300 hover:text-pesco-cyan align-middle ml-0.5" '
        'title="{}: {}" aria-label="Qué significa {}"><i class="fa-regular fa-circle-question text-[11px]"></i></a>',
        reverse('calculadora:guia'), clave, nombre, definicion, nombre)
