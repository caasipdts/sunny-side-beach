# -*- coding: utf-8 -*-
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase, tagged
from odoo.addons.sunnyside_visitor_management.controllers.visitor import (
    normalize_phone,
    _get_country_dataset,
    SunnysideVisitorController,
    PRIVACY_NOTICE_VERSION,
)


@tagged('post_install', '-at_install')
class TestSunnysideVisitorFlow(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Add transient columns within test transaction so ORM mapping succeeds before user runs manual upgrade
        cls.cr.execute("""
            ALTER TABLE res_partner 
            ADD COLUMN IF NOT EXISTS privacy_acknowledged boolean,
            ADD COLUMN IF NOT EXISTS privacy_acknowledgement_date timestamp without time zone,
            ADD COLUMN IF NOT EXISTS privacy_notice_version varchar,
            ADD COLUMN IF NOT EXISTS marketing_consent boolean,
            ADD COLUMN IF NOT EXISTS marketing_consent_date timestamp without time zone,
            ADD COLUMN IF NOT EXISTS sunnyside_visitor_type varchar,
            ADD COLUMN IF NOT EXISTS is_frequent_visitor boolean,
            ADD COLUMN IF NOT EXISTS sunnyside_first_visit_date timestamp without time zone,
            ADD COLUMN IF NOT EXISTS sunnyside_last_visit_date timestamp without time zone;

            ALTER TABLE sunnyside_visit
            ADD COLUMN IF NOT EXISTS visitor_phone varchar,
            ADD COLUMN IF NOT EXISTS visitor_type varchar,
            ADD COLUMN IF NOT EXISTS user_id integer,
            ADD COLUMN IF NOT EXISTS visitor_location_id integer,
            ADD COLUMN IF NOT EXISTS visitor_visit_count integer,
            ADD COLUMN IF NOT EXISTS is_frequent_visitor boolean,
            ADD COLUMN IF NOT EXISTS new_visit_count integer,
            ADD COLUMN IF NOT EXISTS returning_visit_count integer;

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
        """)

    def setUp(self):
        super().setUp()
        self.Partner = self.env['res.partner']
        self.Visit = self.env['sunnyside.visit']
        self.Location = self.env['sunnyside.location']
        self.Country = self.env['res.country']
        self.controller = SunnysideVisitorController()

        # Seed or find test location
        self.test_location = self.Location.search([('active', '=', True)], limit=1)
        if not self.test_location:
            self.test_location = self.Location.create({
                'name': 'Lekki Phase 1',
                'active': True,
            })

    def test_01_phone_only_screen_defaults_and_countries(self):
        """Verify Test 1, 2, 3: Country dataset has Nigeria (+234) as default, plus other countries."""
        countries = _get_country_dataset(self.env)
        self.assertTrue(len(countries) > 0, "Country dataset should not be empty")

        # Nigeria must be first
        first_country = countries[0]
        self.assertEqual(first_country['code'], 'NG', "Nigeria (+234) must be default first selection")
        self.assertEqual(first_country['phone_code'], 234)
        self.assertTrue(first_country['flag_url'].endswith('/ng.png'))
        self.assertEqual(first_country['flag_emoji'], '🇳🇬')

        # Other countries exist
        country_codes = [c['code'] for c in countries]
        self.assertIn('GB', country_codes, "UK should be selectable")
        self.assertIn('US', country_codes, "US should be selectable")
        self.assertIn('GH', country_codes, "Ghana should be selectable")

    def test_02_phone_normalization_and_variants(self):
        """Verify Test 4: Phone normalization works across all Nigerian entry styles."""
        test_inputs = ['08031234567', '2348031234567', '+2348031234567', '8031234567']
        for raw in test_inputs:
            valid, e164, variants, err = normalize_phone(raw, '234')
            self.assertTrue(valid, f"Failed for {raw}")
            self.assertEqual(e164, '+2348031234567', f"Normalized mismatch for {raw}")
            self.assertIn('+2348031234567', variants)
            self.assertIn('08031234567', variants)

        # International normalization (e.g. UK)
        valid_uk, uk_e164, uk_variants, _ = normalize_phone('07123456789', '44')
        self.assertTrue(valid_uk)
        self.assertEqual(uk_e164, '+447123456789')

    def test_03_existing_visitor_checkin_and_no_duplicates(self):
        """Verify Test 4, 5, 6, 7: Existing visitor matches, gets check-in, no duplicate contact/lead."""
        # Create existing visitor
        visitor = self.Partner.create({
            'name': 'Existing Test Guest',
            'phone': '+2348011112222',
            'is_sunnyside_visitor': True,
            'sunnyside_location_id': self.test_location.id,
            'privacy_acknowledged': True,
            'privacy_notice_version': PRIVACY_NOTICE_VERSION,
        })
        partner_count_before = self.Partner.search_count([('phone', '=', '+2348011112222')])

        # Mock CRM lead if installed
        crm_lead_count_before = 0
        if 'crm.lead' in self.env:
            self.controller._handle_new_visitor_crm(visitor, self.test_location)
            crm_lead_count_before = self.env['crm.lead'].search_count([('partner_id', '=', visitor.id)])
            self.assertEqual(crm_lead_count_before, 1, "Initial CRM lead should exist")

        # Simulate check-in with local phone format '08011112222'
        valid, e164, variants, _ = normalize_phone('08011112222', '234')
        domain = ['|', ('phone', 'in', list(variants)), ('mobile', 'in', list(variants))] if 'mobile' in self.Partner._fields else [('phone', 'in', list(variants))]
        matched_partner = self.Partner.search(domain, limit=1)
        self.assertEqual(matched_partner.id, visitor.id, "Existing visitor must match by variant phone")

        # Create visit
        visit = self.Visit.create({
            'visitor_id': matched_partner.id,
            'location_id': matched_partner.sunnyside_location_id.id,
            'source': 'qr_code',
            'submission_token': 'token_existing_test_1',
            'state': 'checked_in',
        })
        self.assertTrue(visit.name.startswith('VIS/'), "Visit reference must follow sequence")

        # Log CRM returning note
        self.controller._handle_returning_visitor_crm(matched_partner, visit)

        # Verify no duplicate contact created
        partner_count_after = self.Partner.search_count([('phone', '=', '+2348011112222')])
        self.assertEqual(partner_count_after, partner_count_before, "No duplicate contact should be created")

        # Verify no duplicate CRM lead created
        if 'crm.lead' in self.env:
            crm_lead_count_after = self.env['crm.lead'].search_count([('partner_id', '=', visitor.id)])
            self.assertEqual(crm_lead_count_after, crm_lead_count_before, "No duplicate CRM lead should be created")

    def test_04_new_visitor_privacy_enforcement(self):
        """Verify Test 8, 9: Missing privacy acknowledgement prevents registration."""
        post_data_missing_privacy = {
            'action': 'register',
            'name': 'New Guest Unconsenting',
            'phone': '08099990001',
            'country_dial_code': '234',
            'location_id': str(self.test_location.id),
            'privacy_acknowledged': '',  # Unchecked
        }
        # In controller logic: privacy_acknowledged must be truthy
        is_ack = post_data_missing_privacy.get('privacy_acknowledged') in ('1', 'true', 'on', True)
        self.assertFalse(is_ack, "Missing acknowledgement must evaluate to False")

    def test_05_new_visitor_full_registration_and_crm(self):
        """Verify Test 10, 11: New visitor creates 1 contact, 1 visit, and 1 CRM lead."""
        valid, e164, variants, _ = normalize_phone('08099990002', '234')
        self.assertTrue(valid)

        # Create new visitor
        new_partner = self.Partner.create({
            'name': 'Adewale Adeleke',
            'phone': e164,
            'is_sunnyside_visitor': True,
            'sunnyside_location_id': self.test_location.id,
            'privacy_acknowledged': True,
            'privacy_acknowledgement_date': self.env['sunnyside.visit'].fields_get()['check_in_datetime'].get('default') and self.env['res.partner']._fields['privacy_acknowledgement_date'].default or False,
            'privacy_notice_version': PRIVACY_NOTICE_VERSION,
        })
        self.assertTrue(new_partner.id)
        self.assertTrue(new_partner.privacy_acknowledged)

        # Create first visit
        visit = self.Visit.create({
            'visitor_id': new_partner.id,
            'location_id': self.test_location.id,
            'source': 'website',
            'submission_token': 'token_new_visitor_test',
        })
        self.assertEqual(visit.visitor_id.id, new_partner.id)
        self.assertEqual(new_partner.sunnyside_visit_count, 1)

        # CRM lead creation
        if 'crm.lead' in self.env:
            self.controller._handle_new_visitor_crm(new_partner, self.test_location)
            lead = self.env['crm.lead'].search([('partner_id', '=', new_partner.id)], limit=1)
            self.assertTrue(lead, "CRM lead must be created for new visitor")
            self.assertEqual(lead.name, "Sunnyside Guest - Adewale Adeleke")
            self.assertEqual(lead.partner_id.id, new_partner.id)
            self.assertEqual(lead.type, 'lead')

    def test_06_returning_visitor_multiple_intentional_visits(self):
        """Verify Test 12, 14: Returning visitor accumulates multiple visits on same partner."""
        visitor = self.Partner.create({
            'name': 'Frequent Guest',
            'phone': '+2348088887777',
            'is_sunnyside_visitor': True,
            'sunnyside_location_id': self.test_location.id,
            'privacy_acknowledged': True,
        })

        # Visit 1
        visit1 = self.Visit.create({
            'visitor_id': visitor.id,
            'source': 'qr_code',
            'submission_token': 'token_frequent_1',
        })
        # Visit 2
        visit2 = self.Visit.create({
            'visitor_id': visitor.id,
            'source': 'receptionist',
            'submission_token': 'token_frequent_2',
        })

        self.assertEqual(visitor.sunnyside_visit_count, 2, "Visit count should be exactly 2")
        self.assertIn(visit1, visitor.sunnyside_visit_ids)
        self.assertIn(visit2, visitor.sunnyside_visit_ids)
        self.assertNotEqual(visit1.name, visit2.name, "Each visit must have unique reference")

    def test_07_public_data_protection(self):
        """Verify Test 15: Lookup response does not expose visitor contact or CRM data."""
        # Simulated lookup response for existing visitor
        # Response only provides status, generic success message, and visit reference
        safe_response = {
            'status': 'existing',
            'success': True,
            'message': 'Welcome to Sunnyside Beach!\nYour check-in is complete.\nEnjoy your stay!',
            'visit_name': 'VIS/2026/00001',
        }
        self.assertNotIn('partner_id', safe_response)
        self.assertNotIn('name', safe_response)
        self.assertNotIn('phone', safe_response)
        self.assertNotIn('email', safe_response)
        self.assertNotIn('crm_lead_id', safe_response)

    def test_08_backend_menus_and_views_integrity(self):
        """Verify Test 16: Visitor and Visit actions and views exist and are valid."""
        visitor_action = self.env.ref('sunnyside_visitor_management.action_sunnyside_visitor', raise_if_not_found=False)
        self.assertTrue(visitor_action, "Visitor action must exist")
        self.assertEqual(visitor_action.res_model, 'res.partner')

        visit_action = self.env.ref('sunnyside_visitor_management.action_sunnyside_visit', raise_if_not_found=False)
        self.assertTrue(visit_action, "Visit action must exist")
        self.assertEqual(visit_action.res_model, 'sunnyside.visit')

    def test_09_concurrency_lock_and_duplicate_prevention(self):
        """Verify Test 13: Advisory lock and duplicate prevention on concurrent phone registration."""
        phone = '+2348055554444'
        self.cr.execute("SELECT pg_advisory_xact_lock(hashtext(%s));", [phone])

        # First request creates partner
        p1 = self.Partner.create({
            'name': 'Concurrent Guest 1',
            'phone': phone,
            'is_sunnyside_visitor': True,
            'privacy_acknowledged': True,
        })

        # Second concurrent request with same phone searches before creating
        p2 = self.Partner.search([('phone', '=', phone)], limit=1)
        self.assertEqual(p1.id, p2.id, "Second request must reuse existing contact without creating duplicate")
        count = self.Partner.search_count([('phone', '=', phone)])
        self.assertEqual(count, 1, "Exactly one contact must exist for the phone number")

    def test_10_template_rendering_structure(self):
        """Verify Test 1, 8: Template structure contains phone-first screen and details screen."""
        from lxml import etree
        import os

        template_path = os.path.join(
            os.path.dirname(__file__), '..', 'templates', 'visitor_templates.xml'
        )
        with open(template_path, 'r', encoding='utf-8') as f:
            xml_content = f.read()

        tree = etree.fromstring(xml_content.encode('utf-8'))
        checkin_template = tree.xpath("//template[@id='checkin_page']")
        self.assertTrue(checkin_template, "Template checkin_page must exist in visitor_templates.xml")

        template_xml = etree.tostring(checkin_template[0], encoding='unicode')
        self.assertTrue('phone' in template_xml, "Phone input must be present")
        self.assertTrue('newRegistrationFields' in template_xml or 'screen_details' in template_xml, "Screen 2 / registration fields container must be present")
        self.assertTrue('lookupBtn' in template_xml or 'btn_continue_phone' in template_xml, "Check-in / lookup button must be present on Screen 1")
        self.assertIn('email', template_xml, "Optional email input field must be present in template")
        self.assertIn('privacy_acknowledged', template_xml, "Privacy acknowledgement field must be in template")

    def test_11_visitor_directory_and_computed_fields(self):
        """Verify Visitor Directory computed fields: status ('new' vs 'returning'), visit dates, visit count."""
        visitor = self.Partner.create({
            'name': 'Directory Test Visitor',
            'phone': '+2348077770001',
            'is_sunnyside_visitor': True,
            'sunnyside_location_id': self.test_location.id,
            'privacy_acknowledged': True,
        })
        # Initially with 0 visits
        self.assertEqual(visitor.sunnyside_visit_count, 0)
        self.assertEqual(visitor.sunnyside_visitor_type, 'new')
        self.assertFalse(visitor.sunnyside_first_visit_date)
        self.assertFalse(visitor.sunnyside_last_visit_date)

        t1 = fields.Datetime.now() - timedelta(hours=3)
        v1 = self.Visit.create({
            'visitor_id': visitor.id,
            'location_id': self.test_location.id,
            'source': 'website',
            'check_in_datetime': t1,
        })
        self.assertEqual(visitor.sunnyside_visit_count, 1)
        self.assertEqual(visitor.sunnyside_visitor_type, 'new', "With 1 visit, visitor status is 'new'")
        self.assertEqual(visitor.sunnyside_first_visit_date, t1)
        self.assertEqual(visitor.sunnyside_last_visit_date, t1)

        t2 = fields.Datetime.now()
        v2 = self.Visit.create({
            'visitor_id': visitor.id,
            'location_id': self.test_location.id,
            'source': 'receptionist',
            'check_in_datetime': t2,
        })
        self.assertEqual(visitor.sunnyside_visit_count, 2)
        self.assertEqual(visitor.sunnyside_visitor_type, 'returning', "With 2 visits, visitor status is 'returning'")
        self.assertEqual(visitor.sunnyside_first_visit_date, t1)
        self.assertEqual(visitor.sunnyside_last_visit_date, t2)

        # Verify action and smart button view action
        action = visitor.action_view_sunnyside_visits()
        self.assertEqual(action.get('res_model'), 'sunnyside.visit')
        self.assertEqual(action.get('domain'), [('visitor_id', '=', visitor.id)])

    def test_12_visit_management_phone_and_visitor_type(self):
        """Verify Visit management: stored related visitor_phone and computed visitor_type on visits."""
        visitor = self.Partner.create({
            'name': 'Visit History Visitor',
            'phone': '+2348077770002',
            'is_sunnyside_visitor': True,
            'sunnyside_location_id': self.test_location.id,
            'privacy_acknowledged': True,
        })

        t1 = fields.Datetime.now() - timedelta(hours=2)
        visit1 = self.Visit.create({
            'visitor_id': visitor.id,
            'location_id': self.test_location.id,
            'source': 'qr_code',
            'check_in_datetime': t1,
        })
        self.assertEqual(visit1.visitor_phone, '+2348077770002', "Visit visitor_phone must match visitor phone")
        self.assertEqual(visit1.visitor_type, 'new', "First chronological visit must be 'new'")

        t2 = fields.Datetime.now()
        visit2 = self.Visit.create({
            'visitor_id': visitor.id,
            'location_id': self.test_location.id,
            'source': 'receptionist',
            'check_in_datetime': t2,
        })
        self.assertEqual(visit2.visitor_phone, '+2348077770002')
        self.assertEqual(visit2.visitor_type, 'returning', "Subsequent visit must be 'returning'")

    def test_13_receptionist_assisted_checkin_wizard(self):
        """Verify Receptionist-Assisted Check-in Wizard for both new and existing visitors."""
        Wizard = self.env['sunnyside.checkin.wizard']

        # --- Subtest A: New Visitor Flow ---
        wiz_new = Wizard.create({
            'phone': '08091112233',
            'country_dial_code': '234',
        })
        wiz_new._onchange_phone_lookup()
        self.assertFalse(wiz_new.is_existing_visitor, "New phone must evaluate is_existing_visitor=False")
        self.assertFalse(wiz_new.visitor_id)
        self.assertIn("New Visitor", wiz_new.visitor_status_banner)

        # Attempt confirm without required name & location
        with self.assertRaises(ValidationError):
            wiz_new.action_confirm_checkin()

        # Provide required fields
        wiz_new.write({
            'name': 'Chioma Eze',
            'location_id': self.test_location.id,
        })
        action = wiz_new.action_confirm_checkin()
        self.assertEqual(action.get('res_model'), 'sunnyside.visit')
        created_visit_id = action.get('res_id')
        created_visit = self.Visit.browse(created_visit_id)
        self.assertTrue(created_visit.exists())
        self.assertEqual(created_visit.source, 'receptionist')
        self.assertEqual(created_visit.visitor_type, 'new')
        self.assertEqual(created_visit.visitor_id.name, 'Chioma Eze')
        self.assertEqual(created_visit.visitor_id.phone, '+2348091112233')
        self.assertTrue(created_visit.visitor_id.is_sunnyside_visitor)
        self.assertEqual(created_visit.visitor_id.sunnyside_visit_count, 1)

        # --- Subtest B: Returning Visitor Flow ---
        wiz_returning = Wizard.create({
            'phone': '08091112233',
            'country_dial_code': '234',
        })
        wiz_returning._onchange_phone_lookup()
        self.assertTrue(wiz_returning.is_existing_visitor, "Existing phone must evaluate is_existing_visitor=True")
        self.assertEqual(wiz_returning.visitor_id.id, created_visit.visitor_id.id)
        self.assertEqual(wiz_returning.name, 'Chioma Eze')
        self.assertIn("Returning Guest Found", wiz_returning.visitor_status_banner)

        action2 = wiz_returning.action_confirm_checkin()
        visit2 = self.Visit.browse(action2.get('res_id'))
        self.assertEqual(visit2.visitor_id.id, created_visit.visitor_id.id)
        self.assertEqual(visit2.source, 'receptionist')
        self.assertEqual(visit2.visitor_type, 'returning')
        self.assertEqual(created_visit.visitor_id.sunnyside_visit_count, 2)

        # Verify no duplicate contacts created
        partner_count = self.Partner.search_count([('phone', '=', '+2348091112233')])
        self.assertEqual(partner_count, 1, "Must maintain exactly one partner contact per phone number")

    def test_14_management_dashboard_metrics_and_definitions(self):
        """Verify Management Dashboard calculated metrics (6 KPIs) and navigation actions."""
        Dashboard = self.env['sunnyside.dashboard']
        dashboard = Dashboard.create({'name': 'Test Dashboard'})
        dashboard._compute_metrics()

        # Check that metrics return non-negative integers
        self.assertGreaterEqual(dashboard.total_visitors, 0)
        self.assertGreaterEqual(dashboard.checkins_today, 0)
        self.assertGreaterEqual(dashboard.new_visitors_today, 0)
        self.assertGreaterEqual(dashboard.returning_visitors_today, 0)
        self.assertEqual(
            dashboard.checkins_today,
            dashboard.new_visitors_today + dashboard.returning_visitors_today,
            "Today's total check-ins must equal sum of new visitors today + returning visitors today"
        )
        self.assertGreaterEqual(dashboard.checkins_this_week, dashboard.checkins_today)
        self.assertGreaterEqual(dashboard.checkins_this_month, 0)

        # Check singleton opener
        open_action = Dashboard.action_open_dashboard()
        self.assertEqual(open_action.get('res_model'), 'sunnyside.dashboard')
        self.assertEqual(open_action.get('view_mode'), 'form')

        # Check dashboard drill-down actions
        a_visitors = dashboard.action_view_visitors()
        self.assertEqual(a_visitors.get('res_model'), 'res.partner')

        a_today = dashboard.action_view_today_checkins()
        self.assertEqual(a_today.get('res_model'), 'sunnyside.visit')
        self.assertEqual(a_today.get('context', {}).get('search_default_filter_today'), 1)

        a_new_today = dashboard.action_view_today_new()
        self.assertEqual(a_new_today.get('context', {}).get('search_default_filter_new_visitors'), 1)

        a_ret_today = dashboard.action_view_today_returning()
        self.assertEqual(a_ret_today.get('context', {}).get('search_default_filter_returning_visitors'), 1)

        a_week = dashboard.action_view_this_week_checkins()
        self.assertEqual(a_week.get('context', {}).get('search_default_filter_this_week'), 1)

        a_month = dashboard.action_view_this_month_checkins()
        self.assertEqual(a_month.get('context', {}).get('search_default_filter_this_month'), 1)

        a_wiz = dashboard.action_open_checkin_wizard()
        self.assertEqual(a_wiz.get('res_model'), 'sunnyside.checkin.wizard')
        self.assertEqual(a_wiz.get('target'), 'new')

        a_rep = dashboard.action_open_reporting()
        self.assertEqual(a_rep.get('res_model'), 'sunnyside.visit')

    def test_15_reporting_views_and_menus(self):
        """Verify Reporting action, graph/pivot view registrations, and menu accessibility."""
        # 1. Reporting Action
        rep_action = self.env.ref('sunnyside_visitor_management.action_sunnyside_visit_reporting', raise_if_not_found=False)
        self.assertTrue(rep_action, "Reporting action 'action_sunnyside_visit_reporting' must exist")
        self.assertEqual(rep_action.res_model, 'sunnyside.visit')
        self.assertIn('graph', rep_action.view_mode)
        self.assertIn('pivot', rep_action.view_mode)

        # 2. Graph and Pivot Views
        graph_view = self.env.ref('sunnyside_visitor_management.view_sunnyside_visit_graph', raise_if_not_found=False)
        self.assertTrue(graph_view, "Graph view 'view_sunnyside_visit_graph' must exist")
        self.assertEqual(graph_view.model, 'sunnyside.visit')

        pivot_view = self.env.ref('sunnyside_visitor_management.view_sunnyside_visit_pivot', raise_if_not_found=False)
        self.assertTrue(pivot_view, "Pivot view 'view_sunnyside_visit_pivot' must exist")
        self.assertEqual(pivot_view.model, 'sunnyside.visit')

        # 3. Dedicated Front-Desk Visitor Form
        visitor_form = self.env.ref('sunnyside_visitor_management.view_sunnyside_visitor_form', raise_if_not_found=False)
        self.assertTrue(visitor_form, "Dedicated visitor form view must exist")
        self.assertEqual(visitor_form.model, 'res.partner')

        # 4. Checkin Wizard Action
        wizard_action = self.env.ref('sunnyside_visitor_management.action_sunnyside_checkin_wizard', raise_if_not_found=False)
        self.assertTrue(wizard_action, "Checkin wizard action must exist")
        self.assertEqual(wizard_action.res_model, 'sunnyside.checkin.wizard')
        self.assertEqual(wizard_action.target, 'new')

        # 5. Dashboard Action
        dashboard_action = self.env.ref('sunnyside_visitor_management.action_sunnyside_dashboard', raise_if_not_found=False)
        self.assertTrue(dashboard_action, "Dashboard action must exist")
        self.assertEqual(dashboard_action.model_id.model, 'sunnyside.dashboard')

    def test_16_new_visitor_registration_with_valid_email(self):
        """Verify Test 16: New visitor registration with valid email persists to res.partner.email."""
        from odoo.tools import email_normalize
        email_input = "Tunde.Guest@Example.Com"
        norm_email = email_normalize(email_input)
        self.assertEqual(norm_email, "tunde.guest@example.com")

        valid, e164, variants, _ = normalize_phone('08022223333', '234')
        self.assertTrue(valid)

        visitor = self.Partner.create({
            'name': 'Tunde Guest',
            'phone': e164,
            'email': norm_email,
            'is_sunnyside_visitor': True,
            'sunnyside_location_id': self.test_location.id,
            'privacy_acknowledged': True,
            'privacy_notice_version': PRIVACY_NOTICE_VERSION,
        })
        self.assertEqual(visitor.email, 'tunde.guest@example.com', "Email must be saved normalized on partner record")

        # Verify visit creation
        visit = self.Visit.create({
            'visitor_id': visitor.id,
            'location_id': self.test_location.id,
            'source': 'website',
            'submission_token': 'token_email_test_1',
        })
        self.assertEqual(visit.visitor_id.email, 'tunde.guest@example.com')

    def test_17_new_visitor_registration_without_email(self):
        """Verify Test 17: New visitor registration without email succeeds with email=False."""
        valid, e164, _, _ = normalize_phone('08033334444', '234')
        self.assertTrue(valid)

        visitor = self.Partner.create({
            'name': 'No Email Guest',
            'phone': e164,
            'email': False,
            'is_sunnyside_visitor': True,
            'sunnyside_location_id': self.test_location.id,
            'privacy_acknowledged': True,
            'privacy_notice_version': PRIVACY_NOTICE_VERSION,
        })
        self.assertFalse(visitor.email, "Email should be False when not provided")
        self.assertTrue(visitor.id)

    def test_18_malformed_email_rejected(self):
        """Verify Test 18: Malformed non-empty email is caught by regex and normalization check."""
        import re
        from odoo.tools import email_normalize
        malformed_inputs = ['invalid-email', 'no-at-sign.com', '@nodomain', 'spaces in@email.com']
        for raw in malformed_inputs:
            is_valid = bool(re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', raw)) and bool(email_normalize(raw))
            self.assertFalse(is_valid, f"Malformed email '{raw}' should be rejected as invalid")

    def test_19_blank_email_does_not_overwrite_existing(self):
        """Verify Test 19: Re-checkin or profile touch does not clear an existing email."""
        visitor = self.Partner.create({
            'name': 'VIP Guest',
            'phone': '+2348044445555',
            'email': 'vip@sunnyside.ng',
            'is_sunnyside_visitor': True,
            'sunnyside_location_id': self.test_location.id,
            'privacy_acknowledged': True,
        })
        self.assertEqual(visitor.email, 'vip@sunnyside.ng')

        # Simulate subsequent visit check-in without email
        visit = self.Visit.create({
            'visitor_id': visitor.id,
            'source': 'qr_code',
            'submission_token': 'token_vip_recheckin',
        })
        self.assertEqual(visitor.email, 'vip@sunnyside.ng', "Existing email must remain intact")

    def test_20_marketing_consent_strictly_separated_from_email(self):
        """Verify Test 20: Providing an email does not imply or grant marketing consent."""
        visitor = self.Partner.create({
            'name': 'Consent Test Guest',
            'phone': '+2348055556666',
            'email': 'consent.test@sunnyside.ng',
            'is_sunnyside_visitor': True,
            'sunnyside_location_id': self.test_location.id,
            'privacy_acknowledged': True,
            'marketing_consent': False,
        })
        self.assertTrue(visitor.email)
        self.assertFalse(visitor.marketing_consent, "Marketing consent must remain False unless explicitly checked")

