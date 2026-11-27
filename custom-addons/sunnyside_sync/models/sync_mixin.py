import os

from odoo import api, fields, models, _
from odoo.exceptions import UserError

from .uuid import new_uuid7


_SYNC_APPLY_TOKEN = object()


class SunnysideSyncMixin(models.AbstractModel):
    _name = 'sunnyside.sync.mixin'
    _description = 'Sunnyside Synchronization Metadata'
    _abstract = True

    sync_uuid = fields.Char(
        string='Synchronization UUID',
        index=True,
        copy=False,
        help='Stable cross-database identity. It must never be changed after assignment.',
    )
    sync_origin = fields.Selection(
        selection=[('local', 'Local'), ('cloud', 'Cloud')],
        default=lambda self: os.environ.get('SUNNYSIDE_SYNC_ORIGIN', 'local'),
        copy=False,
        help='Database where this record was first created.',
    )
    sync_rev = fields.Integer(
        string='Synchronization Revision',
        default=1,
        copy=False,
        help='Incremented for each local business-data edit.',
    )
    sync_deleted_at = fields.Datetime(
        string='Synchronization Deletion Time',
        copy=False,
        help='Tombstone timestamp; synced rows are retained rather than hard-deleted.',
    )
    cloud_id = fields.Integer(
        string='Cloud Record ID',
        index=True,
        copy=False,
        help='Optional informational ID assigned by the cloud Odoo database.',
    )

    _SYNC_FIELDS = frozenset({
        'sync_uuid',
        'sync_origin',
        'sync_rev',
        'sync_deleted_at',
        'cloud_id',
    })
    _sync_tombstone_enabled = True

    def _sync_is_managed(self):
        """Return whether this row belongs to the Sunnyside sync scope."""
        return True

    def _sync_tombstone_values(self):
        """Build the local values that hide a row while retaining its history."""
        values = {'sync_deleted_at': fields.Datetime.now()}
        if 'active' in self._fields:
            values['active'] = False
        return values

    def _sync_tombstone_context(self, values):
        return {}

    def _sync_queue_event(self, operation, increment=True, extra_values=None):
        self.ensure_one()
        metadata = {}
        if not self.sync_uuid:
            metadata.update({
                'sync_uuid': new_uuid7(),
                'sync_origin': self.sync_origin or 'local',
                'sync_rev': max(self.sync_rev or 1, 1),
            })
            if operation != 'delete':
                operation = 'create'
        elif increment:
            metadata['sync_rev'] = (self.sync_rev or 0) + 1

        if extra_values:
            metadata.update(extra_values)

        if metadata:
            context = {'sync_applying': _SYNC_APPLY_TOKEN}
            context.update(self._sync_tombstone_context(metadata))
            self.sudo().with_context(**context).write(metadata)

        self.env['sunnyside.sync.outbox'].sudo().enqueue(
            model=self._name,
            record_uuid=self.sync_uuid,
            operation=operation,
            revision=self.sync_rev,
        )

    @api.model_create_multi
    def create(self, vals_list):
        if self.env.context.get('sync_applying') is not _SYNC_APPLY_TOKEN:
            if any(self._SYNC_FIELDS.intersection(vals) for vals in vals_list):
                raise UserError(_("Synchronization metadata is managed by the sync service."))

        records = super().create(vals_list)
        if self.env.context.get('sync_applying') is not _SYNC_APPLY_TOKEN:
            for record in records:
                if record._sync_is_managed():
                    record._sync_queue_event('create', increment=False)
        return records

    def write(self, vals):
        if self.env.context.get('sync_applying') is _SYNC_APPLY_TOKEN:
            return super().write(vals)
        if self._SYNC_FIELDS.intersection(vals):
            raise UserError(_("Synchronization metadata is managed by the sync service."))

        managed_before = {
            record.id: record._sync_is_managed()
            for record in self
        }
        result = super().write(vals)

        for record in self:
            was_managed = managed_before[record.id]
            is_managed = record._sync_is_managed()
            if not was_managed and not is_managed:
                continue

            if was_managed and not is_managed:
                operation = 'delete'
                extra_values = {'sync_deleted_at': fields.Datetime.now()}
            elif not was_managed:
                operation = 'update' if record.sync_uuid else 'create'
                extra_values = {'sync_deleted_at': False}
            else:
                operation = 'delete' if record.sync_deleted_at else 'update'
                extra_values = {}

            record._sync_queue_event(operation, extra_values=extra_values)
        return result

    def unlink(self):
        if (
            self.env.context.get('sync_applying') is _SYNC_APPLY_TOKEN
            or not self._sync_tombstone_enabled
        ):
            return super().unlink()

        managed = self.filtered(lambda record: record._sync_is_managed())
        unmanaged = self - managed
        if unmanaged:
            super(SunnysideSyncMixin, unmanaged).unlink()

        for record in managed:
            values = record._sync_tombstone_values()
            record._sync_queue_event('delete', extra_values=values)
        return True
