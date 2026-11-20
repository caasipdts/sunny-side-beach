# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class SunnysideSeatingArea(models.Model):
    _name = 'sunnyside.seating.area'
    _description = 'Sunnyside Beach Seating Area'
    _order = 'sequence, name, id'

    name = fields.Char(
        string='Area Name',
        required=True,
        help='Physical beach area or zone name (e.g. VIP Cabanas, Beachfront, Main Deck).',
    )
    sequence = fields.Integer(
        string='Sequence',
        default=10,
        help='Display order of seating areas.',
    )
    active = fields.Boolean(
        string='Active',
        default=True,
        help='Archive state for the seating area.',
    )
    background_image = fields.Image(
        string='Background Image',
        help='Optional layout background map or overhead photo for future visual seating map.',
    )
    background_color = fields.Char(
        string='Background Color',
        help='Optional hex or CSS color representation for the area.',
    )
    unit_ids = fields.One2many(
        'sunnyside.seating.unit',
        'area_id',
        string='Seating Units',
    )


class SunnysideSeatingUnit(models.Model):
    _name = 'sunnyside.seating.unit'
    _description = 'Sunnyside Beach Seating Unit'
    _order = 'area_id, sequence, name, id'

    name = fields.Char(
        string='Unit Name / Identifier',
        required=True,
        help='Name or label of the table, beachfront seat, or cabana (e.g. Cabana 1, Table 4, Sunbed 12).',
    )
    area_id = fields.Many2one(
        'sunnyside.seating.area',
        string='Seating Area',
        required=True,
        ondelete='restrict',
        index=True,
    )
    active = fields.Boolean(
        string='Active',
        default=True,
        help='Archive state for the seating unit.',
    )
    seating_type = fields.Selection(
        selection=[
            ('table', 'Standard Table'),
            ('beachfront_seat', 'Beachfront Seat'),
            ('cabana', 'Cabana'),
        ],
        string='Seating Type',
        required=True,
        default='table',
        index=True,
    )
    capacity_min = fields.Integer(
        string='Minimum Capacity',
        required=True,
        default=1,
        help='Minimum permitted guest count for this unit.',
    )
    capacity_max = fields.Integer(
        string='Maximum Capacity',
        required=True,
        default=4,
        help='Maximum permitted guest count for this unit.',
    )
    pricing_mode = fields.Selection(
        selection=[
            ('per_guest', 'Per Guest'),
            ('fixed', 'Fixed'),
        ],
        string='Pricing Mode',
        required=True,
        default='per_guest',
        help='Whether pricing multiplies per guest or is a fixed package amount.',
    )
    price_per_guest = fields.Monetary(
        string='Price Per Guest',
        currency_field='currency_id',
        default=20000.0,
        help='Rate charged per guest for per-guest seating units.',
    )
    fixed_price = fields.Monetary(
        string='Fixed Price',
        currency_field='currency_id',
        default=0.0,
        help='Flat inclusive rate charged for fixed-price seating units (e.g. cabana).',
    )
    entry_fee_amount = fields.Monetary(
        string='Entry Fee Component (per guest)',
        currency_field='currency_id',
        default=5000.0,
        help='Entry fee portion included in the per-guest price.',
    )
    minimum_spend_amount = fields.Monetary(
        string='Minimum Spend Component (per guest)',
        currency_field='currency_id',
        default=15000.0,
        help='Minimum spend portion included in the per-guest price.',
    )
    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        required=True,
        default=lambda self: self.env.company.currency_id,
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
    )
    sequence = fields.Integer(
        string='Sequence',
        default=10,
    )
    position_x = fields.Integer(
        string='Position X',
        help='Optional horizontal coordinate on layout background.',
    )
    position_y = fields.Integer(
        string='Position Y',
        help='Optional vertical coordinate on layout background.',
    )
    width = fields.Integer(
        string='Width',
        help='Optional width dimension on layout display.',
    )
    height = fields.Integer(
        string='Height',
        help='Optional height dimension on layout display.',
    )
    color = fields.Char(
        string='Display Color',
        help='Optional display color code.',
    )
    image_ids = fields.One2many(
        'sunnyside.seating.image',
        'unit_id',
        string='Photographs',
    )
    booking_ids = fields.One2many(
        'sunnyside.booking',
        'unit_id',
        string='Bookings',
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            stype = vals.get('seating_type', 'table')
            if stype == 'table':
                vals.setdefault('capacity_min', 1)
                vals.setdefault('capacity_max', 4)
                vals.setdefault('pricing_mode', 'per_guest')
                vals.setdefault('price_per_guest', 20000.0)
                vals.setdefault('entry_fee_amount', 5000.0)
                vals.setdefault('minimum_spend_amount', 15000.0)
                vals.setdefault('fixed_price', 0.0)
            elif stype == 'beachfront_seat':
                vals.setdefault('capacity_min', 1)
                vals.setdefault('capacity_max', 1)
                vals.setdefault('pricing_mode', 'per_guest')
                vals.setdefault('price_per_guest', 20000.0)
                vals.setdefault('entry_fee_amount', 5000.0)
                vals.setdefault('minimum_spend_amount', 15000.0)
                vals.setdefault('fixed_price', 0.0)
            elif stype == 'cabana':
                vals.setdefault('capacity_min', 1)
                vals.setdefault('capacity_max', 9)
                vals.setdefault('pricing_mode', 'fixed')
                vals.setdefault('fixed_price', 250000.0)
                vals.setdefault('price_per_guest', 0.0)
                vals.setdefault('entry_fee_amount', 0.0)
                vals.setdefault('minimum_spend_amount', 0.0)
        return super().create(vals_list)

    @api.onchange('seating_type')
    def _onchange_seating_type_defaults(self):
        """Set approved business configuration defaults when seating_type changes."""
        if self.seating_type == 'table':
            self.capacity_min = 1
            self.capacity_max = 4
            self.pricing_mode = 'per_guest'
            self.price_per_guest = 20000.0
            self.entry_fee_amount = 5000.0
            self.minimum_spend_amount = 15000.0
            self.fixed_price = 0.0
        elif self.seating_type == 'beachfront_seat':
            self.capacity_min = 1
            self.capacity_max = 1
            self.pricing_mode = 'per_guest'
            self.price_per_guest = 20000.0
            self.entry_fee_amount = 5000.0
            self.minimum_spend_amount = 15000.0
            self.fixed_price = 0.0
        elif self.seating_type == 'cabana':
            self.capacity_min = 1
            self.capacity_max = 9
            self.pricing_mode = 'fixed'
            self.fixed_price = 250000.0
            self.price_per_guest = 0.0
            self.entry_fee_amount = 0.0
            self.minimum_spend_amount = 0.0

    @api.constrains('capacity_min', 'capacity_max', 'seating_type')
    def _check_capacities(self):
        for unit in self:
            if unit.capacity_min < 1:
                raise ValidationError(_("Minimum capacity must be at least 1 guest."))
            if unit.capacity_max < unit.capacity_min:
                raise ValidationError(_("Maximum capacity cannot be lower than minimum capacity."))

            if unit.seating_type == 'table':
                if unit.capacity_max > 4:
                    raise ValidationError(_("Standard table capacity cannot exceed 4 guests."))
            elif unit.seating_type == 'beachfront_seat':
                if unit.capacity_min != 1 or unit.capacity_max != 1:
                    raise ValidationError(_("Beachfront seat capacity must be exactly 1 guest."))
            elif unit.seating_type == 'cabana':
                if unit.capacity_max > 9:
                    raise ValidationError(_("Cabana capacity cannot exceed 9 guests."))

    @api.constrains('pricing_mode', 'price_per_guest', 'fixed_price', 'entry_fee_amount', 'minimum_spend_amount')
    def _check_pricing_values(self):
        for unit in self:
            if unit.price_per_guest < 0:
                raise ValidationError(_("Price per guest cannot be negative."))
            if unit.fixed_price < 0:
                raise ValidationError(_("Fixed price cannot be negative."))
            if unit.entry_fee_amount < 0:
                raise ValidationError(_("Entry fee amount cannot be negative."))
            if unit.minimum_spend_amount < 0:
                raise ValidationError(_("Minimum spend amount cannot be negative."))

            if unit.pricing_mode == 'fixed':
                if unit.fixed_price <= 0:
                    raise ValidationError(_("A fixed-price seating unit must have a positive fixed price."))
            elif unit.pricing_mode == 'per_guest':
                if unit.price_per_guest <= 0:
                    raise ValidationError(_("A per-guest seating unit must have a positive price per guest."))

    # -------------------------------------------------------------------------
    # Stage 5: Backend methods for Visual Seating Dashboard
    # -------------------------------------------------------------------------
    @api.model
    def get_dashboard_data(self, area_id=None):
        """
        Return structured live seating data and metrics for the OWL dashboard.
        Authoritative server-side availability:
        - Unit is available if active and has no booking with state='reserved'.
        - Released bookings do NOT count as active reservations.
        """
        currency = self.env.company.currency_id

        # 1. Active Areas
        Area = self.env['sunnyside.seating.area']
        all_areas = Area.search([('active', '=', True)], order='sequence, name, id')
        areas_data = [{
            'id': a.id,
            'name': a.name,
            'sequence': a.sequence,
            'color': a.background_color or '#0284c7',
        } for a in all_areas]

        # 2. Active Units
        domain = [('active', '=', True)]
        if area_id:
            domain.append(('area_id', '=', int(area_id)))
        active_units = self.search(domain, order='area_id, sequence, name, id')

        # 3. Active Reserved Bookings
        Booking = self.env['sunnyside.booking']
        reserved_bookings = Booking.search([
            ('state', '=', 'reserved'),
            ('unit_id', 'in', active_units.ids if active_units else [0]),
        ])
        booking_by_unit = {b.unit_id.id: b for b in reserved_bookings}

        # 4. Units Data
        units_data = []
        for u in active_units:
            booking = booking_by_unit.get(u.id)
            is_reserved = bool(booking)
            booking_info = None

            if booking:
                payments_data = [{
                    'id': p.id,
                    'amount': p.amount,
                    'payment_method': p.payment_method,
                    'payment_method_label': dict(p._fields['payment_method'].selection).get(p.payment_method, p.payment_method),
                    'reference': p.reference or '',
                    'payment_datetime': fields.Datetime.to_string(p.payment_datetime) if p.payment_datetime else '',
                    'user_name': p.user_id.name or '',
                } for p in booking.payment_ids]

                booking_info = {
                    'id': booking.id,
                    'name': booking.name,
                    'visitor_id': booking.visitor_id.id if booking.visitor_id else False,
                    'visitor_name': booking.visitor_id.name if booking.visitor_id else '',
                    'visitor_phone': booking.visitor_id.phone or '',
                    'visit_id': booking.visit_id.id if booking.visit_id else False,
                    'visit_name': booking.visit_id.name if booking.visit_id else '',
                    'visit_check_in': fields.Datetime.to_string(booking.visit_id.check_in_datetime) if booking.visit_id and booking.visit_id.check_in_datetime else '',
                    'guest_count': booking.guest_count,
                    'seating_type': booking.seating_type,
                    'pricing_mode': booking.pricing_mode,
                    'unit_price': booking.unit_price,
                    'entry_fee_amount': booking.entry_fee_amount,
                    'minimum_spend_amount': booking.minimum_spend_amount,
                    'amount_total': booking.amount_total,
                    'amount_paid': booking.amount_paid,
                    'amount_due': booking.amount_due,
                    'payment_status': booking.payment_status,
                    'state': booking.state,
                    'reserved_datetime': fields.Datetime.to_string(booking.reserved_datetime) if booking.reserved_datetime else '',
                    'reserved_by_name': booking.reserved_by_id.name if booking.reserved_by_id else '',
                    'payments': payments_data,
                }

            # Photograph if available
            image_url = False
            try:
                first_img = u.image_ids[:1]
                if first_img:
                    image_url = f"/web/image/sunnyside.seating.image/{first_img.id}/image"
            except Exception:
                image_url = False

            units_data.append({
                'id': u.id,
                'name': u.name,
                'area_id': u.area_id.id,
                'area_name': u.area_id.name,
                'seating_type': u.seating_type,
                'seating_type_label': dict(u._fields['seating_type'].selection).get(u.seating_type, u.seating_type),
                'capacity_min': u.capacity_min,
                'capacity_max': u.capacity_max,
                'pricing_mode': u.pricing_mode,
                'price_per_guest': u.price_per_guest,
                'fixed_price': u.fixed_price,
                'entry_fee_amount': u.entry_fee_amount,
                'minimum_spend_amount': u.minimum_spend_amount,
                'active': u.active,
                'is_reserved': is_reserved,
                'image_url': image_url,
                'booking': booking_info,
            })

        # 5. Global Summary Metrics (calculated from all active units across all areas)
        all_active_units = self.search([('active', '=', True)])
        all_reserved_count = Booking.search_count([
            ('state', '=', 'reserved'),
            ('unit_id', 'in', all_active_units.ids if all_active_units else [0]),
        ])
        total_units_count = len(all_active_units)
        available_units_count = max(0, total_units_count - all_reserved_count)

        return {
            'metrics': {
                'total_units': total_units_count,
                'available_units': available_units_count,
                'reserved_units': all_reserved_count,
                'total_areas': len(all_areas),
            },
            'areas': areas_data,
            'units': units_data,
            'currency': {
                'id': currency.id,
                'symbol': currency.symbol or '₦',
                'position': currency.position or 'before',
            },
        }

    @api.model
    def get_checked_in_visits(self, search_query=None, visitor_id=None):
        """
        Return checked-in visits eligible for seating assignment.
        Visits with an existing active reserved booking are excluded.
        """
        Visit = self.env['sunnyside.visit']
        Booking = self.env['sunnyside.booking']

        # Visits currently having an active reservation
        reserved_visit_ids = Booking.search([
            ('state', '=', 'reserved')
        ]).mapped('visit_id.id')

        domain = [
            ('state', '=', 'checked_in'),
            ('id', 'not in', reserved_visit_ids if reserved_visit_ids else [0]),
        ]

        if visitor_id:
            domain.append(('visitor_id', '=', int(visitor_id)))

        if search_query and search_query.strip():
            q = search_query.strip()
            domain += ['|', '|',
                ('name', 'ilike', q),
                ('visitor_id.name', 'ilike', q),
                ('visitor_id.phone', 'ilike', q),
            ]

        eligible_visits = Visit.search(domain, order='check_in_datetime desc', limit=50)

        return [{
            'id': v.id,
            'name': v.name,
            'visitor_id': v.visitor_id.id if v.visitor_id else False,
            'visitor_name': v.visitor_id.name if v.visitor_id else '',
            'visitor_phone': v.visitor_id.phone or '',
            'check_in_datetime': fields.Datetime.to_string(v.check_in_datetime) if v.check_in_datetime else '',
            'location_name': v.location_id.name if v.location_id else '',
            'visitor_type': v.visitor_type,
        } for v in eligible_visits]

    @api.model
    def create_dashboard_booking(self, visit_id, unit_id, guest_count, payment_amount=0.0, payment_method='cash', payment_reference=False):
        """
        Atomic booking and optional payment creation endpoint for the seating dashboard.
        Delegates authoritative pricing snapshot to Booking.create_booking()
        and payment capture to Booking.record_payment().
        """
        Booking = self.env['sunnyside.booking']

        # Server-side validation
        if not visit_id:
            raise ValidationError(_("A valid checked-in visit is required."))
        if not unit_id:
            raise ValidationError(_("A seating unit must be selected."))

        guest_count = int(guest_count) if guest_count else 1
        if guest_count < 1:
            raise ValidationError(_("Guest count must be at least 1."))

        booking = Booking.create_booking(
            visit_id=int(visit_id),
            unit_id=int(unit_id),
            guest_count=guest_count,
        )

        currency = booking.currency_id or self.env.company.currency_id
        amount = currency.round(float(payment_amount or 0.0))

        if amount > 0:
            booking.record_payment(
                amount=amount,
                payment_method=payment_method or 'cash',
                reference=(payment_reference or '').strip() or False,
            )

        return {
            'success': True,
            'booking_id': booking.id,
            'booking_name': booking.name,
            'amount_total': booking.amount_total,
            'amount_paid': booking.amount_paid,
            'amount_due': booking.amount_due,
            'payment_status': booking.payment_status,
        }

    @api.model
    def record_dashboard_payment(self, booking_id, amount, payment_method, reference=False):
        """Record a payment from the seating dashboard."""
        Booking = self.env['sunnyside.booking']
        booking = Booking.browse(int(booking_id))
        if not booking.exists():
            raise ValidationError(_("The specified booking does not exist."))

        payment = booking.record_payment(
            amount=float(amount),
            payment_method=payment_method,
            reference=reference,
        )

        return {
            'success': True,
            'payment_id': payment.id,
            'amount_paid': booking.amount_paid,
            'amount_due': booking.amount_due,
            'payment_status': booking.payment_status,
        }

    @api.model
    def release_dashboard_booking(self, booking_id):
        """Release a reservation from the seating dashboard."""
        Booking = self.env['sunnyside.booking']
        booking = Booking.browse(int(booking_id))
        if not booking.exists():
            raise ValidationError(_("The specified booking does not exist."))

        booking.action_release()
        return {
            'success': True,
            'message': _("Reservation %s released successfully.") % booking.name,
        }


class SunnysideSeatingImage(models.Model):
    _name = 'sunnyside.seating.image'
    _description = 'Sunnyside Beach Seating Photograph'
    _order = 'sequence, id'

    name = fields.Char(
        string='Image Description',
        required=True,
    )
    unit_id = fields.Many2one(
        'sunnyside.seating.unit',
        string='Seating Unit',
        required=True,
        ondelete='cascade',
        index=True,
    )
    sequence = fields.Integer(
        string='Sequence',
        default=10,
    )
    image = fields.Image(
        string='Photograph',
        required=True,
    )

