"""
Stage 6.1 — Idempotent seating inventory seed for Sunnyside Beach.
Run via:
  ./.venv/bin/python ./odoo-bin shell -c odoo.conf -d sunnyside_beach \
    < custom-addons/sunnyside_visitor_management/scripts/seed_seating_inventory.py
"""

Area = env['sunnyside.seating.area']
Unit = env['sunnyside.seating.unit']

# ---------------------------------------------------------------------------
# 1. Create / match seating areas
# ---------------------------------------------------------------------------
area_defs = [
    {'name': 'Cabana Area',       'sequence': 10},
    {'name': 'Table Seating',     'sequence': 20},
    {'name': 'Beachfront Seating','sequence': 30},
]

areas = {}
for ad in area_defs:
    rec = Area.search([('name', '=', ad['name'])], limit=1)
    if rec:
        areas[ad['name']] = rec
        print(f"[AREA] matched  : {ad['name']} (id={rec.id})")
    else:
        rec = Area.create({'name': ad['name'], 'sequence': ad['sequence'], 'active': True})
        areas[ad['name']] = rec
        print(f"[AREA] created  : {ad['name']} (id={rec.id})")

# ---------------------------------------------------------------------------
# 2. Define all 29 seating units
# ---------------------------------------------------------------------------
unit_defs = []

# Cabana Area — 3 cabanas
for i in range(1, 4):
    unit_defs.append({
        'name': f'CAB-0{i}',
        'area': 'Cabana Area',
        'seating_type': 'cabana',
        'capacity_min': 1,
        'capacity_max': 9,
        'pricing_mode': 'fixed',
        'fixed_price': 250000.0,
        'price_per_guest': 0.0,
        'entry_fee_amount': 0.0,
        'minimum_spend_amount': 0.0,
    })

# Table Seating — 6 tables
for i in range(1, 7):
    unit_defs.append({
        'name': f'TBL-0{i}',
        'area': 'Table Seating',
        'seating_type': 'table',
        'capacity_min': 1,
        'capacity_max': 4,
        'pricing_mode': 'per_guest',
        'price_per_guest': 20000.0,
        'fixed_price': 0.0,
        'entry_fee_amount': 5000.0,
        'minimum_spend_amount': 15000.0,
    })

# Beachfront Seating — 20 individual seats
for i in range(1, 21):
    unit_defs.append({
        'name': f'BFR-{i:02d}',
        'area': 'Beachfront Seating',
        'seating_type': 'beachfront_seat',
        'capacity_min': 1,
        'capacity_max': 1,
        'pricing_mode': 'per_guest',
        'price_per_guest': 20000.0,
        'fixed_price': 0.0,
        'entry_fee_amount': 5000.0,
        'minimum_spend_amount': 15000.0,
    })

# ---------------------------------------------------------------------------
# 3. Idempotent create / match
# ---------------------------------------------------------------------------
created = 0
matched = 0

for ud in unit_defs:
    area_rec = areas[ud['area']]
    existing = Unit.search(
        [('name', '=', ud['name']), ('area_id', '=', area_rec.id)],
        limit=1,
    )
    if existing:
        matched += 1
        print(f"[UNIT] matched  : {ud['name']} in '{ud['area']}'")
    else:
        vals = {k: v for k, v in ud.items() if k != 'area'}
        vals['area_id'] = area_rec.id
        vals['active'] = True
        Unit.create(vals)
        created += 1
        print(f"[UNIT] created  : {ud['name']} in '{ud['area']}'")

# ---------------------------------------------------------------------------
# 4. Commit and report
# ---------------------------------------------------------------------------
env.cr.commit()

total = created + matched
print()
print("=" * 60)
print("Stage 6.1 Seating Inventory — COMPLETE")
print("=" * 60)
print(f"  Areas      : {len(areas)} (Cabana Area, Table Seating, Beachfront Seating)")
print(f"  Units total: {total}  (created={created}, matched={matched})")
print(f"  Cabanas    : 3  × capacity 9  = 27 guest-slots")
print(f"  Tables     : 6  × capacity 4  = 24 guest-slots")
print(f"  Beachfront : 20 × capacity 1  = 20 guest-slots")
print(f"  Max capacity                  = 71 guests")
print()
print("Photographs: upload via Configuration > Seating Units")
print("  Open a unit > Photographs tab > Add a line > upload image")
print("=" * 60)

