# -*- coding: utf-8 -*-
from odoo import api, fields, models, _


class ResPartner(models.Model):
    _inherit = 'res.partner'

    is_pearl_visitor = fields.Boolean(
        string='Is Pearl Visitor',
        default=False,
        index=True,
        help='Indicates whether this contact is registered as a Pearl Restaurant visitor.',
    )
    pearl_location_id = fields.Many2one(
        'pearl.location',
        string='Neighbourhood / Location',
        index=True,
        tracking=True,
        help='Home neighbourhood or recorded area for this visitor.',
    )
    pearl_visit_ids = fields.One2many(
        'pearl.visit',
        'visitor_id',
        string='Visits',
    )
    pearl_booking_ids = fields.One2many(
        'pearl.booking',
        'visitor_id',
        string='Seating Bookings',
    )
    pearl_visit_count = fields.Integer(
        string='Visit Count',
        compute='_compute_pearl_visit_count',
        store=True,
        help='Total number of recorded visits for this visitor.',
    )
    privacy_acknowledged = fields.Boolean(
        string='Privacy Notice Acknowledged',
        default=False,
        tracking=True,
        help='Indicates whether the visitor acknowledged the Pearl Restaurant privacy notice.',
    )
    privacy_acknowledgement_date = fields.Datetime(
        string='Privacy Acknowledgement Date',
        readonly=True,
        help='Timestamp when the visitor acknowledged the privacy notice.',
    )
    privacy_notice_version = fields.Char(
        string='Privacy Notice Version',
        readonly=True,
        help='Version of the privacy notice acknowledged by the visitor (e.g. 1.0).',
    )
    marketing_consent = fields.Boolean(
        string='Marketing Communications Consent',
        default=False,
        tracking=True,
        help='Optional visitor opt-in for marketing updates (strictly separated from privacy notice acknowledgement).',
    )
    marketing_consent_date = fields.Datetime(
        string='Marketing Consent Date',
        readonly=True,
        help='Timestamp when the visitor consented to marketing communications.',
    )
    pearl_visitor_type = fields.Selection(
        selection=[
            ('new', 'New Visitor'),
            ('returning', 'Returning Visitor'),
        ],
        string='Visitor Status',
        compute='_compute_pearl_visitor_type',
        store=True,
        index=True,
        help='New visitor has 1 check-in; Returning visitor has 2 or more check-ins.',
    )
    is_frequent_visitor = fields.Boolean(
        string='Frequent Visitor',
        compute='_compute_is_frequent_visitor',
        store=True,
        index=True,
        help='Indicates whether the visitor has 3 or more lifetime check-in visits (documented threshold).',
    )
    pearl_first_visit_date = fields.Datetime(
        string='First Visit Date',
        compute='_compute_visit_dates',
        store=True,
        index=True,
        help='Date and time of the visitor\'s first check-in.',
    )
    pearl_last_visit_date = fields.Datetime(
        string='Last Visit Date',
        compute='_compute_visit_dates',
        store=True,
        index=True,
        help='Date and time of the visitor\'s most recent check-in.',
    )

    def init(self):
        super().init()
        self.env.cr.execute("""
            ALTER TABLE res_partner
            ADD COLUMN IF NOT EXISTS is_frequent_visitor boolean default false;
        """)

    @api.depends('pearl_visit_count')
    def _compute_is_frequent_visitor(self):
        for partner in self:
            partner.is_frequent_visitor = (partner.pearl_visit_count or 0) >= 3

    @api.depends('pearl_visit_count')
    def _compute_pearl_visitor_type(self):
        for partner in self:
            partner.pearl_visitor_type = 'returning' if partner.pearl_visit_count > 1 else 'new'

    @api.depends('pearl_visit_ids.check_in_datetime')
    def _compute_visit_dates(self):
        for partner in self:
            checked_in_visits = partner.pearl_visit_ids.filtered(lambda v: v.state == 'checked_in')
            if checked_in_visits:
                sorted_visits = checked_in_visits.sorted('check_in_datetime')
                partner.pearl_first_visit_date = sorted_visits[0].check_in_datetime
                partner.pearl_last_visit_date = sorted_visits[-1].check_in_datetime
            else:
                partner.pearl_first_visit_date = False
                partner.pearl_last_visit_date = False

    @api.depends('pearl_visit_ids')
    def _compute_pearl_visit_count(self):
        for partner in self:
            partner.pearl_visit_count = len(partner.pearl_visit_ids)

    def action_view_pearl_visits(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id(
            'pearl_checkin.action_pearl_visit'
        )
        action['domain'] = [('visitor_id', '=', self.id)]
        action['context'] = {
            'default_visitor_id': self.id,
            'default_location_id': self.pearl_location_id.id if self.pearl_location_id else False,
        }
        return action

    def action_open_seating_dashboard(self):
        """Open the Visual Seating Dashboard with this visitor preselected."""
        self.ensure_one()
        latest_checked_in = self.env['pearl.visit'].search([
            ('visitor_id', '=', self.id),
            ('state', '=', 'checked_in'),
        ], order='check_in_datetime desc, id desc', limit=1)
        return {
            'type': 'ir.actions.client',
            'tag': 'pearl_seating_dashboard',
            'name': _('Seating Management'),
            'context': {
                'default_visitor_id': self.id,
                'default_visit_id': latest_checked_in.id if latest_checked_in else False,
            },
        }

    @property
    def booking_ids(self):
        """Convenience property referencing the visitor's seating bookings."""
        return self.pearl_booking_ids

