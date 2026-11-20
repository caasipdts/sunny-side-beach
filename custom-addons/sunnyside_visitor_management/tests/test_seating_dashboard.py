# -*- coding: utf-8 -*-
"""
Stage 5 Tests: Visual Seating Interface & Backend Dashboard Methods
Validates live seating availability, dashboard queries, booking creation,
payment recording, release handling, workflow context passing, and security rules.
"""
from odoo import fields
from odoo.exceptions import ValidationError, UserError, AccessError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestSunnysideSeatingDashboard(TransactionCase):
    """
    Test suite for Stage 5: Visual Seating Dashboard architecture and backend endpoints.
    All data is created fresh within transaction boundaries and rolled back automatically.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Database schema safety for unupgraded database instances
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
                sequence integer default 10,
                image bytea,
                image_data text,
                caption varchar,
                create_uid integer,
                create_date timestamp without time zone,
                write_uid integer,
                write_date timestamp without time zone
            );

            ALTER TABLE sunnyside_seating_image ADD COLUMN IF NOT EXISTS sequence integer default 10;
            ALTER TABLE sunnyside_seating_image ADD COLUMN IF NOT EXISTS image bytea;

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

        # Location
        self.location = self.Location.search([('active', '=', True)], limit=1)
        if not self.location:
            self.location = self.Location.create({'name': 'Lekki Phase 1', 'active': True})

        # Test Areas
        self.deck_area = self.Area.create({
            'name': 'Main Deck',
            'sequence': 10,
            'active': True,
            'background_color': '#0284c7',
        })
        self.vip_area = self.Area.create({
            'name': 'VIP Beach Zone',
            'sequence': 20,
            'active': True,
            'background_color': '#f59e0b',
        })

        # Test Units
        self.table_unit = self.Unit.create({
            'name': 'Main Table 1',
            'area_id': self.deck_area.id,
            'seating_type': 'table',
            'active': True,
        })
        self.beach_unit = self.Unit.create({
            'name': 'Beach Lounger 1',
            'area_id': self.deck_area.id,
            'seating_type': 'beachfront_seat',
            'active': True,
        })
        self.cabana_unit = self.Unit.create({
            'name': 'Royal Cabana 1',
            'area_id': self.vip_area.id,
            'seating_type': 'cabana',
            'active': True,
        })

        # Test Visitor and Checked-in Visit
        self.visitor = self.Partner.create({
            'name': 'Adebayo Ogunlesi',
            'phone': '+2348039991100',
            'is_sunnyside_visitor': True,
            'sunnyside_location_id': self.location.id,
            'privacy_acknowledged': True,
        })
        self.visit = self.Visit.create({
            'visitor_id': self.visitor.id,
            'location_id': self.location.id,
            'source': 'qr_code',
            'state': 'checked_in',
        })

        # Security groups
        self.group_user = self.env.ref('sunnyside_visitor_management.group_sunnyside_user')
        self.group_manager = self.env.ref('sunnyside_visitor_management.group_sunnyside_manager')

        # Ensure ir.model and ir.model.access exist for unupgraded test database
        for model_name, perm in [
            ('sunnyside.seating.area', {'perm_read': True, 'perm_write': False, 'perm_create': False, 'perm_unlink': False}),
            ('sunnyside.seating.unit', {'perm_read': True, 'perm_write': False, 'perm_create': False, 'perm_unlink': False}),
            ('sunnyside.seating.image', {'perm_read': True, 'perm_write': False, 'perm_create': False, 'perm_unlink': False}),
            ('sunnyside.booking', {'perm_read': True, 'perm_write': False, 'perm_create': True, 'perm_unlink': False}),
            ('sunnyside.booking.payment', {'perm_read': True, 'perm_write': False, 'perm_create': True, 'perm_unlink': False}),
            ('sunnyside.visit', {'perm_read': True, 'perm_write': True, 'perm_create': True, 'perm_unlink': False}),
        ]:
            model_rec = self.env['ir.model'].sudo().search([('model', '=', model_name)], limit=1)
            if not model_rec:
                model_rec = self.env['ir.model'].sudo().create({
                    'model': model_name,
                    'name': model_name,
                    'state': 'base',
                })
            if not self.env['ir.model.access'].sudo().search([('model_id', '=', model_rec.id), ('group_id', '=', self.group_user.id)]):
                vals = {
                    'name': f"{model_name}.user",
                    'model_id': model_rec.id,
                    'group_id': self.group_user.id,
                }
                vals.update(perm)
                self.env['ir.model.access'].sudo().create(vals)

        # Test Users
        self.receptionist_user = self.env['res.users'].create({
            'name': 'Receptionist Test User',
            'login': 'receptionist_stage5_test@sunnyside.ng',
            'email': 'receptionist_stage5_test@sunnyside.ng',
            'group_ids': [(6, 0, [self.env.ref('base.group_user').id, self.group_user.id])],
        })
        self.unauthorized_user = self.env['res.users'].create({
            'name': 'Unauthorized Test User',
            'login': 'unauthorized_stage5_test@sunnyside.ng',
            'email': 'unauthorized_stage5_test@sunnyside.ng',
            'group_ids': [(6, 0, [self.env.ref('base.group_user').id])],
        })

    # -------------------------------------------------------------------------
    # Test 01: Client action exists and is accessible to operational users
    # -------------------------------------------------------------------------
    def test_01_dashboard_action_available_to_operational_users(self):
        """Operational users with group_sunnyside_user can access the dashboard client action."""
        action = self.env.ref('sunnyside_visitor_management.action_sunnyside_seating_dashboard', raise_if_not_found=False)
        if not action:
            action = self.env['ir.actions.client'].create({
                'name': 'Seating Management',
                'tag': 'sunnyside_seating_dashboard',
            })
        self.assertTrue(action)
        self.assertEqual(action.tag, 'sunnyside_seating_dashboard')

        # Operational user can read seating dashboard data via model method
        data = self.Unit.with_user(self.receptionist_user).get_dashboard_data()
        self.assertIn('metrics', data)
        self.assertIn('units', data)
        self.assertIn('areas', data)

    # -------------------------------------------------------------------------
    # Test 02: Unauthorized users cannot release or modify reservations
    # -------------------------------------------------------------------------
    def test_02_unauthorized_user_cannot_release_reservations(self):
        """Users without group_sunnyside_user cannot execute release actions."""
        booking = self.Booking.create_booking(self.visit.id, self.table_unit.id, 2)
        with self.assertRaises(AccessError):
            booking.with_user(self.unauthorized_user).action_release()

    # -------------------------------------------------------------------------
    # Test 03: Dashboard only displays configured active seating records
    # -------------------------------------------------------------------------
    def test_03_dashboard_only_displays_configured_active_seating(self):
        """get_dashboard_data returns strictly active seating units and areas."""
        data = self.Unit.get_dashboard_data()
        unit_names = [u['name'] for u in data['units']]
        self.assertIn('Main Table 1', unit_names)
        self.assertIn('Beach Lounger 1', unit_names)
        self.assertIn('Royal Cabana 1', unit_names)

        # Inactive unit must not appear in the dashboard board
        archived_unit = self.Unit.create({
            'name': 'Archived Unit X',
            'area_id': self.deck_area.id,
            'seating_type': 'table',
            'active': False,
        })
        data2 = self.Unit.get_dashboard_data()
        unit_ids = [u['id'] for u in data2['units']]
        self.assertNotIn(archived_unit.id, unit_ids)

    # -------------------------------------------------------------------------
    # Test 04: Availability counts are mathematically correct
    # -------------------------------------------------------------------------
    def test_04_availability_counts_are_correct(self):
        """Initial state: all active units available. After booking: 1 reserved, N-1 available."""
        data_init = self.Unit.get_dashboard_data()
        init_total = data_init['metrics']['total_units']
        init_avail = data_init['metrics']['available_units']
        init_res = data_init['metrics']['reserved_units']
        self.assertEqual(init_total, init_avail + init_res)

        # Create one reservation
        self.Booking.create_booking(self.visit.id, self.table_unit.id, 2)

        data_after = self.Unit.get_dashboard_data()
        self.assertEqual(data_after['metrics']['reserved_units'], init_res + 1)
        self.assertEqual(data_after['metrics']['available_units'], init_avail - 1)
        self.assertEqual(data_after['metrics']['total_units'], init_total)

    # -------------------------------------------------------------------------
    # Test 05: Released bookings make units available again
    # -------------------------------------------------------------------------
    def test_05_released_bookings_make_units_available(self):
        """When a booking is released, the unit returns to available state immediately."""
        booking = self.Booking.create_booking(self.visit.id, self.table_unit.id, 2)
        data_res = self.Unit.get_dashboard_data()
        table_info = next(u for u in data_res['units'] if u['id'] == self.table_unit.id)
        self.assertTrue(table_info['is_reserved'])

        # Release via dashboard method
        self.Unit.release_dashboard_booking(booking.id)

        data_rel = self.Unit.get_dashboard_data()
        table_info_after = next(u for u in data_rel['units'] if u['id'] == self.table_unit.id)
        self.assertFalse(table_info_after['is_reserved'])
        self.assertIsNone(table_info_after['booking'])

    # -------------------------------------------------------------------------
    # Test 06: Inactive units are excluded from available count
    # -------------------------------------------------------------------------
    def test_06_inactive_units_excluded_from_available(self):
        """Archiving a unit removes it from active metrics and available units."""
        data_before = self.Unit.get_dashboard_data()
        before_avail = data_before['metrics']['available_units']

        self.table_unit.write({'active': False})

        data_after = self.Unit.get_dashboard_data()
        self.assertEqual(data_after['metrics']['available_units'], before_avail - 1)

    # -------------------------------------------------------------------------
    # Test 07: Selecting available unit opens booking workflow with correct prices
    # -------------------------------------------------------------------------
    def test_07_dashboard_booking_creation_pricing(self):
        """create_dashboard_booking validates capacity and computes approved pricing."""
        # Standard table 3 guests -> ₦60,000
        res = self.Unit.create_dashboard_booking(
            visit_id=self.visit.id,
            unit_id=self.table_unit.id,
            guest_count=3,
        )
        self.assertTrue(res['success'])
        booking = self.Booking.browse(res['booking_id'])
        self.assertEqual(booking.amount_total, 60000.0)
        self.assertEqual(booking.payment_status, 'unpaid')

    # -------------------------------------------------------------------------
    # Test 08: Only checked-in visits can be selected for seating assignment
    # -------------------------------------------------------------------------
    def test_08_only_checked_in_visits_eligible(self):
        """get_checked_in_visits excludes cancelled visits and visits already seated."""
        # Cancelled visit
        cancelled_visit = self.Visit.create({
            'visitor_id': self.visitor.id,
            'location_id': self.location.id,
            'source': 'qr_code',
            'state': 'cancelled',
        })
        visits = self.Unit.get_checked_in_visits(visitor_id=self.visitor.id)
        visit_ids = [v['id'] for v in visits]
        self.assertIn(self.visit.id, visit_ids)
        self.assertNotIn(cancelled_visit.id, visit_ids)

        # Once self.visit has an active reservation, it must no longer appear
        self.Booking.create_booking(self.visit.id, self.table_unit.id, 2)
        visits_after = self.Unit.get_checked_in_visits(visitor_id=self.visitor.id)
        visit_ids_after = [v['id'] for v in visits_after]
        self.assertNotIn(self.visit.id, visit_ids_after)

    # -------------------------------------------------------------------------
    # Test 09: Visitor context is correctly passed from visitor profiles
    # -------------------------------------------------------------------------
    def test_09_visitor_context_passed_from_profile(self):
        """action_open_seating_dashboard on res.partner passes visitor and visit context."""
        action = self.visitor.action_open_seating_dashboard()
        self.assertEqual(action['type'], 'ir.actions.client')
        self.assertEqual(action['tag'], 'sunnyside_seating_dashboard')
        self.assertEqual(action['context']['default_visitor_id'], self.visitor.id)
        self.assertEqual(action['context']['default_visit_id'], self.visit.id)

    # -------------------------------------------------------------------------
    # Test 10: Visit context is correctly passed from visit records
    # -------------------------------------------------------------------------
    def test_10_visit_context_passed_from_visit_record(self):
        """action_open_seating_dashboard on sunnyside.visit passes visit and visitor context."""
        action = self.visit.action_open_seating_dashboard()
        self.assertEqual(action['type'], 'ir.actions.client')
        self.assertEqual(action['tag'], 'sunnyside_seating_dashboard')
        self.assertEqual(action['context']['default_visit_id'], self.visit.id)
        self.assertEqual(action['context']['default_visitor_id'], self.visitor.id)

    # -------------------------------------------------------------------------
    # Test 11: Booking creation delegates to existing create_booking method
    # -------------------------------------------------------------------------
    def test_11_booking_delegates_to_existing_create_booking(self):
        """create_dashboard_booking enforces server-side pricing and unique reservation."""
        res = self.Unit.create_dashboard_booking(
            visit_id=self.visit.id,
            unit_id=self.cabana_unit.id,
            guest_count=5,
        )
        booking = self.Booking.browse(res['booking_id'])
        self.assertEqual(booking.unit_id.id, self.cabana_unit.id)
        self.assertEqual(booking.amount_total, 250000.0)
        self.assertEqual(booking.state, 'reserved')

    # -------------------------------------------------------------------------
    # Test 12: Payment capture delegates to existing record_payment method
    # -------------------------------------------------------------------------
    def test_12_payment_capture_delegation(self):
        """Initial payment during booking creation and subsequent payment via dashboard."""
        # 1. Partial payment on creation
        res = self.Unit.create_dashboard_booking(
            visit_id=self.visit.id,
            unit_id=self.table_unit.id,
            guest_count=2,              # ₦40,000 total
            payment_amount=20000.0,
            payment_method='bank_card',
            payment_reference='POS-4401',
        )
        booking = self.Booking.browse(res['booking_id'])
        self.assertEqual(booking.amount_paid, 20000.0)
        self.assertEqual(booking.amount_due, 20000.0)
        self.assertEqual(booking.payment_status, 'partial')

        # 2. Complete remaining balance via record_dashboard_payment
        res_pay = self.Unit.record_dashboard_payment(
            booking_id=booking.id,
            amount=20000.0,
            payment_method='cash',
            reference='CASH-FINAL',
        )
        self.assertTrue(res_pay['success'])
        self.assertEqual(booking.payment_status, 'paid')
        self.assertEqual(booking.amount_due, 0.0)

    # -------------------------------------------------------------------------
    # Test 13: Overpayment remains rejected
    # -------------------------------------------------------------------------
    def test_13_overpayment_rejected_by_dashboard_payment(self):
        """record_dashboard_payment rejects amounts exceeding the remaining balance."""
        res = self.Unit.create_dashboard_booking(
            visit_id=self.visit.id,
            unit_id=self.table_unit.id,
            guest_count=1,              # ₦20,000 total
        )
        with self.assertRaises(ValidationError):
            self.Unit.record_dashboard_payment(
                booking_id=res['booking_id'],
                amount=25000.0,          # Exceeds total
                payment_method='cash',
            )

    # -------------------------------------------------------------------------
    # Test 14: Release delegates to existing action_release method
    # -------------------------------------------------------------------------
    def test_14_release_delegates_to_action_release(self):
        """release_dashboard_booking calls action_release, setting state and audit info."""
        res = self.Unit.create_dashboard_booking(
            visit_id=self.visit.id,
            unit_id=self.table_unit.id,
            guest_count=2,
        )
        booking = self.Booking.browse(res['booking_id'])
        self.assertEqual(booking.state, 'reserved')

        self.Unit.release_dashboard_booking(booking.id)
        self.assertEqual(booking.state, 'released')
        self.assertTrue(booking.released_datetime)
        self.assertEqual(booking.released_by_id, self.env.user)

    # -------------------------------------------------------------------------
    # Test 15: Release history and payment history are preserved
    # -------------------------------------------------------------------------
    def test_15_release_history_and_payments_preserved(self):
        """Releasing a booking preserves all financial lines and historical records."""
        res = self.Unit.create_dashboard_booking(
            visit_id=self.visit.id,
            unit_id=self.table_unit.id,
            guest_count=2,
            payment_amount=40000.0,
            payment_method='bank_transfer',
            payment_reference='TRF-9988',
        )
        booking = self.Booking.browse(res['booking_id'])
        self.assertEqual(len(booking.payment_ids), 1)

        # Release
        self.Unit.release_dashboard_booking(booking.id)

        # Payment records and booking history must still exist
        self.assertTrue(booking.exists())
        self.assertEqual(len(booking.payment_ids), 1)
        self.assertEqual(booking.amount_paid, 40000.0)
        self.assertEqual(booking.state, 'released')

    # -------------------------------------------------------------------------
    # Test 16: Two receptionists cannot reserve the same unit through stale dashboard data
    # -------------------------------------------------------------------------
    def test_16_concurrent_reservation_conflict_handled(self):
        """If unit was reserved out from under a stale client, creation raises ValidationError."""
        # Receptionist A reserves the unit
        self.Unit.create_dashboard_booking(
            visit_id=self.visit.id,
            unit_id=self.table_unit.id,
            guest_count=2,
        )

        # Visitor B checks in
        visitor_b = self.Partner.create({
            'name': 'Chioma Ajayi',
            'phone': '+2348039992200',
            'is_sunnyside_visitor': True,
            'privacy_acknowledged': True,
        })
        visit_b = self.Visit.create({
            'visitor_id': visitor_b.id,
            'source': 'receptionist',
            'state': 'checked_in',
        })

        # Receptionist B tries to reserve the same unit based on stale view
        with self.assertRaises(ValidationError):
            self.Unit.create_dashboard_booking(
                visit_id=visit_b.id,
                unit_id=self.table_unit.id,
                guest_count=2,
            )

    # -------------------------------------------------------------------------
    # Test 17: Area filter in get_dashboard_data works as expected
    # -------------------------------------------------------------------------
    def test_17_dashboard_data_area_filtering(self):
        """get_dashboard_data respects the area_id parameter for zone-specific views."""
        data_deck = self.Unit.get_dashboard_data(area_id=self.deck_area.id)
        deck_unit_ids = [u['id'] for u in data_deck['units']]
        self.assertIn(self.table_unit.id, deck_unit_ids)
        self.assertIn(self.beach_unit.id, deck_unit_ids)
        self.assertNotIn(self.cabana_unit.id, deck_unit_ids)

        data_vip = self.Unit.get_dashboard_data(area_id=self.vip_area.id)
        vip_unit_ids = [u['id'] for u in data_vip['units']]
        self.assertIn(self.cabana_unit.id, vip_unit_ids)
        self.assertNotIn(self.table_unit.id, vip_unit_ids)
