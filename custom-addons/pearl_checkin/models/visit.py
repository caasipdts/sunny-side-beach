# -*- coding: utf-8 -*-
from odoo import api, fields, models, _


class PearlVisit(models.Model):
    _name = 'pearl.visit'
    _description = 'Pearl Restaurant Visit'
    _order = 'check_in_datetime desc, id desc'

    name = fields.Char(
        string='Reference',
        required=True,
        copy=False,
        readonly=True,
        default=lambda self: _('New'),
        index=True,
    )
    visitor_id = fields.Many2one(
        'res.partner',
        string='Visitor',
        required=True,
        index=True,
        ondelete='restrict',
    )
    check_in_datetime = fields.Datetime(
        string='Check-in Time',
        required=True,
        default=fields.Datetime.now,
        index=True,
    )
    source = fields.Selection(
        selection=[
            ('qr_code', 'QR Code'),
            ('website', 'Website'),
            ('receptionist', 'Receptionist'),
        ],
        string='Check-in Source',
        required=True,
        default='receptionist',
        index=True,
    )
    location_id = fields.Many2one(
        'pearl.location',
        string='Neighbourhood / Location',
        index=True,
        help='Recorded neighbourhood at time of visit check-in.',
    )
    submission_token = fields.Char(
        string='Submission Token',
        copy=False,
        index=True,
        help='Idempotency token used to prevent duplicate submissions.',
    )
    visitor_phone = fields.Char(
        related='visitor_id.phone',
        string='Phone',
        readonly=True,
        store=True,
        index=True,
    )
    visitor_type = fields.Selection(
        selection=[
            ('new', 'New Visitor'),
            ('returning', 'Returning Visitor'),
        ],
        string='Visitor Type',
        compute='_compute_visitor_type',
        store=True,
        index=True,
        default='new',
        help='Indicates whether this check-in is the visitor\'s first visit or a returning visit.',
    )
    state = fields.Selection(
        selection=[
            ('checked_in', 'Checked In'),
            ('cancelled', 'Cancelled'),
        ],
        string='Status',
        required=True,
        default='checked_in',
        index=True,
    )
    user_id = fields.Many2one(
        'res.users',
        string='Recorded By',
        default=lambda self: self.env.user if not self.env.user._is_public() else False,
        readonly=True,
        index=True,
        help='User or receptionist who recorded this visit check-in.',
    )
    visitor_location_id = fields.Many2one(
        'pearl.location',
        related='visitor_id.pearl_location_id',
        string='Visitor Home Area',
        store=True,
        readonly=True,
        index=True,
        help="Visitor's home neighbourhood recorded on their profile.",
    )
    visitor_visit_count = fields.Integer(
        related='visitor_id.pearl_visit_count',
        string='Visitor Lifetime Visits',
        store=True,
        readonly=True,
        help="Total lifetime visits recorded for this visitor across all time.",
    )
    is_frequent_visitor = fields.Boolean(
        related='visitor_id.is_frequent_visitor',
        string='Frequent Visitor',
        store=True,
        readonly=True,
        index=True,
        help='Indicates whether this visit was made by a frequent visitor (3+ lifetime visits).',
    )
    new_visit_count = fields.Integer(
        string='New Visitor Visits',
        compute='_compute_reporting_measures',
        store=True,
        aggregator='sum',
        help="1 if this check-in was the visitor's first-ever visit, 0 otherwise.",
    )
    returning_visit_count = fields.Integer(
        string='Returning Visitor Visits',
        compute='_compute_reporting_measures',
        store=True,
        aggregator='sum',
        help="1 if this check-in was a returning visit, 0 otherwise.",
    )
    booking_ids = fields.One2many(
        'pearl.booking',
        'visit_id',
        string='Seating Bookings',
    )

    def init(self):
        super().init()
        self.env.cr.execute("""
            ALTER TABLE pearl_visit
            ADD COLUMN IF NOT EXISTS user_id integer,
            ADD COLUMN IF NOT EXISTS visitor_location_id integer,
            ADD COLUMN IF NOT EXISTS visitor_visit_count integer,
            ADD COLUMN IF NOT EXISTS is_frequent_visitor boolean default false,
            ADD COLUMN IF NOT EXISTS new_visit_count integer default 0,
            ADD COLUMN IF NOT EXISTS returning_visit_count integer default 0;

            UPDATE pearl_visit
            SET user_id = create_uid
            WHERE user_id IS NULL AND source = 'receptionist' AND create_uid IS NOT NULL;
        """)

    @api.depends('visitor_type')
    def _compute_reporting_measures(self):
        for visit in self:
            visit.new_visit_count = 1 if visit.visitor_type == 'new' else 0
            visit.returning_visit_count = 1 if visit.visitor_type == 'returning' else 0

    def create_booking(self, unit_id, guest_count):
        """Create a seating booking for this visit using the centralized booking logic."""
        self.ensure_one()
        return self.env['pearl.booking'].create_booking(
            visit_id=self.id,
            unit_id=unit_id,
            guest_count=guest_count,
        )

    def action_open_seating_dashboard(self):
        """Open the Visual Seating Dashboard with this visit preselected."""
        self.ensure_one()
        return {
            'type': 'ir.actions.client',
            'tag': 'pearl_seating_dashboard',
            'name': _('Seating Management'),
            'context': {
                'default_visit_id': self.id,
                'default_visitor_id': self.visitor_id.id if self.visitor_id else False,
            },
        }

    @api.depends('visitor_id', 'check_in_datetime')
    def _compute_visitor_type(self):
        for visit in self:
            if not visit.visitor_id:
                visit.visitor_type = 'new'
                continue
            ref_dt = visit.check_in_datetime or fields.Datetime.now()
            if visit.id:
                domain = [
                    ('visitor_id', '=', visit.visitor_id.id),
                    ('state', '=', 'checked_in'),
                    '|',
                    ('check_in_datetime', '<', ref_dt),
                    '&',
                    ('check_in_datetime', '=', ref_dt),
                    ('id', '<', visit.id),
                ]
            else:
                domain = [
                    ('visitor_id', '=', visit.visitor_id.id),
                    ('state', '=', 'checked_in'),
                    ('check_in_datetime', '<=', ref_dt),
                ]
            earlier_visit = self.search(domain, limit=1)
            visit.visitor_type = 'returning' if earlier_visit else 'new'

    @api.onchange('visitor_id')
    def _onchange_visitor_id(self):
        if self.visitor_id and self.visitor_id.pearl_location_id and not self.location_id:
            self.location_id = self.visitor_id.pearl_location_id

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('pearl.visit') or _('New')

            # Populate location from visitor profile if not explicitly set
            visitor_id = vals.get('visitor_id')
            if visitor_id:
                visitor = self.env['res.partner'].browse(visitor_id)
                if not vals.get('location_id') and visitor.pearl_location_id:
                    vals['location_id'] = visitor.pearl_location_id.id
                # Flag contact as visitor if not already flagged
                if not visitor.is_pearl_visitor:
                    visitor.sudo().write({'is_pearl_visitor': True})

            # Attribution of recorded by
            source = vals.get('source', 'receptionist')
            if source in ('qr_code', 'website'):
                vals.setdefault('user_id', False)
            elif not vals.get('user_id'):
                if self.env.user and not self.env.user._is_public():
                    vals['user_id'] = self.env.user.id

        return super().create(vals_list)
