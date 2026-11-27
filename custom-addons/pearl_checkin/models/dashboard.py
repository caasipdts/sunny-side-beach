# -*- coding: utf-8 -*-
from datetime import datetime, time, timedelta
from odoo import api, fields, models, _
from odoo.exceptions import AccessError


class PearlDashboard(models.Model):
    _name = 'pearl.dashboard'
    _description = 'Pearl Restaurant Management Dashboard'

    name = fields.Char(
        string='Dashboard Name',
        default='Pearl Restaurant Overview',
        readonly=True,
    )

    # -------------------------------------------------------------------------
    # Existing Visitor Activity KPIs (always visible, computed real-time)
    # -------------------------------------------------------------------------
    total_visitors = fields.Integer(
        string='Total Registered Visitors',
        compute='_compute_metrics',
        help='Total distinct registered visitor contacts.',
    )
    checkins_today = fields.Integer(
        string='Total Check-ins Today',
        compute='_compute_metrics',
        help='Total recorded check-in visits today.',
    )
    new_visitors_today = fields.Integer(
        string='New Visitors Today',
        compute='_compute_metrics',
        help='Visitors whose first-ever check-in was recorded today.',
    )
    returning_visitors_today = fields.Integer(
        string='Returning Visitors Today',
        compute='_compute_metrics',
        help='Visitors who had an earlier visit and checked in again today.',
    )
    checkins_this_week = fields.Integer(
        string='Total Check-ins This Week',
        compute='_compute_metrics',
        help='Total recorded check-in visits since Monday.',
    )
    checkins_this_month = fields.Integer(
        string='Total Check-ins This Month',
        compute='_compute_metrics',
        help='Total recorded check-in visits since the 1st of the current month.',
    )

    # -------------------------------------------------------------------------
    # Date range filter fields (stored on record for form-driven filtering)
    # -------------------------------------------------------------------------
    date_filter = fields.Selection(
        selection=[
            ('today', 'Today'),
            ('this_week', 'This Week'),
            ('this_month', 'This Month'),
            ('this_year', 'This Year'),
            ('custom', 'Custom Range'),
        ],
        string='Date Range',
        default='this_month',
        help='Selected date range for historical KPI calculations.',
    )
    date_from = fields.Date(
        string='From',
        help='Start date for custom date range filter.',
    )
    date_to = fields.Date(
        string='To',
        help='End date for custom date range filter.',
    )

    # -------------------------------------------------------------------------
    # Date-range visitor KPIs
    # -------------------------------------------------------------------------
    visits_in_range = fields.Integer(
        string='Total Visits in Range',
        compute='_compute_range_metrics',
        help='Total check-in visits within the selected date range.',
    )
    new_visitors_in_range = fields.Integer(
        string='New Visitors in Range',
        compute='_compute_range_metrics',
        help='Visits classified as first-time within the selected date range.',
    )
    returning_visitors_in_range = fields.Integer(
        string='Returning Visitors in Range',
        compute='_compute_range_metrics',
        help='Visits classified as returning within the selected date range.',
    )

    # -------------------------------------------------------------------------
    # Seating & Booking Operational KPIs (always visible, current state)
    # -------------------------------------------------------------------------
    total_seating_units = fields.Integer(
        string='Total Seating Units',
        compute='_compute_seating_metrics',
        help='Total number of configured active seating units.',
    )
    reserved_units = fields.Integer(
        string='Reserved Units',
        compute='_compute_seating_metrics',
        help='Seating units currently occupied by an active reservation.',
    )
    available_units = fields.Integer(
        string='Available Units',
        compute='_compute_seating_metrics',
        help='Active seating units with no current reservation.',
    )
    active_bookings = fields.Integer(
        string='Active Bookings',
        compute='_compute_seating_metrics',
        help='Number of bookings currently in reserved state.',
    )
    active_booking_guests = fields.Integer(
        string='Guests in Active Bookings',
        compute='_compute_seating_metrics',
        help='Total guest count across all currently reserved bookings.',
    )

    # -------------------------------------------------------------------------
    # Financial KPIs — manager only, date-range driven
    # -------------------------------------------------------------------------
    contracted_booking_value = fields.Monetary(
        string='Contracted Booking Value',
        currency_field='currency_id',
        compute='_compute_financial_metrics',
        help='Sum of amount_total for bookings created within the selected date range (reserved_datetime basis).',
    )
    recorded_collections = fields.Monetary(
        string='Recorded Collections',
        currency_field='currency_id',
        compute='_compute_financial_metrics',
        help='Sum of recorded payment transactions within the selected date range.',
    )
    outstanding_balances = fields.Monetary(
        string='Outstanding Balances',
        currency_field='currency_id',
        compute='_compute_financial_metrics',
        help='Total amount_due across all bookings (reserved and released) with a remaining balance.',
    )
    # Payment status breakdown
    bookings_unpaid_count = fields.Integer(
        string='Unpaid Bookings',
        compute='_compute_financial_metrics',
        help='Bookings within the selected range with payment_status = unpaid.',
    )
    bookings_partial_count = fields.Integer(
        string='Partially Paid Bookings',
        compute='_compute_financial_metrics',
        help='Bookings within the selected range with payment_status = partial.',
    )
    bookings_paid_count = fields.Integer(
        string='Fully Paid Bookings',
        compute='_compute_financial_metrics',
        help='Bookings within the selected range with payment_status = paid.',
    )
    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        compute='_compute_currency',
    )

    def _compute_currency(self):
        currency = self.env.company.currency_id
        for rec in self:
            rec.currency_id = currency

    # -------------------------------------------------------------------------
    # Helper: resolve date range boundaries
    # -------------------------------------------------------------------------
    def _get_range_boundaries(self):
        """Return (start_dt, end_dt) for the currently selected date_filter."""
        today = fields.Date.today()
        now = fields.Datetime.now()
        date_filter = self.date_filter or 'this_month'

        if date_filter == 'today':
            start = datetime.combine(today, time.min)
            end = datetime.combine(today, time.max)
        elif date_filter == 'this_week':
            start = datetime.combine(today - timedelta(days=today.weekday()), time.min)
            end = now
        elif date_filter == 'this_month':
            start = datetime.combine(today.replace(day=1), time.min)
            end = now
        elif date_filter == 'this_year':
            start = datetime.combine(today.replace(month=1, day=1), time.min)
            end = now
        elif date_filter == 'custom':
            df = self.date_from or today.replace(day=1)
            dt = self.date_to or today
            start = datetime.combine(df, time.min)
            end = datetime.combine(dt, time.max)
        else:
            start = datetime.combine(today.replace(day=1), time.min)
            end = now

        return start, end

    @api.model
    def _get_range_boundaries_for(self, date_filter, date_from=None, date_to=None):
        """Static helper for model-level methods (tests, server-side calls)."""
        today = fields.Date.today()
        now = fields.Datetime.now()

        if date_filter == 'today':
            start = datetime.combine(today, time.min)
            end = datetime.combine(today, time.max)
        elif date_filter == 'this_week':
            start = datetime.combine(today - timedelta(days=today.weekday()), time.min)
            end = now
        elif date_filter == 'this_month':
            start = datetime.combine(today.replace(day=1), time.min)
            end = now
        elif date_filter == 'this_year':
            start = datetime.combine(today.replace(month=1, day=1), time.min)
            end = now
        elif date_filter == 'custom':
            df = date_from or today.replace(day=1)
            dt = date_to or today
            start = datetime.combine(df, time.min)
            end = datetime.combine(dt, time.max)
        else:
            start = datetime.combine(today.replace(day=1), time.min)
            end = now

        return start, end

    # -------------------------------------------------------------------------
    # Existing metric compute (today / this week / this month — unchanged)
    # -------------------------------------------------------------------------
    def _compute_metrics(self):
        Visit = self.env['pearl.visit']
        Partner = self.env['res.partner']
        now = fields.Datetime.now()
        today = fields.Date.today()

        # Date boundaries
        today_start = datetime.combine(today, time.min)
        today_end = datetime.combine(today, time.max)
        week_start = datetime.combine(today - timedelta(days=today.weekday()), time.min)
        month_start = datetime.combine(today.replace(day=1), time.min)

        # 1. Total Registered Visitors
        total_visitors_count = Partner.search_count([('is_pearl_visitor', '=', True)])

        # 2. Check-ins Today
        today_visits = Visit.search([
            ('check_in_datetime', '>=', today_start),
            ('check_in_datetime', '<=', today_end),
            ('state', '=', 'checked_in'),
        ])
        checkins_today_count = len(today_visits)

        # 3. New vs Returning Visitors Today
        new_visitors_today_count = len(today_visits.filtered(lambda v: v.visitor_type == 'new'))
        returning_visitors_today_count = len(today_visits.filtered(lambda v: v.visitor_type == 'returning'))

        # 4. Check-ins This Week
        checkins_this_week_count = Visit.search_count([
            ('check_in_datetime', '>=', week_start),
            ('check_in_datetime', '<=', now),
            ('state', '=', 'checked_in'),
        ])

        # 5. Check-ins This Month
        checkins_this_month_count = Visit.search_count([
            ('check_in_datetime', '>=', month_start),
            ('check_in_datetime', '<=', now),
            ('state', '=', 'checked_in'),
        ])

        for record in self:
            record.total_visitors = total_visitors_count
            record.checkins_today = checkins_today_count
            record.new_visitors_today = new_visitors_today_count
            record.returning_visitors_today = returning_visitors_today_count
            record.checkins_this_week = checkins_this_week_count
            record.checkins_this_month = checkins_this_month_count

    # -------------------------------------------------------------------------
    # Date-range visitor KPI compute
    # -------------------------------------------------------------------------
    def _compute_range_metrics(self):
        Visit = self.env['pearl.visit']
        for record in self:
            start, end = record._get_range_boundaries()
            range_visits = Visit.search([
                ('check_in_datetime', '>=', start),
                ('check_in_datetime', '<=', end),
                ('state', '=', 'checked_in'),
            ])
            record.visits_in_range = len(range_visits)
            record.new_visitors_in_range = len(range_visits.filtered(lambda v: v.visitor_type == 'new'))
            record.returning_visitors_in_range = len(range_visits.filtered(lambda v: v.visitor_type == 'returning'))

    # -------------------------------------------------------------------------
    # Seating & Booking operational KPI compute (current state, not date-ranged)
    # -------------------------------------------------------------------------
    def _compute_seating_metrics(self):
        Unit = self.env['pearl.seating.unit']
        Booking = self.env['pearl.booking']

        all_active_units = Unit.search([('active', '=', True)])
        all_reserved_bookings = Booking.search([
            ('state', '=', 'reserved'),
            ('unit_id', 'in', all_active_units.ids if all_active_units else [0]),
        ])
        total_units = len(all_active_units)
        reserved_count = len(all_reserved_bookings)
        available_count = max(0, total_units - reserved_count)
        total_guests = sum(all_reserved_bookings.mapped('guest_count'))

        for record in self:
            record.total_seating_units = total_units
            record.reserved_units = reserved_count
            record.available_units = available_count
            record.active_bookings = reserved_count
            record.active_booking_guests = total_guests

    # -------------------------------------------------------------------------
    # Financial KPI compute — manager only, enforced server-side
    # -------------------------------------------------------------------------
    def _compute_financial_metrics(self):
        is_manager = self.env.user.has_group('pearl_checkin.group_pearl_manager')
        currency = self.env.company.currency_id

        for record in self:
            if not is_manager:
                # Non-managers receive zeroes; display is hidden in XML too
                record.contracted_booking_value = 0.0
                record.recorded_collections = 0.0
                record.outstanding_balances = 0.0
                record.bookings_unpaid_count = 0
                record.bookings_partial_count = 0
                record.bookings_paid_count = 0
                continue

            start, end = record._get_range_boundaries()

            # Contracted Booking Value: sum of amount_total for bookings
            # reserved within the date range (reserved_datetime basis)
            Booking = self.env['pearl.booking']
            range_bookings = Booking.search([
                ('reserved_datetime', '>=', start),
                ('reserved_datetime', '<=', end),
            ])
            contracted_value = currency.round(sum(range_bookings.mapped('amount_total')))

            # Recorded Collections: sum of payment amounts within the date range
            Payment = self.env['pearl.booking.payment']
            range_payments = Payment.search([
                ('payment_datetime', '>=', start),
                ('payment_datetime', '<=', end),
            ])
            collections = currency.round(sum(range_payments.mapped('amount')))

            # Outstanding Balances: ALL bookings (any state) with amount_due > 0
            outstanding_bookings = Booking.search([('amount_due', '>', 0)])
            outstanding = currency.round(sum(outstanding_bookings.mapped('amount_due')))

            # Payment status breakdown within range
            unpaid_count = len(range_bookings.filtered(lambda b: b.payment_status == 'unpaid'))
            partial_count = len(range_bookings.filtered(lambda b: b.payment_status == 'partial'))
            paid_count = len(range_bookings.filtered(lambda b: b.payment_status == 'paid'))

            record.contracted_booking_value = contracted_value
            record.recorded_collections = collections
            record.outstanding_balances = outstanding
            record.bookings_unpaid_count = unpaid_count
            record.bookings_partial_count = partial_count
            record.bookings_paid_count = paid_count

    # -------------------------------------------------------------------------
    # @api.model method: get_executive_dashboard_data (called from dashboard form)
    # -------------------------------------------------------------------------
    @api.model
    def get_executive_dashboard_data(self, date_filter='this_month', date_from=None, date_to=None):
        """
        Server-side method returning structured dashboard data.
        Financial data is returned only for managers.
        Receptionists receive operational data only.
        """
        is_manager = self.env.user.has_group('pearl_checkin.group_pearl_manager')

        # Parse custom date range
        if date_filter == 'custom' and date_from and date_to:
            try:
                from odoo.tools import date_utils
                df = fields.Date.from_string(date_from)
                dt = fields.Date.from_string(date_to)
            except Exception:
                df = dt = fields.Date.today()
        else:
            df = dt = None

        start, end = self._get_range_boundaries_for(date_filter, date_from=df, date_to=dt)

        Visit = self.env['pearl.visit']
        Unit = self.env['pearl.seating.unit']
        Booking = self.env['pearl.booking']
        currency = self.env.company.currency_id

        # --- Visitor KPIs ---
        today = fields.Date.today()
        today_start = datetime.combine(today, time.min)
        today_end = datetime.combine(today, time.max)

        today_visits = Visit.search([
            ('check_in_datetime', '>=', today_start),
            ('check_in_datetime', '<=', today_end),
            ('state', '=', 'checked_in'),
        ])
        range_visits = Visit.search([
            ('check_in_datetime', '>=', start),
            ('check_in_datetime', '<=', end),
            ('state', '=', 'checked_in'),
        ])

        # --- Seating KPIs ---
        all_active_units = Unit.search([('active', '=', True)])
        all_reserved_bookings = Booking.search([
            ('state', '=', 'reserved'),
            ('unit_id', 'in', all_active_units.ids if all_active_units else [0]),
        ])
        total_units = len(all_active_units)
        reserved_count = len(all_reserved_bookings)
        available_count = max(0, total_units - reserved_count)
        total_guests = sum(all_reserved_bookings.mapped('guest_count'))

        # --- Booking distribution by area ---
        area_distribution = []
        areas = self.env['pearl.seating.area'].search([('active', '=', True)])
        for area in areas:
            area_bookings = all_reserved_bookings.filtered(lambda b: b.area_id.id == area.id)
            if area_bookings:
                area_distribution.append({
                    'area': area.name,
                    'count': len(area_bookings),
                    'guests': sum(area_bookings.mapped('guest_count')),
                })

        # --- Booking distribution by seating type ---
        type_distribution = []
        seating_types = self.env['pearl.seating.type'].search(
            [('active', '=', True)],
            order='sequence, name, id',
        )
        for seating_type in seating_types:
            type_bookings = all_reserved_bookings.filtered(
                lambda booking: booking.seating_type == seating_type.code
            )
            if type_bookings:
                type_distribution.append({
                    'type': seating_type.code,
                    'label': seating_type.name,
                    'count': len(type_bookings),
                    'guests': sum(type_bookings.mapped('guest_count')),
                })

        result = {
            'visitor_kpis': {
                'checkins_today': len(today_visits),
                'new_today': len(today_visits.filtered(lambda v: v.visitor_type == 'new')),
                'returning_today': len(today_visits.filtered(lambda v: v.visitor_type == 'returning')),
                'visits_in_range': len(range_visits),
                'new_in_range': len(range_visits.filtered(lambda v: v.visitor_type == 'new')),
                'returning_in_range': len(range_visits.filtered(lambda v: v.visitor_type == 'returning')),
            },
            'seating_kpis': {
                'total_units': total_units,
                'reserved_units': reserved_count,
                'available_units': available_count,
                'active_bookings': reserved_count,
                'active_booking_guests': total_guests,
                'area_distribution': area_distribution,
                'type_distribution': type_distribution,
            },
            'is_manager': is_manager,
            'financial_kpis': None,
            'date_filter': date_filter,
            'currency_symbol': currency.symbol or '₦',
        }

        if is_manager:
            # Contracted Booking Value
            range_bookings = Booking.search([
                ('reserved_datetime', '>=', start),
                ('reserved_datetime', '<=', end),
            ])
            contracted_value = currency.round(sum(range_bookings.mapped('amount_total')))

            # Recorded Collections
            Payment = self.env['pearl.booking.payment']
            range_payments = Payment.search([
                ('payment_datetime', '>=', start),
                ('payment_datetime', '<=', end),
            ])
            collections = currency.round(sum(range_payments.mapped('amount')))

            # Outstanding Balances (all time, all states with balance)
            outstanding_bookings = Booking.search([('amount_due', '>', 0)])
            outstanding = currency.round(sum(outstanding_bookings.mapped('amount_due')))

            # Payment status breakdown (within range)
            unpaid_count = len(range_bookings.filtered(lambda b: b.payment_status == 'unpaid'))
            partial_count = len(range_bookings.filtered(lambda b: b.payment_status == 'partial'))
            paid_count = len(range_bookings.filtered(lambda b: b.payment_status == 'paid'))

            result['financial_kpis'] = {
                'contracted_booking_value': contracted_value,
                'recorded_collections': collections,
                'outstanding_balances': outstanding,
                'bookings_unpaid_count': unpaid_count,
                'bookings_partial_count': partial_count,
                'bookings_paid_count': paid_count,
                'currency_symbol': currency.symbol or '₦',
            }

        return result

    # -------------------------------------------------------------------------
    # Existing action methods (unchanged)
    # -------------------------------------------------------------------------
    def action_refresh_metrics(self):
        """Action button to trigger a recalculation and refresh of dashboard metrics."""
        self._compute_metrics()
        return True

    @api.model
    def action_open_dashboard(self):
        """Opens or initializes the singleton dashboard overview."""
        record = self.search([], limit=1)
        if not record:
            record = self.create({'name': 'Pearl Restaurant Overview'})
        return {
            'name': _('Management Dashboard'),
            'type': 'ir.actions.act_window',
            'res_model': 'pearl.dashboard',
            'res_id': record.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_view_visitors(self):
        action = self.env['ir.actions.act_window']._for_xml_id('pearl_checkin.action_pearl_visitor')
        return action

    def action_view_today_checkins(self):
        action = self.env['ir.actions.act_window']._for_xml_id('pearl_checkin.action_pearl_visit')
        action['context'] = {'search_default_filter_today': 1}
        return action

    def action_view_today_new(self):
        action = self.env['ir.actions.act_window']._for_xml_id('pearl_checkin.action_pearl_visit')
        action['context'] = {'search_default_filter_today': 1, 'search_default_filter_new_visitors': 1}
        return action

    def action_view_today_returning(self):
        action = self.env['ir.actions.act_window']._for_xml_id('pearl_checkin.action_pearl_visit')
        action['context'] = {'search_default_filter_today': 1, 'search_default_filter_returning_visitors': 1}
        return action

    def action_view_this_week_checkins(self):
        action = self.env['ir.actions.act_window']._for_xml_id('pearl_checkin.action_pearl_visit')
        action['context'] = {'search_default_filter_this_week': 1}
        return action

    def action_view_this_month_checkins(self):
        action = self.env['ir.actions.act_window']._for_xml_id('pearl_checkin.action_pearl_visit')
        action['context'] = {'search_default_filter_this_month': 1}
        return action

    def action_open_checkin_wizard(self):
        return {
            'name': _('Front-Desk Check-in'),
            'type': 'ir.actions.act_window',
            'res_model': 'pearl.checkin.wizard',
            'view_mode': 'form',
            'target': 'new',
        }

    def action_open_reporting(self):
        return self.env['ir.actions.act_window']._for_xml_id('pearl_checkin.action_pearl_visit_reporting')

    def action_view_bookings(self):
        return self.env['ir.actions.act_window']._for_xml_id('pearl_checkin.action_pearl_booking')

    def action_view_booking_reporting(self):
        return self.env['ir.actions.act_window']._for_xml_id('pearl_checkin.action_pearl_booking_reporting')

    def action_view_payment_reporting(self):
        """Financial Collections — manager only."""
        if not self.env.user.has_group('pearl_checkin.group_pearl_manager'):
            raise AccessError(_("Access to financial reports is restricted to managers."))
        return self.env['ir.actions.act_window']._for_xml_id('pearl_checkin.action_pearl_payment_reporting')

    def action_view_receivables(self):
        """Outstanding Receivables — manager only."""
        if not self.env.user.has_group('pearl_checkin.group_pearl_manager'):
            raise AccessError(_("Access to financial reports is restricted to managers."))
        return self.env['ir.actions.act_window']._for_xml_id('pearl_checkin.action_pearl_booking_receivables')

    def action_view_reserved_bookings(self):
        """Open the bookings list filtered to currently reserved state."""
        action = self.env['ir.actions.act_window']._for_xml_id('pearl_checkin.action_pearl_booking')
        action['domain'] = [('state', '=', 'reserved')]
        action['display_name'] = _('Active Reservations')
        return action

    def action_view_seating_management(self):
        return {
            'type': 'ir.actions.client',
            'tag': 'pearl_seating_dashboard',
            'name': _('Seating Management'),
        }

    def action_apply_date_filter(self):
        """Reload the dashboard form after applying a date filter change."""
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'pearl.dashboard',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'current',
        }
