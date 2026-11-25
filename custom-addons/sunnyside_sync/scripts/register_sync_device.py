import hashlib
import os
from pathlib import Path

from odoo.exceptions import UserError


device_id = os.environ.get('SUNNYSIDE_SYNC_DEVICE_ID', '').strip()
token_file = os.environ.get(
    'SUNNYSIDE_SYNC_DEVICE_TOKEN_FILE',
    '/run/secrets/sync_device_token',
)
if not device_id:
    raise UserError("SUNNYSIDE_SYNC_DEVICE_ID must be configured.")

try:
    token = Path(token_file).read_text(encoding='utf-8').strip()
except OSError as error:
    raise UserError("The configured synchronization token file cannot be read.") from error
if len(token) < 32:
    raise UserError("The synchronization token must contain at least 256 bits.")

Device = env['sunnyside.sync.device'].sudo()
device = Device.search([('device_id', '=', device_id)], limit=1)
values = {
    'name': device_id,
    'device_id': device_id,
    'token_hash': hashlib.sha256(token.encode('utf-8')).hexdigest(),
    'active': True,
}
if device:
    device.write(values)
else:
    Device.create(values)
env.cr.commit()
print("Registered synchronization device:", device_id)
