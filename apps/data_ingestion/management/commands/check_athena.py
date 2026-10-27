from django.core.management.base import BaseCommand

from apps.data_ingestion.athena_client import _clients, run_query


class Command(BaseCommand):
    help = 'Prueba la conexion a Athena (credenciales, workgroup, bucket y acceso a la base SAP).'

    def handle(self, *args, **opts):
        athena, s3 = _clients()
        sts_ok = False
        try:
            import boto3
            ident = boto3.client('sts').get_caller_identity()
            self.stdout.write(f"1. Credenciales OK: {ident['Arn']}")
            sts_ok = True
        except Exception as e:
            self.stdout.write(f'1. STS no disponible ({type(e).__name__}); se prueba Athena directo.')
        _, rows = run_query('SELECT 1', athena, s3)
        self.stdout.write(f'2. Athena + bucket de resultados OK (SELECT 1 -> {rows[0][0]}).')
        _, rows = run_query('SELECT COUNT(*) FROM pesco_sbo_pescousd.oitm', athena, s3)
        self.stdout.write(f'3. Base SAP OK: oitm tiene {rows[0][0]} articulos.')
