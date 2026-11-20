# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError
from odoo.addons.sunnyside_visitor_management.controllers.visitor import (
    normalize_phone,
    SunnysideVisitorController,
    PRIVACY_NOTICE_VERSION,
)


class SunnysideCheckinWizard(models.TransientModel):
    _name = 'sunnyside.checkin.wizard'
    _description = 'Receptionist-Assisted Visitor Check-in Wizard'

    # -------------------------------------------------------------------------
    # Existing Visitor-identification fields (unchanged)
    # -------------------------------------------------------------------------
    phone = fields.Char(
        string='Phone Number',
        required=True,
        help='Enter visitor phone number (e.g. 0803 123 4567).',
    )
    country_dial_code = fields.Char(
        string='Dialing Code',
        default='234',
        required=True,
        help='Country international dialing code (default Nigeria +234).',
    )
    visitor_id = fields.Many2one(
        'res.partner',
        string='Matched Visitor',
        readonly=True,
    )
    is_existing_visitor = fields.Boolean(
        string='Existing Visitor',
        default=False,
    )
    name = fields.Char(
        string='Full Name',
        help='Required for new guest registration.',
    )
    location_id = fields.Many2one(
        'sunnyside.location',
        string='Neighbourhood / Location',
        domain="[('active', '=', True)]",
        help='Home neighbourhood or recorded area.',
    )
    visitor_status_banner = fields.Html(
        string='Guest Status',
        readonly=True,
    )
    source = fields.Selection(
        selection=[
            ('qr_code', 'QR Code'),
            ('website', 'Website'),
            ('receptionist', 'Receptionist'),
        ],
        string='Check-in Source',
        default='receptionist',
        readonly=True,
        required=True,
    )

    # -------------------------------------------------------------------------
    # Seating Assignment fields
    # -------------------------------------------------------------------------
    seating_area_id = fields.Many2one(
        'sunnyside.seating.area',
        string='Seating Area',
        domain="[('active', '=', True)]",
        help='Select the beach zone for seating assignment (optional).',
    )
    seating_unit_id = fields.Many2one(
        'sunnyside.seating.unit',
        string='Seating Unit',
        domain="[('active', '=', True), ('area_id', '=', seating_area_id)]",
        help='Select the specific table, beachfront seat, or cabana. '
             'Only active units not currently reserved are displayed.',
    )
    guest_count = fields.Integer(
        string='Guest Count',
        default=1,
        help='Number of guests occupying the selected seating unit.',
    )

    # Informational price preview — the booking model is authoritative
    estimated_price = fields.Monetary(
        string='Estimated Booking Price',
        currency_field='currency_id',
        readonly=True,
        help='Server-calculated booking price for the selected unit and guest count. '
             'The booking model enforces the final price.',
    )
    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        default=lambda self: self.env.company.currency_id,
        readonly=True,
    )

    # -------------------------------------------------------------------------
    # Payment capture fields
    # -------------------------------------------------------------------------
    payment_amount = fields.Monetary(
        string='Amount Paid',
        currency_field='currency_id',
        default=0.0,
        help='Amount received now. Zero means no payment is recorded today.',
    )
    payment_method = fields.Selection(
        selection=[
            ('cash', 'Cash'),
            ('bank_card', 'Bank Card'),
            ('bank_transfer', 'Bank Transfer'),
            ('other', 'Other'),
        ],
        string='Payment Method',
        default='cash',
        help='Method of payment received at the front desk.',
    )
    payment_reference = fields.Char(
        string='Payment Reference',
        help='Optional receipt number, POS reference, or bank transaction ID.',
    )
    estimated_outstanding = fields.Monetary(
        string='Outstanding Amount',
        currency_field='currency_id',
        compute='_compute_estimated_outstanding',
        help='Remaining amount after the payment captured above.',
    )

    # -------------------------------------------------------------------------
    # Computed helpers
    # -------------------------------------------------------------------------
    @api.depends('estimated_price', 'payment_amount')
    def _compute_estimated_outstanding(self):
        for wizard in self:
            currency = wizard.currency_id or self.env.company.currency_id
            price = currency.round(wizard.estimated_price or 0.0)
            paid = currency.round(wizard.payment_amount or 0.0)
            wizard.estimated_outstanding = max(0.0, currency.round(price - paid))

    # -------------------------------------------------------------------------
    # Existing phone-lookup onchange (preserved verbatim)
    # -------------------------------------------------------------------------
    @api.onchange('phone', 'country_dial_code')
    def _onchange_phone_lookup(self):
        """Performs real-time server-side phone lookup as receptionist types."""
        if not self.phone:
            self.visitor_id = False
            self.is_existing_visitor = False
            self.name = ''
            self.location_id = False
            self.visitor_status_banner = False
            return

        is_valid, e164, variants, err = normalize_phone(self.phone, self.country_dial_code or '234')
        if not is_valid:
            self.visitor_id = False
            self.is_existing_visitor = False
            self.visitor_status_banner = (
                f"<div class='alert alert-secondary py-2 px-3 mb-0'>"
                f"<i class='fa fa-phone me-2'></i>{err or _('Please enter a valid phone number.')}</div>"
            )
            return

        Partner = self.env['res.partner']
        if 'mobile' in Partner._fields:
            domain = ['|', ('phone', 'in', list(variants)), ('mobile', 'in', list(variants))]
        else:
            domain = [('phone', 'in', list(variants))]

        existing = Partner.search(domain, limit=1)
        if existing:
            self.visitor_id = existing.id
            self.is_existing_visitor = True
            self.name = existing.name
            self.location_id = existing.sunnyside_location_id.id if existing.sunnyside_location_id else False
            visit_count = existing.sunnyside_visit_count
            self.visitor_status_banner = (
                f"<div class='alert alert-info py-2 px-3 mb-0'>"
                f"<i class='fa fa-user me-2'></i>"
                f"<strong>Returning Guest Found:</strong> {existing.name} "
                f"<span class='badge bg-primary ms-2'>{visit_count} past visits</span>"
                f"<br/><small class='text-muted'>Click 'Confirm Check-in' to record visit #{visit_count + 1}.</small>"
                f"</div>"
            )
        else:
            self.visitor_id = False
            self.is_existing_visitor = False
            self.name = ''
            self.location_id = False
            self.visitor_status_banner = (
                f"<div class='alert alert-warning py-2 px-3 mb-0'>"
                f"<i class='fa fa-user-plus me-2'></i>"
                f"<strong>New Visitor:</strong> No previous profile matches this number. "
                f"Please enter the guest's <strong>Full Name</strong> and <strong>Neighbourhood</strong> below."
                f"</div>"
            )

    # -------------------------------------------------------------------------
    # Seating onchange: clear incompatible unit when area changes
    # -------------------------------------------------------------------------
    @api.onchange('seating_area_id')
    def _onchange_seating_area(self):
        """Clear unit selection when area changes to avoid cross-area mismatches."""
        if self.seating_unit_id and self.seating_unit_id.area_id != self.seating_area_id:
            self.seating_unit_id = False
        self.estimated_price = 0.0
        self.estimated_outstanding = 0.0

    @api.onchange('seating_unit_id', 'guest_count')
    def _onchange_seating_unit(self):
        """Recalculate estimated price preview when unit or guest count changes."""
        unit = self.seating_unit_id
        if not unit:
            self.estimated_price = 0.0
            return

        # Sync area
        if unit.area_id:
            self.seating_area_id = unit.area_id

        currency = unit.currency_id or self.env.company.currency_id
        self.currency_id = currency
        guest_count = max(1, self.guest_count or 1)

        if unit.pricing_mode == 'fixed':
            rate = unit.fixed_price if unit.fixed_price > 0 else 250000.0
            self.estimated_price = currency.round(rate)
        else:
            rate = unit.price_per_guest if unit.price_per_guest > 0 else 20000.0
            self.estimated_price = currency.round(rate * guest_count)

    # -------------------------------------------------------------------------
    # Payment amount guard: cap display at estimated_price
    # -------------------------------------------------------------------------
    @api.onchange('payment_amount')
    def _onchange_payment_amount(self):
        """Soft UI guard: warn if payment would exceed estimated price."""
        currency = self.currency_id or self.env.company.currency_id
        amount = self.payment_amount or 0.0
        price = self.estimated_price or 0.0
        if amount < 0:
            self.payment_amount = 0.0
        elif price > 0 and currency.compare_amounts(amount, price) > 0:
            # Reset to full price so user can see the cap; hard validation is in action_confirm_checkin
            self.payment_amount = price

    # -------------------------------------------------------------------------
    #Server-side validation helpers
    # -------------------------------------------------------------------------
    def _validate_seating_selection(self):
        """Validate the optional seating selection before proceeding."""
        self.ensure_one()
        unit = self.seating_unit_id
        if not unit:
            return  # Seating is optional; skip

        if not unit.active:
            raise ValidationError(
                _("The selected seating unit '%s' is no longer active.") % unit.name
            )

        # Check unit belongs to the selected area (belt-and-suspenders)
        if self.seating_area_id and unit.area_id != self.seating_area_id:
            raise ValidationError(
                _("Seating unit '%s' does not belong to the selected area.") % unit.name
            )

        guest_count = self.guest_count if self.guest_count is not None else 1
        if guest_count < 1:
            raise ValidationError(_("Guest count must be at least 1."))

        if unit.capacity_min and guest_count < unit.capacity_min:
            raise ValidationError(
                _("Guest count %(count)s is below the minimum capacity %(min)s for %(unit)s.") % {
                    'count': guest_count, 'min': unit.capacity_min, 'unit': unit.name,
                }
            )
        if unit.capacity_max and guest_count > unit.capacity_max:
            raise ValidationError(
                _("Guest count %(count)s exceeds the maximum capacity %(max)s for %(unit)s.") % {
                    'count': guest_count, 'max': unit.capacity_max, 'unit': unit.name,
                }
            )
        if unit.seating_type == 'table' and guest_count > 4:
            raise ValidationError(_("Standard tables cannot accommodate more than 4 guests."))
        if unit.seating_type == 'beachfront_seat' and guest_count != 1:
            raise ValidationError(_("Beachfront seats must have exactly 1 guest."))
        if unit.seating_type == 'cabana' and guest_count > 9:
            raise ValidationError(_("Cabanas cannot accommodate more than 9 guests."))

    def _validate_payment_input(self):
        """Validate the optional payment input before committing."""
        self.ensure_one()
        currency = self.currency_id or self.env.company.currency_id
        amount = currency.round(self.payment_amount or 0.0)

        if currency.compare_amounts(amount, 0.0) < 0:
            raise ValidationError(_("Payment amount cannot be negative."))

        if amount > 0:
            price = currency.round(self.estimated_price or 0.0)
            if price > 0 and currency.compare_amounts(amount, price) > 0:
                raise ValidationError(
                    _("Payment amount %(paid)s exceeds the booking total %(total)s.") % {
                        'paid': currency.format(amount),
                        'total': currency.format(price),
                    }
                )
            # Validate method
            valid_methods = dict(
                self.env['sunnyside.booking.payment']._fields['payment_method'].selection
            )
            if self.payment_method not in valid_methods:
                raise ValidationError(
                    _("Invalid payment method '%s'.") % self.payment_method
                )

    # -------------------------------------------------------------------------
    # Main action extended to cover seating + payment
    # -------------------------------------------------------------------------
    def action_confirm_checkin(self):
        """
        Executes receptionist check-in reusing core business logic,
        advisory transaction locking, CRM integration, and idempotency protection.

        Stage 4 extension:
        - Validates seating selection (optional).
        - Validates payment input (optional).
        - Creates booking via existing SunnysideBooking.create_booking().
        - Records payment via existing SunnysideBooking.record_payment().
        - Returns booking form if a booking was created; otherwise returns visit form.

        The entire operation runs inside a single DB transaction; any failure
        (validation, duplicate booking, payment overage) rolls back everything.
        """
        self.ensure_one()

        # --- Run all wizard-level validation up-front before touching any data ---
        # 1. Normalize phone
        is_valid, e164, variants, err = normalize_phone(self.phone, self.country_dial_code or '234')
        if not is_valid:
            raise ValidationError(err or _('Please enter a valid phone number.'))

        # 2. Seating validation (optional field set)
        self._validate_seating_selection()

        # 3. Payment validation (optional only when amount > 0 and unit selected)
        if self.seating_unit_id:
            self._validate_payment_input()
        elif (self.payment_amount or 0.0) > 0:
            raise ValidationError(
                _("A payment amount was entered but no seating unit is selected. "
                  "Please either select a seating unit or clear the payment amount.")
            )

        # 4. Concurrency lock to prevent duplicate partner creation (unchanged)
        self.env.cr.execute("SELECT pg_advisory_xact_lock(hashtext(%s));", [e164])

        Partner = self.env['res.partner'].sudo()
        if 'mobile' in Partner._fields:
            domain = ['|', ('phone', 'in', list(variants)), ('mobile', 'in', list(variants))]
        else:
            domain = [('phone', 'in', list(variants))]

        visitor = Partner.search(domain, limit=1)
        controller = SunnysideVisitorController()

        if visitor:
            # -----------------------------------------------------------------
            # Existing Visitor Match (unchanged logic)
            # -----------------------------------------------------------------
            if not visitor.is_sunnyside_visitor:
                visitor.write({'is_sunnyside_visitor': True})

            if self.location_id and not visitor.sunnyside_location_id:
                visitor.write({'sunnyside_location_id': self.location_id.id})

            chosen_location = self.location_id or visitor.sunnyside_location_id

            visit = self.env['sunnyside.visit'].sudo().create({
                'visitor_id': visitor.id,
                'location_id': chosen_location.id if chosen_location else False,
                'source': 'receptionist',
                'check_in_datetime': fields.Datetime.now(),
                'state': 'checked_in',
            })

            controller._handle_returning_visitor_crm(visitor, visit, env=self.env)

        else:
            # -----------------------------------------------------------------
            # New Visitor (unchanged logic)
            # -----------------------------------------------------------------
            guest_name = (self.name or '').strip()
            if not guest_name or len(guest_name) < 2:
                raise ValidationError(_("Please enter the visitor's Full Name (at least 2 characters)."))

            if not self.location_id:
                raise ValidationError(_("Please select where the visitor is visiting from."))

            visitor = Partner.create({
                'name': guest_name,
                'phone': e164,
                'is_sunnyside_visitor': True,
                'sunnyside_location_id': self.location_id.id,
                'privacy_acknowledged': True,
                'privacy_acknowledgement_date': fields.Datetime.now(),
                'privacy_notice_version': PRIVACY_NOTICE_VERSION,
            })

            controller._handle_new_visitor_crm(visitor, self.location_id, env=self.env)

            visit = self.env['sunnyside.visit'].sudo().create({
                'visitor_id': visitor.id,
                'location_id': self.location_id.id,
                'source': 'receptionist',
                'check_in_datetime': fields.Datetime.now(),
                'state': 'checked_in',
            })

        # -----------------------------------------------------------------
        # Stage 4: Seating booking (only if a unit was selected)
        # -----------------------------------------------------------------
        booking = None
        if self.seating_unit_id:
            # create_booking() does its own row-level lock + uniqueness check
            booking = self.env['sunnyside.booking'].create_booking(
                visit_id=visit.id,
                unit_id=self.seating_unit_id.id,
                guest_count=self.guest_count if self.guest_count is not None else 1,
            )

            # -----------------------------------------------------------------
            # Stage 4: Payment recording (only when amount > 0 and booking exists)
            # -----------------------------------------------------------------
            currency = booking.currency_id or self.env.company.currency_id
            amount = currency.round(self.payment_amount or 0.0)
            if currency.compare_amounts(amount, 0.0) > 0:
                booking.record_payment(
                    amount=amount,
                    payment_method=self.payment_method or 'cash',
                    reference=(self.payment_reference or '').strip() or False,
                )

        # -----------------------------------------------------------------
        # Return: booking form when booking exists, visit form otherwise
        # -----------------------------------------------------------------
        if booking:
            return {
                'name': _('Booking Confirmed'),
                'type': 'ir.actions.act_window',
                'res_model': 'sunnyside.booking',
                'res_id': booking.id,
                'view_mode': 'form',
                'target': 'current',
            }

        return {
            'name': _('Visit Confirmed'),
            'type': 'ir.actions.act_window',
            'res_model': 'sunnyside.visit',
            'res_id': visit.id,
            'view_mode': 'form',
            'target': 'current',
        }
