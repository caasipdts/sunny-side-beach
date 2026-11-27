import json

from odoo import fields, http, _
from odoo.exceptions import UserError, ValidationError
from odoo.http import request


_PROTOCOL_VERSION = '1'
_MAX_REQUEST_BYTES = 12 * 1024 * 1024


class SunnysideSyncController(http.Controller):

    def _response(self, data, status=200):
        return request.make_json_response(
            data,
            status=status,
            headers=[('Cache-Control', 'no-store')],
        )

    def _device(self):
        authorization = request.httprequest.headers.get('Authorization', '')
        scheme, separator, token = authorization.partition(' ')
        device_id = request.httprequest.headers.get('X-Device-ID', '')
        if not separator or scheme.lower() != 'bearer' or not token or not device_id:
            return False
        return request.env['sunnyside.sync.protocol'].sudo().authenticate_device(
            device_id,
            token,
        )

    def _authenticated_request(self):
        if request.httprequest.headers.get('X-Sunnyside-Sync-Version') != _PROTOCOL_VERSION:
            return False, self._response({
                'error': 'protocol_version_mismatch',
                'supported_version': _PROTOCOL_VERSION,
            }, status=426)
        device = self._device()
        if not device:
            return False, self._response({'error': 'unauthorized'}, status=401)
        return device, False

    @http.route(
        '/sunnyside_sync/status',
        type='http',
        auth='user',
        methods=['GET', 'POST'],
        csrf=False,
        save_session=False,
    )
    def status(self, **kwargs):
        state = request.env['sunnyside.sync.state'].sudo().get_singleton()
        Outbox = request.env['sunnyside.sync.outbox'].sudo()
        return self._response({
            'state': state.state,
            'last_success_at': fields.Datetime.to_string(state.last_success_at)
            if state.last_success_at else False,
            'last_attempt_at': fields.Datetime.to_string(state.last_attempt_at)
            if state.last_attempt_at else False,
            'offline_since': fields.Datetime.to_string(state.offline_since)
            if state.offline_since else False,
            'pending_count': Outbox.search_count([('status', '=', 'pending')]),
            'quarantined_count': Outbox.search_count([('status', '=', 'quarantined')]),
            'last_error': state.last_error or '',
        })

    @http.route(
        '/sunnyside_sync/v1/health',
        type='http',
        auth='public',
        methods=['GET'],
        csrf=False,
        save_session=False,
    )
    def health(self, **kwargs):
        device, error = self._authenticated_request()
        if error:
            return error
        response = request.env['sunnyside.sync.protocol'].sudo().health_signature(device)
        return self._response(response)

    @http.route(
        '/sunnyside_sync/v1/push',
        type='http',
        auth='public',
        methods=['POST'],
        csrf=False,
        save_session=False,
    )
    def push(self, **kwargs):
        device, error = self._authenticated_request()
        if error:
            return error
        if request.httprequest.content_length and request.httprequest.content_length > _MAX_REQUEST_BYTES:
            return self._response({'error': 'request_too_large'}, status=413)
        if request.httprequest.mimetype != 'application/json':
            return self._response({'error': 'application_json_required'}, status=415)
        payload = request.httprequest.get_json(silent=True)
        if not isinstance(payload, dict):
            return self._response({'error': 'invalid_json_body'}, status=400)
        try:
            result = request.env['sunnyside.sync.protocol'].sudo().apply_push_chunk(
                device.device_id,
                payload.get('session_id'),
                payload.get('chunk_no'),
                payload.get('items'),
            )
        except (ValidationError, UserError) as error:
            return self._response({'error': 'invalid_chunk', 'message': str(error)}, status=400)
        return self._response(result)

    @http.route(
        '/sunnyside_sync/v1/pull',
        type='http',
        auth='public',
        methods=['GET'],
        csrf=False,
        save_session=False,
    )
    def pull(self, after='0', limit='200', **kwargs):
        device, error = self._authenticated_request()
        if error:
            return error
        try:
            result = request.env['sunnyside.sync.protocol'].sudo().pull_changes(after, limit)
        except ValidationError as error:
            return self._response({'error': 'invalid_cursor', 'message': str(error)}, status=400)
        return self._response(result)

    @http.route(
        '/sunnyside_sync/v1/manifest',
        type='http',
        auth='public',
        methods=['GET'],
        csrf=False,
        save_session=False,
    )
    def manifest(self, model=None, after_uuid='', limit='500', **kwargs):
        device, error = self._authenticated_request()
        if error:
            return error
        try:
            result = request.env['sunnyside.sync.protocol'].sudo().manifest(
                model or None,
                after_uuid,
                limit,
            )
        except ValidationError as error:
            return self._response({'error': 'invalid_manifest', 'message': str(error)}, status=400)
        return self._response(result)

    @http.route(
        '/sunnyside_sync/v1/record',
        type='http',
        auth='public',
        methods=['GET'],
        csrf=False,
        save_session=False,
    )
    def record(self, model=None, record_uuid=None, **kwargs):
        device, error = self._authenticated_request()
        if error:
            return error
        try:
            item = request.env['sunnyside.sync.protocol'].sudo().serialize_record(
                model,
                record_uuid,
            )
        except ValidationError as error:
            return self._response({'error': 'invalid_record', 'message': str(error)}, status=400)
        if not item:
            return self._response({'error': 'record_not_found'}, status=404)
        return self._response(item)

    @http.route(
        '/sunnyside_sync/v1/records/batch',
        type='http',
        auth='public',
        methods=['POST'],
        csrf=False,
        save_session=False,
    )
    def records_batch(self, **kwargs):
        device, error = self._authenticated_request()
        if error:
            return error
        try:
            payload = json.loads(request.httprequest.get_data() or '{}')
        except ValueError:
            return self._response({'error': 'invalid_json'}, status=400)

        model = payload.get('model')
        uuids = payload.get('uuids', [])
        if not model or not isinstance(uuids, list):
            return self._response({'error': 'invalid_parameters'}, status=400)

        try:
            items = request.env['sunnyside.sync.protocol'].sudo().serialize_records_batch(
                model,
                uuids,
            )
        except ValidationError as err:
            return self._response({'error': 'invalid_record', 'message': str(err)}, status=400)

        return self._response({'model': model, 'items': items})
