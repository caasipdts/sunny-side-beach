from odoo import api, fields, models, _

from .sync_mixin import _SYNC_APPLY_TOKEN


class SunnysideSyncResUsers(models.Model):
    _inherit = 'res.users'

    @api.model_create_multi
    def create(self, vals_list):
        return super(
            SunnysideSyncResUsers,
            self.with_context(sync_applying=_SYNC_APPLY_TOKEN),
        ).create(vals_list)


class SunnysideSyncResPartner(models.Model):
    _name = 'res.partner'
    _inherit = ['res.partner', 'sunnyside.sync.mixin']

    _sync_uuid_uniq = models.Constraint(
        'UNIQUE(sync_uuid)',
        'Synchronization UUIDs must be unique.',
    )

    def _sync_is_managed(self):
        self.ensure_one()
        return bool(self.is_sunnyside_visitor)


class SunnysideSyncVisit(models.Model):
    _name = 'sunnyside.visit'
    _inherit = ['sunnyside.visit', 'sunnyside.sync.mixin']

    active = fields.Boolean(default=True, index=True)

    _sync_uuid_uniq = models.Constraint(
        'UNIQUE(sync_uuid)',
        'Synchronization UUIDs must be unique.',
    )


class SunnysideSyncBooking(models.Model):
    _name = 'sunnyside.booking'
    _inherit = ['sunnyside.booking', 'sunnyside.sync.mixin']

    active = fields.Boolean(default=True, index=True)

    _sync_uuid_uniq = models.Constraint(
        'UNIQUE(sync_uuid)',
        'Synchronization UUIDs must be unique.',
    )

    def _sync_tombstone_values(self):
        values = super()._sync_tombstone_values()
        if self.state == 'reserved':
            values.update({
                'state': 'released',
                'released_by_id': self.env.user.id,
                'released_datetime': fields.Datetime.now(),
            })
        return values

    def _sync_tombstone_context(self, values):
        context = super()._sync_tombstone_context(values)
        if 'state' in values:
            context['_sunnyside_releasing'] = True
        return context


class SunnysideSyncSeatingType(models.Model):
    _name = 'sunnyside.seating.type'
    _inherit = ['sunnyside.seating.type', 'sunnyside.sync.mixin']

    _sync_uuid_uniq = models.Constraint(
        'UNIQUE(sync_uuid)',
        'Synchronization UUIDs must be unique.',
    )

    def _sync_is_managed(self):
        self.ensure_one()
        return not self.is_builtin and self.active


class SunnysideSyncPayment(models.Model):
    _name = 'sunnyside.booking.payment'
    _inherit = ['sunnyside.booking.payment', 'sunnyside.sync.mixin']
    _sync_tombstone_enabled = False

    _sync_uuid_uniq = models.Constraint(
        'UNIQUE(sync_uuid)',
        'Synchronization UUIDs must be unique.',
    )

    def write(self, vals):
        if (
            self.env.context.get('sync_applying') is _SYNC_APPLY_TOKEN
            and set(vals) <= self._SYNC_FIELDS
        ):
            return models.Model.write(self, vals)
        return super().write(vals)


class SunnysideSyncAttachment(models.Model):
    _name = 'ir.attachment'
    _inherit = ['ir.attachment', 'sunnyside.sync.mixin']

    _sync_uuid_uniq = models.Constraint(
        'UNIQUE(sync_uuid)',
        'Synchronization UUIDs must be unique.',
    )

    _SYNCED_ATTACHMENT_MODELS = frozenset({
        'res.partner',
        'sunnyside.visit',
        'sunnyside.booking',
        'sunnyside.booking.payment',
    })

    def _sync_tombstone_values(self):
        values = super()._sync_tombstone_values()
        # ir.attachment deliberately does not support active filtering; detach it
        # while retaining the binary so remote deletion can be synchronized.
        values.update({
            'res_model': False,
            'res_id': 0,
            'public': False,
            'access_token': False,
        })
        return values

    def _sync_is_managed(self):
        self.ensure_one()
        if self.res_model not in self._SYNCED_ATTACHMENT_MODELS or not self.res_id:
            return False
        linked_record = self.env[self.res_model].browse(self.res_id).exists()
        return bool(linked_record and linked_record._sync_is_managed())
