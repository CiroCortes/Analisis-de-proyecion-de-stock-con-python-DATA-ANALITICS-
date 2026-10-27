"""El archivo oficial de consultas (data/consultas_datalake.sql) y los cargadores hablan de
los mismos TXT: cada consulta declara un nombre que la plataforma efectivamente busca."""
from django.test import SimpleTestCase

from apps.calculadora.cargadores import ARCHIVOS
from apps.data_ingestion.athena_client import load_queries

# Nombres que lee run_full_datalake_pipeline (consultas 1 a 7)
PIPELINE = [
    'Maestro de Artículos & Costos.txt',
    'Stock Físico por Bodega.txt',
    'Órdenes de Fabricación (OF).txt',
    'Pedidos de Clientes (PC).txt',
    'Órdenes de Compra en Tránsito (OC).txt',
    'Solicitudes de Compra (SC).txt',
    'Entradas de Mercancias (EM).txt',
]


class ConsultasDatalakeTest(SimpleTestCase):
    def test_catorce_consultas_en_orden(self):
        archivos = [a for a, _ in load_queries()]
        self.assertEqual(len(archivos), 14)
        self.assertEqual(archivos[:7], PIPELINE)
        self.assertEqual(archivos[7:9], ['Consumo Mensual.txt', 'Plazos de Entrega OC.txt'])

    def test_cada_archivo_lo_lee_la_plataforma(self):
        esperados = set(PIPELINE) | {largo for largo, _ in ARCHIVOS.values()}
        for archivo, sql in load_queries():
            self.assertIn(archivo, esperados)
            self.assertTrue(sql.upper().startswith('SELECT'), archivo)
            self.assertNotIn('LIMIT', sql.upper(), archivo)

    def test_sin_nombres_repetidos(self):
        archivos = [a for a, _ in load_queries()]
        self.assertEqual(len(archivos), len(set(archivos)))
