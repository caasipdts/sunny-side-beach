# Cloud Odoo Compose deployment

This stack runs the official `odoo:19.0` image with PostgreSQL 15 and Caddy.
It is separate from the repository's existing local PostgreSQL Compose file.
PostgreSQL and Odoo are not published to the host; Caddy is the only public
entry point. The default bind address is loopback for safe local testing.

Before using this stack for a production launch, complete the [go-live readiness
form](go-live-form.html) and review the [deployment go-live checklist](GO_LIVE.md).
The example domain, bind address, image tags, and worker URL are development
defaults and need a production review.

## Start

From `deploy/cloud`:

```powershell
.\setup-secrets.ps1
docker compose config
docker compose up -d
docker compose logs -f odoo
```

The first Odoo startup installs `sunnyside_visitor_management` and
`sunnyside_sync` in the `sunnyside_cloud` database. Custom addons are mounted
read-only from `custom-addons`. The named PostgreSQL and Odoo volumes preserve
the database and attachment filestore across container replacement.

Set `CLOUD_DOMAIN` to a DNS name pointing at the server before public use.
Keep `CLOUD_BIND_ADDRESS=127.0.0.1` for local testing. On a cloud VM, set it
to `0.0.0.0` only after restricting the host firewall to ports 80/443 and
admin-only SSH. Caddy obtains and renews HTTPS certificates for public DNS
names. `localhost` uses Caddy's local CA; for a worker on another machine,
export that CA and set `ca_file` in its config rather than disabling TLS
verification.

## Register the local sync device

After Odoo is healthy, register the token hash in the cloud database. The
token itself is read from the Docker secret and is never printed:

```powershell
Get-Content ..\..\custom-addons\sunnyside_sync\scripts\register_sync_device.py |
    docker compose exec -T odoo odoo shell -d sunnyside_cloud
```

Provision a dedicated internal Odoo user for the local worker and grant it
**Sunnyside Sync User** access. Run `setup-secrets.ps1` if the cloud secrets do
not exist yet. Edit `secrets/worker.ini` with that local Odoo user's database,
username, and password. The setup script creates this file with placeholders.
Keep it private; it is mounted read-only into the worker container.

The worker runs as a Docker service in the cloud Compose stack. From the
repository root, start it with:

```powershell
make cloud-worker-up
make cloud-worker-ps
make cloud-worker-logs
```

By default, the container reaches local Odoo at
`http://host.docker.internal:8069` and reaches cloud Odoo through Caddy over
the private Docker network. Set `WORKER_ODOO_URL` in `deploy/cloud/.env` if the
local Odoo server uses another address reachable from Docker. The start target
exports Caddy's public local CA certificate to `secrets/cloud_local_ca.crt`;
the worker trusts that certificate and keeps TLS verification enabled. The
device ID must match the registered cloud device and `SYNC_DEVICE_ID`.

The worker pushes the local outbox, pulls cloud changes, and performs a
manifest reconciliation once per hour by default. Docker restarts it after
host or container restarts. Stop only the worker with `make cloud-worker-down`.
The device token and config are mounted read-only and are never copied into
the worker image.

Bookings require matching seating-unit names, areas, capacities, and prices on
both databases. Seed the cloud inventory with the existing idempotent script:

```powershell
Get-Content ..\..\custom-addons\sunnyside_visitor_management\scripts\seed_seating_inventory.py |
    docker compose exec -T odoo odoo shell -d sunnyside_cloud
```

Custom seating types created under Configuration synchronize through the sync
worker. Their definitions are applied before other synchronized records in a
chunk, so the cloud can validate bookings that use them.

For the first local-to-cloud transfer, run the local initial migration once
after installing/upgrading `sunnyside_sync`; the migration only queues data
locally. Start the worker after cloud device registration and inventory setup.

## Backup and restore

Create a consistent, paired database and filestore backup with:

```powershell
.\backup.ps1 -Destination E:\SunnysideBackups
```

The script stops Odoo during the snapshot, writes a timestamped backup
directory, and starts Odoo again. Store backups outside the Docker volumes and
the application host. Restore is destructive: verify the selected backup, then
run:

```powershell
.\restore.ps1 -BackupDirectory E:\SunnysideBackups\sunnyside-cloud-YYYYMMDD-HHMMSS -Force
```

The restore script validates the manifest and PostgreSQL dump before replacing
the cloud database and filestore. If restoration fails after Odoo is stopped,
it leaves Odoo stopped so an inconsistent database and filestore are not served.
Test restore procedures in a separate environment before relying on them.

These scripts do not encrypt backups, upload them off-site, or implement
retention. Configure encryption, access controls, off-site storage, retention,
and scheduled restore drills for the target deployment before go-live. Do not
treat Docker volumes as backups.
