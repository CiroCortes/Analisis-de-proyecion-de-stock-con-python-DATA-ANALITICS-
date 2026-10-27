from django.core.management.base import BaseCommand

from apps.calculadora.cargadores import cargar_todo
from apps.calculadora.servicio import ejecutar_corrida


class Command(BaseCommand):
    help = 'Carga los TXT de la Calculadora y ejecuta una corrida completa (SPEC-18).'

    def add_arguments(self, parser):
        parser.add_argument('--sin-carga', action='store_true', help='Solo calcula, sin recargar los TXT')
        parser.add_argument('--solicitudes', action='store_true', help='Genera las solicitudes del dia al terminar')

    def handle(self, *args, **opts):
        if not opts['sin_carga']:
            self.stdout.write(f'Carga: {cargar_todo()}')
        corrida = ejecutar_corrida()
        self.stdout.write(self.style.SUCCESS(f'Corrida {corrida.pk}: {corrida.resumen}'))
        if opts['solicitudes']:
            from apps.calculadora.solicitudes import generar
            self.stdout.write(f'Solicitudes creadas: {len(generar())}')
