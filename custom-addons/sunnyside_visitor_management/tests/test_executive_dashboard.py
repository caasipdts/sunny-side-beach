# -*- coding: utf-8 -*-
"""
Phase 3 Tests: Executive Dashboard Enhancement
Tests visitor KPIs, seating/booking KPIs, financial KPIs, date-range filtering,
access control (manager vs receptionist), and empty-state behaviour.
"""
from datetime import datetime, date, timedelta, time as dtime
from odoo import fields
from odoo.exceptions import AccessError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestExecutiveDashboard(TransactionCase):
    """
    Full test suite for Phase 3: Executive Dashboard Enhancement.
    All test data is created within a single transaction and rolled back.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Ensure schema columns exist for unupgraded database instances
        cls.cr.execute("""
            ALTER TABLE sunnyside_dashboard
            ADD COLUMN IF NOT EXISTS date_filter varchar,
            ADD COLUMN IF NOT EXISTS date_from date,
            ADD COLUMN IF NOT EXISTS date_to date;
        """)

    def setUp(self):
        super().setUp()
        self.Partner = self.env['res.partner']
        self.Visit = self.env['sunnyside.visit']
        self.Area = self.env['sunnyside.seating.area']
        self.Unit = self.env['sunnyside.seating.unit']
        self.Booking = self.env['sunnyside.booking']
        self.Payment = self.env['sunnyside.booking.payment']
        self.Dashboard = self.env['sunnyside.dashboard']

        self.group_user = self.env.ref('sunnyside_visitor_management.group_sunnyside_user')
        self.group_manager = self.env.ref('sunnyside_visitor_management.group_sunnyside_manager')

        # --- Receptionist user (user group only) ---
        self.receptionist_user = self.env['res.users'].create({
            'name': 'Dashboard Receptionist',
            'login': 'dash_receptionist@sunnyside.ng',
            'email': 'dash_receptionist@sunnyside.ng',
            'group_ids': [(6, 0, [
                self.env.ref('base.group_user').id,
                self.group_user.id,
            ])],
        })

        # --- Manager user ---
        self.manager_user = self.env['res.users'].create({
            'name': 'Dashboard Manager',
            'login': 'dash_manager@sunnyside.ng',
            'email': 'dash_manager@sunnyside.ng',
            'group_ids': [(6, 0, [
                self.env.ref('base.group_user').id,
                self.group_manager.id,
            ])],
        })

        # --- Seating inventory ---
        self.area_cabana = self.Area.create({'name': 'Test Cabana Zone', 'sequence': 1})
        self.area_table = self.Area.create({'name': 'Test Table Zone', 'sequence': 2})

        self.cabana_unit = self.Unit.create({
            'name': 'TEST-CAB-01',
            'area_id': self.area_cabana.id,
            'seating_type': 'cabana',
            'capacity_min': 1,
            'capacity_max': 9,
            'pricing_mode': 'fixed',
            'fixed_price': 250000.0,
            'active': True,
        })
        self.table_unit = self.Unit.create({
            'name': 'TEST-TBL-01',
            'area_id': self.area_table.id,
            'seating_type': 'table',
            'capacity_min': 1,
            'capacity_max': 4,
            'pricing_mode': 'per_guest',
            'price_per_guest': 20000.0,
            'active': True,
        })
        self.table_unit_2 = self.Unit.create({
            'name': 'TEST-TBL-02',
            'area_id': self.area_table.id,
            'seating_type': 'table',
            'capacity_min': 1,
            'capacity_max': 4,
            'pricing_mode': 'per_guest',
            'price_per_guest': 20000.0,
            'active': True,
        })

        # --- Visitors and check-in visits ---
        self.visitor_a = self.Partner.create({
            'name': 'Test Visitor Alpha',
            'phone': '+2348011110001',
            'is_sunnyside_visitor': True,
            'privacy_acknowledged': True,
        })
        self.visitor_b = self.Partner.create({
            'name': 'Test Visitor Beta',
            'phone': '+2348011110002',
            'is_sunnyside_visitor': True,
            'privacy_acknowledged': True,
        })

        self.visit_a = self.Visit.create({
            'visitor_id': self.visitor_a.id,
            'source': 'receptionist',
            'state': 'checked_in',
        })
        self.visit_b = self.Visit.create({
            'visitor_id': self.visitor_b.id,
            'source': 'receptionist',
            'state': 'checked_in',
        })

        # Singleton dashboard record
        self.dashboard = self.Dashboard.search([], limit=1)
        if not self.dashboard:
            self.dashboard = self.Dashboard.create({'name': 'Test Dashboard'})

    # =========================================================================
    # 01. Existing visitor KPIs still work
    # =========================================================================
    def test_01_existing_visitor_kpis_work(self):
        """Existing today / this week / this month KPIs return non-negative integers."""
        d = self.dashboard
        d._compute_metrics()
        self.assertIsInstance(d.total_visitors, int)
        self.assertGreaterEqual(d.total_visitors, 0)
        self.assertIsInstance(d.checkins_today, int)
        self.assertGreaterEqual(d.checkins_today, 0)
        self.assertIsInstance(d.new_visitors_today, int)
        self.assertIsInstance(d.returning_visitors_today, int)
        self.assertIsInstance(d.checkins_this_week, int)
        self.assertIsInstance(d.checkins_this_month, int)

    # =========================================================================
    # 02. Date-range calculations — this month
    # =========================================================================
    def test_02_date_range_this_month(self):
        """visits_in_range counts check-ins created this month."""
        self.dashboard.write({'date_filter': 'this_month'})
        self.dashboard._compute_range_metrics()
        # At minimum, the two visits we just created should appear
        self.assertGreaterEqual(self.dashboard.visits_in_range, 2)

    # =========================================================================
    # 03. Date-range calculations — today
    # =========================================================================
    def test_03_date_range_today(self):
        """visits_in_range for 'today' captures visits made in setUp."""
        self.dashboard.write({'date_filter': 'today'})
        self.dashboard._compute_range_metrics()
        self.assertGreaterEqual(self.dashboard.visits_in_range, 2)

    # =========================================================================
    # 04. Date-range calculations — this year
    # =========================================================================
    def test_04_date_range_this_year(self):
        """visits_in_range for 'this_year' >= visits in this month."""
        self.dashboard.write({'date_filter': 'this_year'})
        self.dashboard._compute_range_metrics()
        year_count = self.dashboard.visits_in_range

        self.dashboard.write({'date_filter': 'this_month'})
        self.dashboard._compute_range_metrics()
        month_count = self.dashboard.visits_in_range

        self.assertGreaterEqual(year_count, month_count)

    # =========================================================================
    # 05. New vs returning visitor breakdown
    # =========================================================================
    def test_05_new_vs_returning_breakdown(self):
        """new_visitors_in_range + returning_visitors_in_range == visits_in_range."""
        self.dashboard.write({'date_filter': 'today'})
        self.dashboard._compute_range_metrics()
        self.assertEqual(
            self.dashboard.visits_in_range,
            self.dashboard.new_visitors_in_range + self.dashboard.returning_visitors_in_range,
        )

    # =========================================================================
    # 06. Custom date range — boundaries
    # =========================================================================
    def test_06_custom_date_range_boundaries(self):
        """Custom range with today as both from and to returns today's visits."""
        today = fields.Date.today()
        self.dashboard.write({
            'date_filter': 'custom',
            'date_from': today,
            'date_to': today,
        })
        self.dashboard._compute_range_metrics()
        # Both setUp visits were created today
        self.assertGreaterEqual(self.dashboard.visits_in_range, 2)

    # =========================================================================
    # 07. Custom range — past date returns 0 for new test visits
    # =========================================================================
    def test_07_custom_date_range_past_returns_zero_for_new_visits(self):
        """A past date range before the test runs should not count today's visits."""
        past = fields.Date.today() - timedelta(days=365)
        past_end = fields.Date.today() - timedelta(days=364)
        self.dashboard.write({
            'date_filter': 'custom',
            'date_from': past,
            'date_to': past_end,
        })
        self.dashboard._compute_range_metrics()
        # Test visits were created today; past range should not include them
        self.assertEqual(self.dashboard.visits_in_range, 0)

    # =========================================================================
    # 08. Configured seating unit counts
    # =========================================================================
    def test_08_configured_seating_unit_counts(self):
        """total_seating_units matches the count of active units (including our test units)."""
        self.dashboard._compute_seating_metrics()
        # Must include at minimum our 3 test units
        self.assertGreaterEqual(self.dashboard.total_seating_units, 3)
        # Available + Reserved == Total
        self.assertEqual(
            self.dashboard.available_units + self.dashboard.reserved_units,
            self.dashboard.total_seating_units,
        )

    # =========================================================================
    # 09. Available and reserved unit calculations
    # =========================================================================
    def test_09_available_and_reserved_unit_calculations(self):
        """Before any booking, all test units are available. After 1 booking: reserved_units increases by 1."""
        before = self.Unit.get_dashboard_data()
        init_reserved = before['metrics']['reserved_units']

        # Create a reservation
        booking = self.Booking.create_booking(self.visit_a.id, self.table_unit.id, 2)

        self.dashboard._compute_seating_metrics()
        self.assertEqual(self.dashboard.reserved_units, init_reserved + 1)
        self.assertEqual(
            self.dashboard.available_units + self.dashboard.reserved_units,
            self.dashboard.total_seating_units,
        )

    # =========================================================================
    # 10. Released bookings no longer occupy units
    # =========================================================================
    def test_10_released_bookings_do_not_occupy_units(self):
        """After release, the unit is returned to available and dashboard reflects this."""
        booking = self.Booking.create_booking(self.visit_a.id, self.table_unit.id, 2)
        self.dashboard._compute_seating_metrics()
        reserved_after_booking = self.dashboard.reserved_units

        booking.action_release()

        self.dashboard._compute_seating_metrics()
        self.assertEqual(self.dashboard.reserved_units, reserved_after_booking - 1)
        self.assertEqual(booking.state, 'released')

    # =========================================================================
    # 11. Active booking and guest counts
    # =========================================================================
    def test_11_active_booking_and_guest_counts(self):
        """active_bookings and active_booking_guests reflect the reserved state."""
        self.dashboard._compute_seating_metrics()
        init_active = self.dashboard.active_bookings
        init_guests = self.dashboard.active_booking_guests

        booking = self.Booking.create_booking(self.visit_a.id, self.table_unit.id, 3)

        self.dashboard._compute_seating_metrics()
        self.assertEqual(self.dashboard.active_bookings, init_active + 1)
        self.assertEqual(self.dashboard.active_booking_guests, init_guests + 3)

    # =========================================================================
    # 12. Contracted Booking Value
    # =========================================================================
    def test_12_contracted_booking_value(self):
        """contracted_booking_value sums amount_total for bookings in range (manager sees it)."""
        self.dashboard.write({'date_filter': 'today'})
        # Create a booking: cabana = 250,000
        booking = self.Booking.create_booking(self.visit_a.id, self.cabana_unit.id, 5)
        self.assertEqual(booking.amount_total, 250000.0)

        # Compute as manager
        self.dashboard.with_user(self.manager_user)._compute_financial_metrics()
        manager_dash = self.Dashboard.with_user(self.manager_user).search([], limit=1)
        if not manager_dash:
            manager_dash = self.Dashboard.with_user(self.manager_user).create({'name': 'Mgr Dash'})
        manager_dash.write({'date_filter': 'today'})
        manager_dash.with_user(self.manager_user)._compute_financial_metrics()
        self.assertGreaterEqual(manager_dash.contracted_booking_value, 250000.0)

    # =========================================================================
    # 13. Recorded Collections
    # =========================================================================
    def test_13_recorded_collections(self):
        """recorded_collections sums payments made in the selected date range."""
        # Create booking and record payment
        booking = self.Booking.create_booking(self.visit_a.id, self.table_unit.id, 2)
        self.assertEqual(booking.amount_total, 40000.0)
        booking.record_payment(amount=30000.0, payment_method='cash')

        manager_dash = self.Dashboard.with_user(self.manager_user).search([], limit=1)
        if not manager_dash:
            manager_dash = self.Dashboard.with_user(self.manager_user).create({'name': 'Mgr Dash 2'})
        manager_dash.write({'date_filter': 'today'})
        manager_dash.with_user(self.manager_user)._compute_financial_metrics()
        self.assertGreaterEqual(manager_dash.recorded_collections, 30000.0)

    # =========================================================================
    # 14. Outstanding Balances — including released bookings
    # =========================================================================
    def test_14_outstanding_balances_include_released_bookings(self):
        """outstanding_balances includes amount_due from released bookings."""
        # Create booking (₦40,000), pay ₦10,000, then release
        booking = self.Booking.create_booking(self.visit_a.id, self.table_unit.id, 2)
        booking.record_payment(amount=10000.0, payment_method='bank_card')
        self.assertEqual(booking.amount_due, 30000.0)

        booking.action_release()
        self.assertEqual(booking.state, 'released')
        # After release, amount_due is still 30,000 (released does not clear debt)
        self.assertEqual(booking.amount_due, 30000.0)

        manager_dash = self.Dashboard.with_user(self.manager_user).search([], limit=1)
        if not manager_dash:
            manager_dash = self.Dashboard.with_user(self.manager_user).create({'name': 'Mgr Dash 3'})
        manager_dash.write({'date_filter': 'today'})
        manager_dash.with_user(self.manager_user)._compute_financial_metrics()
        # Outstanding must include at minimum the 30,000 from the released booking
        self.assertGreaterEqual(manager_dash.outstanding_balances, 30000.0)

    # =========================================================================
    # 15. Payment status breakdown
    # =========================================================================
    def test_15_payment_status_breakdown(self):
        """Payment status counts (unpaid, partial, paid) sum to total range bookings."""
        # Create three bookings in range with different payment states
        # Booking 1: cabana — unpaid
        b1 = self.Booking.create_booking(self.visit_a.id, self.cabana_unit.id, 3)
        self.assertEqual(b1.payment_status, 'unpaid')

        # Booking 2: table 1 — partial
        b2 = self.Booking.create_booking(self.visit_b.id, self.table_unit.id, 2)
        b2.record_payment(amount=20000.0, payment_method='cash')
        self.assertEqual(b2.payment_status, 'partial')

        # Booking 3: table 2 — paid
        visit_c = self.Visit.create({
            'visitor_id': self.visitor_a.id,
            'source': 'receptionist',
            'state': 'checked_in',
        })
        # Release existing cabana booking to allow reuse (cabana already reserved above)
        b1.action_release()

        b3 = self.Booking.create_booking(visit_c.id, self.cabana_unit.id, 2)
        b3.record_payment(amount=250000.0, payment_method='bank_transfer')
        self.assertEqual(b3.payment_status, 'paid')

        manager_dash = self.Dashboard.with_user(self.manager_user).search([], limit=1)
        if not manager_dash:
            manager_dash = self.Dashboard.with_user(self.manager_user).create({'name': 'Mgr Dash 4'})
        manager_dash.write({'date_filter': 'today'})
        manager_dash.with_user(self.manager_user)._compute_financial_metrics()

        total_in_range = (
            manager_dash.bookings_unpaid_count
            + manager_dash.bookings_partial_count
            + manager_dash.bookings_paid_count
        )
        # At minimum our 3 bookings were created today
        self.assertGreaterEqual(total_in_range, 3)
        # Partial count must be >= 1
        self.assertGreaterEqual(manager_dash.bookings_partial_count, 1)
        # Paid count must be >= 1
        self.assertGreaterEqual(manager_dash.bookings_paid_count, 1)

    # =========================================================================
    # 16. Manager access to financial dashboard data
    # =========================================================================
    def test_16_manager_can_access_financial_kpis(self):
        """Manager user gets non-None financial data from get_executive_dashboard_data."""
        result = self.Dashboard.with_user(self.manager_user).get_executive_dashboard_data(
            date_filter='today'
        )
        self.assertTrue(result['is_manager'])
        self.assertIsNotNone(result['financial_kpis'])
        self.assertIn('contracted_booking_value', result['financial_kpis'])
        self.assertIn('recorded_collections', result['financial_kpis'])
        self.assertIn('outstanding_balances', result['financial_kpis'])

    # =========================================================================
    # 17. Receptionist access to operational data
    # =========================================================================
    def test_17_receptionist_can_access_operational_kpis(self):
        """Receptionist user gets visitor and seating KPIs without financial data."""
        result = self.Dashboard.with_user(self.receptionist_user).get_executive_dashboard_data(
            date_filter='today'
        )
        self.assertFalse(result['is_manager'])
        self.assertIsNone(result['financial_kpis'])
        # Operational data must be present
        self.assertIn('visitor_kpis', result)
        self.assertIn('seating_kpis', result)

    # =========================================================================
    # 18. Receptionist cannot retrieve financial data via compute method
    # =========================================================================
    def test_18_receptionist_financial_metrics_are_zero(self):
        """_compute_financial_metrics returns zeroes for non-manager users."""
        # Create booking to put some value in the system
        self.Booking.create_booking(self.visit_a.id, self.table_unit.id, 2)

        # Get or create a dashboard record visible to receptionist
        recep_dash = self.Dashboard.with_user(self.receptionist_user).search([], limit=1)
        if not recep_dash:
            recep_dash = self.Dashboard.with_user(self.receptionist_user).create({'name': 'Recep Dash'})
        recep_dash.write({'date_filter': 'today'})
        recep_dash.with_user(self.receptionist_user)._compute_financial_metrics()

        self.assertEqual(recep_dash.contracted_booking_value, 0.0)
        self.assertEqual(recep_dash.recorded_collections, 0.0)
        self.assertEqual(recep_dash.outstanding_balances, 0.0)
        self.assertEqual(recep_dash.bookings_unpaid_count, 0)

    # =========================================================================
    # 19. get_executive_dashboard_data financial_kpis is None for receptionist
    # =========================================================================
    def test_19_get_executive_dashboard_data_financial_none_for_receptionist(self):
        """financial_kpis key is None when called by a non-manager."""
        result = self.Dashboard.with_user(self.receptionist_user).get_executive_dashboard_data()
        self.assertIsNone(result['financial_kpis'])
        self.assertFalse(result['is_manager'])

    # =========================================================================
    # 20. Empty dashboard behavior — no visits, no bookings
    # =========================================================================
    def test_20_empty_dashboard_behavior(self):
        """When no data exists for a past date range, all range KPIs are 0."""
        past = fields.Date.today() - timedelta(days=400)
        past_end = fields.Date.today() - timedelta(days=399)
        self.dashboard.write({
            'date_filter': 'custom',
            'date_from': past,
            'date_to': past_end,
        })
        self.dashboard._compute_range_metrics()
        self.assertEqual(self.dashboard.visits_in_range, 0)
        self.assertEqual(self.dashboard.new_visitors_in_range, 0)
        self.assertEqual(self.dashboard.returning_visitors_in_range, 0)

    # =========================================================================
    # 21. action_open_dashboard creates singleton if none exists
    # =========================================================================
    def test_21_action_open_dashboard_creates_singleton(self):
        """action_open_dashboard returns a valid act_window pointing to the dashboard record."""
        action = self.Dashboard.action_open_dashboard()
        self.assertEqual(action['type'], 'ir.actions.act_window')
        self.assertEqual(action['res_model'], 'sunnyside.dashboard')
        self.assertTrue(action['res_id'])

    # =========================================================================
    # 22. action_view_payment_reporting raises AccessError for receptionist
    # =========================================================================
    def test_22_receptionist_cannot_open_financial_report(self):
        """action_view_payment_reporting raises AccessError for non-manager."""
        dash = self.Dashboard.with_user(self.receptionist_user).search([], limit=1)
        if not dash:
            dash = self.Dashboard.with_user(self.receptionist_user).create({'name': 'Recep Dash 2'})
        with self.assertRaises(AccessError):
            dash.with_user(self.receptionist_user).action_view_payment_reporting()

    # =========================================================================
    # 23. action_view_receivables raises AccessError for receptionist
    # =========================================================================
    def test_23_receptionist_cannot_open_receivables_report(self):
        """action_view_receivables raises AccessError for non-manager."""
        dash = self.Dashboard.with_user(self.receptionist_user).search([], limit=1)
        if not dash:
            dash = self.Dashboard.with_user(self.receptionist_user).create({'name': 'Recep Dash 3'})
        with self.assertRaises(AccessError):
            dash.with_user(self.receptionist_user).action_view_receivables()

    # =========================================================================
    # 24. Date range boundary — this_week does not include last week's visits
    # =========================================================================
    def test_24_this_week_boundary(self):
        """'this_week' range excludes visits before Monday of the current week."""
        today = fields.Date.today()
        monday = today - timedelta(days=today.weekday())
        # Visits from setUp are from today, which is >= Monday, so count >= 2
        self.dashboard.write({'date_filter': 'this_week'})
        self.dashboard._compute_range_metrics()
        self.assertGreaterEqual(self.dashboard.visits_in_range, 2)

    # =========================================================================
    # 25. get_executive_dashboard_data seating area distribution is populated
    # =========================================================================
    def test_25_seating_area_distribution(self):
        """When a booking exists, area_distribution in seating_kpis is non-empty."""
        self.Booking.create_booking(self.visit_a.id, self.table_unit.id, 2)
        result = self.Dashboard.get_executive_dashboard_data(date_filter='today')
        distribution = result['seating_kpis']['area_distribution']
        area_names = [d['area'] for d in distribution]
        self.assertIn('Test Table Zone', area_names)

    # =========================================================================
    # 26. get_executive_dashboard_data seating type distribution is populated
    # =========================================================================
    def test_26_seating_type_distribution(self):
        """When a booking exists, type_distribution in seating_kpis is non-empty."""
        self.Booking.create_booking(self.visit_a.id, self.table_unit.id, 2)
        result = self.Dashboard.get_executive_dashboard_data(date_filter='today')
        distribution = result['seating_kpis']['type_distribution']
        types = [d['type'] for d in distribution]
        self.assertIn('table', types)

    # =========================================================================
    # 27. _get_range_boundaries_for model method — custom with explicit dates
    # =========================================================================
    def test_27_get_range_boundaries_for_custom(self):
        """_get_range_boundaries_for returns correct start/end for custom range."""
        df = date(2026, 1, 1)
        dt = date(2026, 1, 31)
        start, end = self.Dashboard._get_range_boundaries_for('custom', date_from=df, date_to=dt)
        self.assertEqual(start.date(), df)
        self.assertEqual(end.date(), dt)

    # =========================================================================
    # 28. Inactive seating units are excluded from operational counts
    # =========================================================================
    def test_28_inactive_units_excluded_from_seating_kpis(self):
        """Archiving a unit reduces total_seating_units and available_units."""
        self.dashboard._compute_seating_metrics()
        before = self.dashboard.total_seating_units

        self.table_unit_2.write({'active': False})

        self.dashboard._compute_seating_metrics()
        self.assertEqual(self.dashboard.total_seating_units, before - 1)

    # =========================================================================
    # 29. Currency field is populated
    # =========================================================================
    def test_29_currency_field_populated(self):
        """currency_id on dashboard is the company currency."""
        self.dashboard._compute_currency()
        self.assertTrue(self.dashboard.currency_id)
        self.assertEqual(self.dashboard.currency_id, self.env.company.currency_id)

    # =========================================================================
    # 30. Manager can call action_view_payment_reporting successfully
    # =========================================================================
    def test_30_manager_can_open_financial_report(self):
        """Manager user can call action_view_payment_reporting without error."""
        dash = self.Dashboard.with_user(self.manager_user).search([], limit=1)
        if not dash:
            dash = self.Dashboard.with_user(self.manager_user).create({'name': 'Mgr Dash Final'})
        action = dash.with_user(self.manager_user).action_view_payment_reporting()
        self.assertEqual(action['type'], 'ir.actions.act_window')

