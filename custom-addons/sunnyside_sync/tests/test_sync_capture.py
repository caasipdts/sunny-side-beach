import base64
import hashlib
import uuid

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged

from ..models.sync_mixin import _SYNC_APPLY_TOKEN


@tagged('post_install', '-at_install')
class TestSunnysideSyncCapture(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Partner = cls.env['res.partner']
        cls.Outbox = cls.env['sunnyside.sync.outbox']

    def _pending_event(self, record):
        return self.Outbox.search([
            ('model', '=', record._name),
            ('record_uuid', '=', record.sync_uuid),
            ('status', '=', 'pending'),
        ])

    def test_custom_seating_type_syncs_its_rules_without_echo(self):
        seating_type = self.env['sunnyside.seating.type'].create({
            'name': 'Sync Rooftop Lounge',
            'capacity_min': 2,
            'capacity_max': 12,
            'pricing_mode': 'fixed',
            'price_per_guest': 0.0,
            'fixed_price': 300000.0,
            'entry_fee_amount': 0.0,
            'minimum_spend_amount': 0.0,
        })
        protocol = self.env['sunnyside.sync.protocol']
        item = protocol.serialize_record(
            seating_type._name,
            seating_type.sync_uuid,
        )
        self.assertEqual(item['data']['code'], seating_type.code)
        self.assertEqual(item['data']['capacity_max'], 12)
        self.assertEqual(self._pending_event(seating_type).op, 'create')

        remote_uuid = str(uuid.uuid4())
        remote_data = dict(item['data'], code='custom_remote_lounge')
        result = protocol._apply_remote_item(False, {
            'model': 'sunnyside.seating.type',
            'uuid': remote_uuid,
            'op': 'create',
            'rev': 1,
            'origin': 'local',
            'data': remote_data,
        })

        imported = self.env['sunnyside.seating.type'].search([
            ('sync_uuid', '=', remote_uuid),
        ])
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(imported.capacity_max, 12)
        self.assertEqual(imported.pricing_mode, 'fixed')
        self.assertFalse(self._pending_event(imported))

    def test_visitor_edits_coalesce_under_stable_uuid(self):
        visitor = self.Partner.create({
            'name': 'Sync Test Visitor',
            'is_sunnyside_visitor': True,
        })
        parsed_uuid = uuid.UUID(visitor.sync_uuid)
        self.assertEqual(parsed_uuid.version, 7)
        self.assertEqual(visitor.sync_origin, 'local')

        visitor.write({'phone': '+2348012345678'})
        visitor.write({'email': 'visitor@example.test'})

        event = self._pending_event(visitor)
        self.assertEqual(len(event), 1)
        self.assertEqual(event.op, 'create')
        self.assertEqual(event.rev, visitor.sync_rev)
        self.assertEqual(visitor.sync_rev, 3)

    def test_nonvisitor_is_not_captured_until_marked_as_visitor(self):
        contact = self.Partner.create({'name': 'Ordinary Contact'})
        self.assertFalse(self._pending_event(contact))

        contact.write({'is_sunnyside_visitor': True})

        event = self._pending_event(contact)
        self.assertEqual(event.op, 'create')
        self.assertTrue(contact.sync_uuid)

    def test_sync_applying_does_not_create_echo_events(self):
        remote_uuid = str(uuid.uuid4())
        visitor = self.Partner.with_context(sync_applying=_SYNC_APPLY_TOKEN).create({
            'name': 'Cloud Visitor',
            'is_sunnyside_visitor': True,
            'sync_uuid': remote_uuid,
            'sync_origin': 'cloud',
            'sync_rev': 7,
        })
        visitor.with_context(sync_applying=_SYNC_APPLY_TOKEN).write({
            'email': 'cloud@example.test',
        })

        self.assertFalse(self._pending_event(visitor))
        self.assertEqual(visitor.sync_rev, 7)

    def test_payment_sync_metadata_preserves_payment_immutability(self):
        location = self.env['sunnyside.location'].create({'name': 'Sync Test Location'})
        visitor = self.Partner.create({
            'name': 'Visitor With Payment',
            'is_sunnyside_visitor': True,
        })
        visit = self.env['sunnyside.visit'].create({
            'visitor_id': visitor.id,
            'location_id': location.id,
            'source': 'receptionist',
        })
        area = self.env['sunnyside.seating.area'].create({'name': 'Sync Test Area'})
        unit = self.env['sunnyside.seating.unit'].create({
            'name': 'Sync Test Table',
            'area_id': area.id,
            'seating_type': 'table',
        })
        booking = self.env['sunnyside.booking'].create_booking(visit.id, unit.id, 1)
        payment = booking.record_payment(5000, 'cash')
        protocol = self.env['sunnyside.sync.protocol']

        self.assertTrue(payment.sync_uuid)
        self.assertEqual(self._pending_event(payment).op, 'create')
        booking_data = protocol._record_data(booking)
        payment_data = protocol._record_data(payment)
        self.assertEqual(protocol._values_from_item({
            'model': booking._name,
            'data': booking_data,
        }, existing=booking), {})
        self.assertEqual(protocol._values_from_item({
            'model': payment._name,
            'data': payment_data,
        }, existing=payment), {})
        with self.assertRaises(UserError):
            payment.write({'reference': 'must remain immutable'})

    def test_deleting_visitor_writes_tombstone_and_outbox_event(self):
        visitor = self.Partner.create({
            'name': 'Deleted Sync Visitor',
            'is_sunnyside_visitor': True,
        })
        self._pending_event(visitor).write({'status': 'acked'})

        visitor.unlink()

        self.assertTrue(visitor.exists())
        self.assertFalse(visitor.active)
        self.assertTrue(visitor.sync_deleted_at)
        event = self._pending_event(visitor)
        self.assertEqual(event.op, 'delete')

    def test_only_attachments_of_synced_records_are_captured(self):
        plain_contact = self.Partner.create({'name': 'Not A Visitor'})
        visitor = self.Partner.create({
            'name': 'Visitor With Attachment',
            'is_sunnyside_visitor': True,
        })
        attachment_values = {
            'name': 'visitor-note.txt',
            'type': 'binary',
            'mimetype': 'text/plain',
            'datas': base64.b64encode(b'sync test').decode(),
            'res_model': 'res.partner',
        }
        plain_attachment = self.env['ir.attachment'].create({
            **attachment_values,
            'res_id': plain_contact.id,
        })
        visitor_attachment = self.env['ir.attachment'].create({
            **attachment_values,
            'res_id': visitor.id,
        })

        self.assertFalse(self._pending_event(plain_attachment))
        self.assertEqual(self._pending_event(visitor_attachment).op, 'create')

    def test_deleting_synced_attachment_detaches_and_tombstones_it(self):
        visitor = self.Partner.create({
            'name': 'Visitor With Deleted Attachment',
            'is_sunnyside_visitor': True,
        })
        attachment = self.env['ir.attachment'].create({
            'name': 'visitor-note.txt',
            'type': 'binary',
            'mimetype': 'text/plain',
            'datas': base64.b64encode(b'sync test').decode(),
            'res_model': 'res.partner',
            'res_id': visitor.id,
        })

        attachment.unlink()

        self.assertTrue(attachment.exists())
        self.assertFalse(attachment.res_model)
        self.assertFalse(attachment.res_id)
        self.assertFalse(attachment.public)
        self.assertTrue(attachment.sync_deleted_at)
        self.assertEqual(self._pending_event(attachment).op, 'delete')

    def test_sync_metadata_is_not_user_writable(self):
        visitor = self.Partner.create({
            'name': 'Protected Sync Identity',
            'is_sunnyside_visitor': True,
        })

        with self.assertRaises(UserError):
            visitor.write({'sync_uuid': str(uuid.uuid4())})
        with self.assertRaises(UserError):
            visitor.with_context(sync_applying=True).write({
                'sync_rev': visitor.sync_rev + 1,
            })

    def test_cloud_push_is_idempotent_and_does_not_echo(self):
        device_id = 'sync-test-device'
        token = 'T' * 40
        self.env['sunnyside.sync.device'].create({
            'name': 'Sync Test Device',
            'device_id': device_id,
            'token_hash': hashlib.sha256(token.encode()).hexdigest(),
        })
        record_uuid = str(uuid.uuid4())
        session_uuid = str(uuid.uuid4())
        item = {
            'model': 'res.partner',
            'uuid': record_uuid,
            'op': 'create',
            'rev': 1,
            'origin': 'local',
            'data': {
                'name': 'Pushed Cloud Visitor',
                'phone': '+2348011112222',
                'email': 'pushed@example.test',
                'is_sunnyside_visitor': True,
                'location_name': False,
                'privacy_acknowledged': True,
                'privacy_acknowledgement_date': False,
                'privacy_notice_version': '1.0',
                'marketing_consent': False,
                'marketing_consent_date': False,
            },
        }
        protocol = self.env['sunnyside.sync.protocol'].sudo()
        response = protocol.apply_push_chunk(device_id, session_uuid, 0, [item])
        replay = protocol.apply_push_chunk(device_id, session_uuid, 0, [item])
        visitor = self.Partner.search([('sync_uuid', '=', record_uuid)])

        self.assertEqual(response, replay)
        self.assertEqual(response['results'][0]['status'], 'ok')
        self.assertEqual(len(visitor), 1)
        self.assertEqual(visitor.name, 'Pushed Cloud Visitor')
        self.assertFalse(self._pending_event(visitor))
        self.assertEqual(self.env['sunnyside.sync.push.log'].search_count([
            ('session_uuid', '=', session_uuid),
            ('chunk_no', '=', 0),
        ]), 1)

    def test_device_authentication_rejects_wrong_tokens(self):
        token = 'A' * 40
        device = self.env['sunnyside.sync.device'].create({
            'name': 'Authentication Test Device',
            'device_id': 'sync-auth-test-device',
            'token_hash': hashlib.sha256(token.encode()).hexdigest(),
        })
        protocol = self.env['sunnyside.sync.protocol'].sudo()

        self.assertEqual(
            protocol.authenticate_device(device.device_id, token),
            device,
        )
        self.assertFalse(protocol.authenticate_device(device.device_id, 'B' * 40))

    def test_invalid_push_item_is_quarantined_without_aborting_chunk(self):
        device_id = 'sync-quarantine-test-device'
        self.env['sunnyside.sync.device'].create({
            'name': 'Quarantine Test Device',
            'device_id': device_id,
            'token_hash': hashlib.sha256(b'Q' * 40).hexdigest(),
        })
        session_uuid = str(uuid.uuid4())
        record_uuid = str(uuid.uuid4())
        protocol = self.env['sunnyside.sync.protocol'].sudo()

        response = protocol.apply_push_chunk(device_id, session_uuid, 0, [{
            'model': 'unsupported.model',
            'uuid': record_uuid,
            'op': 'create',
            'rev': 1,
            'data': {},
        }])

        self.assertEqual(response['results'][0]['status'], 'quarantined')
        quarantine = self.env['sunnyside.sync.quarantine'].search([
            ('session_uuid', '=', session_uuid),
            ('record_uuid', '=', record_uuid),
        ])
        self.assertEqual(len(quarantine), 1)

    def test_imports_released_bookings_and_their_historical_payments(self):
        area = self.env['sunnyside.seating.area'].create({
            'name': 'Sync History Test Area',
        })
        unit = self.env['sunnyside.seating.unit'].create({
            'name': 'Sync History Test Table',
            'area_id': area.id,
            'seating_type': 'table',
            'capacity_min': 1,
            'capacity_max': 4,
            'price_per_guest': 20000,
            'entry_fee_amount': 5000,
            'minimum_spend_amount': 15000,
        })
        protocol = self.env['sunnyside.sync.protocol'].sudo()
        visitor_uuid = str(uuid.uuid4())
        visit_uuid = str(uuid.uuid4())
        booking_uuid = str(uuid.uuid4())
        payment_uuid = str(uuid.uuid4())
        now = fields.Datetime.to_string(fields.Datetime.now())

        protocol._apply_remote_item(False, {
            'model': 'res.partner',
            'uuid': visitor_uuid,
            'op': 'create',
            'rev': 1,
            'origin': 'local',
            'data': {
                'name': 'Historical Sync Visitor',
                'phone': '',
                'email': '',
                'is_sunnyside_visitor': True,
                'location_name': False,
                'privacy_acknowledged': False,
                'privacy_acknowledgement_date': False,
                'privacy_notice_version': '',
                'marketing_consent': False,
                'marketing_consent_date': False,
            },
        })
        protocol._apply_remote_item(False, {
            'model': 'sunnyside.visit',
            'uuid': visit_uuid,
            'op': 'create',
            'rev': 1,
            'origin': 'local',
            'data': {
                'name': 'VISIT/SYNC-HISTORY',
                'visitor_uuid': visitor_uuid,
                'check_in_datetime': now,
                'source': 'receptionist',
                'location_name': False,
                'submission_token': '',
                'state': 'checked_in',
            },
        })
        protocol._apply_remote_item(False, {
            'model': 'sunnyside.booking',
            'uuid': booking_uuid,
            'op': 'create',
            'rev': 1,
            'origin': 'local',
            'data': {
                'name': 'BKG/SYNC-HISTORY',
                'visit_uuid': visit_uuid,
                'unit_name': unit.name,
                'area_name': area.name,
                'guest_count': 1,
                'seating_type': unit.seating_type,
                'pricing_mode': unit.pricing_mode,
                'unit_price': unit.price_per_guest,
                'entry_fee_amount': unit.entry_fee_amount,
                'minimum_spend_amount': unit.minimum_spend_amount,
                'amount_total': unit.price_per_guest,
                'currency_code': unit.currency_id.name,
                'state': 'released',
                'reserved_datetime': now,
                'released_datetime': now,
            },
        })
        protocol._apply_remote_item(False, {
            'model': 'sunnyside.booking.payment',
            'uuid': payment_uuid,
            'op': 'create',
            'rev': 1,
            'origin': 'local',
            'data': {
                'booking_uuid': booking_uuid,
                'amount': 1000,
                'payment_method': 'cash',
                'reference': 'SYNC-HISTORY',
                'payment_datetime': now,
                'currency_code': unit.currency_id.name,
            },
        })

        booking = self.env['sunnyside.booking'].search([
            ('sync_uuid', '=', booking_uuid),
        ])
        payment = self.env['sunnyside.booking.payment'].search([
            ('sync_uuid', '=', payment_uuid),
        ])
        self.assertEqual(booking.state, 'released')
        self.assertEqual(payment.booking_id, booking)
        self.assertEqual(payment.amount, 1000)

    def test_pull_includes_a_deleted_visitor_tombstone(self):
        visitor = self.Partner.create({
            'name': 'Pulled Tombstone Visitor',
            'is_sunnyside_visitor': True,
        })
        record_uuid = visitor.sync_uuid
        visitor.unlink()
        change = self.env['sunnyside.sync.change'].search([
            ('model', '=', 'res.partner'),
            ('record_uuid', '=', record_uuid),
        ], order='id desc', limit=1)

        page = self.env['sunnyside.sync.protocol'].sudo().pull_changes(
            after=change.id - 1,
        )

        tombstone = next(
            item for item in page['items']
            if item['uuid'] == record_uuid
        )
        self.assertEqual(tombstone['op'], 'delete')
        self.assertEqual(tombstone['rev'], visitor.sync_rev)

    def test_manifest_includes_tombstones_without_live_records(self):
        record_uuid = 'ffffffff-ffff-ffff-ffff-ffffffffffff'
        self.env['sunnyside.sync.tombstone'].create({
            'model': 'res.partner',
            'record_uuid': record_uuid,
            'rev': 3,
            'origin': 'cloud',
        })

        page = self.env['sunnyside.sync.protocol'].sudo().manifest(
            'res.partner',
            after_uuid=record_uuid[:-1],
            limit=10,
        )

        tombstone = next(
            entry for entry in page['res.partner']
            if entry['uuid'] == record_uuid
        )
        self.assertTrue(tombstone['deleted'])
        self.assertEqual(tombstone['rev'], 3)

    def test_reconciliation_requeues_tombstones_without_live_records(self):
        record_uuid = str(uuid.uuid4())
        self.env['sunnyside.sync.tombstone'].create({
            'model': 'res.partner',
            'record_uuid': record_uuid,
            'rev': 4,
            'origin': 'local',
        })
        quarantined = self.Outbox.create({
            'model': 'res.partner',
            'record_uuid': record_uuid,
            'op': 'delete',
            'rev': 4,
            'status': 'quarantined',
        })
        sync_user = self.env['res.users'].create({
            'name': 'Sync Worker Test User',
            'login': 'sync-worker-test',
            'group_ids': [(6, 0, self.env.ref(
                'sunnyside_sync.group_sunnyside_sync_user'
            ).ids)],
        })

        self.env['sunnyside.sync.state'].with_user(sync_user).worker_requeue(
            'res.partner',
            record_uuid,
        )

        event = self.Outbox.search([
            ('model', '=', 'res.partner'),
            ('record_uuid', '=', record_uuid),
            ('status', '=', 'pending'),
        ])
        self.assertEqual(event.op, 'delete')
        self.assertEqual(event.rev, 4)
        session = self.env['sunnyside.sync.session'].create({'direction': 'push'})
        chunk = self.env['sunnyside.sync.chunk'].create({
            'session_id': session.id,
            'chunk_no': 1,
            'payload': [{
                'seq': event.id,
                'model': event.model,
                'uuid': record_uuid,
                'rev': event.rev,
            }],
            'status': 'sent',
        })
        self.env['sunnyside.sync.state'].with_user(sync_user).worker_apply_ack(
            chunk.id,
            {'results': [{
                'model': 'res.partner',
                'uuid': record_uuid,
                'status': 'ok',
            }]},
        )
        self.assertEqual(event.status, 'acked')
        self.assertEqual(quarantined.status, 'acked')
        self.assertTrue(quarantined.acked_at)

    def test_invalid_pull_item_is_quarantined_and_cursor_advances(self):
        sync_user = self.env['res.users'].create({
            'name': 'Sync Pull Test User',
            'login': 'sync-pull-test',
            'group_ids': [(6, 0, self.env.ref(
                'sunnyside_sync.group_sunnyside_sync_user'
            ).ids)],
        })
        record_uuid = str(uuid.uuid4())

        result = self.env['sunnyside.sync.state'].with_user(
            sync_user,
        ).worker_apply_remote([{
            'model': 'unsupported.model',
            'uuid': record_uuid,
            'op': 'create',
            'rev': 1,
            'data': {},
        }], 17)

        self.assertEqual(result['quarantined'], 1)
        self.assertEqual(result['cursor'], 17)
        self.assertTrue(self.env['sunnyside.sync.quarantine'].search([
            ('record_uuid', '=', record_uuid),
            ('reason', '!=', False),
        ]))

    def test_local_cloud_pull_wins_equal_revision_conflict(self):
        remote_uuid = str(uuid.uuid4())
        visitor = self.Partner.with_context(sync_applying=_SYNC_APPLY_TOKEN).create({
            'name': 'Local Copy',
            'is_sunnyside_visitor': True,
            'sync_uuid': remote_uuid,
            'sync_origin': 'local',
            'sync_rev': 4,
        })
        item = {
            'model': 'res.partner',
            'uuid': remote_uuid,
            'op': 'update',
            'rev': 4,
            'origin': 'cloud',
            'cloud_id': 9001,
            'data': {
                'name': 'Cloud Copy',
                'phone': '',
                'email': '',
                'is_sunnyside_visitor': True,
                'location_name': False,
                'privacy_acknowledged': False,
                'privacy_acknowledgement_date': False,
                'privacy_notice_version': '',
                'marketing_consent': False,
                'marketing_consent_date': False,
            },
        }

        self.env['sunnyside.sync.protocol'].sudo()._apply_remote_item(
            False,
            item,
            cloud_wins=True,
        )

        self.assertEqual(visitor.name, 'Cloud Copy')
        self.assertEqual(visitor.sync_origin, 'cloud')
        self.assertEqual(visitor.cloud_id, 9001)
        self.assertEqual(self.env['sunnyside.sync.conflict'].search_count([
            ('record_uuid', '=', remote_uuid),
        ]), 1)
        self.assertFalse(self._pending_event(visitor))
