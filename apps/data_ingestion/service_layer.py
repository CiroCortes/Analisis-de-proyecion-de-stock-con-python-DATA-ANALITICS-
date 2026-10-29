"""Cliente de SAP Business One Service Layer, SOLO LECTURA (SPEC-30).

Reglas de TI de Pesco (29-oct-2026) que este modulo hace cumplir por codigo:
- Nunca se escribe en SAP: solo GET, mas POST a Login y Logout. Cualquier otro metodo o ruta se
  rechaza antes de salir a la red (`EscrituraProhibida`).
- Solo desde la red de Pesco (IP nateada al Datacenter): si el servidor no responde, se detiene.
- No sobrecargar el servidor: una sesion, peticiones en secuencia con pausa, paginas chicas, un
  presupuesto maximo de peticiones por corrida y corte automatico si responde lento o con errores.
- Por defecto solo la base de pruebas. Produccion requiere SAP_SL_PERMITIR_PRODUCCION=1.

Configuracion en .env (nunca en el repositorio, que es publico): ver .env.example.
"""
import logging
import os
import socket
import time
from dataclasses import dataclass, field
from urllib.parse import urlparse

import requests
from django.conf import settings

log = logging.getLogger(__name__)

RUTAS_POST_PERMITIDAS = ('Login', 'Logout')


class ErrorServiceLayer(Exception):
    pass


class EscrituraProhibida(ErrorServiceLayer):
    """Se intento algo que no es una lectura: no se envia."""


class SinConexion(ErrorServiceLayer):
    """El servidor no responde: fuera de la red de Pesco o servidor caido."""


class CorteDeSeguridad(ErrorServiceLayer):
    """Se detuvo la corrida para no sobrecargar el servidor (lento, errores o presupuesto)."""


def _env(nombre, defecto=''):
    return os.environ.get(nombre, defecto).strip()


def cargar_env():
    """Lee .env de la raiz sin pisar variables ya definidas (mismo criterio que athena_client)."""
    ruta = os.path.join(settings.BASE_DIR, '.env')
    if not os.path.exists(ruta):
        return
    with open(ruta, encoding='utf-8') as f:
        for linea in f:
            linea = linea.strip()
            if linea and not linea.startswith('#') and '=' in linea:
                k, v = linea.split('=', 1)
                os.environ.setdefault(k.strip(), v.split(' #')[0].strip().strip('"').strip("'"))


@dataclass
class Config:
    url: str                      # https://host:50000/b1s/v1
    usuario: str
    clave: str
    base: str                     # CompanyDB
    verificar_tls: object = True  # True, False o ruta al certificado de TI
    permitir_produccion: bool = False
    bases_prueba: tuple = ('X_CHILE_PRUEBAS',)
    timeout: float = 30           # segundos por peticion
    pausa: float = 0.5            # segundos entre peticiones
    pagina: int = 100             # filas por pagina (Prefer: odata.maxpagesize)
    max_peticiones: int = 300     # presupuesto por corrida
    lento: float = 15             # una respuesta mas lenta cuenta como sintoma de carga
    max_lentas: int = 3
    max_errores: int = 3

    @classmethod
    def desde_env(cls):
        cargar_env()
        tls = _env('SAP_SL_CA_BUNDLE') or (_env('SAP_SL_VERIFICAR_TLS', '1') != '0')
        bases = tuple(b.strip() for b in _env('SAP_SL_BASES_PRUEBA', 'X_CHILE_PRUEBAS').split(',') if b.strip())
        cfg = cls(url=_env('SAP_SL_URL').rstrip('/'), usuario=_env('SAP_SL_USER'), clave=_env('SAP_SL_PASSWORD'),
                  base=_env('SAP_SL_COMPANY'), verificar_tls=tls,
                  permitir_produccion=_env('SAP_SL_PERMITIR_PRODUCCION') == '1', bases_prueba=bases)
        for nombre in ('timeout', 'pausa', 'lento'):
            if _env(f'SAP_SL_{nombre.upper()}'):
                setattr(cfg, nombre, float(_env(f'SAP_SL_{nombre.upper()}')))
        for nombre in ('pagina', 'max_peticiones'):
            if _env(f'SAP_SL_{nombre.upper()}'):
                setattr(cfg, nombre, int(_env(f'SAP_SL_{nombre.upper()}')))
        return cfg

    def validar(self):
        faltan = [n for n, v in (('SAP_SL_URL', self.url), ('SAP_SL_USER', self.usuario),
                                 ('SAP_SL_PASSWORD', self.clave), ('SAP_SL_COMPANY', self.base)) if not v]
        if faltan:
            raise ErrorServiceLayer(f'Faltan en .env: {", ".join(faltan)}')
        if not self.url.startswith('https://'):
            raise ErrorServiceLayer('SAP_SL_URL debe ser https:// (la clave viaja por internet hasta el Datacenter)')
        if self.base not in self.bases_prueba and not self.permitir_produccion:
            raise ErrorServiceLayer(f'La base {self.base} no es de pruebas ({", ".join(self.bases_prueba)}). '
                                    'Para produccion se requiere SAP_SL_PERMITIR_PRODUCCION=1, acordado con TI.')
        if not 1 <= self.pagina <= 500:
            raise ErrorServiceLayer('SAP_SL_PAGINA debe estar entre 1 y 500')


@dataclass
class Estadisticas:
    peticiones: int = 0
    filas: int = 0
    segundos: float = 0.0
    lentas: int = 0
    errores: int = 0
    detalle: list = field(default_factory=list)   # (ruta, segundos, estado)

    def resumen(self):
        return (f'{self.peticiones} peticiones, {self.filas} filas, {self.segundos:.1f} s, '
                f'{self.lentas} lentas, {self.errores} errores')


class ClienteServiceLayer:
    """Uso:
        with ClienteServiceLayer(Config.desde_env()) as sl:
            for fila in sl.leer('Items', select='ItemCode,ItemName', filtro="Valid eq 'tYES'"):
                ...
    """

    def __init__(self, config, sesion=None):
        config.validar()
        self.cfg = config
        self.http = sesion or requests.Session()
        self.http.verify = config.verificar_tls
        self.stats = Estadisticas()
        self._conectado = False
        self._errores_seguidos = 0

    # ── Sesion ────────────────────────────────────────────────────────────────
    def __enter__(self):
        self.comprobar_red()
        self._enviar('POST', 'Login', json={'CompanyDB': self.cfg.base, 'UserName': self.cfg.usuario,
                                            'Password': self.cfg.clave})
        self._conectado = True
        return self

    def __exit__(self, *exc):
        if self._conectado:
            try:
                self._enviar('POST', 'Logout', cuenta=False)
            except ErrorServiceLayer as e:          # cerrar nunca debe ocultar el error original
                log.warning('Logout del Service Layer fallo: %s', e)
            self._conectado = False
        self.http.close()
        return False

    def comprobar_red(self, timeout=5):
        """Abre un socket al puerto del servidor sin enviar nada. Falla rapido fuera de la red de Pesco."""
        destino = urlparse(self.cfg.url)
        try:
            with socket.create_connection((destino.hostname, destino.port or 443), timeout=timeout):
                return True
        except OSError as e:
            raise SinConexion(f'No hay conexion con {destino.hostname}:{destino.port}. El Service Layer solo '
                              f'responde desde la red de Pesco (IP nateada al Datacenter). Detalle: {e}')

    # ── Lectura ───────────────────────────────────────────────────────────────
    def leer(self, entidad, select, filtro=None, orden=None, maximo=None):
        """Recorre una coleccion pagina a pagina (siguiendo odata.nextLink). `select` es obligatorio:
        nunca se piden todos los campos. `maximo` corta despues de esa cantidad de filas."""
        if not select:
            raise ErrorServiceLayer('Siempre indicar $select: traer todos los campos sobrecarga el servidor')
        params = {'$select': select}
        if filtro:
            params['$filter'] = filtro
        if orden:
            params['$orderby'] = orden
        ruta, entregadas = entidad, 0
        while ruta:
            datos = self._enviar('GET', ruta, params=params)
            params = None                        # el nextLink ya trae los parametros
            for fila in datos.get('value', []):
                yield fila
                entregadas += 1
                if maximo and entregadas >= maximo:
                    return
            ruta = datos.get('odata.nextLink') or datos.get('@odata.nextLink')

    def contar(self, entidad, filtro=None):
        """Cantidad de registros sin traerlos ($count)."""
        params = {'$filter': filtro} if filtro else None
        return int(self._enviar('GET', f'{entidad}/$count', params=params, json_resp=False))

    # ── Unico punto de salida a la red ────────────────────────────────────────
    def _enviar(self, metodo, ruta, params=None, json=None, cuenta=True, json_resp=True):
        metodo = metodo.upper()
        base_ruta = ruta.split('?')[0].rsplit('/b1s/v1/', 1)[-1].strip('/')
        if metodo != 'GET' and not (metodo == 'POST' and base_ruta in RUTAS_POST_PERMITIDAS):
            raise EscrituraProhibida(f'{metodo} {base_ruta}: la plataforma solo lee de SAP (SPEC-30)')
        if cuenta and self.stats.peticiones >= self.cfg.max_peticiones:
            raise CorteDeSeguridad(f'Presupuesto de {self.cfg.max_peticiones} peticiones agotado')
        if self.stats.peticiones:
            time.sleep(self.cfg.pausa)
        url = ruta if ruta.startswith('http') else f'{self.cfg.url}/{ruta.lstrip("/")}'
        inicio = time.monotonic()
        try:
            r = self.http.request(metodo, url, params=params, json=json, timeout=self.cfg.timeout,
                                  headers={'Prefer': f'odata.maxpagesize={self.cfg.pagina}'})
        except requests.exceptions.SSLError as e:
            raise ErrorServiceLayer('El certificado del servidor no es de confianza. Pedir a TI el certificado y '
                                    f'ponerlo en SAP_SL_CA_BUNDLE. Detalle: {e}')
        except requests.exceptions.RequestException as e:
            self._registrar(base_ruta, time.monotonic() - inicio, 'sin respuesta', cuenta)
            self._error()
            raise SinConexion(f'{metodo} {base_ruta}: {e}')
        seg = time.monotonic() - inicio
        self._registrar(base_ruta, seg, r.status_code, cuenta)
        if seg > self.cfg.lento:
            self.stats.lentas += 1
            if self.stats.lentas >= self.cfg.max_lentas:
                raise CorteDeSeguridad(f'{self.stats.lentas} respuestas de mas de {self.cfg.lento:g} s: '
                                       'el servidor esta cargado, se corta la corrida')
        if r.status_code >= 400:
            self._error()
            raise ErrorServiceLayer(f'{metodo} {base_ruta}: HTTP {r.status_code} {self._mensaje(r)}')
        self._errores_seguidos = 0
        if metodo == 'POST' or not json_resp:
            return r.text
        datos = r.json()
        self.stats.filas += len(datos.get('value', []))
        return datos

    def _registrar(self, ruta, seg, estado, cuenta):
        if cuenta:
            self.stats.peticiones += 1
        self.stats.segundos += seg
        self.stats.detalle.append((ruta, round(seg, 2), estado))

    def _error(self):
        self.stats.errores += 1
        self._errores_seguidos += 1
        if self._errores_seguidos >= self.cfg.max_errores:
            raise CorteDeSeguridad(f'{self._errores_seguidos} errores seguidos: se corta la corrida')

    @staticmethod
    def _mensaje(r):
        try:
            return r.json().get('error', {}).get('message', {}).get('value', '')[:200]
        except ValueError:
            return r.text[:200]
