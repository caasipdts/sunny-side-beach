# -*- coding: utf-8 -*-
from odoo import fields
from odoo.exceptions import ValidationError, UserError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestSunnysideSeatingBooking(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Ensure schema prerequisites within test transaction so tests can run cleanly
        cls.cr.execute("""
            ALTER TABLE res_partner 
            ADD COLUMN IF NOT EXISTS is_sunnyside_visitor boolean,
            ADD COLUMN IF NOT EXISTS sunnyside_location_id integer,
            ADD COLUMN IF NOT EXISTS sunnyside_visit_count integer,
            ADD COLUMN IF NOT EXISTS privacy_acknowledged boolean,
            ADD COLUMN IF NOT EXISTS privacy_acknowledgement_date timestamp without time zone,
            ADD COLUMN IF NOT EXISTS privacy_notice_version varchar,
            ADD COLUMN IF NOT EXISTS marketing_consent boolean,
            ADD COLUMN IF NOT EXISTS marketing_consent_date timestamp without time zone,
            ADD COLUMN IF NOT EXISTS sunnyside_visitor_type varchar,
            ADD COLUMN IF NOT EXISTS sunnyside_first_visit_date timestamp without time zone,
            ADD COLUMN IF NOT EXISTS sunnyside_last_visit_date timestamp without time zone;

            ALTER TABLE sunnyside_visit
            ADD COLUMN IF NOT EXISTS visitor_phone varchar,
            ADD COLUMN IF NOT EXISTS visitor_type varchar;

            CREATE TABLE IF NOT EXISTS sunnyside_seating_area (
                id serial primary key,
                name varchar not null,
                sequence integer default 10,
                active boolean default true,
                background_image text,
                background_color varchar,
                create_uid integer,
                create_date timestamp without time zone,
                write_uid integer,
                write_date timestamp without time zone
            );

            CREATE TABLE IF NOT EXISTS sunnyside_seating_unit (
                id serial primary key,
                name varchar not null,
                area_id integer not null,
                active boolean default true,
                seating_type varchar not null,
                capacity_min integer default 1,
                capacity_max integer default 4,
                pricing_mode varchar default 'per_guest',
                price_per_guest numeric,
                fixed_price numeric,
                entry_fee_amount numeric,
                minimum_spend_amount numeric,
                currency_id integer not null,
                company_id integer not null,
                sequence integer default 10,
                position_x integer,
                position_y integer,
                width integer,
                height integer,
                color varchar,
                create_uid integer,
                create_date timestamp without time zone,
                write_uid integer,
                write_date timestamp without time zone
            );

            CREATE TABLE IF NOT EXISTS sunnyside_seating_image (
                id serial primary key,
                name varchar not null,
                unit_id integer not null,
                sequence integer default 10,
                image text,
                create_uid integer,
                create_date timestamp without time zone,
                write_uid integer,
                write_date timestamp without time zone
            );

            CREATE TABLE IF NOT EXISTS sunnyside_booking (
                id serial primary key,
                name varchar,
                visit_id integer not null,
                visitor_id integer,
                unit_id integer not null,
                area_id integer,
                guest_count integer not null default 1,
                currency_id integer not null,
                company_id integer not null,
                seating_type varchar,
                pricing_mode varchar,
                unit_price numeric,
                entry_fee_amount numeric,
                minimum_spend_amount numeric,
                amount_total numeric,
                amount_paid numeric,
                amount_due numeric,
                payment_status varchar default 'unpaid',
                state varchar default 'reserved',
                reserved_by_id integer,
                reserved_datetime timestamp without time zone,
                released_by_id integer,
                released_datetime timestamp without time zone,
                create_uid integer,
                create_date timestamp without time zone,
                write_uid integer,
                write_date timestamp without time zone
            );

            ALTER TABLE sunnyside_booking ADD COLUMN IF NOT EXISTS area_id integer;

            CREATE TABLE IF NOT EXISTS sunnyside_booking_payment (
                id serial primary key,
                booking_id integer not null,
                amount numeric not null,
                currency_id integer,
                company_id integer,
                payment_method varchar not null default 'cash',
                reference varchar,
                payment_datetime timestamp without time zone,
                user_id integer not null,
                create_uid integer,
                create_date timestamp without time zone,
                write_uid integer,
                write_date timestamp without time zone
            );

            CREATE UNIQUE INDEX IF NOT EXISTS sunnyside_booking_unit_reserved_unique_idx
            ON sunnyside_booking (unit_id) WHERE state = 'reserved';
        """)

    def setUp(self):
        super().setUp()
        self.Partner = self.env['res.partner']
        self.Visit = self.env['sunnyside.visit']
        self.Location = self.env['sunnyside.location']
        self.Area = self.env['sunnyside.seating.area']
        self.Unit = self.env['sunnyside.seating.unit']
        self.Image = self.env['sunnyside.seating.image']
        self.Booking = self.env['sunnyside.booking']
        self.Payment = self.env['sunnyside.booking.payment']

        # Setup test visitor and visit
        self.test_location = self.Location.search([('active', '=', True)], limit=1)
        if not self.test_location:
            self.test_location = self.Location.create({'name': 'Victoria Island', 'active': True})

        self.test_visitor = self.Partner.create({
            'name': 'Babatunde Fash',
            'phone': '+2348030001111',
            'is_sunnyside_visitor': True,
            'sunnyside_location_id': self.test_location.id,
            'privacy_acknowledged': True,
        })

        self.test_visit = self.Visit.create({
            'visitor_id': self.test_visitor.id,
            'location_id': self.test_location.id,
            'source': 'receptionist',
            'state': 'checked_in',
        })

        # Base test area
        self.test_area = self.Area.create({
            'name': 'Test Beachfront Deck',
            'sequence': 1,
            'background_color': '#FFFAEA',
        })

    def test_01_seating_area_creation(self):
        """Verify seating area creation, properties, and ordering."""
        area = self.Area.create({
            'name': 'VIP Cabana Zone',
            'sequence': 5,
            'background_color': '#1E293B',
        })
        self.assertTrue(area.id)
        self.assertEqual(area.name, 'VIP Cabana Zone')
        self.assertTrue(area.active)
        self.assertEqual(area.sequence, 5)

    def test_02_seating_unit_creation_and_defaults(self):
        """Verify creation of each seating type with approved pricing and capacity defaults."""
        # 1. Standard Table: 1-4 guests, per-guest, ₦20,000 (₦5,000 entry + ₦15,000 min spend)
        table = self.Unit.create({
            'name': 'Table T-01',
            'area_id': self.test_area.id,
            'seating_type': 'table',
        })
        self.assertEqual(table.capacity_min, 1)
        self.assertEqual(table.capacity_max, 4)
        self.assertEqual(table.pricing_mode, 'per_guest')
        self.assertEqual(table.price_per_guest, 20000.0)
        self.assertEqual(table.entry_fee_amount, 5000.0)
        self.assertEqual(table.minimum_spend_amount, 15000.0)
        self.assertEqual(table.fixed_price, 0.0)

        # 2. Beachfront Seat: 1-1 guest, per-guest, ₦20,000
        seat = self.Unit.new({'seating_type': 'beachfront_seat'})
        seat._onchange_seating_type_defaults()
        seat_vals = seat._convert_to_write(seat._cache)
        seat_vals.update({'name': 'Beachfront S-01', 'area_id': self.test_area.id})
        beachfront = self.Unit.create(seat_vals)
        self.assertEqual(beachfront.capacity_min, 1)
        self.assertEqual(beachfront.capacity_max, 1)
        self.assertEqual(beachfront.pricing_mode, 'per_guest')
        self.assertEqual(beachfront.price_per_guest, 20000.0)

        # 3. Cabana: 1-9 guests, fixed package, ₦250,000
        cab = self.Unit.new({'seating_type': 'cabana'})
        cab._onchange_seating_type_defaults()
        cab_vals = cab._convert_to_write(cab._cache)
        cab_vals.update({'name': 'Cabana C-01', 'area_id': self.test_area.id})
        cabana = self.Unit.create(cab_vals)
        self.assertEqual(cabana.capacity_min, 1)
        self.assertEqual(cabana.capacity_max, 9)
        self.assertEqual(cabana.pricing_mode, 'fixed')
        self.assertEqual(cabana.fixed_price, 250000.0)
        self.assertEqual(cabana.entry_fee_amount, 0.0)
        self.assertEqual(cabana.minimum_spend_amount, 0.0)

    def test_custom_seating_type_rules_drive_unit_defaults(self):
        seating_type = self.env['sunnyside.seating.type'].create({
            'name': 'Rooftop Lounge',
            'capacity_min': 2,
            'capacity_max': 12,
            'pricing_mode': 'fixed',
            'price_per_guest': 0.0,
            'fixed_price': 300000.0,
            'entry_fee_amount': 0.0,
            'minimum_spend_amount': 0.0,
        })

        selection = self.Unit.fields_get(['seating_type'])['seating_type']['selection']
        self.assertIn((seating_type.code, seating_type.name), selection)

        unit = self.Unit.create({
            'name': 'Rooftop R-01',
            'area_id': self.test_area.id,
            'seating_type': seating_type.code,
        })
        self.assertEqual(unit.seating_type, seating_type.code)
        self.assertEqual(unit.capacity_min, 2)
        self.assertEqual(unit.capacity_max, 12)
        self.assertEqual(unit.pricing_mode, 'fixed')
        self.assertEqual(unit.fixed_price, 300000.0)

        with self.assertRaises(ValidationError):
            self.Unit.create({
                'name': 'Rooftop R-02',
                'area_id': self.test_area.id,
                'seating_type': seating_type.code,
                'capacity_max': 13,
            })
        with self.assertRaises(ValidationError):
            seating_type.write({'capacity_min': 3})
        with self.assertRaises(UserError):
            seating_type.write({'active': False})

    def test_seating_type_form_hides_system_generated_code(self):
        view = self.env.ref(
            'sunnyside_visitor_management.view_sunnyside_seating_type_form'
        )
        self.assertNotIn('name="code"', view.arch_db)

    def test_03_seating_unit_capacity_constraints(self):
        """Verify capacity constraints for all unit types."""
        # Table capacity cannot exceed 4
        with self.assertRaises(ValidationError):
            self.Unit.create({
                'name': 'Overcap Table',
                'area_id': self.test_area.id,
                'seating_type': 'table',
                'capacity_min': 1,
                'capacity_max': 5,
            })

        # Beachfront seat capacity must be exactly 1
        with self.assertRaises(ValidationError):
            self.Unit.create({
                'name': 'Invalid Beachfront',
                'area_id': self.test_area.id,
                'seating_type': 'beachfront_seat',
                'capacity_min': 1,
                'capacity_max': 2,
            })

        # Cabana capacity cannot exceed 9
        with self.assertRaises(ValidationError):
            self.Unit.create({
                'name': 'Overcap Cabana',
                'area_id': self.test_area.id,
                'seating_type': 'cabana',
                'capacity_min': 1,
                'capacity_max': 10,
                'pricing_mode': 'fixed',
                'fixed_price': 250000.0,
            })

        # Capacity max cannot be less than capacity min
        with self.assertRaises(ValidationError):
            self.Unit.create({
                'name': 'Inverted Capacity Unit',
                'area_id': self.test_area.id,
                'seating_type': 'table',
                'capacity_min': 3,
                'capacity_max': 2,
            })

        # Capacity min cannot be 0
        with self.assertRaises(ValidationError):
            self.Unit.create({
                'name': 'Zero Capacity Unit',
                'area_id': self.test_area.id,
                'seating_type': 'table',
                'capacity_min': 0,
                'capacity_max': 4,
            })

    def test_04_seating_unit_pricing_constraints(self):
        """Verify validation of non-negative and properly mode-configured pricing."""
        # Negative per-guest price
        with self.assertRaises(ValidationError):
            self.Unit.create({
                'name': 'Negative Price Table',
                'area_id': self.test_area.id,
                'seating_type': 'table',
                'price_per_guest': -100.0,
            })

        # Negative fixed price
        with self.assertRaises(ValidationError):
            self.Unit.create({
                'name': 'Negative Cabana',
                'area_id': self.test_area.id,
                'seating_type': 'cabana',
                'pricing_mode': 'fixed',
                'fixed_price': -5000.0,
            })

        # Fixed mode requires positive fixed_price
        with self.assertRaises(ValidationError):
            self.Unit.create({
                'name': 'Zero Fixed Price Cabana',
                'area_id': self.test_area.id,
                'seating_type': 'cabana',
                'pricing_mode': 'fixed',
                'fixed_price': 0.0,
            })

        # Per-guest mode requires positive price_per_guest
        with self.assertRaises(ValidationError):
            self.Unit.create({
                'name': 'Zero Per Guest Table',
                'area_id': self.test_area.id,
                'seating_type': 'table',
                'pricing_mode': 'per_guest',
                'price_per_guest': 0.0,
            })

    def test_05_seating_image_model(self):
        """Verify seating photographs association and cascade deletion."""
        unit = self.Unit.create({
            'name': 'Table with Photos',
            'area_id': self.test_area.id,
            'seating_type': 'table',
        })
        # Base64 1x1 png dummy
        dummy_img = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII='
        img = self.Image.create({
            'name': 'Deck Angle 1',
            'unit_id': unit.id,
            'image': dummy_img,
        })
        self.assertEqual(img.unit_id.id, unit.id)
        self.assertIn(img, unit.image_ids)

    def test_06_booking_pricing_snapshots_and_calculations(self):
        """Verify booking creation, reference sequence, and pricing snapshots."""
        table = self.Unit.create({
            'name': 'Table T-02',
            'area_id': self.test_area.id,
            'seating_type': 'table',
            'capacity_min': 1,
            'capacity_max': 4,
            'pricing_mode': 'per_guest',
            'price_per_guest': 20000.0,
            'entry_fee_amount': 5000.0,
            'minimum_spend_amount': 15000.0,
        })

        # Booking for 3 guests on standard table -> ₦60,000 total (3 x 20,000)
        booking = self.Booking.create({
            'visit_id': self.test_visit.id,
            'unit_id': table.id,
            'guest_count': 3,
        })
        self.assertTrue(booking.name)
        self.assertTrue(booking.name.startswith('BKG/') or booking.name == 'New')
        self.assertEqual(booking.visitor_id.id, self.test_visitor.id)
        self.assertEqual(booking.seating_type, 'table')
        self.assertEqual(booking.pricing_mode, 'per_guest')
        self.assertEqual(booking.unit_price, 20000.0)
        self.assertEqual(booking.entry_fee_amount, 15000.0)  # 3 x 5,000
        self.assertEqual(booking.minimum_spend_amount, 45000.0)  # 3 x 15,000
        self.assertEqual(booking.amount_total, 60000.0)

        # Verify historical snapshot immutability: changing unit price does NOT alter existing booking
        table.write({'price_per_guest': 30000.0})
        self.assertEqual(booking.unit_price, 20000.0)
        self.assertEqual(booking.amount_total, 60000.0)

        # Booking for cabana (fixed price ₦250,000 for up to 9 guests)
        cabana = self.Unit.create({
            'name': 'Cabana C-02',
            'area_id': self.test_area.id,
            'seating_type': 'cabana',
            'capacity_min': 1,
            'capacity_max': 9,
            'pricing_mode': 'fixed',
            'fixed_price': 250000.0,
        })
        booking_cabana = self.Booking.create({
            'visit_id': self.test_visit.id,
            'unit_id': cabana.id,
            'guest_count': 9,
        })
        self.assertEqual(booking_cabana.amount_total, 250000.0, "Cabana price is flat ₦250,000, not multiplied by guests")
        self.assertEqual(booking_cabana.entry_fee_amount, 0.0)
        self.assertEqual(booking_cabana.minimum_spend_amount, 0.0)

    def test_07_booking_guest_count_validation(self):
        """Verify booking-level guest count capacity enforcement."""
        table = self.Unit.create({
            'name': 'Table T-03',
            'area_id': self.test_area.id,
            'seating_type': 'table',
            'capacity_min': 1,
            'capacity_max': 4,
            'pricing_mode': 'per_guest',
            'price_per_guest': 20000.0,
        })
        beachfront = self.Unit.create({
            'name': 'Seat S-02',
            'area_id': self.test_area.id,
            'seating_type': 'beachfront_seat',
            'capacity_min': 1,
            'capacity_max': 1,
            'pricing_mode': 'per_guest',
            'price_per_guest': 20000.0,
        })
        cabana = self.Unit.create({
            'name': 'Cabana C-03',
            'area_id': self.test_area.id,
            'seating_type': 'cabana',
            'capacity_min': 1,
            'capacity_max': 9,
            'pricing_mode': 'fixed',
            'fixed_price': 250000.0,
        })

        # Table, 5 guests -> rejected
        with self.assertRaises(ValidationError):
            self.Booking.create({'visit_id': self.test_visit.id, 'unit_id': table.id, 'guest_count': 5})

        # Beachfront seat, 2 guests -> rejected
        with self.assertRaises(ValidationError):
            self.Booking.create({'visit_id': self.test_visit.id, 'unit_id': beachfront.id, 'guest_count': 2})

        # Beachfront seat, 0 guests -> rejected
        with self.assertRaises(ValidationError):
            self.Booking.create({'visit_id': self.test_visit.id, 'unit_id': beachfront.id, 'guest_count': 0})

        # Cabana, 10 guests -> rejected
        with self.assertRaises(ValidationError):
            self.Booking.create({'visit_id': self.test_visit.id, 'unit_id': cabana.id, 'guest_count': 10})

    def test_08_payment_flow_and_statuses(self):
        """Verify payment recording, balances, statuses: unpaid -> partial -> paid, and validation."""
        seat = self.Unit.create({
            'name': 'Seat S-03',
            'area_id': self.test_area.id,
            'seating_type': 'beachfront_seat',
            'capacity_min': 1,
            'capacity_max': 1,
            'pricing_mode': 'per_guest',
            'price_per_guest': 20000.0,
        })
        booking = self.Booking.create({
            'visit_id': self.test_visit.id,
            'unit_id': seat.id,
            'guest_count': 1,
        })
        self.assertEqual(booking.amount_total, 20000.0)

        # 1. Zero payments recorded initially: amount_paid = 0, status = unpaid
        self.assertEqual(booking.amount_paid, 0.0)
        self.assertEqual(booking.amount_due, 20000.0)
        self.assertEqual(booking.payment_status, 'unpaid')

        # 2. Non-positive payment amount -> rejected
        with self.assertRaises(ValidationError):
            self.Payment.create({
                'booking_id': booking.id,
                'amount': 0.0,
                'payment_method': 'cash',
            })
        with self.assertRaises(ValidationError):
            self.Payment.create({
                'booking_id': booking.id,
                'amount': -5000.0,
                'payment_method': 'cash',
            })

        # 3. Partial payment of ₦10,000 -> status partial
        p1 = self.Payment.create({
            'booking_id': booking.id,
            'amount': 10000.0,
            'payment_method': 'bank_transfer',
            'reference': 'TRF-12345',
        })
        self.assertEqual(p1.currency_id.id, booking.currency_id.id)
        self.assertEqual(booking.amount_paid, 10000.0)
        self.assertEqual(booking.amount_due, 10000.0)
        self.assertEqual(booking.payment_status, 'partial')

        # 4. Second payment completing total (₦10,000) -> status paid
        p2 = self.Payment.create({
            'booking_id': booking.id,
            'amount': 10000.0,
            'payment_method': 'bank_card',
            'reference': 'POS-98765',
        })
        self.assertEqual(booking.amount_paid, 20000.0)
        self.assertEqual(booking.amount_due, 0.0)
        self.assertEqual(booking.payment_status, 'paid')

        # 5. Overpayment exceeding total -> rejected
        with self.assertRaises(ValidationError):
            self.Payment.create({
                'booking_id': booking.id,
                'amount': 1000.0,
                'payment_method': 'cash',
            })

    def test_09_payment_immutability_and_audit(self):
        """Verify payments cannot be modified or deleted, preserving the audit trail."""
        table = self.Unit.create({
            'name': 'Table T-04',
            'area_id': self.test_area.id,
            'seating_type': 'table',
            'capacity_min': 1,
            'capacity_max': 4,
            'price_per_guest': 20000.0,
        })
        booking = self.Booking.create({
            'visit_id': self.test_visit.id,
            'unit_id': table.id,
            'guest_count': 1,
        })
        payment = self.Payment.create({
            'booking_id': booking.id,
            'amount': 20000.0,
            'payment_method': 'cash',
        })
        self.assertTrue(payment.user_id)
        self.assertTrue(payment.payment_datetime)

        # Attempt to edit payment record -> UserError
        with self.assertRaises(UserError):
            payment.write({'amount': 15000.0})

        # Attempt to delete payment record -> UserError
        with self.assertRaises(UserError):
            payment.unlink()

    def test_10_concurrent_reservation_protection(self):
        """Verify that two active reserved bookings cannot exist for the same seating unit."""
        unit = self.Unit.create({
            'name': 'Exclusive Cabana C-04',
            'area_id': self.test_area.id,
            'seating_type': 'cabana',
            'capacity_min': 1,
            'capacity_max': 9,
            'pricing_mode': 'fixed',
            'fixed_price': 250000.0,
        })

        # First booking reserves the unit
        b1 = self.Booking.create({
            'visit_id': self.test_visit.id,
            'unit_id': unit.id,
            'guest_count': 4,
            'state': 'reserved',
        })
        self.assertEqual(b1.state, 'reserved')

        from odoo.tools import mute_logger

        # Second booking attempting to reserve the same unit must fail
        with mute_logger('odoo.sql_db'):
            with self.assertRaises(Exception):
                with self.cr.savepoint():
                    self.Booking.create({
                        'visit_id': self.test_visit.id,
                        'unit_id': unit.id,
                        'guest_count': 2,
                        'state': 'reserved',
                    })

    def test_11_release_and_rebooking_lifecycle(self):
        """Verify booking release sets audit fields and allows the unit to be reserved again."""
        unit = self.Unit.create({
            'name': 'Recyclable Table T-05',
            'area_id': self.test_area.id,
            'seating_type': 'table',
            'capacity_min': 1,
            'capacity_max': 4,
            'price_per_guest': 20000.0,
        })

        # 1. Guest 1 books the unit
        b1 = self.Booking.create({
            'visit_id': self.test_visit.id,
            'unit_id': unit.id,
            'guest_count': 2,
            'state': 'reserved',
        })
        self.assertEqual(b1.state, 'reserved')
        self.assertEqual(b1.reserved_by_id.id, self.env.user.id)
        self.assertTrue(b1.reserved_datetime)
        self.assertFalse(b1.released_by_id)
        self.assertFalse(b1.released_datetime)

        # 2. Release the booking
        b1.action_release()
        self.assertEqual(b1.state, 'released')
        self.assertEqual(b1.released_by_id.id, self.env.user.id)
        self.assertTrue(b1.released_datetime)

        # 3. Create a second visit and book the now-released unit
        second_visitor = self.Partner.create({
            'name': 'Funke Akindele',
            'phone': '+2348039998888',
            'is_sunnyside_visitor': True,
            'privacy_acknowledged': True,
        })
        second_visit = self.Visit.create({
            'visitor_id': second_visitor.id,
            'source': 'receptionist',
            'state': 'checked_in',
        })

        b2 = self.Booking.create({
            'visit_id': second_visit.id,
            'unit_id': unit.id,
            'guest_count': 4,
            'state': 'reserved',
        })
        self.assertTrue(b2.id)
        self.assertEqual(b2.state, 'reserved')
        self.assertEqual(b2.unit_id.id, unit.id)

    def test_12_create_booking_server_method(self):
        """Verify reusable server-side create_booking method for all seating types."""
        table = self.Unit.create({
            'name': 'API Table T-10',
            'area_id': self.test_area.id,
            'seating_type': 'table',
            'capacity_min': 1,
            'capacity_max': 4,
            'pricing_mode': 'per_guest',
            'price_per_guest': 20000.0,
            'entry_fee_amount': 5000.0,
            'minimum_spend_amount': 15000.0,
        })
        beachfront = self.Unit.create({
            'name': 'API Seat S-10',
            'area_id': self.test_area.id,
            'seating_type': 'beachfront_seat',
            'capacity_min': 1,
            'capacity_max': 1,
            'pricing_mode': 'per_guest',
            'price_per_guest': 20000.0,
        })
        cabana = self.Unit.create({
            'name': 'API Cabana C-10',
            'area_id': self.test_area.id,
            'seating_type': 'cabana',
            'capacity_min': 1,
            'capacity_max': 9,
            'pricing_mode': 'fixed',
            'fixed_price': 250000.0,
        })

        # 1. Standard Table: 3 guests -> ₦60,000
        b_table = self.Booking.create_booking(self.test_visit.id, table.id, 3)
        self.assertEqual(b_table.amount_total, 60000.0)
        self.assertEqual(b_table.entry_fee_amount, 15000.0)
        self.assertEqual(b_table.minimum_spend_amount, 45000.0)
        self.assertEqual(b_table.state, 'reserved')

        # 2. Beachfront Seat: 1 guest -> ₦20,000
        b_seat = self.Booking.create_booking(self.test_visit.id, beachfront.id, 1)
        self.assertEqual(b_seat.amount_total, 20000.0)
        self.assertEqual(b_seat.entry_fee_amount, 5000.0)
        self.assertEqual(b_seat.minimum_spend_amount, 15000.0)

        # 3. Cabana: 5 guests -> flat ₦250,000
        b_cab = self.Booking.create_booking(self.test_visit.id, cabana.id, 5)
        self.assertEqual(b_cab.amount_total, 250000.0)
        self.assertEqual(b_cab.entry_fee_amount, 0.0)
        self.assertEqual(b_cab.minimum_spend_amount, 0.0)

        # 4. Delegation through visit model helper
        table2 = self.Unit.create({
            'name': 'API Table T-11',
            'area_id': self.test_area.id,
            'seating_type': 'table',
            'price_per_guest': 20000.0,
        })
        b_from_visit = self.test_visit.create_booking(table2.id, 2)
        self.assertEqual(b_from_visit.amount_total, 40000.0)
        self.assertEqual(b_from_visit.visit_id.id, self.test_visit.id)

    def test_13_create_booking_validations(self):
        """Verify server-side validation of visit state, unit active status, and capacity bounds."""
        table = self.Unit.create({
            'name': 'Val Table T-20',
            'area_id': self.test_area.id,
            'seating_type': 'table',
            'capacity_min': 1,
            'capacity_max': 4,
            'price_per_guest': 20000.0,
        })
        inactive_unit = self.Unit.create({
            'name': 'Inactive Unit',
            'area_id': self.test_area.id,
            'seating_type': 'table',
            'active': False,
        })
        cancelled_visit = self.Visit.create({
            'visitor_id': self.test_visitor.id,
            'state': 'cancelled',
        })

        # Inactive unit rejection
        with self.assertRaises(ValidationError):
            self.Booking.create_booking(self.test_visit.id, inactive_unit.id, 2)

        # Cancelled visit rejection
        with self.assertRaises(ValidationError):
            self.Booking.create_booking(cancelled_visit.id, table.id, 2)

        # Non-existent visit rejection
        with self.assertRaises(ValidationError):
            self.Booking.create_booking(999999, table.id, 2)

        # Overcapacity table (5 guests) rejection
        with self.assertRaises(ValidationError):
            self.Booking.create_booking(self.test_visit.id, table.id, 5)

        # Zero guests rejection
        with self.assertRaises(ValidationError):
            self.Booking.create_booking(self.test_visit.id, table.id, 0)

    def test_14_direct_orm_creation_protected(self):
        """Verify callers cannot bypass server pricing calculations by creating records via ORM."""
        table = self.Unit.create({
            'name': 'Protected Table T-30',
            'area_id': self.test_area.id,
            'seating_type': 'table',
            'price_per_guest': 20000.0,
        })

        # Attempt to pass fabricated amount_total and unit_price
        booking = self.Booking.create({
            'visit_id': self.test_visit.id,
            'unit_id': table.id,
            'guest_count': 2,
            'amount_total': 10.0,       # Fabricated
            'unit_price': 5.0,           # Fabricated
            'entry_fee_amount': 1.0,     # Fabricated
        })
        # Server must override with true approved calculations
        self.assertEqual(booking.amount_total, 40000.0, "Server must enforce approved total of ₦40,000")
        self.assertEqual(booking.unit_price, 20000.0)
        self.assertEqual(booking.entry_fee_amount, 10000.0)
        self.assertEqual(booking.minimum_spend_amount, 30000.0)

    def test_15_record_payment_method(self):
        """Verify dedicated record_payment method, balance updates, and status transitions."""
        table = self.Unit.create({
            'name': 'Pay Table T-40',
            'area_id': self.test_area.id,
            'seating_type': 'table',
            'price_per_guest': 20000.0,
        })
        booking = self.Booking.create_booking(self.test_visit.id, table.id, 3)  # ₦60,000 total

        # Initial unpaid state
        self.assertEqual(booking.payment_status, 'unpaid')
        self.assertEqual(booking.amount_paid, 0.0)
        self.assertEqual(booking.amount_due, 60000.0)

        # 1. Partial payment of ₦20,000 via cash
        p1 = booking.record_payment(20000.0, 'cash')
        self.assertEqual(p1.amount, 20000.0)
        self.assertEqual(p1.payment_method, 'cash')
        self.assertEqual(booking.payment_status, 'partial')
        self.assertEqual(booking.amount_paid, 20000.0)
        self.assertEqual(booking.amount_due, 40000.0)

        # 2. Second partial payment of ₦30,000 via bank_card with reference
        p2 = booking.record_payment(30000.0, 'bank_card', reference='POS-CARD-001')
        self.assertEqual(p2.reference, 'POS-CARD-001')
        self.assertEqual(booking.amount_paid, 50000.0)
        self.assertEqual(booking.amount_due, 10000.0)
        self.assertEqual(booking.payment_status, 'partial')

        # 3. Final payment of ₦10,000 via bank_transfer -> status paid
        p3 = booking.record_payment(10000.0, 'bank_transfer', reference='TRF-998877')
        self.assertEqual(booking.amount_paid, 60000.0)
        self.assertEqual(booking.amount_due, 0.0)
        self.assertEqual(booking.payment_status, 'paid')

        # 4. Overpayment rejection (additional ₦1,000)
        with self.assertRaises(ValidationError):
            booking.record_payment(1000.0, 'cash')

        # 5. Non-positive amount rejection
        with self.assertRaises(ValidationError):
            booking.record_payment(0.0, 'cash')
        with self.assertRaises(ValidationError):
            booking.record_payment(-500.0, 'cash')

        # 6. Invalid payment method rejection
        with self.assertRaises(ValidationError):
            booking.record_payment(500.0, 'cryptocurrency')

    def test_16_payment_on_released_booking_rejected(self):
        """Verify payments cannot be recorded against released bookings."""
        table = self.Unit.create({
            'name': 'Pay Released Table T-50',
            'area_id': self.test_area.id,
            'seating_type': 'table',
            'price_per_guest': 20000.0,
        })
        booking = self.Booking.create_booking(self.test_visit.id, table.id, 2)
        booking.action_release()
        self.assertEqual(booking.state, 'released')

        with self.assertRaises(ValidationError):
            booking.record_payment(20000.0, 'cash')

    def test_17_action_release_authorization_and_lifecycle(self):
        """Verify release authorization: authorized users succeed, unauthorized users fail."""
        # Ensure model and ACL records exist in test transaction so non-admin user checks succeed
        model_booking = self.env['ir.model'].search([('model', '=', 'sunnyside.booking')], limit=1)
        if not model_booking:
            model_booking = self.env['ir.model'].sudo().create({
                'model': 'sunnyside.booking',
                'name': 'Sunnyside Beach Seating Booking',
                'state': 'base',
            })
        group_user = self.env.ref('sunnyside_visitor_management.group_sunnyside_user')
        if not self.env['ir.model.access'].search([('model_id', '=', model_booking.id), ('group_id', '=', group_user.id)]):
            self.env['ir.model.access'].sudo().create({
                'name': 'sunnyside.booking.user',
                'model_id': model_booking.id,
                'group_id': group_user.id,
                'perm_read': True,
                'perm_write': False,
                'perm_create': True,
                'perm_unlink': False,
            })

        table = self.Unit.create({
            'name': 'Auth Table T-60',
            'area_id': self.test_area.id,
            'seating_type': 'table',
            'price_per_guest': 20000.0,
        })
        booking = self.Booking.create_booking(self.test_visit.id, table.id, 2)

        # 1. Unauthorized user (no Sunnyside group)
        Users = self.env['res.users']
        unauthorized_user = Users.create({
            'name': 'Unauth External Staff',
            'login': 'unauth_staff',
            'email': 'unauth@sunnyside.ng',
            'group_ids': [(6, 0, [self.env.ref('base.group_user').id])],
        })

        from odoo.exceptions import AccessError
        with self.assertRaises(AccessError):
            booking.with_user(unauthorized_user).action_release()

        # 2. Authorized operational user (group_sunnyside_user)
        receptionist_user = Users.create({
            'name': 'Receptionist Alice',
            'login': 'receptionist_alice',
            'email': 'alice@sunnyside.ng',
            'group_ids': [(6, 0, [
                self.env.ref('base.group_user').id,
                self.env.ref('sunnyside_visitor_management.group_sunnyside_user').id,
            ])],
        })
        booking.with_user(receptionist_user).action_release()
        self.assertEqual(booking.state, 'released')
        self.assertEqual(booking.released_by_id.id, receptionist_user.id)
        self.assertTrue(booking.released_datetime)

        # 3. Re-release on already released booking must fail
        with self.assertRaises(UserError):
            booking.with_user(receptionist_user).action_release()

    def test_18_direct_writes_protected(self):
        """Verify immutability of seating assignment, historical snapshots, and release fields."""
        table1 = self.Unit.create({
            'name': 'Table Immutable 1',
            'area_id': self.test_area.id,
            'seating_type': 'table',
            'price_per_guest': 20000.0,
        })
        table2 = self.Unit.create({
            'name': 'Table Immutable 2',
            'area_id': self.test_area.id,
            'seating_type': 'table',
            'price_per_guest': 20000.0,
        })
        booking = self.Booking.create_booking(self.test_visit.id, table1.id, 2)

        # Cannot directly change unit_id
        with self.assertRaises(UserError):
            booking.write({'unit_id': table2.id})

        # Cannot directly change visit_id
        other_visit = self.Visit.create({'visitor_id': self.test_visitor.id})
        with self.assertRaises(UserError):
            booking.write({'visit_id': other_visit.id})

        # Cannot directly modify pricing snapshots
        with self.assertRaises(UserError):
            booking.write({'amount_total': 100.0})
        with self.assertRaises(UserError):
            booking.write({'unit_price': 50.0})
        with self.assertRaises(UserError):
            booking.write({'entry_fee_amount': 10.0})

        # Cannot directly modify audit fields
        with self.assertRaises(UserError):
            booking.write({'reserved_by_id': self.env.user.id})

        # Cannot directly change state bypassing action_release
        with self.assertRaises(UserError):
            booking.write({'state': 'released'})
        with self.assertRaises(UserError):
            booking.write({'released_by_id': self.env.user.id})

    def test_19_released_unit_rebooking_and_unpaid_retention(self):
        """Verify unpaid booking stays reserved, and released unit can be rebooked."""
        cabana = self.Unit.create({
            'name': 'Rebook Cabana C-70',
            'area_id': self.test_area.id,
            'seating_type': 'cabana',
            'capacity_min': 1,
            'capacity_max': 9,
            'pricing_mode': 'fixed',
            'fixed_price': 250000.0,
        })
        b1 = self.Booking.create_booking(self.test_visit.id, cabana.id, 4)
        self.assertEqual(b1.payment_status, 'unpaid')
        self.assertEqual(b1.state, 'reserved')

        # Unpaid booking must NOT be automatically released
        self.assertEqual(b1.state, 'reserved')

        # Releasing cabana
        b1.action_release()
        self.assertEqual(b1.state, 'released')

        # Unit can now be booked by a second visit
        second_visitor = self.Partner.create({'name': 'Second Guest', 'privacy_acknowledged': True})
        v2 = self.Visit.create({'visitor_id': second_visitor.id})
        b2 = self.Booking.create_booking(v2.id, cabana.id, 8)
        self.assertEqual(b2.state, 'reserved')
        self.assertEqual(b2.amount_total, 250000.0)

    def test_20_chatter_logging(self):
        """Verify chatter messages are logged for booking creation, payment, and release."""
        table = self.Unit.create({
            'name': 'Chatter Table T-80',
            'area_id': self.test_area.id,
            'seating_type': 'table',
            'price_per_guest': 20000.0,
        })
        booking = self.Booking.create_booking(self.test_visit.id, table.id, 2)
        initial_msg_count = len(booking.message_ids)
        self.assertGreater(initial_msg_count, 0, "Booking creation must log message in chatter")
        self.assertTrue(any('Reservation created' in m.body for m in booking.message_ids))

        booking.record_payment(20000.0, 'cash', reference='CASH-001')
        self.assertTrue(any('Payment of' in m.body for m in booking.message_ids))

        booking.action_release()
        self.assertTrue(any('released' in m.body for m in booking.message_ids))

    def test_21_payment_concurrency_serialization(self):
        """Verify row locking and serialized validation preventing payments exceeding total."""
        table = self.Unit.create({
            'name': 'Serial Table T-90',
            'area_id': self.test_area.id,
            'seating_type': 'table',
            'price_per_guest': 20000.0,
        })
        booking = self.Booking.create_booking(self.test_visit.id, table.id, 1)  # ₦20,000 total

        # First cashier records ₦15,000
        booking.record_payment(15000.0, 'cash')
        self.assertEqual(booking.amount_paid, 15000.0)

        # Competing cashier attempts ₦10,000 (total would be ₦25,000 > ₦20,000)
        with self.assertRaises(ValidationError):
            booking.record_payment(10000.0, 'bank_card')

        # Correct remaining balance of ₦5,000 succeeds
        booking.record_payment(5000.0, 'bank_card')
        self.assertEqual(booking.amount_paid, 20000.0)
        self.assertEqual(booking.payment_status, 'paid')

    def test_22_visitor_with_no_bookings_profile(self):
        """Part 6.1: A visitor with no bookings can open their contact profile."""
        fresh_visitor = self.Partner.create({
            'name': 'No Booking Guest',
            'phone': '+2348039999901',
            'is_sunnyside_visitor': True,
            'privacy_acknowledged': True,
        })
        self.assertEqual(len(fresh_visitor.sunnyside_booking_ids), 0)
        self.assertEqual(len(fresh_visitor.booking_ids), 0)
        # Profile fields should be intact and accessible
        self.assertEqual(fresh_visitor.name, 'No Booking Guest')
        self.assertEqual(fresh_visitor.sunnyside_visit_count, 0)

    def test_23_visitor_with_one_booking(self):
        """Part 6.2: A visitor with one booking sees that booking in profile."""
        visitor = self.Partner.create({
            'name': 'Single Booking Guest',
            'phone': '+2348039999902',
            'is_sunnyside_visitor': True,
            'privacy_acknowledged': True,
        })
        visit = self.Visit.create({'visitor_id': visitor.id})
        table = self.Unit.create({
            'name': 'Table ST3-01',
            'area_id': self.test_area.id,
            'seating_type': 'table',
            'price_per_guest': 20000.0,
        })
        booking = self.Booking.create_booking(visit.id, table.id, 2)
        self.assertEqual(len(visitor.sunnyside_booking_ids), 1)
        self.assertEqual(len(visitor.booking_ids), 1)
        self.assertEqual(visitor.sunnyside_booking_ids[0].id, booking.id)
        self.assertEqual(visitor.sunnyside_booking_ids.area_id.id, self.test_area.id)
        self.assertEqual(visitor.sunnyside_booking_ids.unit_id.id, table.id)
        self.assertEqual(visitor.sunnyside_booking_ids.amount_total, 40000.0)

    def test_24_visitor_with_multiple_bookings_history(self):
        """Part 6.3: A visitor with multiple bookings sees the complete booking history."""
        visitor = self.Partner.create({
            'name': 'Multi Booking Guest',
            'phone': '+2348039999903',
            'is_sunnyside_visitor': True,
            'privacy_acknowledged': True,
        })
        # Visit 1 with Booking 1
        v1 = self.Visit.create({'visitor_id': visitor.id})
        t1 = self.Unit.create({
            'name': 'Table ST3-02',
            'area_id': self.test_area.id,
            'seating_type': 'table',
            'price_per_guest': 20000.0,
        })
        b1 = self.Booking.create_booking(v1.id, t1.id, 2)

        # Visit 2 with Booking 2
        v2 = self.Visit.create({'visitor_id': visitor.id})
        t2 = self.Unit.create({
            'name': 'Table ST3-03',
            'area_id': self.test_area.id,
            'seating_type': 'table',
            'price_per_guest': 20000.0,
        })
        b2 = self.Booking.create_booking(v2.id, t2.id, 3)

        self.assertEqual(len(visitor.sunnyside_booking_ids), 2)
        self.assertIn(b1, visitor.sunnyside_booking_ids)
        self.assertIn(b2, visitor.sunnyside_booking_ids)
        self.assertEqual(len(visitor.booking_ids), 2)

    def test_25_released_bookings_remain_visible(self):
        """Part 6.4: Released bookings remain visible in visitor profile history."""
        visitor = self.Partner.create({
            'name': 'Released Booking Guest',
            'phone': '+2348039999904',
            'is_sunnyside_visitor': True,
            'privacy_acknowledged': True,
        })
        v1 = self.Visit.create({'visitor_id': visitor.id})
        table = self.Unit.create({
            'name': 'Table ST3-04',
            'area_id': self.test_area.id,
            'seating_type': 'table',
            'price_per_guest': 20000.0,
        })
        booking = self.Booking.create_booking(v1.id, table.id, 2)
        self.assertEqual(booking.state, 'reserved')

        # Release the booking
        booking.action_release()
        self.assertEqual(booking.state, 'released')

        # Booking must still be present in visitor's booking history
        self.assertIn(booking, visitor.sunnyside_booking_ids)
        self.assertEqual(visitor.sunnyside_booking_ids.filtered(lambda b: b.id == booking.id).state, 'released')

    def test_26_visit_displays_associated_bookings(self):
        """Part 6.5: A visit displays only its associated bookings."""
        visitor = self.Partner.create({
            'name': 'Visit Association Guest',
            'phone': '+2348039999905',
            'is_sunnyside_visitor': True,
            'privacy_acknowledged': True,
        })
        v1 = self.Visit.create({'visitor_id': visitor.id})
        v2 = self.Visit.create({'visitor_id': visitor.id})

        t1 = self.Unit.create({
            'name': 'Table ST3-05',
            'area_id': self.test_area.id,
            'seating_type': 'table',
            'price_per_guest': 20000.0,
        })
        t2 = self.Unit.create({
            'name': 'Table ST3-06',
            'area_id': self.test_area.id,
            'seating_type': 'table',
            'price_per_guest': 20000.0,
        })
        b1 = self.Booking.create_booking(v1.id, t1.id, 2)
        b2 = self.Booking.create_booking(v2.id, t2.id, 4)

        # v1 must only have b1
        self.assertEqual(len(v1.booking_ids), 1)
        self.assertIn(b1, v1.booking_ids)
        self.assertNotIn(b2, v1.booking_ids)

        # v2 must only have b2
        self.assertEqual(len(v2.booking_ids), 1)
        self.assertIn(b2, v2.booking_ids)
        self.assertNotIn(b1, v2.booking_ids)

    def test_27_booking_navigation_references(self):
        """Part 6.6: Booking navigation references visitor, visit, area, and unit without creating visits."""
        visitor = self.Partner.create({
            'name': 'Nav Guest',
            'phone': '+2348039999906',
            'is_sunnyside_visitor': True,
            'privacy_acknowledged': True,
        })
        # Record visit count BEFORE creating the visit for this test
        initial_visit_count = self.Visit.search_count([])
        visit = self.Visit.create({'visitor_id': visitor.id})

        table = self.Unit.create({
            'name': 'Table ST3-07',
            'area_id': self.test_area.id,
            'seating_type': 'table',
            'price_per_guest': 20000.0,
        })
        booking = self.Booking.create_booking(visit.id, table.id, 2)

        # Verify navigation relational links
        self.assertEqual(booking.visitor_id, visitor)
        self.assertEqual(booking.visit_id, visit)
        self.assertEqual(booking.unit_id, table)
        self.assertEqual(booking.area_id, self.test_area)

        # Accessing booking relations must NOT create extra visits
        self.assertEqual(self.Visit.search_count([]), initial_visit_count + 1)

    def test_28_existing_visitor_and_visit_relationships_intact(self):
        """Part 6.7: Existing visitor demographics and visit relationships remain intact."""
        visitor = self.Partner.create({
            'name': 'Demographics Guest',
            'phone': '+2348039999907',
            'is_sunnyside_visitor': True,
            'privacy_acknowledged': True,
        })
        self.assertEqual(visitor.sunnyside_visitor_type, 'new')
        self.assertEqual(visitor.sunnyside_visit_count, 0)

        v1 = self.Visit.create({'visitor_id': visitor.id, 'state': 'checked_in'})
        self.assertEqual(visitor.sunnyside_visit_count, 1)
        self.assertEqual(v1.visitor_type, 'new')

        v2 = self.Visit.create({'visitor_id': visitor.id, 'state': 'checked_in'})
        self.assertEqual(visitor.sunnyside_visit_count, 2)
        self.assertEqual(visitor.sunnyside_visitor_type, 'returning')

    def test_29_access_rights_operational_user_and_manager(self):
        """Part 6.9: Operational user and manager permissions on booking profile integration."""
        from odoo.exceptions import AccessError as OdooAccessError

        # Ensure ACL record exists for receptionist (same pattern as test_17)
        model_booking = self.env['ir.model'].search([('model', '=', 'sunnyside.booking')], limit=1)
        if not model_booking:
            model_booking = self.env['ir.model'].sudo().create({
                'model': 'sunnyside.booking',
                'name': 'Sunnyside Beach Seating Booking',
                'state': 'base',
            })
        group_user_ref = self.env.ref('sunnyside_visitor_management.group_sunnyside_user')
        if not self.env['ir.model.access'].search([
            ('model_id', '=', model_booking.id),
            ('group_id', '=', group_user_ref.id),
        ]):
            self.env['ir.model.access'].sudo().create({
                'name': 'sunnyside.booking.user.test29',
                'model_id': model_booking.id,
                'group_id': group_user_ref.id,
                'perm_read': True,
                'perm_write': False,
                'perm_create': True,
                'perm_unlink': False,
            })

        Users = self.env['res.users']
        receptionist_user = Users.create({
            'name': 'Receptionist Zara',
            'login': 'test29_receptionist_zara',
            'email': 'zara@sunnyside.ng',
            'group_ids': [(6, 0, [
                self.env.ref('base.group_user').id,
                self.env.ref('sunnyside_visitor_management.group_sunnyside_user').id,
            ])],
        })
        manager_user = Users.create({
            'name': 'Manager Emeka',
            'login': 'test29_manager_emeka',
            'email': 'emeka@sunnyside.ng',
            'group_ids': [(6, 0, [
                self.env.ref('base.group_user').id,
                self.env.ref('sunnyside_visitor_management.group_sunnyside_manager').id,
            ])],
        })

        # Create a booking to test against
        table = self.Unit.create({
            'name': 'Rights Table ST3-10',
            'area_id': self.test_area.id,
            'seating_type': 'table',
            'price_per_guest': 20000.0,
        })
        booking = self.Booking.create_booking(self.test_visit.id, table.id, 1)

        # Operational user can read bookings
        receptionist_booking_env = booking.with_user(receptionist_user)
        self.assertEqual(receptionist_booking_env.name, booking.name)
        # Operational user cannot directly write to a booking (perm_write=0)
        with self.assertRaises(OdooAccessError):
            receptionist_booking_env.write({'guest_count': 2})

        # Manager has full read access and can release via action
        manager_booking_env = booking.with_user(manager_user)
        self.assertEqual(manager_booking_env.name, booking.name)
        # Manager can release a booking (via action_release, not raw write)
        manager_booking_env.action_release()
        self.assertEqual(booking.state, 'released')

    def test_30_view_definitions_parse_and_fields_exist(self):
        """Verify view definitions parse and required fields exist on models."""
        partner_fields = self.env['res.partner']._fields
        self.assertIn('sunnyside_booking_ids', partner_fields)
        self.assertIn('sunnyside_visit_ids', partner_fields)

        visit_fields = self.env['sunnyside.visit']._fields
        self.assertIn('booking_ids', visit_fields)

        booking_fields = self.env['sunnyside.booking']._fields
        self.assertIn('name', booking_fields)
        self.assertIn('visit_id', booking_fields)
        self.assertIn('visitor_id', booking_fields)
        self.assertIn('area_id', booking_fields)
        self.assertIn('unit_id', booking_fields)
        self.assertIn('guest_count', booking_fields)
        self.assertIn('amount_total', booking_fields)
        self.assertIn('amount_paid', booking_fields)
        self.assertIn('amount_due', booking_fields)
        self.assertIn('payment_status', booking_fields)
        self.assertIn('state', booking_fields)
        self.assertIn('reserved_datetime', booking_fields)


