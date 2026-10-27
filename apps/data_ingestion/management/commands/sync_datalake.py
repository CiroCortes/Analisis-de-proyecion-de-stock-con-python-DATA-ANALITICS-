from django.core.management.base import BaseCommand

from apps.data_ingestion.athena_client import sync_datalake


class Command(BaseCommand):
    help = 'Descarga las consultas del datalake (Athena) a data/*.txt y opcionalmente ingesta.'

    def add_arguments(self, parser):
        parser.add_argument('--only', type=int, nargs='+', help='Numeros de consulta (1-7). Por defecto todas.')
        parser.add_argument('--ingest', action='store_true', help='Ejecuta la ingesta tras descargar.')

    def handle(self, *args, **opts):
        sync_datalake(only=opts['only'], log=self.stdout.write)
        if opts['ingest']:
            from apps.data_ingestion.datalake_ingest import run_full_datalake_pipeline
            run_full_datalake_pipeline()
