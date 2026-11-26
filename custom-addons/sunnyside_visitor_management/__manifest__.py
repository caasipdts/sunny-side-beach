# -*- coding: utf-8 -*-
{
    'name': 'Sunnyside Beach - Visitor Management',
    'version': '19.0.1.0.0',
    'category': 'Customizations/Operations',
    'summary': 'Visitor tracking, check-ins, and neighbourhood demographics for Sunnyside Beach',
    'description': """
Sunnyside Beach Visitor Management
==================================
Foundational module for managing beach visitors and check-ins:
- Extended visitor profiles on contact records (res.partner)
- Check-in records tracking timestamps, location, and registration sources
- Configurable Lagos neighbourhoods and locations
- Public mobile check-in portal for guests via QR code
    """,
    'author': 'Sunnyside Beach',
    'website': 'https://sunnysidebeach.ng',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'web',
        'website',
        'mail',
        'contacts',
    ],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'data/ir_sequence_data.xml',
        'data/locations.xml',
        'data/seating_type_data.xml',
        'wizard/checkin_wizard_views.xml',
        'views/location_views.xml',
        'views/visit_views.xml',
        'views/visitor_views.xml',
        'views/booking_views.xml',
        'views/payment_views.xml',
        'views/seating_views.xml',
        'views/dashboard_views.xml',
        'views/menu_views.xml',
        'templates/visitor_templates.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'sunnyside_visitor_management/static/src/scss/seating_dashboard/seating_dashboard.scss',
            'sunnyside_visitor_management/static/src/js/seating_dashboard/seating_dashboard.js',
            'sunnyside_visitor_management/static/src/xml/seating_dashboard/seating_dashboard.xml',
        ],
        'web.assets_frontend': [
            'sunnyside_visitor_management/static/src/css/visitor_checkin.css',
            'sunnyside_visitor_management/static/src/js/visitor_checkin.js',
        ],
    },
    'installable': True,
    'application': True,
    'auto_install': False,
}
