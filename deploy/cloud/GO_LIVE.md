# Sunnyside Beach deployment go-live checklist

Use this checklist with [the step-by-step go-live form](go-live-form.html). Complete each section with the people responsible for the deployment. The form saves in the current browser and exports a JSON record; it does not ask for or store passwords, tokens, private keys, or secret values.

## 1. Deployment owner and scope

- Name the deployment owner, technical operator, and business approver.
- Confirm production environment, planned go-live date, support contact, and escalation path.
- Confirm business company name, operating timezone, country, and currency. Set the Odoo company currency before recording bookings; the dashboards use the active company currency.
- Record recovery objectives: acceptable data loss (RPO) and time to restore service (RTO).

## 2. Host, DNS, and network

- Choose a supported, maintained Docker host with sufficient CPU, memory, disk, and monitored free space.
- Point the production DNS name in `CLOUD_DOMAIN` to the host. Use a real DNS name for public service; `localhost` is for local testing.
- Set `CLOUD_BIND_ADDRESS=0.0.0.0` only on the production host. Permit inbound 80/443 to Caddy and restrict SSH to named administrators or a VPN.
- Keep PostgreSQL and Odoo unpublished to the host. In this Compose file, Caddy is the only published service.
- The worker must reach the local Odoo URL in `WORKER_ODOO_URL`. `host.docker.internal` is a workstation default, not a production network plan. Prefer a private VPN or private network route; do not expose local Odoo directly to the public internet. Confirm that the cloud worker can resolve and reach the chosen URL.
- Confirm outbound access needed for image retrieval and Caddy certificate issuance/renewal.

## 3. Images, secrets, and HTTPS

- Review `deploy/cloud/.env` before starting. Set the production domain, bind address, and the selected `SYNC_DEVICE_ID` / `WORKER_ODOO_URL`.
- Pin and record tested Odoo, PostgreSQL, Caddy, and worker image versions (ideally immutable digests) for production. The example uses major/minor tags and can change when pulled.
- Run `deploy/cloud/setup-secrets.ps1` only for a fresh deployment. It refuses to replace an existing secrets directory.
- Keep `deploy/cloud/secrets/` out of source control and readable only by deployment administrators. Store a protected copy of recovery-critical secrets separately from the host.
- Use a unique, strong Odoo master password, PostgreSQL password, and sync device token. Keep values in an approved secret store; never paste them into the go-live form.
- Confirm Caddy has a valid public HTTPS certificate for the production hostname. Keep worker TLS verification enabled; do not disable certificate verification to work around trust errors.
- Configure Odoo outgoing mail if operators rely on email notifications, password reset, or chatter email. Verify sender identity and delivery with a real mailbox.

## 4. Odoo company, accounts, and roles

- Confirm the production database (`sunnyside_cloud`) and both custom modules (`sunnyside_visitor_management`, `sunnyside_sync`) are installed and upgraded to the release being deployed.
- Set company legal/display name, address, timezone, and currency. Review user timezone and language settings.
- Create named staff accounts; do not share administrator logins. Grant ordinary reception operators **Sunnyside User** and grant only configuration owners **Sunnyside Manager**. Assign sync controls only to designated synchronization managers.
- Sign in as a real reception operator and verify they can read seating types, view the dashboard, create check-ins/bookings, and record payments. This catches the “no group currently allows this operation” access error.
- Review Odoo master/admin password handling and disable or restrict database listing and database-manager access for public production access.

## 5. Operational master data

- Configure each location, seating area, and seating type, then configure every seating unit with the correct active state, name, capacity, pricing mode, price, entry fee, and minimum spend.
- Keep unit name + area unique and ensure local and cloud databases have the same corresponding units, capacities, and currency. Booking records refer to these by name and area.
- Seed standard cloud seating inventory with `seed_seating_inventory.py` where appropriate. Review custom VIP types and any local-only units separately; do not assume standard seeding copies custom inventory.
- Verify the displayed currency and prices with a small controlled booking. Confirm payment methods and reference-number procedures match the beach’s actual cash/card/mobile-money workflow.
- Decide whether historic test/demo visitors, bookings, and payments should be migrated. Back up both databases before queuing the initial migration.

## 6. Synchronization setup

- Create a dedicated local Odoo service user for the worker. Grant **Sunnyside Sync User** access and only the additional rights required by the operation. Do not use a personal administrator account.
- Fill `deploy/cloud/secrets/worker.ini` with the local URL, database, dedicated username, and password. Check that these credentials work from inside the worker container over the planned private network.
- Keep `SYNC_DEVICE_ID` identical in `deploy/cloud/.env`, the worker config, and the cloud registration. Register the token hash in the cloud database with `register_sync_device.py`; keep the token itself in its Docker secret.
- Start Odoo on the local host bound to an interface Docker can reach. For a production remote worker, configure a VPN/private route and firewall rules instead of opening Odoo to the internet.
- Run the initial local migration once after module installation/upgrade. Start the worker only after cloud registration and seating inventory setup are complete.
- Check `make cloud-worker-ps`, `make cloud-worker-logs`, and Odoo sync status. Require online state, zero pending events, zero quarantined events, and a recent successful sync. Agree who investigates future conflicts and quarantines.
- Set the reconciliation cadence intentionally. The current worker default is hourly; confirm that this meets the business recovery and data freshness needs.

## 7. Backups, recovery, and maintenance

- Set a backup schedule and retention window that meet the agreed RPO. `backup.ps1` saves a paired PostgreSQL dump and Odoo filestore, but does not encrypt, off-site upload, or apply retention.
- Copy backups off the application host, encrypt them, restrict access, and monitor backup age/failure. Do not treat Docker volumes as backups.
- Complete a restore drill in a separate environment using `restore.ps1`; confirm both database and filestore are present and Odoo can serve records afterwards.
- Record the rollback steps for the application image, addon release, and database backup. Take a backup before upgrades and plan a maintenance window.
- Assign someone to monitor disk space, container health, Odoo/Caddy/worker logs, certificate expiry, backups, and sync status. Define alert routes and a response owner.

## 8. End-to-end acceptance and sign-off

- Verify the public hostname redirects or serves HTTPS correctly and only intended ports are reachable.
- As a reception user, create a visitor check-in, reserve a test unit, record a test payment, and verify the dashboard totals and currency.
- Verify the booking and payment appear in cloud Odoo; verify a cloud-side change pulls back where supported. Confirm the sync worker resumes after a container restart.
- Confirm there are no pending or quarantined events after the test, and remove or clearly label test transactions before opening for business.
- Confirm backup completion, restore drill, staff training, support rota, escalation path, and business approval.
- Record the production release/image identifiers, date/time, operator, and approver.

## Deployment commands

Run from the repository root in PowerShell:

```powershell
if (-not (Test-Path deploy/cloud/.env)) { Copy-Item deploy/cloud/env.example deploy/cloud/.env }
# Edit deploy/cloud/.env for the production domain, bind address, and device ID.
.\deploy\cloud\setup-secrets.ps1
docker compose -f deploy/cloud/compose.yaml config
make cloud-up
make cloud-ps
make cloud-logs SERVICE=odoo
make cloud-worker-up
make cloud-worker-ps
make cloud-worker-logs
```

`setup-secrets.ps1` creates a private secrets directory and refuses to overwrite one. If secrets already exist, review and reuse them instead of running the setup command again. Do not run the deployment commands until the form sections above are complete for the target environment.
