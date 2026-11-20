# -*- coding: utf-8 -*-
"""
Stage 4 Tests: Receptionist Check-in Wizard Integration
Tests the extended wizard covering seating assignment and payment capture.
"""
from odoo import fields
from odoo.exceptions import ValidationError, UserError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestSunnysideCheckinWizard(TransactionCase):
    """
    Tests for the Stage 4 extended receptionist check-in wizard.
    All seating units, areas, visitors, and payments are created fresh inside
    each test transaction (rolled back automatically) — no live data seeding.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Ensure schema prerequisites for the unupgraded database
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
            ADD COLUMN IF NOT EXISTS visitor_type varchar,
            ADD COLUMN IF NOT EXISTS booking_ids integer;

            CREATE TABLE IF NOT EXISTS sunnyside_seating_area (
                id serial primary key,
                name varchar not null,
                sequence integer default 10,
                active boolean default true,
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
                price_per_guest numeric default 20000,
                fixed_price numeric default 0,
                entry_fee_amount numeric default 5000,
                minimum_spend_amount numeric default 15000,
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
                name varchar,
                unit_id integer not null,
                image_data text,
                caption varchar,
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

            CREATE TABLE IF NOT EXISTS sunnyside_dashboard (
                id serial primary key,
                name varchar,
                create_uid integer,
                create_date timestamp without time zone,
                write_uid integer,
                write_date timestamp without time zone
            );

            CREATE TABLE IF NOT EXISTS sunnyside_checkin_wizard (
                id serial primary key,
                phone varchar,
                country_dial_code varchar,
                visitor_id integer,
                is_existing_visitor boolean,
                name varchar,
                location_id integer,
                visitor_status_banner text,
                source varchar,
                seating_area_id integer,
                seating_unit_id integer,
                guest_count integer default 1,
                estimated_price numeric default 0,
                currency_id integer,
                payment_amount numeric default 0,
                payment_method varchar default 'cash',
                payment_reference varchar,
                estimated_outstanding numeric default 0,
                create_uid integer,
                create_date timestamp without time zone,
                write_uid integer,
                write_date timestamp without time zone
            );

            -- Idempotent column additions: needed when test_visitor_flow's setUpClass
            -- already created the table with the original minimal schema before this
            -- setUpClass runs. CREATE TABLE IF NOT EXISTS above silently skips in that
            -- case, so we must ALTER TABLE to ensure every Stage 4 column exists.
            ALTER TABLE sunnyside_checkin_wizard ADD COLUMN IF NOT EXISTS seating_area_id integer;
            ALTER TABLE sunnyside_checkin_wizard ADD COLUMN IF NOT EXISTS seating_unit_id integer;
            ALTER TABLE sunnyside_checkin_wizard ADD COLUMN IF NOT EXISTS guest_count integer;
            ALTER TABLE sunnyside_checkin_wizard ADD COLUMN IF NOT EXISTS estimated_price numeric;
            ALTER TABLE sunnyside_checkin_wizard ADD COLUMN IF NOT EXISTS currency_id integer;
            ALTER TABLE sunnyside_checkin_wizard ADD COLUMN IF NOT EXISTS payment_amount numeric;
            ALTER TABLE sunnyside_checkin_wizard ADD COLUMN IF NOT EXISTS payment_method varchar;
            ALTER TABLE sunnyside_checkin_wizard ADD COLUMN IF NOT EXISTS payment_reference varchar;
            ALTER TABLE sunnyside_checkin_wizard ADD COLUMN IF NOT EXISTS estimated_outstanding numeric;

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
        self.Booking = self.env['sunnyside.booking']
        self.Wizard = self.env['sunnyside.checkin.wizard']

        # Shared location
        self.test_location = self.Location.search([('active', '=', True)], limit=1)
        if not self.test_location:
            self.test_location = self.Location.create({'name': 'Ikeja', 'active': True})

        # Shared seating area
        self.test_area = self.Area.create({
            'name': 'Wizard Test Deck',
            'sequence': 99,
            'active': True,
        })

        # Standard table unit
        self.table_unit = self.Unit.create({
            'name': 'Wizard Table W-01',
            'area_id': self.test_area.id,
            'seating_type': 'table',
            'price_per_guest': 20000.0,
        })

        # Beachfront seat unit
        self.beach_unit = self.Unit.create({
            'name': 'Wizard Beach B-01',
            'area_id': self.test_area.id,
            'seating_type': 'beachfront_seat',
        })

        # Cabana unit
        self.cabana_unit = self.Unit.create({
            'name': 'Wizard Cabana C-01',
            'area_id': self.test_area.id,
            'seating_type': 'cabana',
        })

    # -------------------------------------------------------------------------
    # Test 1: Existing visitor check-in still works (no seating)
    # -------------------------------------------------------------------------
    def test_01_existing_visitor_checkin_no_seating(self):
        """Existing visitor check-in without seating selection returns visit form."""
        visitor = self.Partner.sudo().create({
            'name': 'Ada Okafor',
            'phone': '+2348031110001',
            'is_sunnyside_visitor': True,
            'sunnyside_location_id': self.test_location.id,
            'privacy_acknowledged': True,
        })
        initial_partner_count = self.Partner.search_count([])
        initial_visit_count = self.Visit.search_count([])
        initial_booking_count = self.Booking.search_count([])

        wizard = self.Wizard.create({
            'phone': '+2348031110001',
            'country_dial_code': '234',
        })
        result = wizard.action_confirm_checkin()

        # Returns visit form
        self.assertEqual(result['res_model'], 'sunnyside.visit')
        # No new partner created
        self.assertEqual(self.Partner.search_count([]), initial_partner_count)
        # Exactly one new visit
        self.assertEqual(self.Visit.search_count([]), initial_visit_count + 1)
        # No booking created
        self.assertEqual(self.Booking.search_count([]), initial_booking_count)

    # -------------------------------------------------------------------------
    # Test 2: New visitor check-in still works (no seating)
    # -------------------------------------------------------------------------
    def test_02_new_visitor_checkin_no_seating(self):
        """New visitor check-in without seating creates partner + visit, returns visit form."""
        initial_partner_count = self.Partner.search_count([])
        initial_visit_count = self.Visit.search_count([])
        initial_booking_count = self.Booking.search_count([])

        wizard = self.Wizard.create({
            'phone': '+2348031110002',
            'country_dial_code': '234',
            'name': 'Chukwuemeka Nwosu',
            'location_id': self.test_location.id,
        })
        result = wizard.action_confirm_checkin()

        self.assertEqual(result['res_model'], 'sunnyside.visit')
        self.assertEqual(self.Partner.search_count([]), initial_partner_count + 1)
        self.assertEqual(self.Visit.search_count([]), initial_visit_count + 1)
        self.assertEqual(self.Booking.search_count([]), initial_booking_count)

    # -------------------------------------------------------------------------
    # Test 3: Existing visitor is NOT duplicated
    # -------------------------------------------------------------------------
    def test_03_existing_visitor_not_duplicated(self):
        """Re-checking an existing phone creates a new visit but no new partner."""
        self.Partner.sudo().create({
            'name': 'Fatima Abubakar',
            'phone': '+2348031110003',
            'is_sunnyside_visitor': True,
            'privacy_acknowledged': True,
        })
        initial_partner_count = self.Partner.search_count([])

        wizard = self.Wizard.create({'phone': '+2348031110003', 'country_dial_code': '234'})
        wizard.action_confirm_checkin()

        self.assertEqual(self.Partner.search_count([]), initial_partner_count)

    # -------------------------------------------------------------------------
    # Test 4: Exactly one visit created when seating is assigned
    # -------------------------------------------------------------------------
    def test_04_exactly_one_visit_with_seating(self):
        """Assigning a seat must create exactly 1 visit and 1 booking, no extra visits."""
        visitor = self.Partner.sudo().create({
            'name': 'Obinna Eze',
            'phone': '+2348031110004',
            'is_sunnyside_visitor': True,
            'privacy_acknowledged': True,
        })
        initial_visit_count = self.Visit.search_count([])

        wizard = self.Wizard.create({
            'phone': '+2348031110004',
            'country_dial_code': '234',
            'seating_area_id': self.test_area.id,
            'seating_unit_id': self.table_unit.id,
            'guest_count': 2,
        })
        result = wizard.action_confirm_checkin()

        self.assertEqual(result['res_model'], 'sunnyside.booking')
        new_visits = self.Visit.search_count([]) - initial_visit_count
        self.assertEqual(new_visits, 1, "Exactly 1 visit must be created when seating is assigned")

    # -------------------------------------------------------------------------
    # Test 5: Booking linked to correct visit and visitor
    # -------------------------------------------------------------------------
    def test_05_booking_linked_to_visit_and_visitor(self):
        """Booking created by wizard must reference the correct visit and visitor."""
        visitor = self.Partner.sudo().create({
            'name': 'Sade Balogun',
            'phone': '+2348031110005',
            'is_sunnyside_visitor': True,
            'privacy_acknowledged': True,
        })
        wizard = self.Wizard.create({
            'phone': '+2348031110005',
            'country_dial_code': '234',
            'seating_area_id': self.test_area.id,
            'seating_unit_id': self.table_unit.id,
            'guest_count': 1,
        })
        result = wizard.action_confirm_checkin()

        booking = self.Booking.browse(result['res_id'])
        self.assertTrue(booking.exists())
        self.assertEqual(booking.visitor_id.id, visitor.id)
        # Visit linked to booking must belong to this visitor
        self.assertEqual(booking.visit_id.visitor_id.id, visitor.id)
        self.assertEqual(booking.visit_id.state, 'checked_in')

    # -------------------------------------------------------------------------
    # Test 6: Valid standard table booking
    # -------------------------------------------------------------------------
    def test_06_valid_standard_table_booking(self):
        """Standard table booking: 2 guests → ₦40,000 total."""
        self.Partner.sudo().create({
            'name': 'Taiwo Adekunle',
            'phone': '+2348031110006',
            'is_sunnyside_visitor': True,
            'privacy_acknowledged': True,
        })
        wizard = self.Wizard.create({
            'phone': '+2348031110006',
            'country_dial_code': '234',
            'seating_area_id': self.test_area.id,
            'seating_unit_id': self.table_unit.id,
            'guest_count': 2,
        })
        result = wizard.action_confirm_checkin()

        booking = self.Booking.browse(result['res_id'])
        self.assertEqual(booking.seating_type, 'table')
        self.assertEqual(booking.guest_count, 2)
        self.assertEqual(booking.amount_total, 40000.0)
        self.assertEqual(booking.state, 'reserved')

    # -------------------------------------------------------------------------
    # Test 7: Valid beachfront seat booking (exactly 1 guest)
    # -------------------------------------------------------------------------
    def test_07_valid_beachfront_seat_booking(self):
        """Beachfront seat booking: 1 guest → ₦20,000 total."""
        self.Partner.sudo().create({
            'name': 'Yemi Adeyemi',
            'phone': '+2348031110007',
            'is_sunnyside_visitor': True,
            'privacy_acknowledged': True,
        })
        wizard = self.Wizard.create({
            'phone': '+2348031110007',
            'country_dial_code': '234',
            'seating_area_id': self.test_area.id,
            'seating_unit_id': self.beach_unit.id,
            'guest_count': 1,
        })
        result = wizard.action_confirm_checkin()

        booking = self.Booking.browse(result['res_id'])
        self.assertEqual(booking.seating_type, 'beachfront_seat')
        self.assertEqual(booking.guest_count, 1)
        self.assertEqual(booking.amount_total, 20000.0)

    # -------------------------------------------------------------------------
    # Test 8: Valid cabana booking
    # -------------------------------------------------------------------------
    def test_08_valid_cabana_booking(self):
        """Cabana booking: 5 guests → ₦250,000 fixed total."""
        self.Partner.sudo().create({
            'name': 'Kemi Oladipo',
            'phone': '+2348031110008',
            'is_sunnyside_visitor': True,
            'privacy_acknowledged': True,
        })
        wizard = self.Wizard.create({
            'phone': '+2348031110008',
            'country_dial_code': '234',
            'seating_area_id': self.test_area.id,
            'seating_unit_id': self.cabana_unit.id,
            'guest_count': 5,
        })
        result = wizard.action_confirm_checkin()

        booking = self.Booking.browse(result['res_id'])
        self.assertEqual(booking.seating_type, 'cabana')
        self.assertEqual(booking.amount_total, 250000.0)
        self.assertEqual(booking.state, 'reserved')

    # -------------------------------------------------------------------------
    # Test 9: Invalid guest counts are rejected
    # -------------------------------------------------------------------------
    def test_09_invalid_guest_counts_rejected(self):
        """Oversized and undersized guest counts must be rejected by the wizard."""
        self.Partner.sudo().create({
            'name': 'Dayo Ogundimu',
            'phone': '+2348031110009',
            'is_sunnyside_visitor': True,
            'privacy_acknowledged': True,
        })
        # Table: max 4 guests
        wizard = self.Wizard.create({
            'phone': '+2348031110009',
            'country_dial_code': '234',
            'seating_area_id': self.test_area.id,
            'seating_unit_id': self.table_unit.id,
            'guest_count': 5,
        })
        with self.assertRaises(ValidationError):
            wizard.action_confirm_checkin()

        # Beachfront seat: must be exactly 1
        wizard2 = self.Wizard.create({
            'phone': '+2348031110009',
            'country_dial_code': '234',
            'seating_area_id': self.test_area.id,
            'seating_unit_id': self.beach_unit.id,
            'guest_count': 2,
        })
        with self.assertRaises(ValidationError):
            wizard2.action_confirm_checkin()

        # Zero guests rejected
        wizard3 = self.Wizard.create({
            'phone': '+2348031110009',
            'country_dial_code': '234',
            'seating_area_id': self.test_area.id,
            'seating_unit_id': self.table_unit.id,
            'guest_count': 0,
        })
        with self.assertRaises(ValidationError):
            wizard3.action_confirm_checkin()

    # -------------------------------------------------------------------------
    # Test 10: Inactive seating units cannot be selected
    # -------------------------------------------------------------------------
    def test_10_inactive_unit_rejected(self):
        """An inactive seating unit must be rejected by the wizard validation."""
        self.Partner.sudo().create({
            'name': 'Biodun Fashola',
            'phone': '+2348031110010',
            'is_sunnyside_visitor': True,
            'privacy_acknowledged': True,
        })
        inactive_unit = self.Unit.create({
            'name': 'Archived Table W-02',
            'area_id': self.test_area.id,
            'seating_type': 'table',
            'active': False,
        })
        wizard = self.Wizard.create({
            'phone': '+2348031110010',
            'country_dial_code': '234',
            'seating_area_id': self.test_area.id,
            'seating_unit_id': inactive_unit.id,
            'guest_count': 1,
        })
        with self.assertRaises(ValidationError):
            wizard.action_confirm_checkin()

    # -------------------------------------------------------------------------
    # Test 11: Already-reserved unit cannot be double-booked
    # -------------------------------------------------------------------------
    def test_11_already_reserved_unit_rejected(self):
        """A unit that already has an active reservation must be rejected."""
        # Reserve the table unit directly first
        visitor1 = self.Partner.sudo().create({
            'name': 'Tunde Adewale', 'phone': '+2348031110113',
            'is_sunnyside_visitor': True, 'privacy_acknowledged': True,
        })
        v1 = self.Visit.create({'visitor_id': visitor1.id, 'state': 'checked_in'})
        self.Booking.create_booking(v1.id, self.table_unit.id, 1)

        # Now try via wizard
        visitor2 = self.Partner.sudo().create({
            'name': 'Ngozi Okonkwo', 'phone': '+2348031110114',
            'is_sunnyside_visitor': True, 'privacy_acknowledged': True,
        })
        wizard = self.Wizard.create({
            'phone': '+2348031110114',
            'country_dial_code': '234',
            'seating_area_id': self.test_area.id,
            'seating_unit_id': self.table_unit.id,
            'guest_count': 1,
        })
        with self.assertRaises(ValidationError):
            wizard.action_confirm_checkin()

    # -------------------------------------------------------------------------
    # Test 12: Zero payment creates no payment record
    # -------------------------------------------------------------------------
    def test_12_zero_payment_creates_no_payment_record(self):
        """When payment_amount is 0, no sunnyside.booking.payment is created."""
        self.Partner.sudo().create({
            'name': 'Emeka Obi',
            'phone': '+2348031110012',
            'is_sunnyside_visitor': True,
            'privacy_acknowledged': True,
        })
        wizard = self.Wizard.create({
            'phone': '+2348031110012',
            'country_dial_code': '234',
            'seating_area_id': self.test_area.id,
            'seating_unit_id': self.table_unit.id,
            'guest_count': 1,
            'payment_amount': 0.0,
        })
        result = wizard.action_confirm_checkin()
        booking = self.Booking.browse(result['res_id'])
        self.assertEqual(len(booking.payment_ids), 0)
        self.assertEqual(booking.payment_status, 'unpaid')

    # -------------------------------------------------------------------------
    # Test 13: Partial payment is recorded correctly
    # -------------------------------------------------------------------------
    def test_13_partial_payment_recorded(self):
        """Partial payment creates one payment record and sets status to 'partial'."""
        self.Partner.sudo().create({
            'name': 'Aisha Bello',
            'phone': '+2348031110013',
            'is_sunnyside_visitor': True,
            'privacy_acknowledged': True,
        })
        wizard = self.Wizard.create({
            'phone': '+2348031110013',
            'country_dial_code': '234',
            'seating_area_id': self.test_area.id,
            'seating_unit_id': self.table_unit.id,
            'guest_count': 2,            # ₦40,000 total
            'payment_amount': 20000.0,   # ₦20,000 partial
            'payment_method': 'cash',
        })
        result = wizard.action_confirm_checkin()
        booking = self.Booking.browse(result['res_id'])

        self.assertEqual(len(booking.payment_ids), 1)
        self.assertEqual(booking.payment_ids[0].amount, 20000.0)
        self.assertEqual(booking.payment_ids[0].payment_method, 'cash')
        self.assertEqual(booking.payment_status, 'partial')
        self.assertEqual(booking.amount_paid, 20000.0)
        self.assertEqual(booking.amount_due, 20000.0)

    # -------------------------------------------------------------------------
    # Test 14: Full payment is recorded correctly
    # -------------------------------------------------------------------------
    def test_14_full_payment_recorded(self):
        """Full payment creates one payment record and sets status to 'paid'."""
        self.Partner.sudo().create({
            'name': 'Chika Obi',
            'phone': '+2348031110014',
            'is_sunnyside_visitor': True,
            'privacy_acknowledged': True,
        })
        wizard = self.Wizard.create({
            'phone': '+2348031110014',
            'country_dial_code': '234',
            'seating_area_id': self.test_area.id,
            'seating_unit_id': self.table_unit.id,
            'guest_count': 1,           # ₦20,000 total
            'payment_amount': 20000.0,  # Full payment
            'payment_method': 'bank_card',
            'payment_reference': 'POS-WIZ-001',
        })
        result = wizard.action_confirm_checkin()
        booking = self.Booking.browse(result['res_id'])

        self.assertEqual(len(booking.payment_ids), 1)
        self.assertEqual(booking.payment_ids[0].payment_method, 'bank_card')
        self.assertEqual(booking.payment_ids[0].reference, 'POS-WIZ-001')
        self.assertEqual(booking.payment_status, 'paid')
        self.assertEqual(booking.amount_due, 0.0)

    # -------------------------------------------------------------------------
    # Test 15: Overpayment is rejected before any data is written
    # -------------------------------------------------------------------------
    def test_15_overpayment_rejected(self):
        """An amount exceeding the booking total must raise ValidationError."""
        self.Partner.sudo().create({
            'name': 'Jide Kosoko',
            'phone': '+2348031110015',
            'is_sunnyside_visitor': True,
            'privacy_acknowledged': True,
        })
        wizard = self.Wizard.create({
            'phone': '+2348031110015',
            'country_dial_code': '234',
            'seating_area_id': self.test_area.id,
            'seating_unit_id': self.table_unit.id,
            'guest_count': 1,           # ₦20,000 total
            'payment_amount': 25000.0,  # Overpayment
            'payment_method': 'cash',
        })
        with self.assertRaises(ValidationError):
            wizard.action_confirm_checkin()

    # -------------------------------------------------------------------------
    # Test 16: Invalid payment method rejected
    # -------------------------------------------------------------------------
    def test_16_invalid_payment_method_rejected(self):
        """An unrecognised payment_method value must raise an error.

        When 'crypto' (not a valid selection value) is supplied the ORM
        raises ValueError at create() time before action_confirm_checkin()
        is called.  Both ValueError and ValidationError represent rejection,
        so either is acceptable evidence that the system refuses the value.
        """
        self.Partner.sudo().create({
            'name': 'Femi Bankole',
            'phone': '+2348031110016',
            'is_sunnyside_visitor': True,
            'privacy_acknowledged': True,
        })
        try:
            wizard = self.Wizard.create({
                'phone': '+2348031110016',
                'country_dial_code': '234',
                'seating_area_id': self.test_area.id,
                'seating_unit_id': self.table_unit.id,
                'guest_count': 1,
                'payment_amount': 10000.0,
                'payment_method': 'crypto',   # Invalid — ORM raises ValueError
            })
            # If create() somehow succeeded, the action must reject it
            with self.assertRaises(ValidationError):
                wizard.action_confirm_checkin()
        except (ValidationError, ValueError):
            pass  # Either exception confirms the invalid value was rejected

    # -------------------------------------------------------------------------
    # Test 17: Payment failure rolls back the entire transaction
    # -------------------------------------------------------------------------
    def test_17_payment_failure_rolls_back_transaction(self):
        """
        If payment recording fails (overpayment), the visit and booking
        created earlier in the same transaction must also be rolled back.
        """
        self.Partner.sudo().create({
            'name': 'Ireti Doyle',
            'phone': '+2348031110017',
            'is_sunnyside_visitor': True,
            'privacy_acknowledged': True,
        })
        initial_visit_count = self.Visit.search_count([])
        initial_booking_count = self.Booking.search_count([])

        wizard = self.Wizard.create({
            'phone': '+2348031110017',
            'country_dial_code': '234',
            'seating_area_id': self.test_area.id,
            'seating_unit_id': self.table_unit.id,
            'guest_count': 1,           # ₦20,000 total
            'payment_amount': 25000.0,  # Will fail
            'payment_method': 'cash',
        })
        with self.assertRaises(ValidationError):
            wizard.action_confirm_checkin()

        # Validation occurs pre-commit — wizard-level guards prevent any DB write
        self.assertEqual(self.Visit.search_count([]), initial_visit_count)
        self.assertEqual(self.Booking.search_count([]), initial_booking_count)

    # -------------------------------------------------------------------------
    # Test 18: Booking failure rolls back the entire transaction
    # -------------------------------------------------------------------------
    def test_18_booking_failure_rolls_back_transaction(self):
        """
        If booking creation fails (already reserved unit), the visit created
        in the same call must also be rolled back.
        """
        # Pre-reserve the table unit
        visitor_first = self.Partner.sudo().create({
            'name': 'Chinyere Oguta', 'phone': '+2348031110181',
            'is_sunnyside_visitor': True, 'privacy_acknowledged': True,
        })
        v_first = self.Visit.create({'visitor_id': visitor_first.id, 'state': 'checked_in'})
        self.Booking.create_booking(v_first.id, self.table_unit.id, 1)

        # Second receptionist tries same unit via wizard
        self.Partner.sudo().create({
            'name': 'Olumide Akintunde', 'phone': '+2348031110182',
            'is_sunnyside_visitor': True, 'privacy_acknowledged': True,
        })
        initial_visit_count = self.Visit.search_count([])

        wizard = self.Wizard.create({
            'phone': '+2348031110182',
            'country_dial_code': '234',
            'seating_area_id': self.test_area.id,
            'seating_unit_id': self.table_unit.id,
            'guest_count': 1,
        })
        with self.assertRaises(ValidationError):
            wizard.action_confirm_checkin()

        # The failed wizard must not leave a dangling visit for visitor18b
        new_partner = self.Partner.search([('phone', 'in', ['+2348031110182'])])
        if new_partner:
            new_visits = self.Visit.search([('visitor_id', '=', new_partner.id)])
            self.assertEqual(len(new_visits), 0,
                "No visit should persist when booking creation fails mid-transaction")

    # -------------------------------------------------------------------------
    # Test 19: CRM behavior remains intact after Stage 4 extension
    # -------------------------------------------------------------------------
    def test_19_crm_behavior_intact(self):
        """
        CRM helper calls must still fire as before:
        - New visitor → _handle_new_visitor_crm
        - Returning visitor → _handle_returning_visitor_crm
        These are tested indirectly by ensuring the wizard completes without error.
        """
        # New visitor → no crash from CRM
        wizard_new = self.Wizard.create({
            'phone': '+2348031110191',
            'country_dial_code': '234',
            'name': 'Olawale Festus',
            'location_id': self.test_location.id,
        })
        result_new = wizard_new.action_confirm_checkin()
        self.assertEqual(result_new['res_model'], 'sunnyside.visit')

        # Returning visitor → no crash from CRM
        self.Partner.sudo().create({
            'name': 'Bolade Ogun',
            'phone': '+2348031110192',
            'is_sunnyside_visitor': True,
            'privacy_acknowledged': True,
        })
        wizard_ret = self.Wizard.create({
            'phone': '+2348031110192',
            'country_dial_code': '234',
        })
        result_ret = wizard_ret.action_confirm_checkin()
        self.assertEqual(result_ret['res_model'], 'sunnyside.visit')

    # -------------------------------------------------------------------------
    # Test 20: Payment with bank_transfer method works
    # -------------------------------------------------------------------------
    def test_20_bank_transfer_payment_method(self):
        """bank_transfer payment method must be accepted and stored correctly."""
        self.Partner.sudo().create({
            'name': 'Rotimi Akinola',
            'phone': '+2348031110020',
            'is_sunnyside_visitor': True,
            'privacy_acknowledged': True,
        })
        wizard = self.Wizard.create({
            'phone': '+2348031110020',
            'country_dial_code': '234',
            'seating_area_id': self.test_area.id,
            'seating_unit_id': self.table_unit.id,
            'guest_count': 1,
            'payment_amount': 20000.0,
            'payment_method': 'bank_transfer',
            'payment_reference': 'TRF-20241011-001',
        })
        result = wizard.action_confirm_checkin()
        booking = self.Booking.browse(result['res_id'])
        self.assertEqual(booking.payment_ids[0].payment_method, 'bank_transfer')
        self.assertEqual(booking.payment_status, 'paid')

    # -------------------------------------------------------------------------
    # Test 21: New visitor with seating — all three records created correctly
    # -------------------------------------------------------------------------
    def test_21_new_visitor_with_seating_full_flow(self):
        """
        New visitor + seating + payment: partner, visit, booking, and payment
        records must all be created and correctly linked.
        """
        initial_partner = self.Partner.search_count([])
        initial_visit = self.Visit.search_count([])

        wizard = self.Wizard.create({
            'phone': '+2348031110021',
            'country_dial_code': '234',
            'name': 'Chiamaka Ikenna',
            'location_id': self.test_location.id,
            'seating_area_id': self.test_area.id,
            'seating_unit_id': self.cabana_unit.id,
            'guest_count': 3,
            'payment_amount': 100000.0,
            'payment_method': 'cash',
        })
        result = wizard.action_confirm_checkin()
        self.assertEqual(result['res_model'], 'sunnyside.booking')

        booking = self.Booking.browse(result['res_id'])
        self.assertTrue(booking.exists())
        self.assertEqual(booking.amount_total, 250000.0)
        self.assertEqual(len(booking.payment_ids), 1)
        self.assertEqual(booking.payment_ids[0].amount, 100000.0)
        self.assertEqual(booking.payment_status, 'partial')

        # Partner and visit created
        self.assertEqual(self.Partner.search_count([]), initial_partner + 1)
        self.assertEqual(self.Visit.search_count([]), initial_visit + 1)

        # Booking linked to visit linked to new visitor
        new_visitor = self.Partner.search([('phone', 'like', '2348031110021')], limit=1)
        self.assertTrue(new_visitor)
        self.assertEqual(booking.visitor_id.id, new_visitor.id)
        self.assertEqual(booking.visit_id.visitor_id.id, new_visitor.id)

    # -------------------------------------------------------------------------
    # Test 22: Payment-only wizard field guards — negative amount
    # -------------------------------------------------------------------------
    def test_22_negative_payment_rejected(self):
        """A negative payment_amount must be rejected by wizard validation."""
        self.Partner.sudo().create({
            'name': 'Gbenga Adetokunbo',
            'phone': '+2348031110022',
            'is_sunnyside_visitor': True,
            'privacy_acknowledged': True,
        })
        wizard = self.Wizard.create({
            'phone': '+2348031110022',
            'country_dial_code': '234',
            'seating_area_id': self.test_area.id,
            'seating_unit_id': self.table_unit.id,
            'guest_count': 1,
            'payment_amount': -500.0,
            'payment_method': 'cash',
        })
        with self.assertRaises(ValidationError):
            wizard.action_confirm_checkin()

    # -------------------------------------------------------------------------
    # Test 23: Payment without seating is rejected
    # -------------------------------------------------------------------------
    def test_23_payment_without_seating_rejected(self):
        """Entering a payment amount without selecting a seating unit must fail."""
        self.Partner.sudo().create({
            'name': 'Lanre Olusanya',
            'phone': '+2348031110023',
            'is_sunnyside_visitor': True,
            'privacy_acknowledged': True,
        })
        wizard = self.Wizard.create({
            'phone': '+2348031110023',
            'country_dial_code': '234',
            # No seating_unit_id
            'payment_amount': 5000.0,
            'payment_method': 'cash',
        })
        with self.assertRaises(ValidationError):
            wizard.action_confirm_checkin()
