# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError, UserError, AccessError
from odoo.tools.sql import create_index

from .seating import seating_type_selection


class PearlBooking(models.Model):
    _name = 'pearl.booking'
    _description = 'Pearl Restaurant Seating Booking'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'reserved_datetime desc, id desc'

    name = fields.Char(
        string='Booking Reference',
        required=True,
        copy=False,
        readonly=True,
        default=lambda self: _('New'),
        index=True,
    )
    visit_id = fields.Many2one(
        'pearl.visit',
        string='Visit',
        required=True,
        ondelete='restrict',
        index=True,
        help='Existing visitor visit check-in record for this booking.',
    )
    visitor_id = fields.Many2one(
        'res.partner',
        related='visit_id.visitor_id',
        string='Visitor',
        readonly=True,
        store=True,
        index=True,
    )
    visitor_phone = fields.Char(
        related='visitor_id.phone',
        string='Phone',
        readonly=True,
    )
    unit_id = fields.Many2one(
        'pearl.seating.unit',
        string='Seating Unit',
        required=True,
        ondelete='restrict',
        index=True,
        help='Assigned beach seating unit (table, beachfront seat, or cabana).',
    )
    area_id = fields.Many2one(
        'pearl.seating.area',
        related='unit_id.area_id',
        string='Seating Area',
        readonly=True,
        store=True,
        index=True,
    )
    guest_count = fields.Integer(
        string='Guest Count',
        required=True,
        default=1,
        help='Number of guests occupying the seating unit for this booking.',
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

    # Pricing snapshot fields (locked at booking time to protect historical records)
    seating_type = fields.Selection(
        selection=seating_type_selection,
        string='Seating Type',
        readonly=True,
        copy=False,
        help='Snapshot of the seating type at the time of booking.',
    )
    pricing_mode = fields.Selection(
        selection=[
            ('per_guest', 'Per Guest'),
            ('fixed', 'Fixed'),
        ],
        string='Pricing Mode',
        readonly=True,
        copy=False,
        help='Snapshot of pricing mode at the time of booking.',
    )
    unit_price = fields.Monetary(
        string='Unit Price',
        currency_field='currency_id',
        readonly=True,
        copy=False,
        help='Snapshot of base rate applied (per-guest rate or fixed package rate).',
    )
    entry_fee_amount = fields.Monetary(
        string='Entry Fee Component',
        currency_field='currency_id',
        readonly=True,
        copy=False,
        help='Snapshot of entry fee component where applicable.',
    )
    minimum_spend_amount = fields.Monetary(
        string='Minimum Spend Component',
        currency_field='currency_id',
        readonly=True,
        copy=False,
        help='Snapshot of minimum spend component where applicable.',
    )
    amount_total = fields.Monetary(
        string='Total Amount',
        currency_field='currency_id',
        store=True,
        copy=False,
        help='Total calculated booking price.',
    )

    # Payments and status tracking
    payment_ids = fields.One2many(
        'pearl.booking.payment',
        'booking_id',
        string='Payments',
    )
    amount_paid = fields.Monetary(
        string='Amount Paid',
        currency_field='currency_id',
        compute='_compute_payments',
        store=True,
        help='Sum of recorded payments against this booking.',
    )
    amount_due = fields.Monetary(
        string='Amount Due',
        currency_field='currency_id',
        compute='_compute_payments',
        store=True,
        help='Outstanding balance for this booking (Total Amount minus Amount Paid).',
    )
    payment_status = fields.Selection(
        selection=[
            ('unpaid', 'Unpaid'),
            ('partial', 'Partially Paid'),
            ('paid', 'Paid'),
        ],
        string='Payment Status',
        compute='_compute_payments',
        store=True,
        default='unpaid',
        index=True,
        help='Current payment status: Unpaid (0 paid), Partially Paid, or Paid (fully covered).',
    )

    # Reservation state and user audit
    state = fields.Selection(
        selection=[
            ('reserved', 'Reserved'),
            ('released', 'Released'),
        ],
        string='State',
        required=True,
        default='reserved',
        index=True,
        help='Active reservation status. A unit remains reserved until manually released.',
    )
    reserved_by_id = fields.Many2one(
        'res.users',
        string='Reserved By',
        default=lambda self: self.env.user,
        help='User who recorded the reservation.',
    )
    reserved_datetime = fields.Datetime(
        string='Reserved Date & Time',
        default=fields.Datetime.now,
        help='Timestamp when the reservation was made.',
    )
    released_by_id = fields.Many2one(
        'res.users',
        string='Released By',
        copy=False,
        help='User who released the reservation.',
    )
    released_datetime = fields.Datetime(
        string='Released Date & Time',
        copy=False,
        help='Timestamp when the reservation was released.',
    )

    def init(self):
        super().init()
        self.env.cr.execute("""
            ALTER TABLE pearl_booking 
            ADD COLUMN IF NOT EXISTS area_id integer;
        """)
        # Enforce database-level partial unique index: only ONE active 'reserved' booking per seating unit
        create_index(
            self.env.cr,
            'pearl_booking_unit_reserved_unique_idx',
            self._table,
            ['unit_id'],
            unique=True,
            where="state = 'reserved'",
        )

    @api.depends('payment_ids.amount', 'amount_total')
    def _compute_payments(self):
        for booking in self:
            currency = booking.currency_id or self.env.company.currency_id
            total_paid = sum(booking.payment_ids.mapped('amount'))
            total_paid = currency.round(total_paid)
            booking.amount_paid = total_paid
            total_amount = currency.round(booking.amount_total or 0.0)
            booking.amount_due = currency.round(total_amount - total_paid)

            if not booking.payment_ids or currency.compare_amounts(total_paid, 0.0) <= 0:
                booking.payment_status = 'unpaid'
            elif currency.compare_amounts(total_paid, total_amount) >= 0:
                booking.payment_status = 'paid'
            else:
                booking.payment_status = 'partial'

    @api.onchange('unit_id', 'guest_count')
    def _onchange_unit_pricing(self):
        if self.unit_id:
            self.seating_type = self.unit_id.seating_type
            self.pricing_mode = self.unit_id.pricing_mode
            self.currency_id = self.unit_id.currency_id
            guest_count = self.guest_count or 1
            if self.unit_id.pricing_mode == 'fixed':
                self.unit_price = self.unit_id.fixed_price
                self.entry_fee_amount = 0.0
                self.minimum_spend_amount = 0.0
                self.amount_total = self.unit_id.fixed_price
            else:
                self.unit_price = self.unit_id.price_per_guest
                self.entry_fee_amount = (self.unit_id.entry_fee_amount or 0.0) * guest_count
                self.minimum_spend_amount = (self.unit_id.minimum_spend_amount or 0.0) * guest_count
                self.amount_total = (self.unit_id.price_per_guest or 0.0) * guest_count

    @api.constrains('guest_count', 'unit_id')
    def _check_guest_count_capacity(self):
        for booking in self:
            if booking.guest_count < 1:
                raise ValidationError(_("Guest count must be at least 1."))

            unit = booking.unit_id
            if unit:
                if unit.capacity_min and booking.guest_count < unit.capacity_min:
                    raise ValidationError(
                        _("Guest count (%(count)s) is below the minimum capacity (%(min)s) for %(unit)s.") % {
                            'count': booking.guest_count,
                            'min': unit.capacity_min,
                            'unit': unit.name,
                        }
                    )
                if unit.capacity_max and booking.guest_count > unit.capacity_max:
                    raise ValidationError(
                        _("Guest count (%(count)s) exceeds the maximum capacity (%(max)s) for %(unit)s.") % {
                            'count': booking.guest_count,
                            'max': unit.capacity_max,
                            'unit': unit.name,
                        }
                    )

    @api.constrains('unit_id', 'state')
    def _check_single_active_reservation(self):
        for booking in self:
            if booking.unit_id and booking.state == 'reserved':
                domain = [
                    ('unit_id', '=', booking.unit_id.id),
                    ('state', '=', 'reserved'),
                    ('id', '!=', booking.id),
                ]
                if self.search_count(domain) > 0:
                    raise ValidationError(
                        _("Seating unit '%(unit)s' already has an active reservation.") % {
                            'unit': booking.unit_id.name,
                        }
                    )

    @api.model
    def create_booking(self, visit_id, unit_id, guest_count):
        """Server-side reusable booking creation method for receptionist workflows."""
        visit_rec = self.env['pearl.visit'].browse(
            visit_id.id if hasattr(visit_id, 'id') else visit_id
        )
        unit_rec = self.env['pearl.seating.unit'].browse(
            unit_id.id if hasattr(unit_id, 'id') else unit_id
        )
        return self.create({
            'visit_id': visit_rec.id,
            'unit_id': unit_rec.id,
            'guest_count': guest_count,
        })

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            # 1. Visit Validation
            visit_id = vals.get('visit_id')
            if not visit_id:
                raise ValidationError(_("A valid visit check-in record is required to create a booking."))
            visit = self.env['pearl.visit'].browse(visit_id)
            if not visit.exists():
                raise ValidationError(_("The referenced visit record (ID %s) does not exist.") % visit_id)
            if visit.state != 'checked_in':
                raise ValidationError(
                    _("Seating reservations can only be created for checked-in visits (current visit status: '%s').") % visit.state
                )

            # 2. Seating Unit Validation
            unit_id = vals.get('unit_id')
            if not unit_id:
                raise ValidationError(_("A seating unit must be selected for the booking."))
            unit = self.env['pearl.seating.unit'].browse(unit_id)
            if not unit.exists():
                raise ValidationError(_("The referenced seating unit (ID %s) does not exist.") % unit_id)
            if not unit.active:
                raise ValidationError(_("Cannot reserve inactive seating unit '%s'.") % unit.name)

            # 3. Guest Count Validation
            guest_count = vals.get('guest_count')
            if not isinstance(guest_count, int) or guest_count < 1:
                raise ValidationError(_("Guest count must be at least 1."))
            if unit.capacity_min and guest_count < unit.capacity_min:
                raise ValidationError(
                    _("Guest count (%(count)s) is below the minimum capacity (%(min)s) for %(unit)s.") % {
                        'count': guest_count,
                        'min': unit.capacity_min,
                        'unit': unit.name,
                    }
                )
            if unit.capacity_max and guest_count > unit.capacity_max:
                raise ValidationError(
                    _("Guest count (%(count)s) exceeds the maximum capacity (%(max)s) for %(unit)s.") % {
                        'count': guest_count,
                        'max': unit.capacity_max,
                        'unit': unit.name,
                    }
                )
            # 4. Concurrency Protection - Row Lock on Unit and Recheck Active Reservations
            self.env.cr.execute(
                "SELECT id, active FROM pearl_seating_unit WHERE id = %s FOR UPDATE",
                [unit.id]
            )
            self.env.cr.execute(
                "SELECT id FROM pearl_booking WHERE unit_id = %s AND state = 'reserved' FOR UPDATE",
                [unit.id]
            )
            if self.env.cr.fetchone():
                raise ValidationError(_("Seating unit '%s' already has an active reservation.") % unit.name)

            # 5. Server-side Pricing Calculation and Snapshot Enforce (Overrides client-passed values)
            currency = unit.currency_id or self.env.company.currency_id
            company = unit.company_id or self.env.company
            vals['currency_id'] = currency.id
            vals['company_id'] = company.id
            vals['area_id'] = unit.area_id.id
            vals['state'] = 'reserved'
            vals['reserved_by_id'] = self.env.user.id
            if self.env.context.get('sync_historical_snapshot'):
                # A synchronized booking carries the immutable pricing values
                # captured when it was made, which may predate unit repricing.
                vals.setdefault('reserved_datetime', fields.Datetime.now())
            else:
                vals['seating_type'] = unit.seating_type
                vals['pricing_mode'] = unit.pricing_mode
                vals['reserved_datetime'] = fields.Datetime.now()

                if unit.pricing_mode == 'fixed':
                    fixed_rate = currency.round(unit.fixed_price if unit.fixed_price > 0 else 250000.0)
                    vals['unit_price'] = fixed_rate
                    vals['entry_fee_amount'] = 0.0
                    vals['minimum_spend_amount'] = 0.0
                    vals['amount_total'] = fixed_rate
                else:
                    per_guest_rate = currency.round(unit.price_per_guest if unit.price_per_guest > 0 else 20000.0)
                    entry_rate = currency.round(unit.entry_fee_amount if unit.entry_fee_amount >= 0 else 5000.0)
                    min_spend_rate = currency.round(unit.minimum_spend_amount if unit.minimum_spend_amount >= 0 else 15000.0)
                    vals['unit_price'] = per_guest_rate
                    vals['entry_fee_amount'] = currency.round(entry_rate * guest_count)
                    vals['minimum_spend_amount'] = currency.round(min_spend_rate * guest_count)
                    vals['amount_total'] = currency.round(per_guest_rate * guest_count)

            # 6. Sequence Reference
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('pearl.booking') or _('New')

        # 7. Safe Create Execution with Unique Violation Trapping
        try:
            with self.env.cr.savepoint():
                records = super().create(vals_list)
        except Exception as e:
            if 'pearl_booking_unit_reserved_unique_idx' in str(e):
                unit_name = unit.name if 'unit' in locals() and unit else 'selected'
                raise ValidationError(
                    _("Seating unit '%s' was just reserved by another user. Please select another unit.") % unit_name
                )
            raise

        # 8. Chatter Logging on Creation
        if not self.env.context.get('tracking_disable'):
            for record in records:
                record._log_booking_created()

        return records

    def write(self, vals):
        """Protect reservation lifecycle and immutable historical snapshots after creation."""
        if 'unit_id' in vals:
            raise UserError(_("Changing the seating unit of an existing booking is not permitted."))
        if 'visit_id' in vals:
            raise UserError(_("Changing the visit reference of an existing booking is not permitted."))
        if 'area_id' in vals:
            raise UserError(_("Changing the seating area of an existing booking is not permitted."))

        immutable_snapshots = {
            'amount_total', 'unit_price', 'entry_fee_amount',
            'minimum_spend_amount', 'pricing_mode', 'seating_type',
            'currency_id', 'company_id'
        }
        attempted_snapshots = set(vals.keys()) & immutable_snapshots
        if attempted_snapshots:
            raise UserError(
                _("Historical pricing snapshot fields (%s) are immutable and cannot be modified.") % ', '.join(sorted(attempted_snapshots))
            )

        if 'reserved_by_id' in vals or 'reserved_datetime' in vals:
            raise UserError(_("Reservation creation audit fields cannot be altered."))

        lifecycle_fields = {'state', 'released_by_id', 'released_datetime'}
        if lifecycle_fields & set(vals.keys()):
            if not self.env.context.get('_pearl_releasing'):
                raise UserError(
                    _("Direct modification of booking state or release fields is not permitted. Please use action_release().")
                )

        if 'guest_count' in vals:
            new_count = vals['guest_count']
            for booking in self:
                if booking.state == 'released':
                    raise UserError(_("Cannot modify guest count on a released booking."))
                if booking.payment_ids:
                    raise UserError(_("Cannot modify guest count after payments have been recorded."))
                if not isinstance(new_count, int) or new_count < 1:
                    raise ValidationError(_("Guest count must be at least 1."))
                unit = booking.unit_id
                if unit:
                    if unit.capacity_min and new_count < unit.capacity_min:
                        raise ValidationError(
                            _("Guest count (%(count)s) is below the minimum capacity (%(min)s) for %(unit)s.") % {
                                'count': new_count,
                                'min': unit.capacity_min,
                                'unit': unit.name,
                            }
                        )
                    if unit.capacity_max and new_count > unit.capacity_max:
                        raise ValidationError(
                            _("Guest count (%(count)s) exceeds the maximum capacity (%(max)s) for %(unit)s.") % {
                                'count': new_count,
                                'max': unit.capacity_max,
                                'unit': unit.name,
                            }
                        )
        return super().write(vals)

    def action_release(self):
        """Release the seating reservation manually, allowing the unit to be booked again."""
        is_user = self.env.user.has_group('pearl_checkin.group_pearl_user')
        is_manager = self.env.user.has_group('pearl_checkin.group_pearl_manager')
        if not (is_user or is_manager or self.env.is_admin()):
            raise AccessError(_("You are not authorized to release seating reservations."))

        for booking in self:
            if booking.state != 'reserved':
                raise UserError(_("Only currently reserved bookings can be released."))

            releasing_user = self.env.user
            release_time = fields.Datetime.now()

            # Elevate only the release fields update through controlled internal context
            booking.with_context(_pearl_releasing=True).sudo().write({
                'state': 'released',
                'released_by_id': releasing_user.id,
                'released_datetime': release_time,
            })
            booking.flush_recordset(['state', 'released_by_id', 'released_datetime'])

            # Auditable chatter note
            booking.sudo().message_post(
                body=_("Seating reservation manually released by <b>%s</b>.") % releasing_user.name,
                message_type='comment',
                subtype_xmlid='mail.mt_note',
            )

        return True

    def record_payment(self, amount, payment_method, reference=False, booking_id=None):
        """Record an auditable payment against an existing reserved booking."""
        if not self and booking_id:
            booking = self.browse(booking_id)
        else:
            booking = self
        booking.ensure_one()

        if not booking.exists():
            raise ValidationError(_("The specified booking does not exist."))

        if booking.state != 'reserved':
            raise ValidationError(_("Payments cannot be recorded on a released booking."))

        currency = booking.currency_id
        amount = currency.round(amount or 0.0)
        if currency.compare_amounts(amount, 0.0) <= 0:
            raise ValidationError(_("Payment amount must be strictly greater than zero."))

        valid_methods = dict(self.env['pearl.booking.payment']._fields['payment_method'].selection)
        if payment_method not in valid_methods:
            raise ValidationError(_("Invalid payment method '%s'. Allowed methods: %s") % (
                payment_method, ', '.join(valid_methods.keys())
            ))

        # Concurrency row-level lock on booking row
        self.env.cr.execute(
            "SELECT id, amount_total FROM pearl_booking WHERE id = %s FOR UPDATE",
            [booking.id]
        )

        # Recalculate recorded payments after acquiring lock
        self.env.cr.execute(
            "SELECT COALESCE(SUM(amount), 0) FROM pearl_booking_payment WHERE booking_id = %s",
            [booking.id]
        )
        current_paid = currency.round(self.env.cr.fetchone()[0])
        new_total_paid = currency.round(current_paid + amount)

        if currency.compare_amounts(new_total_paid, booking.amount_total) > 0:
            raise ValidationError(
                _("Payment of %(amount)s exceeds remaining balance. Current paid: %(paid)s, Total: %(total)s, Remaining due: %(due)s.") % {
                    'amount': currency.format(amount),
                    'paid': currency.format(current_paid),
                    'total': currency.format(booking.amount_total),
                    'due': currency.format(currency.round(booking.amount_total - current_paid)),
                }
            )

        payment = self.env['pearl.booking.payment'].create({
            'booking_id': booking.id,
            'amount': amount,
            'payment_method': payment_method,
            'reference': (reference or '').strip() or False,
            'payment_datetime': fields.Datetime.now(),
            'user_id': self.env.user.id,
        })

        booking._compute_payments()
        booking.flush_recordset(['amount_paid', 'amount_due', 'payment_status'])

        ref_text = f" (Ref: {payment.reference})" if payment.reference else ""
        method_label = valid_methods.get(payment_method, payment_method)
        booking.sudo().message_post(
            body=_("Payment of <b>%(amount)s</b> received via %(method)s%(ref)s by %(user)s. Outstanding balance: %(due)s.") % {
                'amount': currency.format(amount),
                'method': method_label,
                'ref': ref_text,
                'user': self.env.user.name,
                'due': currency.format(booking.amount_due),
            },
            message_type='comment',
            subtype_xmlid='mail.mt_note',
        )

        return payment

    def _log_booking_created(self):
        """Log a chatter note when a booking is created."""
        for booking in self:
            currency = booking.currency_id or self.env.company.currency_id
            unit_name = booking.unit_id.name if booking.unit_id else ''
            area_name = booking.unit_id.area_id.name if booking.unit_id and booking.unit_id.area_id else ''
            booking.sudo().message_post(
                body=_(
                    "Reservation created for <b>%(unit)s</b> (%(area)s) with %(guests)d guest(s). "
                    "Total: %(total)s (Reserved by %(user)s)."
                ) % {
                    'unit': unit_name,
                    'area': area_name,
                    'guests': booking.guest_count,
                    'total': currency.format(booking.amount_total),
                    'user': booking.reserved_by_id.name or self.env.user.name,
                },
                message_type='comment',
                subtype_xmlid='mail.mt_note',
            )


class PearlBookingPayment(models.Model):
    _name = 'pearl.booking.payment'
    _description = 'Pearl Restaurant Booking Payment'
    _order = 'payment_datetime desc, id desc'

    booking_id = fields.Many2one(
        'pearl.booking',
        string='Booking',
        required=True,
        ondelete='restrict',
        index=True,
        help='Booking against which this payment was received.',
    )
    amount = fields.Monetary(
        string='Amount',
        currency_field='currency_id',
        required=True,
        help='Monetary amount received.',
    )
    currency_id = fields.Many2one(
        'res.currency',
        related='booking_id.currency_id',
        string='Currency',
        readonly=True,
        store=True,
    )
    company_id = fields.Many2one(
        'res.company',
        related='booking_id.company_id',
        string='Company',
        readonly=True,
        store=True,
    )
    visitor_id = fields.Many2one(
        'res.partner',
        related='booking_id.visitor_id',
        string='Visitor',
        readonly=True,
        store=True,
        index=True,
    )
    payment_method = fields.Selection(
        selection=[
            ('cash', 'Cash'),
            ('bank_card', 'Bank Card'),
            ('bank_transfer', 'Bank Transfer'),
            ('other', 'Other'),
        ],
        string='Payment Method',
        required=True,
        default='cash',
        help='Method of payment received at reception.',
    )
    reference = fields.Char(
        string='Payment Reference',
        help='Optional transaction identifier, bank reference, or receipt number.',
    )
    payment_datetime = fields.Datetime(
        string='Payment Date & Time',
        required=True,
        default=fields.Datetime.now,
        help='Date and time when the payment was received.',
    )
    user_id = fields.Many2one(
        'res.users',
        string='Recorded By',
        required=True,
        default=lambda self: self.env.user,
        readonly=True,
        help='Receptionist or user who recorded this payment.',
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            booking_id = vals.get('booking_id')
            if not booking_id:
                raise ValidationError(_("A payment must be linked to a booking."))
            booking = self.env['pearl.booking'].browse(booking_id)
            if not booking.exists():
                raise ValidationError(_("The referenced booking does not exist."))
            if booking.state != 'reserved':
                raise ValidationError(_("Payments cannot be recorded on a released booking."))

            currency = booking.currency_id
            amount = currency.round(vals.get('amount') or 0.0)
            if currency.compare_amounts(amount, 0.0) <= 0:
                raise ValidationError(_("Payment amount must be strictly greater than zero."))

            # Lock booking row to serialize payment creation
            self.env.cr.execute(
                "SELECT id, amount_total FROM pearl_booking WHERE id = %s FOR UPDATE",
                [booking.id]
            )
            self.env.cr.execute(
                "SELECT COALESCE(SUM(amount), 0) FROM pearl_booking_payment WHERE booking_id = %s",
                [booking.id]
            )
            current_paid = currency.round(self.env.cr.fetchone()[0])
            new_total = currency.round(current_paid + amount)
            if currency.compare_amounts(new_total, booking.amount_total) > 0:
                raise ValidationError(
                    _("Total payments (%(paid)s) cannot exceed the booking total amount (%(total)s).") % {
                        'paid': currency.format(new_total),
                        'total': currency.format(booking.amount_total),
                    }
                )

            vals['amount'] = amount
            if not vals.get('user_id'):
                vals['user_id'] = self.env.user.id
            if not vals.get('payment_datetime'):
                vals['payment_datetime'] = fields.Datetime.now()

        return super().create(vals_list)

    @api.constrains('amount', 'booking_id')
    def _check_payment_amount(self):
        for payment in self:
            currency = payment.currency_id or self.env.company.currency_id
            if currency.compare_amounts(payment.amount, 0.0) <= 0:
                raise ValidationError(_("Payment amount must be strictly greater than zero."))
            if payment.booking_id and payment.booking_id.amount_total:
                total_paid = sum(payment.booking_id.payment_ids.mapped('amount'))
                if currency.compare_amounts(total_paid, payment.booking_id.amount_total) > 0:
                    raise ValidationError(
                        _("Total payments (%(paid)s) cannot exceed the booking total amount (%(total)s).") % {
                            'paid': currency.format(total_paid),
                            'total': currency.format(payment.booking_id.amount_total),
                        }
                    )

    def write(self, vals):
        """Payment records are immutable to preserve the audit trail."""
        raise UserError(_("Payment records are immutable and cannot be modified once recorded."))

    def unlink(self):
        """Payment records cannot be deleted to preserve the financial audit trail."""
        raise UserError(_("Payment records cannot be deleted to preserve the financial audit trail."))
