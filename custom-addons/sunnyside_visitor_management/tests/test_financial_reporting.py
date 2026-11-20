# -*- coding: utf-8 -*-
from datetime import datetime
from odoo import fields
from odoo.exceptions import AccessError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestFinancialReporting(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Area = cls.env['sunnyside.seating.area']
        cls.Unit = cls.env['sunnyside.seating.unit']
        cls.Visit = cls.env['sunnyside.visit']
        cls.Partner = cls.env['res.partner']
        cls.Booking = cls.env['sunnyside.booking']
        cls.Payment = cls.env['sunnyside.booking.payment']
        cls.Users = cls.env['res.users']

        # 1. Setup Users
        cls.receptionist_user = cls.Users.create({
            'name': 'Receptionist Tolu',
            'login': 'test_fin_tolu',
            'email': 'tolu@sunnysidebeach.ng',
            'group_ids': [(6, 0, [
                cls.env.ref('base.group_user').id,
                cls.env.ref('sunnyside_visitor_management.group_sunnyside_user').id,
            ])],
        })

        cls.manager_user = cls.Users.create({
            'name': 'Finance Manager Segun',
            'login': 'test_fin_segun',
            'email': 'segun@sunnysidebeach.ng',
            'group_ids': [(6, 0, [
                cls.env.ref('base.group_user').id,
                cls.env.ref('sunnyside_visitor_management.group_sunnyside_manager').id,
            ])],
        })

        cls.unauthorized_user = cls.Users.create({
            'name': 'Unauthorized User Dave',
            'login': 'test_fin_dave',
            'email': 'dave@example.com',
            'group_ids': [(6, 0, [
                cls.env.ref('base.group_user').id,
            ])],
        })

        # 2. Setup Seating & Visits
        cls.test_area = cls.Area.create({
            'name': 'Financial Reporting Pier',
            'sequence': 20,
        })
        cls.test_table = cls.Unit.create({
            'name': 'FIN-TBL-01',
            'area_id': cls.test_area.id,
            'seating_type': 'table',
            'capacity_min': 1,
            'capacity_max': 4,
            'price_per_guest': 20000.0,
        })
        cls.test_cabana = cls.Unit.create({
            'name': 'FIN-CAB-01',
            'area_id': cls.test_area.id,
            'seating_type': 'cabana',
            'capacity_min': 1,
            'capacity_max': 9,
            'fixed_price': 250000.0,
        })

        cls.visitor = cls.Partner.create({
            'name': 'Ngozi Eze',
            'phone': '+2348099887766',
            'is_sunnyside_visitor': True,
        })
        cls.visit = cls.Visit.create({
            'visitor_id': cls.visitor.id,
            'source': 'receptionist',
            'state': 'checked_in',
        })

        # 3. Create Sample Bookings & Payments
        # Booking 1: Partially Paid (Total 40k, Paid 20k cash by receptionist, Due 20k)
        cls.booking1 = cls.Booking.create_booking(cls.visit.id, cls.test_table.id, 2)
        cls.payment1 = cls.Payment.create({
            'booking_id': cls.booking1.id,
            'amount': 20000.0,
            'payment_method': 'cash',
            'reference': 'REC-CASH-001',
            'user_id': cls.receptionist_user.id,
        })
        cls.booking1.invalidate_recordset()

        # Booking 2: Fully Paid (Total 20k, Paid 20k card by manager, Due 0)
        table2 = cls.Unit.create({
            'name': 'FIN-TBL-02',
            'area_id': cls.test_area.id,
            'seating_type': 'table',
            'capacity_min': 1,
            'capacity_max': 4,
            'price_per_guest': 20000.0,
        })
        cls.booking2 = cls.Booking.create_booking(cls.visit.id, table2.id, 1)
        cls.payment2 = cls.Payment.create({
            'booking_id': cls.booking2.id,
            'amount': 20000.0,
            'payment_method': 'bank_card',
            'reference': 'POS-CARD-002',
            'user_id': cls.manager_user.id,
        })
        cls.booking2.invalidate_recordset()

        # Booking 3: Unpaid and Released (Total 250k, Paid 0, Due 250k)
        cls.booking3 = cls.Booking.create_booking(cls.visit.id, cls.test_cabana.id, 4)
        cls.booking3.action_release()

    def test_01_collections_action_and_menu_exist(self):
        """Verify Financial Collections Analysis action and menu exist and are configured."""
        action = self.env.ref('sunnyside_visitor_management.action_sunnyside_payment_reporting')
        self.assertTrue(action.exists(), "Collections action must be defined.")
        self.assertEqual(action.res_model, 'sunnyside.booking.payment')
        self.assertIn('graph', action.view_mode)
        self.assertIn('pivot', action.view_mode)
        self.assertIn('list', action.view_mode)

        menu = self.env.ref('sunnyside_visitor_management.menu_sunnyside_report_payments')
        self.assertTrue(menu.exists(), "Collections menu item must exist.")
        self.assertEqual(menu.action.id, action.id)
        parent_menu = self.env.ref('sunnyside_visitor_management.menu_sunnyside_reporting')
        self.assertEqual(menu.parent_id.id, parent_menu.id, "Menu must be nested under Reporting.")

    def test_02_collections_views_registered(self):
        """Verify dedicated collections graph, pivot, list, and search views are registered."""
        graph_view = self.env.ref('sunnyside_visitor_management.view_sunnyside_payment_reporting_graph')
        self.assertEqual(graph_view.model, 'sunnyside.booking.payment')
        self.assertEqual(graph_view.type, 'graph')

        pivot_view = self.env.ref('sunnyside_visitor_management.view_sunnyside_payment_reporting_pivot')
        self.assertEqual(pivot_view.model, 'sunnyside.booking.payment')
        self.assertEqual(pivot_view.type, 'pivot')

        list_view = self.env.ref('sunnyside_visitor_management.view_sunnyside_payment_reporting_list')
        self.assertEqual(list_view.model, 'sunnyside.booking.payment')
        self.assertEqual(list_view.type, 'list')

        search_view = self.env.ref('sunnyside_visitor_management.view_sunnyside_payment_reporting_search')
        self.assertEqual(search_view.model, 'sunnyside.booking.payment')
        self.assertEqual(search_view.type, 'search')

    def test_03_collections_report_uses_correct_payment_model(self):
        """Verify the Collections report action targets sunnyside.booking.payment directly."""
        action = self.env.ref('sunnyside_visitor_management.action_sunnyside_payment_reporting')
        self.assertEqual(action.res_model, 'sunnyside.booking.payment')

    def test_04_payment_amount_aggregation(self):
        """Verify payment amount aggregation is available via SUM(amount)."""
        groups = self.Payment._read_group(
            domain=[('id', 'in', [self.payment1.id, self.payment2.id])],
            groupby=[],
            aggregates=['amount:sum', '__count'],
        )
        total_amount, total_count = groups[0]
        self.assertEqual(total_amount, 40000.0)
        self.assertEqual(total_count, 2)

    def test_05_payment_methods_can_be_grouped(self):
        """Verify payment records can be grouped by payment_method."""
        groups = self.Payment._read_group(
            domain=[('id', 'in', [self.payment1.id, self.payment2.id])],
            groupby=['payment_method'],
            aggregates=['amount:sum', '__count'],
        )
        methods = {g[0]: {'amount': g[1], 'count': g[2]} for g in groups}
        self.assertIn('cash', methods)
        self.assertEqual(methods['cash']['amount'], 20000.0)
        self.assertEqual(methods['cash']['count'], 1)
        self.assertIn('bank_card', methods)
        self.assertEqual(methods['bank_card']['amount'], 20000.0)
        self.assertEqual(methods['bank_card']['count'], 1)

    def test_06_payment_dates_can_be_grouped(self):
        """Verify payment records can be grouped by payment date intervals."""
        groups = self.Payment._read_group(
            domain=[('id', 'in', [self.payment1.id, self.payment2.id])],
            groupby=['payment_datetime:day'],
            aggregates=['amount:sum', '__count'],
        )
        self.assertTrue(len(groups) >= 1)

    def test_07_recorded_by_attribution_available(self):
        """Verify cashier/staff attribution is available via user_id grouping."""
        groups = self.Payment._read_group(
            domain=[('id', 'in', [self.payment1.id, self.payment2.id])],
            groupby=['user_id'],
            aggregates=['amount:sum', '__count'],
        )
        users = {g[0].id: {'amount': g[1], 'count': g[2]} for g in groups}
        self.assertIn(self.receptionist_user.id, users)
        self.assertEqual(users[self.receptionist_user.id]['amount'], 20000.0)
        self.assertIn(self.manager_user.id, users)
        self.assertEqual(users[self.manager_user.id]['amount'], 20000.0)

    def test_08_receivables_action_and_menu_exist(self):
        """Verify Outstanding Balances & Receivables action and menu exist and are configured."""
        action = self.env.ref('sunnyside_visitor_management.action_sunnyside_booking_receivables')
        self.assertTrue(action.exists(), "Receivables action must be defined.")
        self.assertEqual(action.res_model, 'sunnyside.booking')
        self.assertIn('list', action.view_mode)
        self.assertIn('pivot', action.view_mode)
        self.assertIn('graph', action.view_mode)

        menu = self.env.ref('sunnyside_visitor_management.menu_sunnyside_report_receivables')
        self.assertTrue(menu.exists(), "Receivables menu item must exist.")
        self.assertEqual(menu.action.id, action.id)
        parent_menu = self.env.ref('sunnyside_visitor_management.menu_sunnyside_reporting')
        self.assertEqual(menu.parent_id.id, parent_menu.id, "Menu must be nested under Reporting.")

    def test_09_receivables_views_registered(self):
        """Verify dedicated receivables list, pivot, graph, and search views are registered."""
        list_view = self.env.ref('sunnyside_visitor_management.view_sunnyside_booking_receivables_list')
        self.assertEqual(list_view.model, 'sunnyside.booking')
        self.assertEqual(list_view.type, 'list')

        pivot_view = self.env.ref('sunnyside_visitor_management.view_sunnyside_booking_receivables_pivot')
        self.assertEqual(pivot_view.model, 'sunnyside.booking')
        self.assertEqual(pivot_view.type, 'pivot')

        graph_view = self.env.ref('sunnyside_visitor_management.view_sunnyside_booking_receivables_graph')
        self.assertEqual(graph_view.model, 'sunnyside.booking')
        self.assertEqual(graph_view.type, 'graph')

        search_view = self.env.ref('sunnyside_visitor_management.view_sunnyside_booking_receivables_search')
        self.assertEqual(search_view.model, 'sunnyside.booking')
        self.assertEqual(search_view.type, 'search')

    def test_10_outstanding_balance_measure_available(self):
        """Verify outstanding balance measure (amount_due) and financial measures are available."""
        groups = self.Booking._read_group(
            domain=[('id', 'in', [self.booking1.id, self.booking2.id, self.booking3.id])],
            groupby=[],
            aggregates=['amount_due:sum', 'amount_total:sum', 'amount_paid:sum', '__count'],
        )
        total_due, total_val, total_paid, total_count = groups[0]
        self.assertEqual(total_val, 40000.0 + 20000.0 + 250000.0)
        self.assertEqual(total_paid, 20000.0 + 20000.0)
        self.assertEqual(total_due, 20000.0 + 250000.0)
        self.assertEqual(total_count, 3)

        # Verify pivot arch specifies these measures
        pivot_arch = self.env.ref('sunnyside_visitor_management.view_sunnyside_booking_receivables_pivot').arch
        self.assertIn('amount_due', pivot_arch)
        self.assertIn('amount_total', pivot_arch)
        self.assertIn('amount_paid', pivot_arch)

    def test_11_payment_status_grouping_available(self):
        """Verify bookings can be grouped by payment_status."""
        groups = self.Booking._read_group(
            domain=[('id', 'in', [self.booking1.id, self.booking2.id, self.booking3.id])],
            groupby=['payment_status'],
            aggregates=['amount_due:sum', '__count'],
        )
        statuses = {g[0]: {'due': g[1], 'count': g[2]} for g in groups}
        self.assertIn('partial', statuses)
        self.assertEqual(statuses['partial']['due'], 20000.0)
        self.assertIn('paid', statuses)
        self.assertEqual(statuses['paid']['due'], 0.0)
        self.assertIn('unpaid', statuses)
        self.assertEqual(statuses['unpaid']['due'], 250000.0)

    def test_12_released_bookings_with_outstanding_balances_reportable(self):
        """Verify released bookings with outstanding balances remain visible and reportable."""
        self.assertEqual(self.booking3.state, 'released')
        self.assertEqual(self.booking3.amount_due, 250000.0)

        # The default search filter for receivables is amount_due > 0
        outstanding_bookings = self.Booking.search([
            ('id', 'in', [self.booking1.id, self.booking2.id, self.booking3.id]),
            ('amount_due', '>', 0),
        ])
        self.assertIn(self.booking1, outstanding_bookings, "Partially paid active booking must be included.")
        self.assertIn(self.booking3, outstanding_bookings, "Released booking with outstanding balance must be included.")
        self.assertNotIn(self.booking2, outstanding_bookings, "Fully paid booking must not appear under outstanding balances.")

    def test_13_manager_only_menu_action_restrictions(self):
        """Verify manager-only restrictions are configured on financial menus and actions."""
        manager_group = self.env.ref('sunnyside_visitor_management.group_sunnyside_manager')

        # Check Menus
        menu_pay = self.env.ref('sunnyside_visitor_management.menu_sunnyside_report_payments')
        self.assertIn(manager_group, menu_pay.group_ids)

        menu_rec = self.env.ref('sunnyside_visitor_management.menu_sunnyside_report_receivables')
        self.assertIn(manager_group, menu_rec.group_ids)

        # Check Actions
        act_pay = self.env.ref('sunnyside_visitor_management.action_sunnyside_payment_reporting')
        self.assertIn(manager_group, act_pay.group_ids)

        act_rec = self.env.ref('sunnyside_visitor_management.action_sunnyside_booking_receivables')
        self.assertIn(manager_group, act_rec.group_ids)

    def test_14_receptionist_cannot_access_manager_reporting_menus(self):
        """Verify receptionists cannot see manager-only financial reporting menus, but retain operational reporting."""
        Menu = self.env['ir.ui.menu']

        menu_pay = self.env.ref('sunnyside_visitor_management.menu_sunnyside_report_payments')
        menu_rec = self.env.ref('sunnyside_visitor_management.menu_sunnyside_report_receivables')
        menu_visits = self.env.ref('sunnyside_visitor_management.menu_sunnyside_report_visits')
        menu_bookings = self.env.ref('sunnyside_visitor_management.menu_sunnyside_report_bookings')

        # Receptionist visible menus query using native Odoo _visible_menu_ids()
        receptionist_visible_ids = Menu.with_user(self.receptionist_user)._visible_menu_ids()

        # Financial menus must NOT be visible to receptionist
        self.assertNotIn(menu_pay.id, receptionist_visible_ids, "Collections menu must be hidden from receptionist.")
        self.assertNotIn(menu_rec.id, receptionist_visible_ids, "Receivables menu must be hidden from receptionist.")

        # Operational menus MUST remain visible to receptionist
        self.assertIn(menu_visits.id, receptionist_visible_ids, "Visits Analysis must remain visible to receptionist.")
        self.assertIn(menu_bookings.id, receptionist_visible_ids, "Seating & Bookings Analysis must remain visible to receptionist.")

        # Manager user sees all 4 menus
        manager_visible_ids = Menu.with_user(self.manager_user)._visible_menu_ids()
        self.assertIn(menu_pay.id, manager_visible_ids)
        self.assertIn(menu_rec.id, manager_visible_ids)
        self.assertIn(menu_visits.id, manager_visible_ids)
        self.assertIn(menu_bookings.id, manager_visible_ids)
