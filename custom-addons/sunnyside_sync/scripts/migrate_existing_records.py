"""
Run once through Odoo shell after installing sunnyside_sync:

    Get-Content .\\custom-addons\\sunnyside_sync\\scripts\\migrate_existing_records.py |
        python .\\odoo-bin shell -d odoo

This queues existing Sunnyside visitor data locally. It does not contact the cloud.
"""

result = env['sunnyside.sync.state'].run_initial_migration()
env.cr.commit()
print("Initial sync migration:", result)
