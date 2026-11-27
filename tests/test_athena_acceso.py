"""La conexion directa a Athena solo existe en DEBUG y para administradores."""
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.data_ingestion import athena_client, views


class AthenaAccesoTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        U = get_user_model()
        cls.normal = U.objects.create_user('normal', password='x')
        cls.admin = U.objects.create_superuser('admin', 'a@a.cl', 'x')

    @override_settings(DEBUG=True)
    def test_permiso_admin_en_debug(self):
        self.assertTrue(athena_client.athena_permitido(self.admin))
        self.assertFalse(athena_client.athena_permitido(self.normal))

    @override_settings(DEBUG=False)
    def test_permiso_nunca_sin_debug(self):
        self.assertFalse(athena_client.athena_permitido(self.admin))

    def _post(self, user):
        llamadas = []
        with mock.patch.object(views, 'sync_datalake', lambda **k: llamadas.append('athena')), \
                mock.patch.object(views, 'run_full_datalake_pipeline', lambda: llamadas.append('ingesta')):
            self.client.force_login(user)
            self.client.post(reverse('data_ingestion:upload'), {'action': 'sync_athena'})
        return llamadas

    @override_settings(DEBUG=True)
    def test_post_admin_debug_ejecuta(self):
        self.assertEqual(self._post(self.admin), ['athena', 'ingesta'])

    @override_settings(DEBUG=True)
    def test_post_usuario_normal_bloqueado(self):
        self.assertEqual(self._post(self.normal), [])

    @override_settings(DEBUG=False)
    def test_post_admin_sin_debug_bloqueado(self):
        self.assertEqual(self._post(self.admin), [])

    @override_settings(DEBUG=True)
    def test_boton_visible_solo_para_admin(self):
        self.client.force_login(self.admin)
        resp_admin = self.client.get(reverse('data_ingestion:upload'))
        self.assertContains(resp_admin, 'syncAthenaForm')
        self.assertNotContains(resp_admin, 'syncDatalakeForm')
        self.client.force_login(self.normal)
        self.assertNotContains(self.client.get(reverse('data_ingestion:upload')), 'syncAthenaForm')

    @override_settings(DEBUG=True)
    def test_streaming_athena_permisos_y_logs(self):
        import time as _t
        # Usuario normal bloqueado en endpoints JSON
        self.client.force_login(self.normal)
        self.assertEqual(self.client.post(reverse('data_ingestion:sync_athena_start')).status_code, 403)
        self.assertEqual(self.client.get(reverse('data_ingestion:sync_athena_status')).status_code, 403)

        # Admin inicia job en vivo con mocks y captura logs + stdout
        def fake_sync(log=print):
            log('[1/2] Maestro de Artículos & Costos.txt ...')
            log('[2/2] Stock Físico por Bodega.txt ...')

        def fake_ingest():
            print('[DATALAKE] 1/5 Instando Maestro...')
            print('[OK] Corrida 1: listo')

        self.client.force_login(self.admin)
        with mock.patch.object(views, 'sync_datalake', fake_sync), \
                mock.patch.object(views, 'run_full_datalake_pipeline', fake_ingest):
            r_start = self.client.post(reverse('data_ingestion:sync_athena_start'))
            self.assertEqual(r_start.status_code, 200)
            self.assertTrue(r_start.json()['started'])

            # Esperar fin del hilo (ms)
            for _ in range(40):
                st = self.client.get(reverse('data_ingestion:sync_athena_status')).json()
                if st['status'] in ('done', 'error'):
                    break
                _t.sleep(0.05)

            self.assertEqual(st['status'], 'done')
            self.assertEqual(st['progress'], 100)
            textos = '\n'.join(l['text'] for l in st['logs'])
            self.assertIn('[1/2] Maestro de Artículos', textos)
            self.assertIn('[DATALAKE] 1/5 Instando Maestro', textos)
            self.assertIsNotNone(st['db_stats'])
