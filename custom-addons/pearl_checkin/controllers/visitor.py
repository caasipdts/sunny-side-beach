# -*- coding: utf-8 -*-
import json
import logging
import re
import secrets
import threading
import time

from odoo import fields, http, tools, _
from odoo.http import request
from odoo.tools import email_normalize

_logger = logging.getLogger(__name__)

# In-memory sliding window rate limiter
_RATE_LIMIT_LOCK = threading.Lock()
_IP_TIMESTAMPS = {}
_IP_LOOKUP_TIMESTAMPS = {}

RATE_LIMIT_MAX_SUBMISSIONS = 30  # Max 30 general submissions per IP in 5 minutes
RATE_LIMIT_WINDOW_SECONDS = 300
RATE_LIMIT_MAX_LOOKUPS = 15      # Max 15 phone lookups per IP in 3 minutes (anti-enumeration)
RATE_LIMIT_LOOKUP_WINDOW = 180

PRIVACY_NOTICE_VERSION = '1.0'


def _check_rate_limit(ip, is_lookup=False):
    """
    Checks if the client IP has exceeded submission or lookup thresholds.
    Mitigates DDoS and automated phone number enumeration.
    """
    now = time.time()
    with _RATE_LIMIT_LOCK:
        if is_lookup:
            timestamps = [t for t in _IP_LOOKUP_TIMESTAMPS.get(ip, []) if now - t < RATE_LIMIT_LOOKUP_WINDOW]
            if len(timestamps) >= RATE_LIMIT_MAX_LOOKUPS:
                _IP_LOOKUP_TIMESTAMPS[ip] = timestamps
                return False
            timestamps.append(now)
            _IP_LOOKUP_TIMESTAMPS[ip] = timestamps
            return True
        else:
            timestamps = [t for t in _IP_TIMESTAMPS.get(ip, []) if now - t < RATE_LIMIT_WINDOW_SECONDS]
            if len(timestamps) >= RATE_LIMIT_MAX_SUBMISSIONS:
                _IP_TIMESTAMPS[ip] = timestamps
                return False
            timestamps.append(now)
            _IP_TIMESTAMPS[ip] = timestamps
            return True


def normalize_phone(raw_phone, country_dial_code='234'):
    """
    Validates and normalizes phone numbers into E.164 and generates search variants.
    Handles Nigerian standard formats (+234, 080..., 234..., 80...) and international numbers.

    Returns:
        is_valid (bool): True if phone format is valid.
        e164 (str): Normalized E.164 formatted number (+<country_code><national_number>).
        variants (set): Set of matching string variants for backwards-compatible partner lookup.
        error (str or None): User-facing validation error message if invalid.
    """
    if not raw_phone or not isinstance(raw_phone, str):
        return False, '', set(), _('Please enter your phone number.')

    # Clean characters (strip whitespace, hyphens, dots, parentheses)
    cleaned = re.sub(r'[\s\-\(\)\.]', '', raw_phone.strip())
    if not cleaned:
        return False, '', set(), _('Please enter your phone number.')

    # Clean country dial code
    c_dial = re.sub(r'\D', '', str(country_dial_code or '234'))
    if not c_dial:
        c_dial = '234'

    if cleaned.startswith('+'):
        digits = cleaned[1:]
        if not digits.isdigit() or len(digits) < 7 or len(digits) > 15:
            return False, '', set(), _('Please enter a valid international phone number (7-15 digits).')
        e164 = '+' + digits
    else:
        digits = cleaned
        if not digits.isdigit() or len(digits) < 6 or len(digits) > 15:
            return False, '', set(), _('Please enter a valid phone number (digits only).')

        if c_dial == '234':
            # Nigerian number formatting
            if digits.startswith('234') and len(digits) >= 12:
                e164 = '+' + digits
            elif digits.startswith('0') and len(digits) == 11:
                e164 = '+234' + digits[1:]
            elif len(digits) == 10 and digits[0] in ('7', '8', '9'):
                e164 = '+234' + digits
            else:
                e164 = '+234' + digits
        else:
            # Other international country: remove trunk zero if user provided (e.g. UK 07xxx)
            if digits.startswith('0') and len(digits) > 7:
                digits = digits[1:]
            if digits.startswith(c_dial) and len(digits) > len(c_dial) + 5:
                e164 = '+' + digits
            else:
                e164 = '+' + c_dial + digits

    # Final validation on normalized length
    e164_digits = e164[1:]
    if len(e164_digits) < 7 or len(e164_digits) > 15:
        return False, '', set(), _('Please enter a valid phone number length.')

    # Generate backwards-compatible lookup variants so previous contacts match regardless of entry style
    variants = {e164, e164_digits}
    if e164.startswith('+234') and len(e164_digits) == 13:
        # e.g., '08031234567' and '8031234567'
        variants.add('0' + e164_digits[3:])
        variants.add(e164_digits[3:])

    return True, e164, variants, None


def _get_country_dataset(env):
    """
    Retrieves country records with dialing codes from local res.country dataset.
    Puts Nigeria (+234) first as default, followed by remaining countries alphabetically.
    Uses local PNG flag assets from base module with zero external CDN dependency.
    """
    countries = env['res.country'].sudo().search_read(
        [('phone_code', '>', 0)],
        ['id', 'name', 'code', 'phone_code'],
        order='name asc'
    )
    ng = None
    rest = []
    for c in countries:
        c_code = (c['code'] or '').upper()
        c['flag_url'] = f'/base/static/img/country_flags/{c_code.lower()}.png'
        # Compute Unicode flag emoji from ISO 3166-1 alpha-2 code
        if len(c_code) == 2:
            c['flag_emoji'] = ''.join(chr(127397 + ord(ch)) for ch in c_code)
        else:
            c['flag_emoji'] = '🌐'

        if c_code == 'NG':
            ng = c
        else:
            rest.append(c)

    return ([ng] if ng else []) + rest


class PearlVisitorController(http.Controller):

    # =========================================================================
    # 1. Main Visitor Check-in Portal
    # =========================================================================
    @http.route(
        ['/pearl/check-in'],
        type='http',
        auth='public',
        website=True,
        csrf=True,
        methods=['GET', 'POST'],
        sitemap=True,
    )
    def check_in(self, **post):
        """
        Progressive, phone-first mobile check-in portal for Pearl Restaurant visitors.

        Screen 1: Phone number + Country selector (default Nigeria +234).
        Branching:
          - Existing Visitor: Direct check-in, creates visit record, logs CRM interaction,
            shows welcome screen without exposing stored contact details or asking for name.
          - New Visitor: Displays Screen 2 requesting Full Name, Neighbourhood, and
            mandatory Privacy Notice Acknowledgement.

        Supports both seamless AJAX/Fetch transitions and standard HTTP POST fallbacks.
        """
        env = request.env
        active_locations = env['pearl.location'].sudo().search(
            [('active', '=', True)],
            order='name asc'
        )
        countries = _get_country_dataset(env)

        source_param = post.get('source', '').strip().lower()
        visit_source = source_param if source_param in ('qr_code', 'website') else 'qr_code'
        is_ajax = (
            request.httprequest.headers.get('X-Requested-With') == 'XMLHttpRequest' or
            'application/json' in request.httprequest.headers.get('Accept', '') or
            post.get('is_ajax') == '1'
        )
        client_ip = request.httprequest.remote_addr or 'unknown'

        # ----------------------------------------------------
        # GET: Display Initial Phone-First Screen (Screen 1)
        # ----------------------------------------------------
        if request.httprequest.method == 'GET':
            submission_token = secrets.token_urlsafe(16)
            return request.render('pearl_checkin.checkin_page', {
                'screen': 1,
                'countries': countries,
                'default_country_code': 'NG',
                'default_dial_code': '234',
                'locations': active_locations,
                'submission_token': submission_token,
                'source': visit_source,
                'privacy_notice_version': PRIVACY_NOTICE_VERSION,
                'values': {},
                'errors': {},
            })

        # ----------------------------------------------------
        # POST: Action Branching (Lookup vs Register)
        # ----------------------------------------------------
        action = (post.get('action') or '').strip().lower()
        raw_phone = (post.get('phone') or '').strip()
        country_dial_code = (post.get('country_dial_code') or '234').strip()
        submission_token = (post.get('submission_token') or '').strip()

        if not submission_token or len(submission_token) < 8 or len(submission_token) > 64:
            submission_token = secrets.token_urlsafe(16)

        # ====================================================
        # BRANCH 1: Phone Lookup (Screen 1 Submission)
        # ====================================================
        if action == 'lookup' or (not action and not post.get('name')):
            # Rate limit check for lookups
            if not _check_rate_limit(client_ip, is_lookup=True):
                _logger.warning("Pearl phone lookup rate limit exceeded for IP=%s", client_ip)
                err_msg = _('Too many attempts from your network. Please wait a minute and try again.')
                if is_ajax:
                    return request.make_response(
                        json.dumps({'status': 'error', 'message': err_msg}),
                        headers=[('Content-Type', 'application/json')]
                    )
                return request.render('pearl_checkin.checkin_page', {
                    'screen': 1,
                    'countries': countries,
                    'default_country_code': post.get('country_code', 'NG'),
                    'default_dial_code': country_dial_code,
                    'locations': active_locations,
                    'submission_token': submission_token,
                    'source': visit_source,
                    'privacy_notice_version': PRIVACY_NOTICE_VERSION,
                    'values': post,
                    'errors': {'phone': err_msg},
                })

            # Validate and normalize phone number
            is_valid, normalized_phone, variants, phone_err = normalize_phone(raw_phone, country_dial_code)
            if not is_valid:
                if is_ajax:
                    return request.make_response(
                        json.dumps({'status': 'error', 'field': 'phone', 'message': phone_err}),
                        headers=[('Content-Type', 'application/json')]
                    )
                return request.render('pearl_checkin.checkin_page', {
                    'screen': 1,
                    'countries': countries,
                    'default_country_code': post.get('country_code', 'NG'),
                    'default_dial_code': country_dial_code,
                    'locations': active_locations,
                    'submission_token': submission_token,
                    'source': visit_source,
                    'privacy_notice_version': PRIVACY_NOTICE_VERSION,
                    'values': post,
                    'errors': {'phone': phone_err},
                })

            # Transaction-level advisory lock to eliminate race conditions
            request.env.cr.execute("SELECT pg_advisory_xact_lock(hashtext(%s));", [normalized_phone])

            # Lookup existing visitor in res.partner
            partner_sudo = env['res.partner'].sudo()
            if 'mobile' in partner_sudo._fields:
                phone_search_domain = ['|', ('phone', 'in', list(variants)), ('mobile', 'in', list(variants))]
            else:
                phone_search_domain = [('phone', 'in', list(variants))]
            existing_visitor = partner_sudo.search(phone_search_domain, limit=1)

            # ------------------------------------------------
            # CASE A: Existing Visitor Match -> Direct Check-in
            # ------------------------------------------------
            if existing_visitor:
                visitor = existing_visitor

                # Ensure visitor flag is set without overwriting other contact details
                if not visitor.is_pearl_visitor:
                    visitor.write({'is_pearl_visitor': True})

                # Idempotency check: replay check-in if same submission token
                existing_visit = env['pearl.visit'].sudo().search(
                    [('submission_token', '=', submission_token)],
                    limit=1
                )
                if not existing_visit:
                    # Create new visit record for this intentional check-in
                    existing_visit = env['pearl.visit'].sudo().create({
                        'visitor_id': visitor.id,
                        'location_id': visitor.pearl_location_id.id if visitor.pearl_location_id else False,
                        'source': visit_source,
                        'submission_token': submission_token,
                        'check_in_datetime': fields.Datetime.now(),
                        'state': 'checked_in',
                    })
                    _logger.info("Pearl check-in for existing visitor id=%s, visit=%s", visitor.id, existing_visit.name)

                    # Update CRM relationship (log note, do not duplicate lead)
                    self._handle_returning_visitor_crm(visitor, existing_visit)

                # Return success response (Do not reveal personal info or previous visit history)
                if is_ajax:
                    return request.make_response(
                        json.dumps({
                            'status': 'existing',
                            'success': True,
                            'message': _('Welcome to Pearl Restaurant!\nYour check-in is complete.\nEnjoy your stay!'),
                            'visit_name': existing_visit.name,
                            'check_in_time': existing_visit.check_in_datetime.strftime('%b %d, %Y at %I:%M %p') if existing_visit.check_in_datetime else '',
                            'visitor_name': visitor.name,
                            'is_returning_visitor': True,
                            'times_visited': visitor.pearl_visit_count,
                        }),
                        headers=[('Content-Type', 'application/json')]
                    )

                return request.render('pearl_checkin.checkin_success', {
                    'visit': existing_visit,
                    'visitor': visitor,
                    'partner': visitor,
                    'is_returning_visitor': True,
                    'source': visit_source,
                })

            # ------------------------------------------------
            # CASE B: New Visitor -> Transition to Screen 2
            # ------------------------------------------------
            if is_ajax:
                return request.make_response(
                    json.dumps({
                        'status': 'new',
                        'normalized_phone': normalized_phone,
                        'display_phone': raw_phone,
                        'country_dial_code': country_dial_code,
                    }),
                    headers=[('Content-Type', 'application/json')]
                )

            # Standard POST fallback: render Screen 2 with phone locked in
            return request.render('pearl_checkin.checkin_page', {
                'screen': 2,
                'countries': countries,
                'default_country_code': post.get('country_code', 'NG'),
                'default_dial_code': country_dial_code,
                'locations': active_locations,
                'submission_token': submission_token,
                'source': visit_source,
                'privacy_notice_version': PRIVACY_NOTICE_VERSION,
                'values': {
                    'phone': raw_phone,
                    'normalized_phone': normalized_phone,
                    'country_dial_code': country_dial_code,
                },
                'errors': {},
            })

        # ====================================================
        # BRANCH 2: New Visitor Registration (Screen 2 Submission)
        # ====================================================
        elif action == 'register':
            # Rate limit check for registrations
            if not _check_rate_limit(client_ip, is_lookup=False):
                _logger.warning("Pearl registration rate limit exceeded for IP=%s", client_ip)
                err_msg = _('Too many attempts from your network. Please wait a few moments and try again.')
                if is_ajax:
                    return request.make_response(
                        json.dumps({'status': 'error', 'message': err_msg}),
                        headers=[('Content-Type', 'application/json')]
                    )
                return request.render('pearl_checkin.checkin_page', {
                    'screen': 2,
                    'countries': countries,
                    'default_country_code': post.get('country_code', 'NG'),
                    'default_dial_code': country_dial_code,
                    'locations': active_locations,
                    'submission_token': submission_token,
                    'source': visit_source,
                    'privacy_notice_version': PRIVACY_NOTICE_VERSION,
                    'values': post,
                    'errors': {'general': err_msg},
                })

            name = (post.get('name') or '').strip()
            raw_email = (post.get('email') or '').strip()
            location_id_raw = post.get('location_id')
            privacy_acknowledged = post.get('privacy_acknowledged') in ('1', 'true', 'on', True)
            marketing_consent = post.get('marketing_consent') in ('1', 'true', 'on', True)

            errors = {}

            # 1. Validate Name
            if not name:
                errors['name'] = _('Please enter your full name.')
            elif len(name) < 2:
                errors['name'] = _('Full name must be at least 2 characters.')
            elif len(name) > 100:
                errors['name'] = _('Full name cannot exceed 100 characters.')

            # 2. Validate Optional Email
            normalized_email = False
            if raw_email:
                if not re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', raw_email):
                    errors['email'] = _('Please enter a valid email address.')
                else:
                    normalized_email = email_normalize(raw_email)
                    if not normalized_email:
                        errors['email'] = _('Please enter a valid email address.')

            # 3. Validate Phone
            is_valid, normalized_phone, variants, phone_err = normalize_phone(raw_phone, country_dial_code)
            if not is_valid:
                errors['phone'] = phone_err

            # 4. Validate Location
            selected_location = False
            try:
                loc_id = int(location_id_raw) if location_id_raw else 0
                selected_location = env['pearl.location'].sudo().search(
                    [('id', '=', loc_id), ('active', '=', True)],
                    limit=1
                )
            except (ValueError, TypeError):
                selected_location = False

            if not selected_location:
                errors['location_id'] = _('Please select where you are visiting from.')

            # 5. Validate Mandatory Privacy Notice Acknowledgement
            if not privacy_acknowledged:
                errors['privacy_acknowledged'] = _(
                    'You must read and acknowledge the Pearl Restaurant privacy notice to complete registration.'
                )

            # Return validation errors if any failed
            if errors:
                if is_ajax:
                    return request.make_response(
                        json.dumps({'status': 'validation_error', 'errors': errors}),
                        headers=[('Content-Type', 'application/json')]
                    )
                return request.render('pearl_checkin.checkin_page', {
                    'screen': 2,
                    'countries': countries,
                    'default_country_code': post.get('country_code', 'NG'),
                    'default_dial_code': country_dial_code,
                    'locations': active_locations,
                    'submission_token': submission_token,
                    'source': visit_source,
                    'privacy_notice_version': PRIVACY_NOTICE_VERSION,
                    'values': post,
                    'errors': errors,
                })

            # Idempotency check with submission token
            existing_visit = env['pearl.visit'].sudo().search(
                [('submission_token', '=', submission_token)],
                limit=1
            )
            if existing_visit:
                _logger.info("Pearl idempotent replay for token=%s, visit=%s", submission_token, existing_visit.name)
                if is_ajax:
                    return request.make_response(
                        json.dumps({
                            'status': 'success',
                            'success': True,
                            'message': _('Welcome to Pearl Restaurant!\nYour check-in is complete.\nEnjoy your stay!'),
                            'visit_name': existing_visit.name,
                            'check_in_time': existing_visit.check_in_datetime.strftime('%b %d, %Y at %I:%M %p') if existing_visit.check_in_datetime else '',
                            'visitor_name': existing_visit.visitor_id.name,
                            'is_returning_visitor': existing_visit.visitor_type == 'returning',
                            'times_visited': existing_visit.visitor_id.pearl_visit_count,
                        }),
                        headers=[('Content-Type', 'application/json')]
                    )
                return request.render('pearl_checkin.checkin_success', {
                    'visit': existing_visit,
                    'visitor': existing_visit.visitor_id,
                    'partner': existing_visit.visitor_id,
                    'is_returning_visitor': existing_visit.visitor_type == 'returning',
                    'source': visit_source,
                })

            # Acquire PostgreSQL transaction-level lock on normalized phone
            request.env.cr.execute("SELECT pg_advisory_xact_lock(hashtext(%s));", [normalized_phone])

            # Re-check if visitor was concurrently created by another request
            partner_sudo = env['res.partner'].sudo()
            if 'mobile' in partner_sudo._fields:
                phone_search_domain = ['|', ('phone', 'in', list(variants)), ('mobile', 'in', list(variants))]
            else:
                phone_search_domain = [('phone', 'in', list(variants))]
            visitor = partner_sudo.search(phone_search_domain, limit=1)

            if visitor:
                # Concurrent request already created contact; reuse it safely
                if not visitor.is_pearl_visitor:
                    visitor.write({'is_pearl_visitor': True})
                if not visitor.pearl_location_id:
                    visitor.write({'pearl_location_id': selected_location.id})
                if normalized_email and not visitor.email:
                    visitor.write({'email': normalized_email})
            else:
                # Create permanent new visitor partner
                partner_vals = {
                    'name': name,
                    'phone': normalized_phone,
                    'email': normalized_email or False,
                    'is_pearl_visitor': True,
                    'pearl_location_id': selected_location.id,
                    'privacy_acknowledged': True,
                    'privacy_acknowledgement_date': fields.Datetime.now(),
                    'privacy_notice_version': PRIVACY_NOTICE_VERSION,
                    'marketing_consent': marketing_consent,
                    'marketing_consent_date': fields.Datetime.now() if marketing_consent else False,
                }
                visitor = partner_sudo.create(partner_vals)
                _logger.info("Created new Pearl visitor partner id=%s (%s)", visitor.id, normalized_phone)

                # Create initial CRM relationship
                self._handle_new_visitor_crm(visitor, selected_location)

            # Create the first pearl.visit record
            visit_sudo = env['pearl.visit'].sudo()
            new_visit = visit_sudo.create({
                'visitor_id': visitor.id,
                'location_id': selected_location.id,
                'source': visit_source,
                'submission_token': submission_token,
                'check_in_datetime': fields.Datetime.now(),
                'state': 'checked_in',
            })

            _logger.info("Pearl initial visit registered: %s (visitor_id=%s)", new_visit.name, visitor.id)

            # Success confirmation
            if is_ajax:
                return request.make_response(
                    json.dumps({
                        'status': 'success',
                        'success': True,
                        'message': _('Welcome to Pearl Restaurant!\nYour check-in is complete.\nEnjoy your stay!'),
                        'visit_name': new_visit.name,
                        'check_in_time': new_visit.check_in_datetime.strftime('%b %d, %Y at %I:%M %p') if new_visit.check_in_datetime else '',
                        'visitor_name': visitor.name,
                        'is_returning_visitor': False,
                        'times_visited': visitor.pearl_visit_count,
                    }),
                    headers=[('Content-Type', 'application/json')]
                )

            return request.render('pearl_checkin.checkin_success', {
                'visit': new_visit,
                'visitor': visitor,
                'partner': visitor,
                'is_returning_visitor': False,
                'source': visit_source,
            })

        # Fallback if unknown action
        return request.redirect('/pearl/check-in')

    # =========================================================================
    # 2. CRM Integration Helpers
    # =========================================================================
    def _handle_new_visitor_crm(self, visitor, location, env=None):
        """
        Creates an initial CRM lead for a newly registered visitor if CRM is installed.
        Assigns the lead to the default sales team and records registration source.
        Does not invent sales or revenue numbers.
        """
        if env is None:
            try:
                env = request.env
            except Exception:
                env = visitor.env if visitor else None

        if not env or 'crm.lead' not in env:
            return

        try:
            Lead = env['crm.lead'].sudo()
            existing_lead = Lead.search([('partner_id', '=', visitor.id)], limit=1)
            if existing_lead:
                return

            # UTM Source for Pearl Registration
            source_id = False
            if 'utm.source' in env:
                source = env['utm.source'].sudo().search([('name', '=', 'Pearl Restaurant Visitor Registration')], limit=1)
                if not source:
                    source = env['utm.source'].sudo().create({'name': 'Pearl Restaurant Visitor Registration'})
                source_id = source.id

            team = env['crm.team'].sudo().search([], limit=1) if 'crm.team' in env else False

            lead_vals = {
                'name': f"Pearl Guest - {visitor.name}",
                'partner_id': visitor.id,
                'contact_name': visitor.name,
                'phone': visitor.phone,
                'email_from': visitor.email or False,
                'type': 'lead',
                'team_id': team.id if team else False,
                'source_id': source_id,
                'description': (
                    f"Pearl Restaurant Visitor Registration\n"
                    f"Registration Date: {fields.Date.today()}\n"
                    f"Neighbourhood: {location.name if location else 'N/A'}\n"
                    f"Privacy Notice Acknowledged: Version {PRIVACY_NOTICE_VERSION}"
                ),
            }
            lead = Lead.create(lead_vals)
            _logger.info("Created CRM lead id=%s for new visitor id=%s", lead.id, visitor.id)
        except Exception as e:
            _logger.warning("CRM lead creation skipped or failed gracefully: %s", str(e))

    def _handle_returning_visitor_crm(self, visitor, visit, env=None):
        """
        Updates relationship history for a returning visitor in CRM.
        Logs an internal chatter note on their existing CRM lead/opportunity.
        Does NOT create duplicate leads or initiate marketing campaigns.
        """
        if env is None:
            try:
                env = request.env
            except Exception:
                env = visitor.env if visitor else None

        if not env or 'crm.lead' not in env:
            return

        try:
            Lead = env['crm.lead'].sudo()
            existing_lead = Lead.search([('partner_id', '=', visitor.id)], limit=1, order='create_date desc')
            if existing_lead:
                visit_time_str = visit.check_in_datetime.strftime('%b %d, %Y at %I:%M %p') if visit.check_in_datetime else 'Just now'
                note_body = (
                    f"<strong>Pearl Visitor Return Check-in</strong><br/>"
                    f"Visit Reference: <code>{visit.name}</code><br/>"
                    f"Check-in Time: {visit_time_str}<br/>"
                    f"Source: {dict(visit._fields['source'].selection).get(visit.source, visit.source)}"
                )
                existing_lead.message_post(
                    body=note_body,
                    message_type='comment',
                    subtype_xmlid='mail.mt_note'
                )
                _logger.info("Logged returning visit note on CRM lead id=%s for visitor id=%s", existing_lead.id, visitor.id)
            else:
                # If no previous lead exists for this contact, create their initial guest lead
                self._handle_new_visitor_crm(visitor, visitor.pearl_location_id, env=env)
        except Exception as e:
            _logger.warning("CRM note logging skipped or failed gracefully: %s", str(e))

    # =========================================================================
    # 3. Dedicated Privacy Notice Page
    # =========================================================================
    @http.route(
        ['/pearl/privacy'],
        type='http',
        auth='public',
        website=True,
        csrf=True,
        methods=['GET'],
        sitemap=True,
    )
    def privacy_notice(self, **kw):
        """Dedicated privacy notice and visitor data protection overview."""
        return request.render('pearl_checkin.privacy_policy', {
            'privacy_notice_version': PRIVACY_NOTICE_VERSION,
        })
