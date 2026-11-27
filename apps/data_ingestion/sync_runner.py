"""Orquestador de sincronización en vivo (Athena -> data/ -> BD -> Motor S&OP).

Ejecuta el pipeline en segundo plano capturando cada línea de log y `stdout` del hilo
de trabajo en tiempo real para alimentar la consola web y la barra de progreso animada.
"""
import datetime
import re
import sys
import threading
import time
from typing import Any, Callable

from django.db import close_old_connections

_QUERY_PROGRESS_RE = re.compile(r'\[(\d+)/(\d+)\]')


class _ThreadLocalStdoutTee:
    """Interceptor seguro por hilo: captura `print()` solo del hilo de sync y lo espeja al stdout real."""

    def __init__(self, real_stdout):
        self._real = real_stdout
        self._local = threading.local()

    def attach(self, callback: Callable[[str], None]):
        self._local.callback = callback
        self._local.buf = ''

    def detach(self):
        buf = getattr(self._local, 'buf', '')
        cb = getattr(self._local, 'callback', None)
        if buf and cb:
            cb(buf)
        self._local.callback = None
        self._local.buf = ''

    def write(self, data: str):
        self._real.write(data)
        cb = getattr(self._local, 'callback', None)
        if cb and data:
            buf = getattr(self._local, 'buf', '') + data
            while '\n' in buf:
                line, buf = buf.split('\n', 1)
                if line.strip():
                    cb(line.rstrip())
            self._local.buf = buf

    def flush(self):
        self._real.flush()

    def __getattr__(self, name):
        return getattr(self._real, name)


_STDOUT_LOCK = threading.Lock()
_STDOUT_TEE: _ThreadLocalStdoutTee | None = None


def _ensure_stdout_tee() -> _ThreadLocalStdoutTee:
    global _STDOUT_TEE
    with _STDOUT_LOCK:
        if _STDOUT_TEE is None:
            _STDOUT_TEE = _ThreadLocalStdoutTee(sys.stdout)
            sys.stdout = _STDOUT_TEE
        return _STDOUT_TEE


def _clasificar_linea(texto: str) -> str:
    up = texto.upper()
    if '[ERROR]' in up or 'ERROR' in up or 'TRACEBACK' in up or 'FAILED' in up:
        return 'error'
    if '[WARN]' in up or 'ADVERTENCIA' in up or 'SKIP' in up:
        return 'warn'
    if '[OK]' in up or 'COMPLETADA' in up or 'EXITO' in up or 'ÉXITO' in up:
        return 'ok'
    if texto.startswith('[') or texto.startswith('===') or 'DATALAKE' in up:
        return 'phase'
    return 'info'


def _inferir_progreso(texto: str, fase_actual: str, progreso_actual: int) -> tuple[str, int]:
    """Calcula (fase, progreso 0..99) a partir de las líneas emitidas por Athena y el ingestor."""
    up = texto.upper()

    # Fase 1: Consultas AWS Athena [n/total] -> 5% a 55%
    m = _QUERY_PROGRESS_RE.search(texto)
    if fase_actual == 'athena' and m and 'DATALAKE' not in up:
        idx, total = int(m.group(1)), max(1, int(m.group(2)))
        pct = 5 + int((idx / total) * 50)
        return 'athena', max(progreso_actual, min(55, pct))

    # Fase 2: Ingesta TXT a BD -> 56% a 85%
    if 'INICIANDO SINCRONIZACION' in up or '[DATALAKE] 1/' in up:
        return 'ingesta', max(progreso_actual, 58)
    if '[DATALAKE] 2/' in up:
        return 'ingesta', max(progreso_actual, 64)
    if '[DATALAKE] 3/' in up:
        return 'ingesta', max(progreso_actual, 70)
    if '[DATALAKE] 4/' in up:
        return 'ingesta', max(progreso_actual, 75)
    if '[DATALAKE] 5/' in up:
        return 'ingesta', max(progreso_actual, 80)
    if 'CONSOLIDANDO' in up or 'INVENTORYMETRIC' in up:
        return 'ingesta', max(progreso_actual, 84)

    # Fase 3: Motor Calculadora + S&OP Equipos -> 86% a 98%
    if 'MOTOR ANTERIOR' in up or 'CALCULADORA DE COMPRAS' in up or 'RECALCULAR' in up:
        return 'calculo', max(progreso_actual, 88)
    if 'CORRIDA' in up and '[OK]' in up:
        return 'calculo', max(progreso_actual, 96)

    return fase_actual, progreso_actual


class AthenaSyncManager:
    """Singleton thread-safe que coordina una corrida de sincronización y expone su estado en vivo."""

    def __init__(self):
        self._lock = threading.Lock()
        self._state: dict[str, Any] = self._initial_state()

    @staticmethod
    def _initial_state() -> dict[str, Any]:
        return {
            'status': 'idle',      # idle | running | done | error
            'phase': 'idle',       # idle | athena | ingesta | calculo | done | error
            'progress': 0,
            'current_step': '',
            'started_at': None,
            'finished_at': None,
            'elapsed_seconds': 0.0,
            'error': '',
            'logs': [],
            'db_stats': None,
        }

    def _append_log(self, texto: str):
        line = str(texto).strip()
        if not line:
            return
        now_str = datetime.datetime.now().strftime('%H:%M:%S')
        level = _clasificar_linea(line)
        with self._lock:
            phase, pct = _inferir_progreso(line, self._state['phase'], self._state['progress'])
            self._state['phase'] = phase
            self._state['progress'] = pct
            if not line.startswith('==='):
                self._state['current_step'] = line[:140]
            self._state['logs'].append({'ts': now_str, 'text': line, 'level': level})
            if len(self._state['logs']) > 800:
                self._state['logs'] = self._state['logs'][-800:]

    def snapshot(self, since: int = 0) -> dict[str, Any]:
        with self._lock:
            st = self._state
            started = st['started_at']
            finished = st['finished_at']
            if started is not None:
                elapsed = round((finished or time.time()) - started, 1)
            else:
                elapsed = 0.0
            total_logs = len(st['logs'])
            start_idx = max(0, min(since, total_logs))
            return {
                'status': st['status'],
                'phase': st['phase'],
                'progress': st['progress'],
                'current_step': st['current_step'],
                'elapsed_seconds': elapsed,
                'error': st['error'],
                'logs': st['logs'][start_idx:],
                'next_index': total_logs,
                'db_stats': st['db_stats'],
            }

    def start(
        self,
        sync_fn: Callable[..., Any],
        ingest_fn: Callable[[], Any],
        stats_fn: Callable[[], dict[str, int]],
    ) -> dict[str, Any]:
        """Lanza la sincronización en segundo plano si no hay una corriendo."""
        with self._lock:
            if self._state['status'] == 'running':
                return {'started': False, 'already_running': True, **self._unsafe_summary()}
            self._state = self._initial_state()
            self._state['status'] = 'running'
            self._state['phase'] = 'athena'
            self._state['progress'] = 3
            self._state['current_step'] = 'Conectando con AWS Athena (pesco_sbo_pescousd)...'
            self._state['started_at'] = time.time()

        t = threading.Thread(
            target=self._run_worker,
            args=(sync_fn, ingest_fn, stats_fn),
            daemon=True,
            name='athena-sync-worker',
        )
        t.start()
        return {'started': True, 'already_running': False, **self.snapshot(since=0)}

    def _unsafe_summary(self) -> dict[str, Any]:
        st = self._state
        return {
            'status': st['status'],
            'phase': st['phase'],
            'progress': st['progress'],
            'current_step': st['current_step'],
            'next_index': len(st['logs']),
        }

    def _run_worker(self, sync_fn, ingest_fn, stats_fn):
        close_old_connections()
        tee = _ensure_stdout_tee()
        tee.attach(self._append_log)
        try:
            self._append_log('[ATHENA] Iniciando extracción oficial desde AWS Athena (Datalake Pesco)...')
            sync_fn(log=self._append_log)

            with self._lock:
                self._state['phase'] = 'ingesta'
                self._state['progress'] = max(self._state['progress'], 56)
            self._append_log('[OK] Consultas Athena finalizadas. Iniciando ingesta a BD y recalculo S&OP...')

            ingest_fn()

            stats = stats_fn()
            with self._lock:
                self._state['status'] = 'done'
                self._state['phase'] = 'done'
                self._state['progress'] = 100
                self._state['current_step'] = 'Sincronización completada con éxito.'
                self._state['finished_at'] = time.time()
                self._state['db_stats'] = stats
            self._append_log('[OK] Sincronización completa: Datalake, Calculadora de Repuestos y S&OP Equipos actualizados.')
        except Exception as exc:
            with self._lock:
                self._state['status'] = 'error'
                self._state['phase'] = 'error'
                self._state['error'] = str(exc)
                self._state['current_step'] = f'Error: {exc}'
                self._state['finished_at'] = time.time()
            self._append_log(f'[ERROR] {exc}')
        finally:
            tee.detach()
            close_old_connections()


sync_manager = AthenaSyncManager()
