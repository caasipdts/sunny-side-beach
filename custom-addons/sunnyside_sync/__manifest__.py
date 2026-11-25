{
    'name': 'Sunnyside Sync',
    'version': '19.0.1.1.0',
    'category': 'Technical',
    'summary': 'Local change capture, an authenticated Odoo sync API, and a durable outbox',
    'description': """
Sunnyside Sync
==============
Provides record identities, revision tracking, tombstones, conflict handling,
an authenticated versioned sync API, and a durable outbox for visitor data.
    """,
    'author': 'Sunnyside Beach',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'web',
        'sunnyside_visitor_management',
    ],
    'data': [
        'security/sync_security.xml',
        'security/ir.model.access.csv',
        'views/sync_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'sunnyside_sync/static/src/js/sync_status.js',
            'sunnyside_sync/static/src/xml/sync_status.xml',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
}
