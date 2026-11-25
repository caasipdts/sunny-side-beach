import argparse
import configparser
import hashlib
import hmac
import json
import logging
import os
import signal
import ssl
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import xmlrpc.client
from pathlib import Path

if os.name == 'nt':
    import msvcrt
else:
    import fcntl


_LOGGER = logging.getLogger('sunnyside_sync.worker')
_PROTOCOL_VERSION = '1'
_PULL_PAGE_SIZE = 200
_MANIFEST_PAGE_SIZE = 500
_SYNC_MODELS = (
    'sunnyside.seating.type',
    'res.partner',
    'sunnyside.visit',
    'sunnyside.booking',
    'sunnyside.booking.payment',
    'ir.attachment',
)
_CLOUD_TIMEOUT_SECONDS = 20


class WorkerError(Exception):
    pass


class SingleInstanceLock:
    def __init__(self, path):
        self.path = Path(path)
        self.stream = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.stream = self.path.open('a+b')
        self.stream.seek(0)
        if not self.stream.read(1):
            self.stream.write(b'\0')
            self.stream.flush()
        self.stream.seek(0)
        try:
            if os.name == 'nt':
                msvcrt.locking(self.stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                fcntl.flock(self.stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            self.stream.close()
            self.stream = None
            raise WorkerError('Another Sunnyside sync worker already holds the lock.') from error
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if self.stream:
            self.stream.seek(0)
            if os.name == 'nt':
                msvcrt.locking(self.stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(self.stream.fileno(), fcntl.LOCK_UN)
            self.stream.close()
            self.stream = None


class OdooRpc:
    def __init__(self, url, database, username, password):
        root = url.rstrip('/')
        self.database = database
        self.password = password
        self.common = xmlrpc.client.ServerProxy(
            root + '/xmlrpc/2/common',
            allow_none=True,
            use_builtin_types=True,
        )
        self.models = xmlrpc.client.ServerProxy(
            root + '/xmlrpc/2/object',
            allow_none=True,
            use_builtin_types=True,
        )
        self.uid = self.common.authenticate(database, username, password, {})
        if not self.uid:
            raise WorkerError('Local Odoo authentication failed.')

    def call(self, model, method, *args):
        return self.models.execute_kw(
            self.database,
            self.uid,
            self.password,
            model,
            method,
            list(args),
        )


class SyncWorker:
    def __init__(self, config, stop_event=None):
        self.config = config
        self.stop_event = stop_event or threading.Event()
        self.device_id = config['cloud']['device_id']
        self.token = Path(config['cloud']['token_file']).read_text(
            encoding='utf-8'
        ).strip()
        if len(self.token) < 32:
            raise WorkerError('The cloud device token must contain at least 256 bits.')
        self.rpc = OdooRpc(
            config['odoo']['url'],
            config['odoo']['database'],
            config['odoo']['username'],
            config['odoo']['password'],
        )
        if config['cloud'].getboolean('verify_tls', fallback=True):
            ca_file = config['cloud'].get('ca_file', '').strip()
            self.ssl_context = ssl.create_default_context(cafile=ca_file or None)
        else:
            _LOGGER.warning('TLS certificate verification is disabled.')
            self.ssl_context = ssl._create_unverified_context()
        self.online_interval = config['worker'].getint('online_interval', fallback=15)
        self.retry_min = config['worker'].getint('retry_min', fallback=5)
        self.retry_max = config['worker'].getint('retry_max', fallback=60)
        self.reconcile_interval = config['worker'].getint(
            'reconcile_interval',
            fallback=3600,
        )
        self.last_reconcile_at = 0
        self.lock_path = config['worker'].get(
            'lock_file',
            str(Path(os.environ.get('LOCALAPPDATA', Path.home()))
                / 'SunnysideSync' / 'worker.lock'),
        )

    def _headers(self):
        return {
            'Authorization': 'Bearer ' + self.token,
            'X-Device-ID': self.device_id,
            'X-Sunnyside-Sync-Version': _PROTOCOL_VERSION,
            'Accept': 'application/json',
        }

    def _request_json(self, path, method='GET', payload=None):
        url = self.config['cloud']['url'].rstrip('/') + path
        data = None
        headers = self._headers()
        if payload is not None:
            data = json.dumps(payload, separators=(',', ':')).encode('utf-8')
            headers['Content-Type'] = 'application/json'
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        start = time.monotonic()
        try:
            with urllib.request.urlopen(
                request,
                timeout=_CLOUD_TIMEOUT_SECONDS,
                context=self.ssl_context,
            ) as response:
                body = response.read()
        except urllib.error.HTTPError as error:
            detail = error.read(2048).decode('utf-8', errors='replace')
            raise WorkerError(
                'Cloud API returned HTTP %s: %s' % (error.code, detail)
            ) from error
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise WorkerError('Cloud API request failed: %s' % error) from error
        elapsed_ms = int((time.monotonic() - start) * 1000)
        try:
            result = json.loads(body.decode('utf-8'))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise WorkerError('Cloud API returned invalid JSON.') from error
        return result, elapsed_ms

    def _record_result(self, success, elapsed_ms=0, error=''):
        self.rpc.call(
            'sunnyside.sync.state',
            'worker_record_result',
            success,
            elapsed_ms,
            error,
        )

    def check_cloud(self):
        try:
            response, elapsed_ms = self._request_json('/sunnyside_sync/v1/health')
            expected = hmac.new(
                hashlib.sha256(self.token.encode('utf-8')).digest(),
                str(response.get('timestamp', '')).encode('ascii'),
                hashlib.sha256,
            ).hexdigest()
            signature = response.get('signature', '')
            if response.get('service') != 'sunnyside' or not hmac.compare_digest(
                expected, signature
            ):
                raise WorkerError('Cloud health response signature is invalid.')
            self._record_result(True, elapsed_ms)
            return True
        except WorkerError as error:
            _LOGGER.warning('%s', error)
            self._record_result(False, error=str(error))
            return False

    def push_all(self):
        session_uuid = self.rpc.call(
            'sunnyside.sync.state',
            'worker_open_session',
            'push',
        )
        try:
            while not self.stop_event.is_set():
                chunk = self.rpc.call(
                    'sunnyside.sync.state',
                    'worker_next_chunk',
                    session_uuid,
                )
                if not chunk:
                    break
                response, elapsed_ms = self._request_json(
                    '/sunnyside_sync/v1/push',
                    method='POST',
                    payload={
                        'session_id': chunk['session_uuid'],
                        'chunk_no': chunk['chunk_no'],
                        'items': chunk['payload'],
                    },
                )
                self.rpc.call(
                    'sunnyside.sync.state',
                    'worker_apply_ack',
                    chunk['id'],
                    response,
                )
                self._record_result(True, elapsed_ms)
        except (WorkerError, xmlrpc.client.Error, OSError) as error:
            self.rpc.call(
                'sunnyside.sync.state',
                'worker_close_session',
                session_uuid,
                str(error),
            )
            self._record_result(False, error=str(error))
            return False

        self.rpc.call(
            'sunnyside.sync.state',
            'worker_close_session',
            session_uuid,
            False,
        )
        return True

    def pull_all(self):
        status = self.rpc.call('sunnyside.sync.state', 'worker_status')
        cursor = status['pull_cursor']
        scan_after = max(0, cursor - 500)
        session_uuid = self.rpc.call(
            'sunnyside.sync.state',
            'worker_open_session',
            'pull',
        )
        try:
            while not self.stop_event.is_set():
                query = urllib.parse.urlencode({
                    'after': scan_after,
                    'limit': _PULL_PAGE_SIZE,
                })
                response, elapsed_ms = self._request_json(
                    '/sunnyside_sync/v1/pull?' + query
                )
                items = response.get('items')
                next_cursor = response.get('next_cursor')
                if not isinstance(items, list) or not isinstance(next_cursor, int):
                    raise WorkerError('Cloud API returned an invalid pull page.')
                new_cursor = max(cursor, next_cursor)
                if items or new_cursor > cursor:
                    self.rpc.call(
                        'sunnyside.sync.state',
                        'worker_apply_remote',
                        items,
                        new_cursor,
                    )
                    cursor = new_cursor
                    self._record_result(True, elapsed_ms)
                if not items or next_cursor <= scan_after:
                    break
                scan_after = next_cursor
        except (WorkerError, xmlrpc.client.Error, OSError) as error:
            self.rpc.call(
                'sunnyside.sync.state',
                'worker_close_session',
                session_uuid,
                str(error),
            )
            self._record_result(False, error=str(error))
            return False
        self.rpc.call(
            'sunnyside.sync.state',
            'worker_close_session',
            session_uuid,
            False,
        )
        return True

    def _local_manifest(self, model):
        entries = []
        after_uuid = ''
        while not self.stop_event.is_set():
            page = self.rpc.call(
                'sunnyside.sync.state',
                'worker_manifest',
                model,
                after_uuid,
                _MANIFEST_PAGE_SIZE,
            ).get(model, [])
            if not isinstance(page, list):
                raise WorkerError('Local Odoo returned an invalid sync manifest.')
            entries.extend(page)
            if len(page) < _MANIFEST_PAGE_SIZE:
                break
            after_uuid = page[-1].get('uuid', '')
            if not after_uuid:
                raise WorkerError('Local Odoo returned an invalid manifest cursor.')
        return {entry['uuid']: entry for entry in entries}

    def _cloud_manifest(self, model):
        entries = []
        after_uuid = ''
        while not self.stop_event.is_set():
            query = urllib.parse.urlencode({
                'model': model,
                'after_uuid': after_uuid,
                'limit': _MANIFEST_PAGE_SIZE,
            })
            response, _elapsed_ms = self._request_json(
                '/sunnyside_sync/v1/manifest?' + query
            )
            page = response.get(model)
            if not isinstance(page, list):
                raise WorkerError('Cloud API returned an invalid sync manifest.')
            entries.extend(page)
            if len(page) < _MANIFEST_PAGE_SIZE:
                break
            after_uuid = page[-1].get('uuid', '')
            if not after_uuid:
                raise WorkerError('Cloud API returned an invalid manifest cursor.')
        return {entry['uuid']: entry for entry in entries}

    def reconcile_all(self):
        local_status = self.rpc.call('sunnyside.sync.state', 'worker_status')
        cursor = local_status['pull_cursor']
        for model in _SYNC_MODELS:
            local = self._local_manifest(model)
            cloud = self._cloud_manifest(model)
            for record_uuid, remote_entry in cloud.items():
                local_entry = local.get(record_uuid)
                if local_entry and local_entry['rev'] > remote_entry['rev']:
                    self.rpc.call(
                        'sunnyside.sync.state',
                        'worker_requeue',
                        model,
                        record_uuid,
                    )
                    continue
                query = urllib.parse.urlencode({
                    'model': model,
                    'record_uuid': record_uuid,
                })
                item, elapsed_ms = self._request_json(
                    '/sunnyside_sync/v1/record?' + query
                )
                if (
                    not isinstance(item, dict)
                    or item.get('model') != model
                    or item.get('uuid') != record_uuid
                ):
                    raise WorkerError('Cloud API returned an invalid reconciled record.')
                self.rpc.call(
                    'sunnyside.sync.state',
                    'worker_apply_remote',
                    [item],
                    cursor,
                )
                self._record_result(True, elapsed_ms)

            for record_uuid in local.keys() - cloud.keys():
                self.rpc.call(
                    'sunnyside.sync.state',
                    'worker_requeue',
                    model,
                    record_uuid,
                )
        return True

    def run_once(self):
        if not self.check_cloud():
            return False
        status = self.rpc.call('sunnyside.sync.state', 'worker_status')
        if status['state'] not in ('online', 'degraded'):
            return False
        if not self.push_all():
            return False
        if not self.pull_all():
            return False
        now = time.monotonic()
        if now - self.last_reconcile_at >= self.reconcile_interval:
            if not self.reconcile_all():
                return False
            self.last_reconcile_at = now
        return True

    def run(self):
        retry_delay = self.retry_min
        with SingleInstanceLock(self.lock_path):
            _LOGGER.info('Sunnyside sync worker started for device %s.', self.device_id)
            while not self.stop_event.is_set():
                try:
                    connected = self.run_once()
                    status = self.rpc.call('sunnyside.sync.state', 'worker_status')
                    if connected and status['state'] in ('online', 'degraded'):
                        retry_delay = self.retry_min
                        delay = self.online_interval
                    else:
                        delay = retry_delay
                        retry_delay = min(self.retry_max, max(self.retry_min, retry_delay * 2))
                    self.stop_event.wait(delay)
                except (WorkerError, xmlrpc.client.Error, OSError) as error:
                    _LOGGER.exception('Sync worker cycle failed: %s', error)
                    self.stop_event.wait(retry_delay)
                    retry_delay = min(self.retry_max, max(self.retry_min, retry_delay * 2))
            _LOGGER.info('Sunnyside sync worker stopped.')


def load_config(path):
    config = configparser.ConfigParser()
    if not config.read(path, encoding='utf-8'):
        raise WorkerError('Worker configuration file not found: %s' % path)
    for env_name, section, key in (
        ('SUNNYSIDE_SYNC_ODOO_URL', 'odoo', 'url'),
        ('SUNNYSIDE_SYNC_ODOO_DATABASE', 'odoo', 'database'),
        ('SUNNYSIDE_SYNC_ODOO_USERNAME', 'odoo', 'username'),
        ('SUNNYSIDE_SYNC_ODOO_PASSWORD', 'odoo', 'password'),
        ('SUNNYSIDE_SYNC_CLOUD_URL', 'cloud', 'url'),
        ('SUNNYSIDE_SYNC_DEVICE_ID', 'cloud', 'device_id'),
        ('SUNNYSIDE_SYNC_TOKEN_FILE', 'cloud', 'token_file'),
        ('SUNNYSIDE_SYNC_VERIFY_TLS', 'cloud', 'verify_tls'),
        ('SUNNYSIDE_SYNC_CA_FILE', 'cloud', 'ca_file'),
        ('SUNNYSIDE_SYNC_LOCK_FILE', 'worker', 'lock_file'),
    ):
        value = os.environ.get(env_name)
        if value is not None:
            if section not in config:
                config[section] = {}
            config[section][key] = value
    for section, keys in {
        'odoo': ('url', 'database', 'username', 'password'),
        'cloud': ('url', 'device_id', 'token_file'),
    }.items():
        if section not in config or any(not config[section].get(key) for key in keys):
            raise WorkerError('Worker configuration is missing [%s] settings.' % section)
    if 'worker' not in config:
        config['worker'] = {}
    return config


def main():
    parser = argparse.ArgumentParser(description='Sunnyside Odoo synchronization worker')
    parser.add_argument(
        '--config',
        default=os.environ.get(
            'SUNNYSIDE_SYNC_CONFIG',
            str(Path(os.environ.get('PROGRAMDATA', Path.home()))
                / 'SunnysideSync' / 'worker.ini'),
        ),
    )
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(levelname)s %(name)s: %(message)s',
    )
    stop_event = threading.Event()
    signal.signal(signal.SIGINT, lambda signum, frame: stop_event.set())
    if hasattr(signal, 'SIGTERM'):
        signal.signal(signal.SIGTERM, lambda signum, frame: stop_event.set())
    config = load_config(args.config)
    retry_min = config['worker'].getint('retry_min', fallback=5)
    retry_max = config['worker'].getint('retry_max', fallback=60)
    retry_delay = retry_min
    while not stop_event.is_set():
        try:
            SyncWorker(config, stop_event=stop_event).run()
            return
        except (WorkerError, xmlrpc.client.Error, OSError) as error:
            _LOGGER.warning('Sync worker could not start: %s', error)
            stop_event.wait(retry_delay)
            retry_delay = min(retry_max, max(retry_min, retry_delay * 2))


if __name__ == '__main__':
    main()
