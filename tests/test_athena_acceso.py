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
        self.assertContains(self.client.get(reverse('data_ingestion:upload')), 'syncAthenaForm')
        self.client.force_login(self.normal)
        self.assertNotContains(self.client.get(reverse('data_ingestion:upload')), 'syncAthenaForm')
