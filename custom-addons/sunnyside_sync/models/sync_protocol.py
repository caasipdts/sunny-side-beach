import base64
import hashlib
import hmac
import json
import uuid
from datetime import datetime, timezone

from psycopg2 import IntegrityError

from odoo import api, fields, models, _
from odoo.exceptions import MissingError, UserError, ValidationError

from .sync_mixin import _SYNC_APPLY_TOKEN


SYNC_MODELS = (
    'sunnyside.seating.type',
    'res.partner',
    'sunnyside.visit',
    'sunnyside.booking',
    'sunnyside.booking.payment',
    'ir.attachment',
)

MAX_CHUNK_ITEMS = 100
MAX_ATTACHMENT_BYTES = 3 * 1024 * 1024


class SunnysideSyncProtocol(models.AbstractModel):
    _name = 'sunnyside.sync.protocol'
    _description = 'Sunnyside Synchronization Protocol'

    @api.model
    def _find_by_uuid(self, model_name, record_uuid):
        if model_name not in SYNC_MODELS:
            raise ValidationError(_("Unsupported synchronization model."))
        return self.env[model_name].sudo().with_context(active_test=False).search(
            [('sync_uuid', '=', record_uuid)],
            limit=1,
        )

    @api.model
    def _record_data(self, record):
        model_name = record._name
        if model_name == 'sunnyside.seating.type':
            return {
                'code': record.code,
                'name': record.name,
                'active': record.active,
                'sequence': record.sequence,
                'capacity_min': record.capacity_min,
                'capacity_max': record.capacity_max,
                'pricing_mode': record.pricing_mode,
                'price_per_guest': record.price_per_guest,
                'fixed_price': record.fixed_price,
                'entry_fee_amount': record.entry_fee_amount,
                'minimum_spend_amount': record.minimum_spend_amount,
            }

        if model_name == 'res.partner':
            location = record.sunnyside_location_id
            data = {
                'name': record.name or '',
                'phone': record.phone or '',
                'email': record.email or '',
                'is_sunnyside_visitor': bool(record.is_sunnyside_visitor),
                'location_name': location.name if location else False,
                'privacy_acknowledged': bool(record.privacy_acknowledged),
                'privacy_acknowledgement_date': fields.Datetime.to_string(
                    record.privacy_acknowledgement_date
                ) if record.privacy_acknowledgement_date else False,
                'privacy_notice_version': record.privacy_notice_version or '',
                'marketing_consent': bool(record.marketing_consent),
                'marketing_consent_date': fields.Datetime.to_string(
                    record.marketing_consent_date
                ) if record.marketing_consent_date else False,
            }
            if 'mobile' in record._fields:
                data['mobile'] = record.mobile or ''
            return data

        if model_name == 'sunnyside.visit':
            return {
                'name': record.name or '',
                'visitor_uuid': record.visitor_id.sync_uuid,
                'check_in_datetime': fields.Datetime.to_string(record.check_in_datetime),
                'source': record.source,
                'location_name': record.location_id.name if record.location_id else False,
                'submission_token': record.submission_token or '',
                'state': record.state,
            }

        if model_name == 'sunnyside.booking':
            return {
                'name': record.name or '',
                'visit_uuid': record.visit_id.sync_uuid,
                'unit_name': record.unit_id.name,
                'area_name': record.unit_id.area_id.name,
                'guest_count': record.guest_count,
                'seating_type': record.seating_type,
                'pricing_mode': record.pricing_mode,
                'unit_price': record.unit_price,
                'entry_fee_amount': record.entry_fee_amount,
                'minimum_spend_amount': record.minimum_spend_amount,
                'amount_total': record.amount_total,
                'currency_code': record.currency_id.name,
                'state': record.state,
                'reserved_datetime': fields.Datetime.to_string(
                    record.reserved_datetime
                ) if record.reserved_datetime else False,
                'released_datetime': fields.Datetime.to_string(
                    record.released_datetime
                ) if record.released_datetime else False,
            }

        if model_name == 'sunnyside.booking.payment':
            return {
                'booking_uuid': record.booking_id.sync_uuid,
                'amount': record.amount,
                'payment_method': record.payment_method,
                'reference': record.reference or '',
                'payment_datetime': fields.Datetime.to_string(record.payment_datetime),
                'currency_code': record.currency_id.name,
            }

        parent = self.env[record.res_model].sudo().browse(record.res_id).exists() \
            if record.res_model in SYNC_MODELS and record.res_id else False
        if not parent or not parent.sync_uuid:
            raise MissingError(_("The attachment's synchronized parent is missing."))
        datas = record.datas or ''
        try:
            encoded = datas.encode('ascii') if isinstance(datas, str) else datas
            decoded_size = len(base64.b64decode(encoded, validate=True))
        except (ValueError, UnicodeEncodeError) as error:
            raise ValidationError(_("The attachment content is not valid base64.")) from error
        if decoded_size > MAX_ATTACHMENT_BYTES:
            raise ValidationError(_("Synchronized attachments may not exceed 3 MiB."))
        return {
            'name': record.name or '',
            'type': record.type,
            'mimetype': record.mimetype or 'application/octet-stream',
            'datas': datas,
            'url': record.url or '',
            'res_model': record.res_model,
            'res_uuid': parent.sync_uuid,
        }

    @api.model
    def serialize_record(self, model_name, record_uuid, sequence=0, operation=None):
        record = self._find_by_uuid(model_name, record_uuid)
        if not record:
            tombstone = self.env['sunnyside.sync.tombstone'].sudo().search([
                ('model', '=', model_name),
                ('record_uuid', '=', record_uuid),
            ], limit=1)
            if not tombstone:
                return False
            return {
                'seq': sequence,
                'model': model_name,
                'uuid': record_uuid,
                'op': 'delete',
                'rev': tombstone.rev,
                'origin': tombstone.origin,
                'deleted_at': fields.Datetime.to_string(tombstone.deleted_at),
                'cloud_id': False,
                # Odoo's XML-RPC server does not marshal Python None values.
                # The sync worker reads this payload over XML-RPC before sending
                # it to the cloud API, and delete operations do not need data.
                'data': False,
            }

        deleted = bool(record.sync_deleted_at)
        return {
            'seq': sequence,
            'model': model_name,
            'uuid': record.sync_uuid,
            'op': 'delete' if deleted else (operation or 'update'),
            'rev': record.sync_rev,
            'origin': record.sync_origin,
            'deleted_at': fields.Datetime.to_string(record.sync_deleted_at)
            if deleted else False,
            'cloud_id': record.id,
            # Keep worker payloads XML-RPC safe; delete operations ignore data.
            'data': False if deleted else self._record_data(record),
        }

    @api.model
    def _location(self, name):
        if not name:
            return self.env['sunnyside.location']
        locations = self.env['sunnyside.location'].sudo().with_context(
            active_test=False
        ).search([('name', '=', name)], limit=2)
        if len(locations) > 1:
            raise ValidationError(_("The location name is ambiguous on this database."))
        return locations or self.env['sunnyside.location'].sudo().create({'name': name})

    @api.model
    def _values_from_item(self, item, existing=False):
        model_name = item['model']
        data = item.get('data')
        if not isinstance(data, dict):
            raise ValidationError(_("The record payload must be an object."))

        if model_name == 'sunnyside.seating.type':
            code = data.get('code')
            if not isinstance(code, str) or not code.startswith('custom_'):
                raise ValidationError(_("Only custom seating types may be synchronized."))
            values = {
                'code': code,
                'name': data.get('name') or '',
                'active': bool(data.get('active', True)),
                'sequence': data.get('sequence', 10),
                'capacity_min': data.get('capacity_min'),
                'capacity_max': data.get('capacity_max'),
                'pricing_mode': data.get('pricing_mode'),
                'price_per_guest': data.get('price_per_guest'),
                'fixed_price': data.get('fixed_price'),
                'entry_fee_amount': data.get('entry_fee_amount'),
                'minimum_spend_amount': data.get('minimum_spend_amount'),
            }
            if existing and existing.code != code:
                raise ValidationError(_("A seating type's code is immutable."))
            return values

        if model_name == 'res.partner':
            if not data.get('is_sunnyside_visitor'):
                raise ValidationError(_("Only Sunnyside visitor contacts may be synchronized."))
            values = {
                'name': data.get('name', ''),
                'phone': data.get('phone') or False,
                'email': data.get('email') or False,
                'is_sunnyside_visitor': True,
                'sunnyside_location_id': self._location(data.get('location_name')).id or False,
                'privacy_acknowledged': bool(data.get('privacy_acknowledged')),
                'privacy_acknowledgement_date': data.get('privacy_acknowledgement_date') or False,
                'privacy_notice_version': data.get('privacy_notice_version') or False,
                'marketing_consent': bool(data.get('marketing_consent')),
                'marketing_consent_date': data.get('marketing_consent_date') or False,
            }
            if 'mobile' in data and 'mobile' in self.env[model_name]._fields:
                values['mobile'] = data.get('mobile') or False
            return values

        if model_name == 'sunnyside.visit':
            visitor = self._find_by_uuid('res.partner', data.get('visitor_uuid'))
            if not visitor or not visitor.is_sunnyside_visitor:
                raise MissingError(_("The synchronized visitor must arrive before its visit."))
            source = data.get('source')
            if source not in ('qr_code', 'website', 'receptionist'):
                raise ValidationError(_("The visit source is invalid."))
            values = {
                'visitor_id': visitor.id,
                'name': data.get('name') or _('New'),
                'check_in_datetime': data.get('check_in_datetime'),
                'source': source,
                'location_id': self._location(data.get('location_name')).id or False,
                'submission_token': data.get('submission_token') or False,
                'state': data.get('state', 'checked_in'),
            }
            if existing:
                values.pop('visitor_id')
                values.pop('name')
                values.pop('source')
                values.pop('submission_token')
            return values

        if model_name == 'sunnyside.booking':
            visit = self._find_by_uuid('sunnyside.visit', data.get('visit_uuid'))
            if not visit:
                raise MissingError(_("The synchronized visit must arrive before its booking."))
            if visit.state != 'checked_in':
                raise ValidationError(_("A booking can only be synchronized for a checked-in visit."))
            units = self.env['sunnyside.seating.unit'].sudo().with_context(
                active_test=False
            ).search([
                ('name', '=', data.get('unit_name')),
                ('area_id.name', '=', data.get('area_name')),
            ], limit=2)
            if len(units) != 1:
                raise MissingError(_("A unique matching seating unit is required on the cloud database."))
            unit = units
            if existing:
                if unit != existing.unit_id or visit != existing.visit_id:
                    raise ValidationError(_("An existing booking's visit and seating unit are immutable."))
                values = {}
                if data.get('state') != existing.state:
                    values.update({
                        'state': data.get('state'),
                        'released_by_id': self.env.user.id if data.get('state') == 'released' else False,
                        'released_datetime': data.get('released_datetime') or fields.Datetime.now()
                        if data.get('state') == 'released' else False,
                    })
                    if data.get('state') not in ('reserved', 'released'):
                        raise ValidationError(_("The booking state is invalid."))
                return values

            if data.get('state') not in ('reserved', 'released'):
                raise ValidationError(_("The booking state is invalid."))
            if not unit.active:
                raise ValidationError(_("The matching seating unit is archived."))
            guest_count = data.get('guest_count')
            if not isinstance(guest_count, int) or guest_count < 1:
                raise ValidationError(_("The booking guest count is invalid."))
            if unit.capacity_min and guest_count < unit.capacity_min:
                raise ValidationError(_("The booking guest count is below the seating capacity minimum."))
            if unit.capacity_max and guest_count > unit.capacity_max:
                raise ValidationError(_("The booking guest count exceeds the seating capacity maximum."))
            currency = unit.currency_id
            if data.get('currency_code') != currency.name:
                raise ValidationError(_("The booking currency does not match the cloud seating unit."))
            pricing_mode = data.get('pricing_mode')
            unit_price = data.get('unit_price')
            if pricing_mode not in ('fixed', 'per_guest'):
                raise ValidationError(_("The booking pricing mode is invalid."))
            if not isinstance(unit_price, (int, float)) or unit_price < 0:
                raise ValidationError(_("The booking price snapshot is invalid."))
            if pricing_mode == 'fixed':
                expected_total = currency.round(unit_price)
            else:
                expected_total = currency.round(unit_price * guest_count)
            if currency.compare_amounts(expected_total, data.get('amount_total') or 0) != 0:
                raise ValidationError(_("The booking total does not match its price snapshot."))
            return {
                'visit_id': visit.id,
                'unit_id': unit.id,
                'guest_count': guest_count,
                'name': data.get('name') or _('New'),
                'reserved_datetime': data.get('reserved_datetime') or fields.Datetime.now(),
                'seating_type': data.get('seating_type'),
                'pricing_mode': pricing_mode,
                'unit_price': data.get('unit_price'),
                'entry_fee_amount': data.get('entry_fee_amount'),
                'minimum_spend_amount': data.get('minimum_spend_amount'),
                'amount_total': data.get('amount_total'),
            }

        if model_name == 'sunnyside.booking.payment':
            booking = self._find_by_uuid('sunnyside.booking', data.get('booking_uuid'))
            if not booking:
                raise MissingError(_("The synchronized booking must arrive before its payment."))
            if data.get('currency_code') != booking.currency_id.name:
                raise ValidationError(_("The payment currency does not match its booking."))
            if existing:
                if (
                    existing.booking_id != booking
                    or existing.amount != data.get('amount')
                    or existing.payment_method != data.get('payment_method')
                    or (existing.reference or '') != (data.get('reference') or '')
                ):
                    raise ValidationError(_("Payment records are immutable and conflict with this update."))
                return {}
            amount = booking.currency_id.round(data.get('amount') or 0.0)
            if booking.currency_id.compare_amounts(amount, 0.0) <= 0:
                raise ValidationError(_("Payment amount must be greater than zero."))
            if data.get('payment_method') not in dict(
                self.env[model_name]._fields['payment_method'].selection
            ):
                raise ValidationError(_("The payment method is invalid."))
            current_paid = sum(booking.payment_ids.mapped('amount'))
            if booking.currency_id.compare_amounts(
                booking.currency_id.round(current_paid + amount),
                booking.amount_total,
            ) > 0:
                raise ValidationError(_("The payment would exceed the booking total."))
            return {
                'booking_id': booking.id,
                'amount': amount,
                'payment_method': data.get('payment_method'),
                'reference': data.get('reference') or False,
                'payment_datetime': data.get('payment_datetime'),
            }

        if model_name == 'ir.attachment':
            parent_model = data.get('res_model')
            parent = self._find_by_uuid(parent_model, data.get('res_uuid'))
            if not parent:
                raise MissingError(_("The synchronized attachment parent must arrive first."))
            values = {
                'name': data.get('name') or 'Attachment',
                'type': data.get('type') or 'binary',
                'mimetype': data.get('mimetype') or 'application/octet-stream',
                'res_model': parent_model,
                'res_id': parent.id,
                'public': False,
            }
            if data.get('type') == 'url':
                values['url'] = data.get('url') or ''
            else:
                encoded = data.get('datas') or ''
                if not isinstance(encoded, str):
                    raise ValidationError(_("Attachment data must be base64 text."))
                try:
                    decoded = base64.b64decode(encoded.encode('ascii'), validate=True)
                except (ValueError, UnicodeEncodeError) as error:
                    raise ValidationError(_("The attachment content is not valid base64.")) from error
                if len(decoded) > MAX_ATTACHMENT_BYTES:
                    raise ValidationError(_("Synchronized attachments may not exceed 3 MiB."))
                values['datas'] = encoded
            return values

        raise ValidationError(_("Unsupported synchronization model."))

    @api.model
    def _apply_remote_item(self, device, item, cloud_wins=False):
        if not isinstance(item, dict):
            raise ValidationError(_("Each chunk item must be an object."))
        model_name = item.get('model')
        record_uuid = item.get('uuid')
        operation = item.get('op')
        revision = item.get('rev')
        try:
            uuid.UUID(record_uuid)
        except (ValueError, TypeError, AttributeError) as error:
            raise ValidationError(_("The record UUID is invalid.")) from error
        if model_name not in SYNC_MODELS:
            raise ValidationError(_("The synchronization model is not allowed."))
        if operation not in ('create', 'update', 'delete'):
            raise ValidationError(_("The synchronization operation is invalid."))
        if not isinstance(revision, int) or revision < 1:
            raise ValidationError(_("The synchronization revision is invalid."))

        tombstone = self.env['sunnyside.sync.tombstone'].sudo().search([
            ('model', '=', model_name),
            ('record_uuid', '=', record_uuid),
        ], limit=1)
        if tombstone:
            if operation == 'delete' and revision > tombstone.rev:
                tombstone.write({
                    'rev': revision,
                    'origin': item.get('origin') or tombstone.origin,
                    'deleted_at': item.get('deleted_at') or fields.Datetime.now(),
                })
                return {'uuid': record_uuid, 'status': 'ok'}
            return {'uuid': record_uuid, 'status': 'ok', 'stale': True}

        record = self._find_by_uuid(model_name, record_uuid)
        context = {
            'sync_applying': _SYNC_APPLY_TOKEN,
            'sync_historical_snapshot': True,
            'tracking_disable': True,
            'mail_create_nolog': True,
            'mail_create_nosubscribe': True,
        }
        if operation == 'delete':
            if record and revision < record.sync_rev:
                return {'uuid': record_uuid, 'status': 'ok', 'stale': True}
            if record:
                values = record._sync_tombstone_values()
                values.update({
                    'sync_rev': revision,
                    'sync_origin': item.get('origin') or record.sync_origin,
                })
                context.update(record._sync_tombstone_context(values))
                record.sudo().with_context(**context).write(values)
            else:
                self.env['sunnyside.sync.tombstone'].sudo().create({
                    'model': model_name,
                    'record_uuid': record_uuid,
                    'rev': revision,
                    'origin': item.get('origin') or 'local',
                    'deleted_at': fields.Datetime.now(),
                })
            return {'uuid': record_uuid, 'status': 'ok'}

        incoming_data = item.get('data')
        if not isinstance(incoming_data, dict):
            raise ValidationError(_("A non-delete item must include a data object."))
        if record and revision < record.sync_rev:
            return {'uuid': record_uuid, 'status': 'ok', 'stale': True}

        values = self._values_from_item(item, existing=record)
        if record:
            local_item = self.serialize_record(model_name, record_uuid)
            if revision == record.sync_rev:
                if local_item['data'] != incoming_data:
                    self.env['sunnyside.sync.conflict'].sudo().create({
                        'model': model_name,
                        'record_uuid': record_uuid,
                        'local_rev': record.sync_rev,
                        'incoming_rev': revision,
                        'local_data': local_item['data'],
                        'incoming_data': incoming_data,
                        'device_id': device.id if device else False,
                    })
                    if not cloud_wins:
                        return {'uuid': record_uuid, 'status': 'ok', 'conflict': True}
                else:
                    return {'uuid': record_uuid, 'status': 'ok'}
            if model_name == 'sunnyside.booking.payment' and values:
                raise ValidationError(_("Payment records are immutable and cannot be updated."))
            values.update({
                'sync_rev': revision,
                'sync_origin': item.get('origin') or record.sync_origin,
                'cloud_id': item.get('cloud_id') or record.cloud_id
                if cloud_wins else record.cloud_id,
                'sync_deleted_at': False,
            })
            if model_name == 'sunnyside.booking':
                context.update(record._sync_tombstone_context(values))
            record.sudo().with_context(**context).write(values)
        else:
            values.update({
                'sync_uuid': record_uuid,
                'sync_origin': item.get('origin') or 'local',
                'sync_rev': revision,
                'cloud_id': (item.get('cloud_id') or False) if cloud_wins else False,
            })
            target_model = self.env[model_name].sudo().with_context(**context)
            if model_name == 'sunnyside.booking' and incoming_data.get('state') == 'released':
                unit = self.env['sunnyside.seating.unit'].sudo().browse(values['unit_id'])
                values.update({
                    'area_id': unit.area_id.id,
                    'company_id': unit.company_id.id or self.env.company.id,
                    'currency_id': unit.currency_id.id,
                    'seating_type': unit.seating_type,
                    'pricing_mode': unit.pricing_mode,
                    'state': 'released',
                    'reserved_by_id': self.env.user.id,
                    'released_by_id': self.env.user.id,
                    'released_datetime': incoming_data.get('released_datetime')
                    or fields.Datetime.now(),
                })
                created = models.Model.create(target_model, values)
            elif (
                model_name == 'sunnyside.booking.payment'
                and self.env['sunnyside.booking'].sudo().browse(
                    values['booking_id']
                ).state == 'released'
            ):
                created = models.Model.create(target_model, values)
            else:
                created = target_model.create(values)
            if model_name == 'sunnyside.booking':
                snapshot_fields = (
                    'unit_price',
                    'entry_fee_amount',
                    'minimum_spend_amount',
                )
                if any(
                    getattr(created, field_name) != incoming_data.get(field_name)
                    for field_name in snapshot_fields
                ):
                    raise ValidationError(_("The cloud booking pricing snapshot does not match."))
        return {'uuid': record_uuid, 'status': 'ok'}

    @api.model
    def apply_push_chunk(self, device_id, session_uuid, chunk_no, items):
        try:
            uuid.UUID(session_uuid)
        except (ValueError, TypeError, AttributeError) as error:
            raise ValidationError(_("The sync session UUID is invalid.")) from error
        if not isinstance(chunk_no, int) or chunk_no < 0:
            raise ValidationError(_("The chunk number is invalid."))
        if not isinstance(items, list) or not items or len(items) > MAX_CHUNK_ITEMS:
            raise ValidationError(_("A chunk must contain between 1 and 100 items."))

        Device = self.env['sunnyside.sync.device'].sudo()
        device = Device.search([('device_id', '=', device_id), ('active', '=', True)], limit=1)
        if not device:
            raise UserError(_("The synchronization device is not registered."))
        PushLog = self.env['sunnyside.sync.push.log'].sudo()
        previous = PushLog.search([
            ('device_id', '=', device.id),
            ('session_uuid', '=', session_uuid),
            ('chunk_no', '=', chunk_no),
        ], limit=1)
        if previous:
            return previous.result

        results = []
        priority = {
            'sunnyside.seating.type': 0,
            'res.partner': 1,
            'sunnyside.visit': 2,
            'sunnyside.booking': 3,
            'sunnyside.booking.payment': 4,
            'ir.attachment': 5,
        }
        ordered_items = sorted(
            enumerate(items),
            key=lambda pair: (priority.get(pair[1].get('model'), 99), pair[0]),
        )
        for original_index, item in ordered_items:
            item_model = item.get('model') if isinstance(item, dict) else ''
            item_uuid = item.get('uuid') if isinstance(item, dict) else ''
            try:
                with self.env.cr.savepoint():
                    result = self._apply_remote_item(device, item)
                    result.setdefault('model', item_model)
            except (
                ValidationError,
                UserError,
                MissingError,
                ValueError,
                TypeError,
                KeyError,
                IntegrityError,
            ) as error:
                self.env['sunnyside.sync.quarantine'].sudo().create({
                    'device_id': device.id,
                    'session_uuid': session_uuid,
                    'chunk_no': chunk_no,
                    'model': item_model,
                    'record_uuid': item_uuid,
                    'item': item if isinstance(item, dict) else {'value': str(item)},
                    'reason': str(error),
                })
                result = {
                    'model': item_model,
                    'uuid': item_uuid,
                    'status': 'quarantined',
                    'reason': str(error),
                }
            results.append((original_index, result))
        results.sort(key=lambda pair: pair[0])
        response = {'results': [result for _, result in results]}
        try:
            with self.env.cr.savepoint():
                PushLog.create({
                    'device_id': device.id,
                    'session_uuid': session_uuid,
                    'chunk_no': chunk_no,
                    'result': response,
                })
        except IntegrityError:
            previous = PushLog.search([
                ('device_id', '=', device.id),
                ('session_uuid', '=', session_uuid),
                ('chunk_no', '=', chunk_no),
            ], limit=1)
            if not previous:
                raise
            response = previous.result
        return response

    @api.model
    def pull_changes(self, after=0, limit=200):
        try:
            after = max(0, int(after))
            limit = min(200, max(1, int(limit)))
        except (TypeError, ValueError) as error:
            raise ValidationError(_("The change cursor or page limit is invalid.")) from error

        changes = self.env['sunnyside.sync.change'].sudo().search(
            [('id', '>', after), ('model', 'in', list(SYNC_MODELS))],
            order='id',
            limit=limit,
        )
        items = []
        encoded_size = 2
        last_scanned = after
        for change in changes:
            item = self.serialize_record(
                change.model,
                change.record_uuid,
                sequence=change.id,
                operation=change.op,
            )
            if item:
                item_size = len(json.dumps(item, separators=(',', ':')).encode('utf-8')) + 1
                if items and encoded_size + item_size > 8 * 1024 * 1024:
                    break
                items.append(item)
                encoded_size += item_size
            last_scanned = change.id
        next_cursor = last_scanned
        return {'items': items, 'next_cursor': next_cursor}

    @api.model
    def authenticate_device(self, device_id, token):
        if not isinstance(device_id, str) or not isinstance(token, str):
            return False
        device = self.env['sunnyside.sync.device'].sudo().search([
            ('device_id', '=', device_id),
            ('active', '=', True),
        ], limit=1)
        if not device:
            return False
        token_hash = hashlib.sha256(token.encode('utf-8')).hexdigest()
        if not hmac.compare_digest(device.token_hash, token_hash):
            return False
        device.last_seen_at = fields.Datetime.now()
        return device

    @api.model
    def health_signature(self, device):
        timestamp = str(int(datetime.now(timezone.utc).timestamp()))
        signature = hmac.new(
            bytes.fromhex(device.token_hash),
            timestamp.encode('ascii'),
            hashlib.sha256,
        ).hexdigest()
        return {'service': 'sunnyside', 'timestamp': timestamp, 'signature': signature}

    @api.model
    def manifest(self, model_name=None, after_uuid='', limit=500):
        if model_name and model_name not in SYNC_MODELS:
            raise ValidationError(_("Unsupported synchronization model."))
        try:
            limit = min(500, max(1, int(limit)))
        except (TypeError, ValueError) as error:
            raise ValidationError(_("The manifest page limit is invalid.")) from error
        models_to_read = [model_name] if model_name else list(SYNC_MODELS)
        result = {}
        for current_model in models_to_read:
            records = self.env[current_model].sudo().with_context(
                active_test=False
            ).search([
                ('sync_uuid', '!=', False),
                ('sync_uuid', '>', after_uuid or ''),
            ], order='sync_uuid', limit=limit + 1)
            entries = {
                record.sync_uuid: {
                    'uuid': record.sync_uuid,
                    'rev': record.sync_rev,
                    'deleted': bool(record.sync_deleted_at),
                }
                for record in records
            }
            tombstones = self.env['sunnyside.sync.tombstone'].sudo().search([
                ('model', '=', current_model),
                ('record_uuid', '>', after_uuid or ''),
            ], order='record_uuid', limit=limit + 1)
            for tombstone in tombstones:
                entries.setdefault(tombstone.record_uuid, {
                    'uuid': tombstone.record_uuid,
                    'rev': tombstone.rev,
                    'deleted': True,
                })
            result[current_model] = [
                entries[record_uuid]
                for record_uuid in sorted(entries)[:limit]
            ]
        return result


class SunnysideSyncTombstone(models.Model):
    _name = 'sunnyside.sync.tombstone'
    _description = 'Sunnyside Synchronization Tombstone'
    _order = 'id'

    model = fields.Char(required=True, index=True)
    record_uuid = fields.Char(required=True, index=True)
    rev = fields.Integer(required=True)
    origin = fields.Selection(
        selection=[('local', 'Local'), ('cloud', 'Cloud')],
        required=True,
    )
    deleted_at = fields.Datetime(required=True, default=fields.Datetime.now, index=True)

    _model_uuid_uniq = models.Constraint(
        'UNIQUE(model, record_uuid)',
        'A synchronization tombstone must be unique per record.',
    )
