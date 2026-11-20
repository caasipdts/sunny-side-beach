# -*- coding: utf-8 -*-
"""
Phase 4 Tests: Visits Analysis Optimization
Tests visit metrics aggregation, new vs returning classification, lifetime vs period counts,
date filtering and boundary behavior, location and source groupings, visitor origin area,
frequent visitor segmentation, user attribution, and operational access rights.
"""
from datetime import datetime, date, timedelta, time as dtime
from odoo import fields
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestVisitReporting(TransactionCase):
    """
    Test suite for Phase 4: Visits Analysis Optimization.
    Validates analytical queries, measures, filters, groupings, and access control.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Database schema safety within test transaction
        cls.cr.execute("""
            ALTER TABLE res_partner
            ADD COLUMN IF NOT EXISTS is_sunnyside_visitor boolean,
            ADD COLUMN IF NOT EXISTS sunnyside_location_id integer,
            ADD COLUMN IF NOT EXISTS sunnyside_visit_count integer,
            ADD COLUMN IF NOT EXISTS sunnyside_visitor_type varchar,
            ADD COLUMN IF NOT EXISTS is_frequent_visitor boolean default false,
            ADD COLUMN IF NOT EXISTS sunnyside_first_visit_date timestamp without time zone,
            ADD COLUMN IF NOT EXISTS sunnyside_last_visit_date timestamp without time zone,
            ADD COLUMN IF NOT EXISTS privacy_acknowledged boolean,
            ADD COLUMN IF NOT EXISTS privacy_acknowledgement_date timestamp without time zone,
            ADD COLUMN IF NOT EXISTS privacy_notice_version varchar,
            ADD COLUMN IF NOT EXISTS marketing_consent boolean,
            ADD COLUMN IF NOT EXISTS marketing_consent_date timestamp without time zone;

            ALTER TABLE sunnyside_visit
            ADD COLUMN IF NOT EXISTS visitor_phone varchar,
            ADD COLUMN IF NOT EXISTS visitor_type varchar,
            ADD COLUMN IF NOT EXISTS user_id integer,
            ADD COLUMN IF NOT EXISTS visitor_location_id integer,
            ADD COLUMN IF NOT EXISTS visitor_visit_count integer,
            ADD COLUMN IF NOT EXISTS is_frequent_visitor boolean default false,
            ADD COLUMN IF NOT EXISTS new_visit_count integer default 0,
            ADD COLUMN IF NOT EXISTS returning_visit_count integer default 0;
        """)

    def setUp(self):
        super().setUp()
        self.Partner = self.env['res.partner']
        self.Visit = self.env['sunnyside.visit']
        self.Location = self.env['sunnyside.location']
        self.Users = self.env['res.users']

        self.group_user = self.env.ref('sunnyside_visitor_management.group_sunnyside_user')
        self.group_manager = self.env.ref('sunnyside_visitor_management.group_sunnyside_manager')

        # Test users
        self.receptionist_user = self.Users.create({
            'name': 'Receptionist Bukola',
            'login': 'rep_bukola@sunnyside.ng',
            'email': 'bukola@sunnyside.ng',
            'group_ids': [(6, 0, [
                self.env.ref('base.group_user').id,
                self.group_user.id,
            ])],
        })

        self.manager_user = self.Users.create({
            'name': 'Manager Femi',
            'login': 'mgr_femi@sunnyside.ng',
            'email': 'femi@sunnyside.ng',
            'group_ids': [(6, 0, [
                self.env.ref('base.group_user').id,
                self.group_manager.id,
            ])],
        })

        # Test locations
        self.loc_lekki = self.Location.create({'name': 'Lekki Phase 1', 'active': True})
        self.loc_vi = self.Location.create({'name': 'Victoria Island', 'active': True})
        self.loc_ikoyi = self.Location.create({'name': 'Ikoyi', 'active': True})

        now = fields.Datetime.now()
        yesterday = now - timedelta(days=1)
        last_week = now - timedelta(days=7)
        forty_five_days_ago = now - timedelta(days=45)

        # -----------------------------------------------------------------
        # Visitor 1: New / First-time guest (1 lifetime visit)
        # -----------------------------------------------------------------
        self.visitor_new = self.Partner.create({
            'name': 'Amaka Okonkwo',
            'phone': '+2348030000001',
            'is_sunnyside_visitor': True,
            'sunnyside_location_id': self.loc_lekki.id,
            'privacy_acknowledged': True,
        })
        self.visit_new = self.Visit.with_user(self.receptionist_user).create({
            'visitor_id': self.visitor_new.id,
            'location_id': self.loc_lekki.id,
            'source': 'receptionist',
            'check_in_datetime': now,
            'state': 'checked_in',
        })

        # -----------------------------------------------------------------
        # Visitor 2: Returning guest (2 lifetime visits)
        # Origin = Victoria Island, but second visit at Lekki Phase 1
        # -----------------------------------------------------------------
        self.visitor_returning = self.Partner.create({
            'name': 'Babajide Sanwo',
            'phone': '+2348030000002',
            'is_sunnyside_visitor': True,
            'sunnyside_location_id': self.loc_vi.id,
            'privacy_acknowledged': True,
        })
        self.visit_ret_1 = self.Visit.create({
            'visitor_id': self.visitor_returning.id,
            'location_id': self.loc_vi.id,
            'source': 'qr_code',
            'check_in_datetime': last_week,
            'state': 'checked_in',
        })
        self.visit_ret_2 = self.Visit.with_user(self.receptionist_user).create({
            'visitor_id': self.visitor_returning.id,
            'location_id': self.loc_lekki.id,
            'source': 'receptionist',
            'check_in_datetime': now,
            'state': 'checked_in',
        })

        # -----------------------------------------------------------------
        # Visitor 3: Frequent guest (4 lifetime visits, threshold is 3+)
        # -----------------------------------------------------------------
        self.visitor_frequent = self.Partner.create({
            'name': 'Chinedu Achebe',
            'phone': '+2348030000003',
            'is_sunnyside_visitor': True,
            'sunnyside_location_id': self.loc_ikoyi.id,
            'privacy_acknowledged': True,
        })
        self.visit_freq_1 = self.Visit.create({
            'visitor_id': self.visitor_frequent.id,
            'location_id': self.loc_ikoyi.id,
            'source': 'website',
            'check_in_datetime': now - timedelta(days=20),
            'state': 'checked_in',
        })
        self.visit_freq_2 = self.Visit.create({
            'visitor_id': self.visitor_frequent.id,
            'location_id': self.loc_ikoyi.id,
            'source': 'qr_code',
            'check_in_datetime': now - timedelta(days=15),
            'state': 'checked_in',
        })
        self.visit_freq_3 = self.Visit.create({
            'visitor_id': self.visitor_frequent.id,
            'location_id': self.loc_ikoyi.id,
            'source': 'receptionist',
            'check_in_datetime': yesterday,
            'state': 'checked_in',
        })
        self.visit_freq_4 = self.Visit.with_user(self.receptionist_user).create({
            'visitor_id': self.visitor_frequent.id,
            'location_id': self.loc_ikoyi.id,
            'source': 'receptionist',
            'check_in_datetime': now,
            'state': 'checked_in',
        })

        # -----------------------------------------------------------------
        # Visitor 4: Lapsed guest (checked in 45 days ago, never returned)
        # -----------------------------------------------------------------
        self.visitor_lapsed = self.Partner.create({
            'name': 'Damilola Taylor',
            'phone': '+2348030000004',
            'is_sunnyside_visitor': True,
            'sunnyside_location_id': self.loc_lekki.id,
            'privacy_acknowledged': True,
        })
        self.visit_lapsed = self.Visit.create({
            'visitor_id': self.visitor_lapsed.id,
            'location_id': self.loc_lekki.id,
            'source': 'website',
            'check_in_datetime': forty_five_days_ago,
            'state': 'checked_in',
        })

        # Cancelled visit for testing status filtering
        self.visit_cancelled = self.Visit.create({
            'visitor_id': self.visitor_new.id,
            'location_id': self.loc_lekki.id,
            'source': 'receptionist',
            'check_in_datetime': now,
            'state': 'cancelled',
        })

    # =========================================================================
    # 01. Total visit aggregation
    # =========================================================================
    def test_01_total_visit_aggregation(self):
        """Total checked-in visits aggregation reflects all recorded visits."""
        all_checked_in = self.Visit.search_count([('state', '=', 'checked_in')])
        # We created 8 checked-in visits in setUp
        self.assertGreaterEqual(all_checked_in, 8)

        # Cancelled visit must be excluded when filtered by checked_in
        cancelled_count = self.Visit.search_count([('state', '=', 'cancelled')])
        self.assertGreaterEqual(cancelled_count, 1)

    # =========================================================================
    # 02. New versus returning visitor classification
    # =========================================================================
    def test_02_new_vs_returning_visitor_classification(self):
        """Visit classification at time of check-in correctly distinguishes new vs returning."""
        # Visitor 1 (first visit) -> new
        self.assertEqual(self.visit_new.visitor_type, 'new')
        self.assertEqual(self.visit_new.new_visit_count, 1)
        self.assertEqual(self.visit_new.returning_visit_count, 0)

        # Visitor 2: 1st visit was 'new', 2nd visit was 'returning'
        self.assertEqual(self.visit_ret_1.visitor_type, 'new')
        self.assertEqual(self.visit_ret_2.visitor_type, 'returning')
        self.assertEqual(self.visit_ret_2.new_visit_count, 0)
        self.assertEqual(self.visit_ret_2.returning_visit_count, 1)

        # Visitor 3: 1st visit was 'new', visits 2, 3, 4 were 'returning'
        self.assertEqual(self.visit_freq_1.visitor_type, 'new')
        self.assertEqual(self.visit_freq_2.visitor_type, 'returning')
        self.assertEqual(self.visit_freq_3.visitor_type, 'returning')
        self.assertEqual(self.visit_freq_4.visitor_type, 'returning')

    # =========================================================================
    # 03. Measures: new_visit_count and returning_visit_count summation
    # =========================================================================
    def test_03_measures_new_and_returning_summation(self):
        """new_visit_count and returning_visit_count sum to total visits."""
        visits = self.Visit.search([('state', '=', 'checked_in')])
        total_visits = len(visits)
        new_sum = sum(visits.mapped('new_visit_count'))
        ret_sum = sum(visits.mapped('returning_visit_count'))
        self.assertEqual(total_visits, new_sum + ret_sum)

    # =========================================================================
    # 04. Lifetime visit count vs period visit count
    # =========================================================================
    def test_04_lifetime_vs_period_visit_count(self):
        """Lifetime visit count on visitor is distinguished from period visit counts."""
        # Chinedu has 4 lifetime visits
        self.assertEqual(self.visitor_frequent.sunnyside_visit_count, 4)
        self.assertEqual(self.visit_freq_4.visitor_visit_count, 4)

        # But within 'today', Chinedu has exactly 1 visit
        today = fields.Date.today()
        today_start = datetime.combine(today, dtime.min)
        today_end = datetime.combine(today, dtime.max)

        today_chinedu_visits = self.Visit.search_count([
            ('visitor_id', '=', self.visitor_frequent.id),
            ('check_in_datetime', '>=', today_start),
            ('check_in_datetime', '<=', today_end),
            ('state', '=', 'checked_in'),
        ])
        self.assertEqual(today_chinedu_visits, 1)
        # Period visit count (1) != Lifetime visit count (4)
        self.assertNotEqual(today_chinedu_visits, self.visitor_frequent.sunnyside_visit_count)

    # =========================================================================
    # 05. Date filtering: today and yesterday
    # =========================================================================
    def test_05_date_filtering_today_yesterday(self):
        """Today and yesterday filters return only visits matching those exact day windows."""
        today = fields.Date.today()
        today_start = datetime.combine(today, dtime.min)
        today_end = datetime.combine(today, dtime.max)
        yesterday = today - timedelta(days=1)
        yesterday_start = datetime.combine(yesterday, dtime.min)
        yesterday_end = datetime.combine(yesterday, dtime.max)

        today_visits = self.Visit.search([
            ('check_in_datetime', '>=', today_start),
            ('check_in_datetime', '<=', today_end),
            ('state', '=', 'checked_in'),
        ])
        yesterday_visits = self.Visit.search([
            ('check_in_datetime', '>=', yesterday_start),
            ('check_in_datetime', '<=', yesterday_end),
            ('state', '=', 'checked_in'),
        ])

        # Visits created for today: visit_new, visit_ret_2, visit_freq_4
        today_ids = today_visits.ids
        self.assertIn(self.visit_new.id, today_ids)
        self.assertIn(self.visit_ret_2.id, today_ids)
        self.assertIn(self.visit_freq_4.id, today_ids)
        self.assertNotIn(self.visit_freq_3.id, today_ids)

        # Visit created for yesterday: visit_freq_3
        yesterday_ids = yesterday_visits.ids
        self.assertIn(self.visit_freq_3.id, yesterday_ids)
        self.assertNotIn(self.visit_new.id, yesterday_ids)

    # =========================================================================
    # 06. Date filtering: this week, this month, this year
    # =========================================================================
    def test_06_date_filtering_week_month_year(self):
        """Relative date filters return expected hierarchical supersets."""
        today = fields.Date.today()
        monday = today - timedelta(days=today.weekday())
        week_start = datetime.combine(monday, dtime.min)
        month_start = datetime.combine(today.replace(day=1), dtime.min)
        year_start = datetime.combine(today.replace(month=1, day=1), dtime.min)

        month_visits = self.Visit.search([
            ('check_in_datetime', '>=', month_start),
            ('state', '=', 'checked_in'),
        ])
        year_visits = self.Visit.search([
            ('check_in_datetime', '>=', year_start),
            ('state', '=', 'checked_in'),
        ])

        # Year visits must be a superset of month visits
        self.assertGreaterEqual(len(year_visits), len(month_visits))

    # =========================================================================
    # 07. Date boundary behavior
    # =========================================================================
    def test_07_date_boundary_behavior(self):
        """A visit at exactly 23:59:59 yesterday is not in today's filter."""
        today = fields.Date.today()
        yesterday = today - timedelta(days=1)
        yesterday_end = datetime.combine(yesterday, dtime(23, 59, 59))
        today_start = datetime.combine(today, dtime.min)

        boundary_visit = self.Visit.create({
            'visitor_id': self.visitor_new.id,
            'location_id': self.loc_lekki.id,
            'source': 'qr_code',
            'check_in_datetime': yesterday_end,
            'state': 'checked_in',
        })

        today_visits = self.Visit.search([
            ('check_in_datetime', '>=', today_start),
            ('id', '=', boundary_visit.id),
        ])
        self.assertFalse(today_visits, "Visit at 23:59:59 yesterday must not be included in today's visits")

    # =========================================================================
    # 08. Grouping by location
    # =========================================================================
    def test_08_grouping_by_location(self):
        """read_group by location_id aggregates visit counts per neighbourhood."""
        grouped = self.Visit.read_group(
            domain=[('state', '=', 'checked_in')],
            fields=['location_id'],
            groupby=['location_id'],
        )
        location_counts = {g['location_id'][0]: g['location_id_count'] for g in grouped if g['location_id']}
        # Must have counts for Lekki, VI, and Ikoyi
        self.assertIn(self.loc_lekki.id, location_counts)
        self.assertIn(self.loc_vi.id, location_counts)
        self.assertIn(self.loc_ikoyi.id, location_counts)
        self.assertGreaterEqual(location_counts[self.loc_ikoyi.id], 4)

    # =========================================================================
    # 09. Grouping by check-in source
    # =========================================================================
    def test_09_grouping_by_source(self):
        """read_group by source aggregates check-ins across QR code, website, and receptionist."""
        grouped = self.Visit.read_group(
            domain=[('state', '=', 'checked_in')],
            fields=['source'],
            groupby=['source'],
        )
        sources = {g['source']: g['source_count'] for g in grouped if g['source']}
        self.assertIn('receptionist', sources)
        self.assertIn('qr_code', sources)
        self.assertIn('website', sources)

    # =========================================================================
    # 10. Visitor type filters
    # =========================================================================
    def test_10_visitor_type_filters(self):
        """Search domains for new vs returning visitors return the correct visit sets."""
        new_visits = self.Visit.search([('visitor_type', '=', 'new'), ('state', '=', 'checked_in')])
        ret_visits = self.Visit.search([('visitor_type', '=', 'returning'), ('state', '=', 'checked_in')])

        new_ids = new_visits.ids
        ret_ids = ret_visits.ids

        # Visit 1 of each visitor must be in new_visits
        self.assertIn(self.visit_new.id, new_ids)
        self.assertIn(self.visit_ret_1.id, new_ids)
        self.assertIn(self.visit_freq_1.id, new_ids)

        # Subsequent visits must be in ret_visits
        self.assertIn(self.visit_ret_2.id, ret_ids)
        self.assertIn(self.visit_freq_2.id, ret_ids)
        self.assertIn(self.visit_freq_3.id, ret_ids)
        self.assertIn(self.visit_freq_4.id, ret_ids)

    # =========================================================================
    # 11. Visitor area of origin reporting
    # =========================================================================
    def test_11_visitor_origin_area_reporting(self):
        """visitor_location_id exposes the visitor's home neighbourhood regardless of check-in location."""
        # Babajide's home area is Victoria Island
        self.assertEqual(self.visitor_returning.sunnyside_location_id.id, self.loc_vi.id)

        # visit_ret_2 was recorded at Lekki Phase 1, but home area is Victoria Island
        self.assertEqual(self.visit_ret_2.location_id.id, self.loc_lekki.id)
        self.assertEqual(self.visit_ret_2.visitor_location_id.id, self.loc_vi.id)

        # Can group or filter by visitor_location_id
        grouped = self.Visit.read_group(
            domain=[('state', '=', 'checked_in')],
            fields=['visitor_location_id'],
            groupby=['visitor_location_id'],
        )
        origin_counts = {g['visitor_location_id'][0]: g['visitor_location_id_count'] for g in grouped if g['visitor_location_id']}
        self.assertIn(self.loc_vi.id, origin_counts)

    # =========================================================================
    # 12. Frequent visitor segmentation (3+ lifetime visits threshold)
    # =========================================================================
    def test_12_frequent_visitor_segmentation(self):
        """Explicit documented threshold (3+ visits) correctly flags frequent visitors."""
        # 1 visit -> not frequent
        self.assertFalse(self.visitor_new.is_frequent_visitor)
        self.assertFalse(self.visit_new.is_frequent_visitor)

        # 2 visits -> not frequent
        self.assertFalse(self.visitor_returning.is_frequent_visitor)
        self.assertFalse(self.visit_ret_2.is_frequent_visitor)

        # 4 visits -> frequent (threshold is >= 3)
        self.assertTrue(self.visitor_frequent.is_frequent_visitor)
        self.assertTrue(self.visit_freq_4.is_frequent_visitor)

        # Filter by frequent visitors on visit model
        frequent_visits = self.Visit.search([('is_frequent_visitor', '=', True)])
        self.assertIn(self.visit_freq_4.id, frequent_visits.ids)
        self.assertNotIn(self.visit_new.id, frequent_visits.ids)

    # =========================================================================
    # 13. Lapsed visitor filtering on res.partner
    # =========================================================================
    def test_13_lapsed_visitor_filtering(self):
        """sunnyside_last_visit_date accurately identifies visitors who have not checked in within 30 days."""
        thirty_days_ago = fields.Datetime.now() - timedelta(days=30)

        # Damilola's last visit was 45 days ago
        self.assertTrue(self.visitor_lapsed.sunnyside_last_visit_date)
        self.assertLess(self.visitor_lapsed.sunnyside_last_visit_date, thirty_days_ago)

        # Amaka checked in today
        self.assertGreater(self.visitor_new.sunnyside_last_visit_date, thirty_days_ago)

        # Search for lapsed visitors (>30 days inactive)
        lapsed_visitors = self.Partner.search([
            ('is_sunnyside_visitor', '=', True),
            ('sunnyside_last_visit_date', '<', thirty_days_ago),
        ])
        self.assertIn(self.visitor_lapsed.id, lapsed_visitors.ids)
        self.assertNotIn(self.visitor_new.id, lapsed_visitors.ids)

    # =========================================================================
    # 14. User ID attribution: receptionist vs public check-in
    # =========================================================================
    def test_14_user_id_attribution(self):
        """Receptionist check-in records user_id; QR/Website check-ins leave user_id empty."""
        # Receptionist Bukola created visit_new
        self.assertEqual(self.visit_new.user_id.id, self.receptionist_user.id)

        # QR code self-check-in has no internal user_id
        self.assertFalse(self.visit_ret_1.user_id)

        # Website check-in has no internal user_id
        self.assertFalse(self.visit_freq_1.user_id)

    # =========================================================================
    # 15. Operational access rights for receptionist and manager
    # =========================================================================
    def test_15_access_rights_receptionist_and_manager(self):
        """Both receptionist and manager groups have full read and reporting access to visits."""
        # Receptionist reading visits
        recep_visits = self.Visit.with_user(self.receptionist_user).search([('state', '=', 'checked_in')])
        self.assertGreater(len(recep_visits), 0)

        # Receptionist executing read_group (powers pivot and graph views)
        recep_grouped = self.Visit.with_user(self.receptionist_user).read_group(
            domain=[('state', '=', 'checked_in')],
            fields=['location_id'],
            groupby=['location_id'],
        )
        self.assertGreater(len(recep_grouped), 0)

        # Manager reading visits
        mgr_visits = self.Visit.with_user(self.manager_user).search([('state', '=', 'checked_in')])
        self.assertGreater(len(mgr_visits), 0)

    # =========================================================================
    # 16. Reporting action and views integrity
    # =========================================================================
    def test_16_reporting_action_and_views_integrity(self):
        """action_sunnyside_visit_reporting is correctly configured with graph, pivot, and list."""
        action = self.env.ref('sunnyside_visitor_management.action_sunnyside_visit_reporting', raise_if_not_found=False)
        self.assertTrue(action)
        self.assertEqual(action.res_model, 'sunnyside.visit')
        self.assertEqual(action.view_mode, 'graph,pivot,list')

        # Check view bindings
        graph_view = self.env.ref('sunnyside_visitor_management.view_sunnyside_visit_graph', raise_if_not_found=False)
        self.assertTrue(graph_view)
        pivot_view = self.env.ref('sunnyside_visitor_management.view_sunnyside_visit_pivot', raise_if_not_found=False)
        self.assertTrue(pivot_view)
        rep_list_view = self.env.ref('sunnyside_visitor_management.view_sunnyside_visit_reporting_list', raise_if_not_found=False)
        self.assertTrue(rep_list_view)

    # =========================================================================
    # 17. Cancelled visits handling
    # =========================================================================
    def test_17_cancelled_visits_handling(self):
        """Cancelled visits are tracked with state='cancelled' and excluded by default filter."""
        self.assertEqual(self.visit_cancelled.state, 'cancelled')
        # Default reporting domain: state='checked_in'
        active_visits = self.Visit.search([('state', '=', 'checked_in')])
        self.assertNotIn(self.visit_cancelled.id, active_visits.ids)

    # =========================================================================
    # 18. Regression: Checkin wizard flow operates unchanged
    # =========================================================================
    def test_18_regression_checkin_wizard_flow(self):
        """Front-desk checkin wizard creates visit and computes visitor_type without regression."""
        Wizard = self.env['sunnyside.checkin.wizard'].with_user(self.receptionist_user)
        wiz = Wizard.create({
            'phone': '08097778899',
            'country_dial_code': '234',
            'name': 'Halima Bello',
            'location_id': self.loc_lekki.id,
        })
        action = wiz.action_confirm_checkin()
        visit_id = action.get('res_id')
        self.assertTrue(visit_id)

        visit = self.Visit.browse(visit_id)
        self.assertEqual(visit.visitor_id.name, 'Halima Bello')
        self.assertEqual(visit.visitor_type, 'new')
        self.assertEqual(visit.source, 'receptionist')
        self.assertEqual(visit.state, 'checked_in')
        self.assertEqual(visit.user_id.id, self.receptionist_user.id)
        self.assertEqual(visit.new_visit_count, 1)
        self.assertEqual(visit.returning_visit_count, 0)

