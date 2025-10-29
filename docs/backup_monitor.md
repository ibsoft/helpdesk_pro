# Backup Monitor Module

The Backup Monitor module adds LTO tape management to Helpdesk Pro. It provides full lifecycle tracking for physical media and the backup jobs recorded on them, including locations, custody history, and auditing.

## Feature Overview

- **Tape Catalogue** — Create cartridges with barcode, LTO generation, capacity, usage tags, and status (empty / in use / full / pending destruction).
- **Backup Jobs** — Log jobs with retention in days, calculated expiry, total file counts, sizes, verification results, source systems, and responsible technicians.
- **Multi-Tape Spanning** — Assign a job to one or more cartridges in sequence. Spanning order is preserved and editable.
- **Location Tracking** — Record where a cartridge is stored (on-site, in transit, off-site) with shelf/locker details, custodians, service providers, and timestamps.
- **Custody Chain** — Maintain hand-off records including signatures for comprehensive chain-of-custody.
- **Auditing** — Every change to tape status, locations, custody, and retention is stored in `backup_audit_log` and surfaced in the UI.
- **Delete With Safety** — Tape and job deletions require confirmation via Bootstrap modal dialogs. Deleting a tape cascades to locations, custody events, and job links; deleting a job removes only the job and its tape bindings.

## Permissions

- The module uses the `backup` entry in Manage → Access for read vs. read/write control.
- Admins always have write access; other roles default to write until overridden.
- Users with read-only access can browse data but cannot add, edit, or delete tapes/jobs.

## Navigation

1. Open **Manage → Backup Monitor** from the sidebar.
2. The overview page shows:
   - Summary metrics (total tapes, jobs, status/location distribution).
   - Quick actions (register tapes, log jobs) when write access is granted.
   - Responsive tables for tapes and recent jobs with inline links to detail pages.

## Workflow Highlights

### Register a Tape
1. Go to Backup Monitor → Quick Actions → Register Tape Cartridge.
2. Enter barcode, generation, capacity, status, tags, and optional notes.
3. Submit to add the cartridge; a new `backup_tape_cartridge` row is created and audited.

### Log a Backup Job
1. Use Quick Actions → Log Backup Job.
2. Supply name, job date, retention, totals, verification result, source system, technician, and tape assignments (multi-select).
3. Submission writes `backup_job`, `backup_job_tape`, and creates audit entries.

### Update Tape or Job
1. From the overview tables or detail pages, open the entity.
2. Edit fields and submit. Updating a job adjusts tape bindings and recalculates expiry.
3. All changes generate audit records for traceability.

### Manage Locations and Custody
1. From a tape detail page, use **Log Location** to add a new `backup_tape_location` row (previous current entries are automatically marked inactive).
2. Use **Record Custody Event** to append entries to `backup_tape_custody`.

### Delete Entities
1. Press the trash icon in the overview tables or use the button on detail pages.
2. Confirm deletion in the modal.
3. On success, you are redirected back to the monitor with feedback (JSON responses are returned when triggered via AJAX).

## Database Changes

Run migrations after pulling the module:

```bash
source helpdesk_pro/.venv/bin/activate
FLASK_APP=helpdesk_pro/wsgi.py flask db upgrade
```

New tables:
- `backup_tape_cartridge`
- `backup_job`
- `backup_job_tape` (association)
- `backup_tape_location`
- `backup_tape_custody`
- `backup_audit_log`

All tables are created by the Alembic revision `f1b8d4ac9c3e_add_backup_monitor_module.py`.

## API / Code Touchpoints

- Routes live in `app/backup/routes.py`.
- SQLAlchemy models are in `app/models/backup.py` with cascades for join tables, locations, and custody.
- Permissions rely on `app/permissions.py` and the `backup` module key.
- UI templates are under `templates/backup/` (`monitor.html`, `tape_detail.html`, `job_detail.html`).

## Maintenance Tips

- Deleting a tape cascades to locations, custody, and job associations—export or audit data before removal.
- Jobs can be deleted independently; cartridges remain in inventory.
- The audit trail is surfaced via `/backup/audit/<entity_type>/<id>` JSON endpoint and on detail pages.
- Background email ingestion continues unaffected; the backup module is a separate blueprint registered in `app/__init__.py`.

