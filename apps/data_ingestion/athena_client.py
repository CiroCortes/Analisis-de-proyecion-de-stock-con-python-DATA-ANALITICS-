"""Cliente Athena (boto3): ejecuta las consultas del datalake y deja los TXT en data/.

Credenciales y parametros por variables de entorno o archivo .env en la raiz
(ver .env.example). Los TXT se escriben en el mismo formato de tabla con pipes
que exporta DBeaver, por lo que datalake_ingest.py los lee sin cambios.
"""
import csv
import io
import os
import re
import time
from urllib.parse import urlparse

from django.conf import settings

SQL_FILE = os.path.join(settings.BASE_DIR, 'data', 'consultas_optimizadas_datalake.sql')

# Orden = numero de consulta en el .sql
OUTPUT_FILES = [
    'Maestro de Artículos & Costos.txt',
    'Stock Físico por Bodega.txt',
    'Órdenes de Fabricación (OF).txt',
    'Pedidos de Clientes (PC).txt',
    'Órdenes de Compra en Tránsito (OC).txt',
    'Solicitudes de Compra (SC).txt',
    'Entradas de Mercancias (EM).txt',
]


def _load_dotenv():
    path = os.path.join(settings.BASE_DIR, '.env')
    if not os.path.exists(path):
        return
    with open(path, encoding='utf-8') as fp:
        for line in fp:
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            k, v = line.split('=', 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def load_queries(sql_file=SQL_FILE):
    """Devuelve las consultas del .sql en orden (sin comentarios)."""
    with open(sql_file, encoding='utf-8') as fp:
        text = re.sub(r'--[^\n]*', '', fp.read())
    return [s.strip() for s in text.split(';') if s.strip()]


def _clients():
    import boto3
    _load_dotenv()
    region = os.environ.get('AWS_REGION') or os.environ.get('AWS_DEFAULT_REGION')
    if not region or not os.environ.get('ATHENA_OUTPUT_S3'):
        raise RuntimeError('Faltan AWS_REGION y/o ATHENA_OUTPUT_S3 (ver .env.example).')
    session = boto3.Session(region_name=region)  # toma AWS_ACCESS_KEY_ID/SECRET/SESSION_TOKEN o AWS_PROFILE
    return session.client('athena'), session.client('s3')


def run_query(sql, athena, s3, poll_seconds=2):
    """Ejecuta una consulta y devuelve (columnas, filas) leyendo el CSV de resultados en S3."""
    params = {
        'QueryString': sql,
        'ResultConfiguration': {'OutputLocation': os.environ['ATHENA_OUTPUT_S3']},
    }
    if os.environ.get('ATHENA_WORKGROUP'):
        params['WorkGroup'] = os.environ['ATHENA_WORKGROUP']
    qid = athena.start_query_execution(**params)['QueryExecutionId']
    while True:
        q = athena.get_query_execution(QueryExecutionId=qid)['QueryExecution']
        state = q['Status']['State']
        if state in ('SUCCEEDED', 'FAILED', 'CANCELLED'):
            break
        time.sleep(poll_seconds)
    if state != 'SUCCEEDED':
        raise RuntimeError(f"Athena {state}: {q['Status'].get('StateChangeReason', '')}")
    loc = urlparse(q['ResultConfiguration']['OutputLocation'])
    body = s3.get_object(Bucket=loc.netloc, Key=loc.path.lstrip('/'))['Body'].read().decode('utf-8')
    reader = csv.reader(io.StringIO(body))
    cols = next(reader)
    return cols, list(reader)


def write_pipe_txt(path, cols, rows):
    def clean(v):
        return str(v).replace('|', '/').replace('\r', ' ').replace('\n', ' ')
    with open(path, 'w', encoding='utf-8') as fp:
        fp.write('|' + '|'.join(cols) + '|\n')
        fp.write('|' + '|'.join('-' * len(c) for c in cols) + '|\n')
        for r in rows:
            fp.write('|' + '|'.join(clean(v) for v in r) + '|\n')


def sync_datalake(only=None, out_dir=None, log=print):
    """Ejecuta las consultas (todas o las numeradas en `only`) y escribe los TXT."""
    out_dir = out_dir or os.path.join(settings.BASE_DIR, 'data')
    queries = load_queries()
    if len(queries) != len(OUTPUT_FILES):
        raise RuntimeError(f'Se esperaban {len(OUTPUT_FILES)} consultas y el .sql trae {len(queries)}.')
    athena, s3 = _clients()
    for n, (sql, fname) in enumerate(zip(queries, OUTPUT_FILES), start=1):
        if only and n not in only:
            continue
        t0 = time.time()
        log(f'[{n}/{len(queries)}] {fname} ...')
        cols, rows = run_query(sql, athena, s3)
        # escribe a temporal y reemplaza: no se pierde el TXT previo si algo falla
        tmp = os.path.join(out_dir, fname + '.tmp')
        write_pipe_txt(tmp, cols, rows)
        os.replace(tmp, os.path.join(out_dir, fname))
        log(f'    {len(rows):,} filas en {time.time() - t0:.0f}s')
