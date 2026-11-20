# -*- coding: utf-8 -*-
from datetime import datetime, timedelta
from odoo import fields
from odoo.exceptions import AccessError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestBookingReporting(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Area = cls.env['sunnyside.seating.area']
        cls.Unit = cls.env['sunnyside.seating.unit']
        cls.Visit = cls.env['sunnyside.visit']
        cls.Partner = cls.env['res.partner']
        cls.Booking = cls.env['sunnyside.booking']
        cls.Users = cls.env['res.users']

        # 1. Setup Users
        cls.receptionist_user = cls.Users.create({
            'name': 'Receptionist Kemi',
            'login': 'test_rep_kemi',
            'email': 'kemi@sunnysidebeach.ng',
            'group_ids': [(6, 0, [
                cls.env.ref('base.group_user').id,
                cls.env.ref('sunnyside_visitor_management.group_sunnyside_user').id,
            ])],
        })

        cls.unauthorized_user = cls.Users.create({
            'name': 'Unauthorized User Bob',
            'login': 'test_rep_bob',
            'email': 'bob@example.com',
            'group_ids': [(6, 0, [
                cls.env.ref('base.group_user').id,
            ])],
        })

        cls.manager_user = cls.Users.create({
            'name': 'Manager Femi',
            'login': 'test_rep_femi',
            'email': 'femi@sunnysidebeach.ng',
            'group_ids': [(6, 0, [
                cls.env.ref('base.group_user').id,
                cls.env.ref('sunnyside_visitor_management.group_sunnyside_manager').id,
            ])],
        })

        # 2. Setup Seating & Visits
        cls.test_area = cls.Area.create({
            'name': 'Reporting Test Deck',
            'sequence': 15,
        })
        cls.test_table = cls.Unit.create({
            'name': 'REP-TBL-01',
            'area_id': cls.test_area.id,
            'seating_type': 'table',
            'capacity_min': 1,
            'capacity_max': 4,
            'price_per_guest': 20000.0,
        })
        cls.test_cabana = cls.Unit.create({
            'name': 'REP-CAB-01',
            'area_id': cls.test_area.id,
            'seating_type': 'cabana',
            'capacity_min': 1,
            'capacity_max': 9,
            'fixed_price': 250000.0,
        })

        cls.visitor = cls.Partner.create({
            'name': 'Amara Okon',
            'phone': '+2348011223344',
            'is_sunnyside_visitor': True,
        })
        cls.visit = cls.Visit.create({
            'visitor_id': cls.visitor.id,
            'source': 'receptionist',
            'state': 'checked_in',
        })

    def test_01_reporting_action_and_menu_exist(self):
        """Verify the Seating & Bookings Analysis action and menu item exist and are configured correctly."""
        action = self.env.ref('sunnyside_visitor_management.action_sunnyside_booking_reporting')
        self.assertTrue(action.exists(), "Reporting action must be defined.")
        self.assertEqual(action.res_model, 'sunnyside.booking')
        self.assertIn('graph', action.view_mode)
        self.assertIn('pivot', action.view_mode)
        self.assertIn('list', action.view_mode)

        search_view = self.env.ref('sunnyside_visitor_management.view_sunnyside_booking_reporting_search')
        self.assertEqual(action.search_view_id.id, search_view.id, "Action must reference dedicated search view.")

        menu = self.env.ref('sunnyside_visitor_management.menu_sunnyside_report_bookings')
        self.assertTrue(menu.exists(), "Reporting menu item must exist.")
        self.assertEqual(menu.action.id, action.id)
        parent_menu = self.env.ref('sunnyside_visitor_management.menu_sunnyside_reporting')
        self.assertEqual(menu.parent_id.id, parent_menu.id, "Menu must be nested under Reporting.")

        # Ensure existing Visits Analysis menu was not modified or removed
        visits_menu = self.env.ref('sunnyside_visitor_management.menu_sunnyside_report_visits')
        self.assertTrue(visits_menu.exists(), "Existing Visits Analysis menu must remain intact.")

    def test_02_views_registered(self):
        """Verify dedicated graph, pivot, list, and search views are registered."""
        graph_view = self.env.ref('sunnyside_visitor_management.view_sunnyside_booking_reporting_graph')
        self.assertEqual(graph_view.model, 'sunnyside.booking')
        self.assertEqual(graph_view.type, 'graph')

        pivot_view = self.env.ref('sunnyside_visitor_management.view_sunnyside_booking_reporting_pivot')
        self.assertEqual(pivot_view.model, 'sunnyside.booking')
        self.assertEqual(pivot_view.type, 'pivot')

        list_view = self.env.ref('sunnyside_visitor_management.view_sunnyside_booking_reporting_list')
        self.assertEqual(list_view.model, 'sunnyside.booking')
        self.assertEqual(list_view.type, 'list')

        search_view = self.env.ref('sunnyside_visitor_management.view_sunnyside_booking_reporting_search')
        self.assertEqual(search_view.model, 'sunnyside.booking')
        self.assertEqual(search_view.type, 'search')

    def test_03_financial_fields_excluded_from_reporting_views(self):
        """Verify financial fields (amount_total, amount_paid, amount_due) are excluded from the reporting views."""
        list_arch = self.env.ref('sunnyside_visitor_management.view_sunnyside_booking_reporting_list').arch
        self.assertNotIn('amount_total', list_arch, "Financial amount_total must not be in operational reporting list.")
        self.assertNotIn('amount_paid', list_arch, "Financial amount_paid must not be in operational reporting list.")
        self.assertNotIn('amount_due', list_arch, "Financial amount_due must not be in operational reporting list.")

        # Required operational fields must be present in the reporting list
        self.assertIn('name', list_arch)
        self.assertIn('visitor_id', list_arch)
        self.assertIn('visit_id', list_arch)
        self.assertIn('unit_id', list_arch)
        self.assertIn('area_id', list_arch)
        self.assertIn('seating_type', list_arch)
        self.assertIn('guest_count', list_arch)
        self.assertIn('reserved_datetime', list_arch)
        self.assertIn('state', list_arch)
        self.assertIn('reserved_by_id', list_arch)

        # Pivot view check
        pivot_arch = self.env.ref('sunnyside_visitor_management.view_sunnyside_booking_reporting_pivot').arch
        self.assertNotIn('amount_total', pivot_arch, "Financial amount_total must not be in reporting pivot.")
        self.assertNotIn('amount_paid', pivot_arch, "Financial amount_paid must not be in reporting pivot.")
        self.assertNotIn('amount_due', pivot_arch, "Financial amount_due must not be in reporting pivot.")
        self.assertIn('guest_count', pivot_arch, "guest_count must be registered as a measure.")

    def test_04_access_control(self):
        """Verify authorized operational users have access, while unauthorized users are denied."""
        # Operational user can read bookings
        receptionist_booking = self.Booking.with_user(self.receptionist_user).search([])
        self.assertIsNotNone(receptionist_booking)

        # Unauthorized user without group cannot read bookings
        with self.assertRaises(AccessError):
            self.Booking.with_user(self.unauthorized_user).search([])

        # Manager user has access
        manager_booking = self.Booking.with_user(self.manager_user).search([])
        self.assertIsNotNone(manager_booking)

    def test_05_released_bookings_available_in_reporting(self):
        """Verify released bookings remain available for historical reporting and are not filtered out by default."""
        booking1 = self.Booking.create_booking(self.visit.id, self.test_table.id, 2)
        booking1.action_release()
        self.assertEqual(booking1.state, 'released', "Booking 1 must be in released state.")

        booking2 = self.Booking.create_booking(self.visit.id, self.test_cabana.id, 5)
        self.assertEqual(booking2.state, 'reserved', "Booking 2 must be in reserved state.")

        # Query without state domain (reporting default)
        all_bookings = self.Booking.search([('id', 'in', [booking1.id, booking2.id])])
        self.assertEqual(len(all_bookings), 2, "Both active and released bookings must be available in reporting.")

        # Filter by Active (Reserved)
        reserved_bookings = self.Booking.search([
            ('id', 'in', [booking1.id, booking2.id]),
            ('state', '=', 'reserved'),
        ])
        self.assertEqual(reserved_bookings.ids, [booking2.id])

        # Filter by Released (Historical)
        released_bookings = self.Booking.search([
            ('id', 'in', [booking1.id, booking2.id]),
            ('state', '=', 'released'),
        ])
        self.assertEqual(released_bookings.ids, [booking1.id])

    def test_06_guest_count_aggregation(self):
        """Verify guest_count correctly sums across bookings in analytical queries."""
        booking1 = self.Booking.create_booking(self.visit.id, self.test_table.id, 3)
        booking1.action_release()
        booking2 = self.Booking.create_booking(self.visit.id, self.test_cabana.id, 7)

        # Use _read_group to simulate pivot measure aggregation
        groups = self.Booking._read_group(
            domain=[('id', 'in', [booking1.id, booking2.id])],
            groupby=['seating_type'],
            aggregates=['guest_count:sum', '__count'],
        )

        counts_by_type = {g[0]: {'guests': g[1], 'count': g[2]} for g in groups}
        self.assertEqual(counts_by_type['table']['guests'], 3)
        self.assertEqual(counts_by_type['table']['count'], 1)
        self.assertEqual(counts_by_type['cabana']['guests'], 7)
        self.assertEqual(counts_by_type['cabana']['count'], 1)

    def test_07_search_filters_and_groupings(self):
        """Verify reporting search filters and group-by expressions execute without syntax errors."""
        now = fields.Datetime.now()
        booking = self.Booking.create_booking(self.visit.id, self.test_table.id, 2)

        # Test Date Filters
        today_bookings = self.Booking.search([
            ('id', '=', booking.id),
            ('reserved_datetime', '>=', 'today'),
            ('reserved_datetime', '<', 'today +1d'),
        ])
        self.assertEqual(len(today_bookings), 1, "Today filter must match newly created booking.")

        year_bookings = self.Booking.search([
            ('id', '=', booking.id),
            ('reserved_datetime', '>=', 'today =1m =1d'),
            ('reserved_datetime', '<', 'today =1m =1d +1y'),
        ])
        self.assertEqual(len(year_bookings), 1, "This year filter must match newly created booking.")

        # Test Groupings supported by reporting
        for group_field in ['reserved_datetime:day', 'seating_type', 'area_id', 'unit_id', 'state', 'reserved_by_id']:
            result = self.Booking._read_group(
                domain=[('id', '=', booking.id)],
                groupby=[group_field],
                aggregates=['__count'],
            )
            self.assertTrue(len(result) >= 1, f"Group-by on {group_field} must return valid results.")

