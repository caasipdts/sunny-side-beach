import json

from psycopg2 import IntegrityError

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, MissingError, UserError, ValidationError

from .uuid import new_uuid7


class SunnysideSyncOutbox(models.Model):
    _name = 'sunnyside.sync.outbox'
    _description = 'Sunnyside Synchronization Outbox'
    _order = 'id'

    # Odoo's serial primary key is the durable, monotonically allocated queue sequence.
    seq = fields.Integer(
        string='Sequence',
        compute='_compute_seq',
        help='Alias for the database-generated ID used to order outbox events.',
    )
    model = fields.Char(required=True, index=True)
    record_uuid = fields.Char(required=True, index=True)
    op = fields.Selection(
        selection=[
            ('create', 'Create'),
            ('update', 'Update'),
            ('delete', 'Delete'),
        ],
        required=True,
    )
    rev = fields.Integer(required=True)
    status = fields.Selection(
        selection=[
            ('pending', 'Pending'),
            ('acked', 'Acknowledged'),
            ('quarantined', 'Quarantined'),
        ],
        required=True,
        default='pending',
        index=True,
    )
    attempts = fields.Integer(default=0)
    last_error = fields.Text()
    created_at = fields.Datetime(required=True, default=fields.Datetime.now, index=True)
    acked_at = fields.Datetime()

    def _compute_seq(self):
        for event in self:
            event.seq = event.id

    def action_retry(self):
        if not self.env.user.has_group('sunnyside_sync.group_sunnyside_sync_manager'):
            raise AccessError(_("Only synchronization managers can retry outbox items."))
        for event in self:
            if event.status != 'quarantined':
                raise UserError(_("Only quarantined outbox items can be retried."))
            pending = self.search([
                ('model', '=', event.model),
                ('record_uuid', '=', event.record_uuid),
                ('status', '=', 'pending'),
            ], limit=1)
            if pending:
                event.write({
                    'status': 'acked',
                    'acked_at': fields.Datetime.now(),
                    'last_error': _('Superseded by a newer pending revision.'),
                })
            else:
                event.write({
                    'status': 'pending',
                    'last_error': False,
                })

    def action_discard(self):
        if not self.env.user.has_group('sunnyside_sync.group_sunnyside_sync_manager'):
            raise AccessError(_("Only synchronization managers can discard outbox items."))
        for event in self:
            if event.status != 'quarantined':
                raise UserError(_("Only quarantined outbox items can be discarded."))
            event.write({
                'status': 'acked',
                'acked_at': fields.Datetime.now(),
                'last_error': _('Discarded by a synchronization manager.'),
            })

    def init(self):
        super().init()
        # A partial unique index makes pending-event coalescing safe across workers.
        self.env.cr.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS sunnyside_sync_outbox_pending_record_uniq
            ON sunnyside_sync_outbox (model, record_uuid)
            WHERE status = 'pending'
        """)

    @api.model
    def _merge_operation(self, previous, incoming):
        if previous == 'delete' or incoming == 'delete':
            return 'delete'
        if previous == 'create':
            return 'create'
        return 'update'

    @api.model
    def enqueue(self, model, record_uuid, operation, revision):
        domain = [
            ('model', '=', model),
            ('record_uuid', '=', record_uuid),
            ('status', '=', 'pending'),
        ]
        pending = self.search(domain, limit=1)
        if pending:
            pending.write({
                'op': self._merge_operation(pending.op, operation),
                'rev': revision,
            })
            event = pending
        else:
            values = {
                'model': model,
                'record_uuid': record_uuid,
                'op': operation,
                'rev': revision,
                'status': 'pending',
            }
            try:
                with self.env.cr.savepoint():
                    event = self.create(values)
            except IntegrityError:
                # Another transaction may have created the pending row after our search.
                pending = self.search(domain, limit=1)
                if not pending:
                    raise
                pending.write({
                    'op': self._merge_operation(pending.op, operation),
                    'rev': revision,
                })
                event = pending
        self.env['sunnyside.sync.change'].sudo().create({
            'model': model,
            'record_uuid': record_uuid,
            'op': operation,
            'rev': revision,
        })
        return event


class SunnysideSyncChange(models.Model):
    _name = 'sunnyside.sync.change'
    _description = 'Sunnyside Synchronization Change Log'
    _order = 'id'

    model = fields.Char(required=True, index=True)
    record_uuid = fields.Char(required=True, index=True)
    op = fields.Selection(
        selection=[
            ('create', 'Create'),
            ('update', 'Update'),
            ('delete', 'Delete'),
        ],
        required=True,
    )
    rev = fields.Integer(required=True)
    created_at = fields.Datetime(required=True, default=fields.Datetime.now, index=True)


class SunnysideSyncDevice(models.Model):
    _name = 'sunnyside.sync.device'
    _description = 'Sunnyside Synchronization Device'
    _order = 'name, id'

    name = fields.Char(required=True)
    device_id = fields.Char(required=True, index=True)
    token_hash = fields.Char(required=True, copy=False)
    active = fields.Boolean(default=True, index=True)
    last_seen_at = fields.Datetime()

    _device_id_uniq = models.Constraint(
        'UNIQUE(device_id)',
        'Synchronization device IDs must be unique.',
    )


class SunnysideSyncPushLog(models.Model):
    _name = 'sunnyside.sync.push.log'
    _description = 'Sunnyside Synchronization Push Log'
    _order = 'id'

    device_id = fields.Many2one('sunnyside.sync.device', required=True, index=True)
    session_uuid = fields.Char(required=True, index=True)
    chunk_no = fields.Integer(required=True)
    result = fields.Json(required=True, default=dict)
    committed_at = fields.Datetime(required=True, default=fields.Datetime.now, index=True)

    _device_chunk_uniq = models.Constraint(
        'UNIQUE(device_id, session_uuid, chunk_no)',
        'A device cannot commit the same synchronization chunk twice.',
    )


class SunnysideSyncConflict(models.Model):
    _name = 'sunnyside.sync.conflict'
    _description = 'Sunnyside Synchronization Conflict'
    _order = 'create_date desc, id desc'

    model = fields.Char(required=True, index=True)
    record_uuid = fields.Char(required=True, index=True)
    local_rev = fields.Integer(required=True)
    incoming_rev = fields.Integer(required=True)
    local_data = fields.Json()
    incoming_data = fields.Json()
    device_id = fields.Many2one('sunnyside.sync.device', index=True)
    resolved = fields.Boolean(default=False, index=True)


class SunnysideSyncQuarantine(models.Model):
    _name = 'sunnyside.sync.quarantine'
    _description = 'Sunnyside Synchronization Quarantine'
    _order = 'create_date desc, id desc'

    device_id = fields.Many2one('sunnyside.sync.device', index=True)
    session_uuid = fields.Char(index=True)
    chunk_no = fields.Integer()
    model = fields.Char(index=True)
    record_uuid = fields.Char(index=True)
    item = fields.Json()
    reason = fields.Text(required=True)
    state = fields.Selection(
        selection=[
            ('open', 'Open'),
            ('retry', 'Queued for Retry'),
            ('discarded', 'Discarded'),
        ],
        required=True,
        default='open',
        index=True,
    )

    def action_retry(self):
        if not self.env.user.has_group('sunnyside_sync.group_sunnyside_sync_manager'):
            raise AccessError(_("Only synchronization managers can retry quarantined items."))
        for quarantine in self:
            device = quarantine.device_id
            self.env['sunnyside.sync.protocol'].sudo()._apply_remote_item(
                device,
                quarantine.item,
            )
            quarantine.state = 'retry'

    def action_discard(self):
        if not self.env.user.has_group('sunnyside_sync.group_sunnyside_sync_manager'):
            raise AccessError(_("Only synchronization managers can discard quarantined items."))
        self.write({'state': 'discarded'})


class SunnysideSyncSession(models.Model):
    _name = 'sunnyside.sync.session'
    _description = 'Sunnyside Synchronization Session'
    _order = 'started_at desc, id desc'

    uuid = fields.Char(
        required=True,
        default=lambda self: new_uuid7(),
        copy=False,
        index=True,
    )
    direction = fields.Selection(
        selection=[
            ('push', 'Push'),
            ('pull', 'Pull'),
            ('reconcile', 'Reconcile'),
        ],
        required=True,
    )
    status = fields.Selection(
        selection=[
            ('open', 'Open'),
            ('partial', 'Partial'),
            ('complete', 'Complete'),
            ('failed', 'Failed'),
        ],
        required=True,
        default='open',
        index=True,
    )
    started_at = fields.Datetime(required=True, default=fields.Datetime.now, index=True)
    ended_at = fields.Datetime()
    counts = fields.Json(default=dict)
    last_error = fields.Text()

    _uuid_uniq = models.Constraint(
        'UNIQUE(uuid)',
        'Synchronization session UUIDs must be unique.',
    )


class SunnysideSyncChunk(models.Model):
    _name = 'sunnyside.sync.chunk'
    _description = 'Sunnyside Synchronization Chunk'
    _order = 'session_id, chunk_no'

    session_id = fields.Many2one(
        'sunnyside.sync.session',
        required=True,
        ondelete='cascade',
        index=True,
    )
    chunk_no = fields.Integer(required=True)
    payload = fields.Json(required=True, default=list)
    status = fields.Selection(
        selection=[
            ('built', 'Built'),
            ('sent', 'Sent'),
            ('acked', 'Acknowledged'),
        ],
        required=True,
        default='built',
        index=True,
    )
    result = fields.Json()

    _session_chunk_uniq = models.Constraint(
        'UNIQUE(session_id, chunk_no)',
        'A synchronization session cannot contain duplicate chunk numbers.',
    )


class SunnysideSyncState(models.Model):
    _name = 'sunnyside.sync.state'
    _description = 'Sunnyside Synchronization State'

    singleton_key = fields.Integer(required=True, default=1)
    state = fields.Selection(
        selection=[
            ('unknown', 'Unknown'),
            ('online', 'Online'),
            ('degraded', 'Degraded'),
            ('offline', 'Offline'),
        ],
        required=True,
        default='unknown',
    )
    last_success_at = fields.Datetime()
    last_attempt_at = fields.Datetime()
    consecutive_failures = fields.Integer(default=0)
    consecutive_successes = fields.Integer(default=0)
    last_error = fields.Text()
    offline_since = fields.Datetime()
    pull_cursor = fields.Integer(default=0)
    device_id = fields.Char(index=True)
    initial_migration_at = fields.Datetime()
    initial_migration_counts = fields.Json(default=dict)

    _singleton_key_uniq = models.Constraint(
        'UNIQUE(singleton_key)',
        'Only one sync state row is allowed.',
    )
    _MAX_CHUNK_BYTES = 8 * 1024 * 1024

    @api.model
    def get_singleton(self):
        state = self.search([], limit=1)
        return state or self.create({})

    @api.model
    def run_initial_migration(self):
        """Assign missing identities and enqueue existing in-scope rows once."""
        state = self.get_singleton()
        if state.initial_migration_at:
            return {
                'already_migrated': True,
                'counts': state.initial_migration_counts or {},
            }

        model_domains = {
            'res.partner': [('is_sunnyside_visitor', '=', True)],
            'sunnyside.visit': [],
            'sunnyside.booking': [],
            'sunnyside.booking.payment': [],
        }
        counts = {}
        outbox = self.env['sunnyside.sync.outbox'].sudo()
        for model_name, domain in model_domains.items():
            records = self.env[model_name].with_context(active_test=False).search(domain)
            count = 0
            for record in records:
                if record._sync_is_managed():
                    record._sync_queue_event('create', increment=False)
                    count += 1
            counts[model_name] = count

        attachment_domain = [
            ('res_model', 'in', list(model_domains)),
            ('res_id', '>', 0),
        ]
        attachments = self.env['ir.attachment'].with_context(active_test=False).search(
            attachment_domain
        )
        attachment_count = 0
        for attachment in attachments:
            if attachment._sync_is_managed():
                attachment._sync_queue_event('create', increment=False)
                attachment_count += 1
        counts['ir.attachment'] = attachment_count

        state.write({
            'initial_migration_at': fields.Datetime.now(),
            'initial_migration_counts': counts,
        })
        return {'already_migrated': False, 'counts': counts}

    @api.model
    def _require_worker(self):
        if not self.env.user.has_group('sunnyside_sync.group_sunnyside_sync_user'):
            raise AccessError(_("This operation is restricted to the synchronization service user."))

    @api.model
    def worker_open_session(self, direction):
        self._require_worker()
        if direction not in ('push', 'pull', 'reconcile'):
            raise ValidationError(_("The synchronization direction is invalid."))
        session = self.env['sunnyside.sync.session'].sudo().create({
            'direction': direction,
        })
        return session.uuid

    @api.model
    def worker_next_chunk(self, session_uuid):
        self._require_worker()
        session = self.env['sunnyside.sync.session'].sudo().search(
            [('uuid', '=', session_uuid)],
            limit=1,
        )
        if not session or session.direction != 'push':
            raise ValidationError(_("An open push session is required."))

        Chunk = self.env['sunnyside.sync.chunk'].sudo()
        chunk = Chunk.search(
            [('status', 'in', ('built', 'sent'))],
            order='id',
            limit=1,
        )
        if not chunk:
            events = self.env['sunnyside.sync.outbox'].sudo().search(
                [('status', '=', 'pending')],
                order='id',
                limit=100,
            )
            if not events:
                return False
            protocol = self.env['sunnyside.sync.protocol'].sudo()
            items = []
            encoded_size = 2
            locally_quarantined = 0
            for event in events:
                try:
                    item = protocol.serialize_record(
                        event.model,
                        event.record_uuid,
                        sequence=event.id,
                        operation=event.op,
                    )
                except ValidationError as error:
                    event.write({
                        'status': 'quarantined',
                        'last_error': str(error),
                    })
                    locally_quarantined += 1
                    continue
                if not item:
                    item = {
                        'seq': event.id,
                        'model': event.model,
                        'uuid': event.record_uuid,
                        'op': 'delete',
                        'rev': event.rev,
                        'origin': 'local',
                        'deleted_at': fields.Datetime.to_string(fields.Datetime.now()),
                        'cloud_id': False,
                        'data': False,
                    }
                item['op'] = event.op
                item['rev'] = event.rev
                item_size = len(json.dumps(item, separators=(',', ':')).encode('utf-8')) + 1
                if items and (
                    len(items) >= 100 or encoded_size + item_size > self._MAX_CHUNK_BYTES
                ):
                    break
                if item_size > self._MAX_CHUNK_BYTES:
                    event.write({
                        'status': 'quarantined',
                        'last_error': _('The serialized sync item exceeds the 8 MiB chunk limit.'),
                    })
                    locally_quarantined += 1
                    continue
                items.append(item)
                encoded_size += item_size
            if locally_quarantined:
                counts = dict(session.counts or {})
                counts['quarantined'] = counts.get('quarantined', 0) + locally_quarantined
                session.write({'counts': counts, 'status': 'partial'})
            if not items:
                return False
            chunk_no = max(
                Chunk.search([('session_id', '=', session.id)]).mapped('chunk_no') or [0]
            ) + 1
            chunk = Chunk.create({
                'session_id': session.id,
                'chunk_no': chunk_no,
                'payload': items,
                'status': 'built',
            })

        outbox_ids = [item.get('seq') for item in chunk.payload if item.get('seq')]
        outbox_events = self.env['sunnyside.sync.outbox'].sudo().browse(outbox_ids).exists()
        for event in outbox_events:
            event.attempts += 1
        payload = list(chunk.payload or [])
        payload_changed = False
        for item in payload:
            if (
                isinstance(item, dict)
                and item.get('op') == 'delete'
                and item.get('data') is None
            ):
                # Repair frozen chunks written before delete payloads became
                # XML-RPC safe. Keep their identity and revision unchanged.
                item['data'] = False
                payload_changed = True
        if payload_changed:
            chunk.payload = payload
        chunk.status = 'sent'
        return {
            'id': chunk.id,
            'session_uuid': chunk.session_id.uuid,
            'chunk_no': chunk.chunk_no,
            'payload': payload,
        }

    @api.model
    def worker_apply_ack(self, chunk_id, response):
        self._require_worker()
        chunk = self.env['sunnyside.sync.chunk'].sudo().browse(int(chunk_id)).exists()
        if not chunk:
            raise ValidationError(_("The frozen synchronization chunk no longer exists."))
        if not isinstance(response, dict) or not isinstance(response.get('results'), list):
            raise ValidationError(_("The cloud response is not a valid chunk acknowledgement."))
        sent = {
            (item.get('model'), item.get('uuid')): item
            for item in chunk.payload
            if isinstance(item, dict)
        }
        returned = {
            (result.get('model'), result.get('uuid')): result
            for result in response['results']
            if isinstance(result, dict)
        }
        if len(returned) != len(sent):
            raise ValidationError(_("The cloud acknowledgement does not cover the sent chunk."))

        Outbox = self.env['sunnyside.sync.outbox'].sudo()
        quarantined = 0
        acknowledged = 0
        for key, sent_item in sent.items():
            result = returned.get(key)
            if not result or result.get('status') not in ('ok', 'quarantined'):
                raise ValidationError(_("The cloud returned an invalid item status."))
            event_domain = [
                ('model', '=', key[0]),
                ('record_uuid', '=', key[1]),
            ]
            event = Outbox.search(event_domain + [('status', '=', 'pending')], limit=1)
            if not event:
                event = Outbox.search(
                    event_domain + [('status', '=', 'quarantined')],
                    order='id desc',
                    limit=1,
                )
            if not event or event.rev != sent_item.get('rev'):
                continue
            if result['status'] == 'ok':
                acked_at = fields.Datetime.now()
                event.write({
                    'status': 'acked',
                    'acked_at': acked_at,
                    'last_error': False,
                })
                Outbox.search(event_domain + [
                    ('status', '=', 'quarantined'),
                    ('rev', '<=', sent_item['rev']),
                ]).write({
                    'status': 'acked',
                    'acked_at': acked_at,
                    'last_error': False,
                })
                acknowledged += 1
            else:
                event.write({
                    'status': 'quarantined',
                    'last_error': result.get('reason') or _('Rejected by the cloud sync API.'),
                })
                quarantined += 1

        chunk.write({
            'status': 'acked',
            'result': response,
        })
        session = chunk.session_id
        counts = dict(session.counts or {})
        counts['pushed'] = counts.get('pushed', 0) + acknowledged
        counts['quarantined'] = counts.get('quarantined', 0) + quarantined
        session.counts = counts
        if quarantined:
            session.status = 'partial'
        return {'acknowledged': acknowledged, 'quarantined': quarantined}

    @api.model
    def worker_close_session(self, session_uuid, error=False):
        self._require_worker()
        session = self.env['sunnyside.sync.session'].sudo().search(
            [('uuid', '=', session_uuid)],
            limit=1,
        )
        if not session:
            raise ValidationError(_("The synchronization session does not exist."))
        if error:
            session.write({
                'status': 'failed',
                'last_error': str(error)[:2000],
                'ended_at': fields.Datetime.now(),
            })
        else:
            session.write({
                'status': 'complete' if session.status == 'open' else session.status,
                'ended_at': fields.Datetime.now(),
            })
        return True

    @api.model
    def worker_apply_remote(self, items, new_cursor):
        self._require_worker()
        if not isinstance(items, list) or len(items) > 200:
            raise ValidationError(_("A pull page must contain no more than 200 records."))
        try:
            new_cursor = max(0, int(new_cursor))
        except (TypeError, ValueError) as error:
            raise ValidationError(_("The pull cursor is invalid.")) from error
        state = self.get_singleton()
        if new_cursor < state.pull_cursor:
            new_cursor = state.pull_cursor
        protocol = self.env['sunnyside.sync.protocol'].sudo()
        quarantined = 0
        for item in items:
            try:
                with self.env.cr.savepoint():
                    protocol._apply_remote_item(False, item, cloud_wins=True)
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
                    'model': item.get('model', '') if isinstance(item, dict) else '',
                    'record_uuid': item.get('uuid', '') if isinstance(item, dict) else '',
                    'item': item if isinstance(item, (dict, list, int, float, str, bool)) else {},
                    'reason': str(error),
                })
                quarantined += 1
        state.pull_cursor = new_cursor
        return {
            'applied': len(items) - quarantined,
            'quarantined': quarantined,
            'cursor': new_cursor,
        }

    @api.model
    def worker_record_result(self, success, latency_ms=0, error=False):
        self._require_worker()
        if not isinstance(success, bool):
            raise ValidationError(_("The connectivity result must be boolean."))
        state = self.get_singleton()
        now = fields.Datetime.now()
        values = {'last_attempt_at': now}
        if success:
            values.update({
                'last_success_at': now,
                'consecutive_failures': 0,
                'consecutive_successes': state.consecutive_successes + 1,
                'last_error': False,
            })
            if state.state != 'online' and state.consecutive_successes + 1 >= 2:
                values.update({'state': 'online', 'offline_since': False})
            if latency_ms > 3000 and values.get('state', state.state) == 'online':
                values['state'] = 'degraded'
        else:
            values.update({
                'consecutive_failures': state.consecutive_failures + 1,
                'consecutive_successes': 0,
                'last_error': str(error or _('Cloud connection failed.'))[:2000],
            })
            if state.state != 'offline' and state.consecutive_failures + 1 >= 3:
                values.update({'state': 'offline', 'offline_since': now})
        state.write(values)
        return {'state': state.state, 'last_attempt_at': state.last_attempt_at}

    @api.model
    def worker_manifest(self, model_name=None, after_uuid='', limit=500):
        self._require_worker()
        return self.env['sunnyside.sync.protocol'].sudo().manifest(
            model_name,
            after_uuid,
            limit,
        )

    @api.model
    def worker_requeue(self, model_name, record_uuid):
        self._require_worker()
        if model_name not in self.env:
            raise ValidationError(_("The requested synchronization model is not installed."))
        record = self.env[model_name].sudo().with_context(active_test=False).search(
            [('sync_uuid', '=', record_uuid)],
            limit=1,
        )
        if record:
            revision = record.sync_rev
            operation = 'delete' if record.sync_deleted_at else 'update'
        else:
            tombstone = self.env['sunnyside.sync.tombstone'].sudo().search([
                ('model', '=', model_name),
                ('record_uuid', '=', record_uuid),
            ], limit=1)
            if not tombstone:
                raise ValidationError(_("The synchronized record no longer exists."))
            revision = tombstone.rev
            operation = 'delete'
        self.env['sunnyside.sync.outbox'].sudo().enqueue(
            model_name,
            record_uuid,
            operation,
            revision,
        )
        return True

    @api.model
    def worker_status(self):
        self._require_worker()
        state = self.get_singleton()
        Outbox = self.env['sunnyside.sync.outbox'].sudo()
        return {
            'state': state.state,
            'last_success_at': fields.Datetime.to_string(state.last_success_at)
            if state.last_success_at else False,
            'last_attempt_at': fields.Datetime.to_string(state.last_attempt_at)
            if state.last_attempt_at else False,
            'offline_since': fields.Datetime.to_string(state.offline_since)
            if state.offline_since else False,
            'pending_count': Outbox.search_count([('status', '=', 'pending')]),
            'quarantined_count': Outbox.search_count([('status', '=', 'quarantined')]),
            'pull_cursor': state.pull_cursor,
            'last_error': state.last_error or '',
        }

    @api.model
    def vacuum_acknowledged_records(self, retention_days=7):
        """
        Prunes acknowledged outbox events and frozen sync chunks older than retention_days.
        Prevents unbounded database growth on the local client machine and cloud database.
        """
        cutoff = fields.Datetime.subtract(fields.Datetime.now(), days=retention_days)
        Chunk = self.env['sunnyside.sync.chunk'].sudo()
        Outbox = self.env['sunnyside.sync.outbox'].sudo()

        old_chunks = Chunk.search([('create_date', '<', cutoff)])
        chunk_count = len(old_chunks)
        if old_chunks:
            old_chunks.unlink()

        old_outbox = Outbox.search([
            ('status', '=', 'acked'),
            ('acked_at', '<', cutoff),
        ])
        outbox_count = len(old_outbox)
        if old_outbox:
            old_outbox.unlink()

        return {
            'chunks_pruned': chunk_count,
            'outbox_pruned': outbox_count,
        }

    @api.model
    def worker_vacuum(self, retention_days=7):
        """Worker XML-RPC wrapper for auto-vacuuming acknowledged records."""
        self._require_worker()
        return self.vacuum_acknowledged_records(retention_days=retention_days)
